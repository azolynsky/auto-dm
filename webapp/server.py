#!/usr/bin/env python3
"""
Campaign Web Companion — FastAPI server.

Serves a player-facing view of the active campaign (resolved by
tools/campaign_lib.py: CAMPAIGN_ROOT env var, else <repo>/campaign):
  - Character sheets (every JSON sheet in characters/)
  - Live narration feed (state/player-feed.jsonl, written by tools/narrate.py)
  - Quest log (known_to_party=True only, secret_truth stripped)
  - Current state: location, date, weather
  - Combat tracker (when active)
  - Table settings (read/write — the one thing players can edit)

Start: python webapp/server.py
Opens on: http://localhost:8765
"""
import asyncio
import json
import re
import ssl
import sys
import traceback
import urllib.error
import urllib.request

import certifi
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "tools"))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "desktop"))
import campaign_lib
import config as appconfig
import prompts as prompt_registry

try:
    import uvicorn
    from fastapi import FastAPI, HTTPException, Request
    from fastapi.responses import FileResponse, JSONResponse
    from fastapi.staticfiles import StaticFiles
    from sse_starlette.sse import EventSourceResponse
    from watchfiles import awatch
except ImportError as e:
    sys.exit(
        f"Missing dependency: {e.name}\n"
        f"Install with: pip install -r {Path(__file__).parent / 'requirements.txt'}"
    )

ROOT = campaign_lib.resolve_root()
# appconfig.BUNDLE is the repo root normally and the PyInstaller bundle when
# frozen — where __file__ points at neither.
STATIC = appconfig.BUNDLE / "webapp" / "static"
CHARACTERS_DIR = ROOT / "characters"
IMAGES_DIR = CHARACTERS_DIR / "images"
STATE_DIR = ROOT / "state"

FEED_FILE = STATE_DIR / "player-feed.jsonl"
DEVLOG_FILE = STATE_DIR / "dev-log.jsonl"  # written by desktop/agent.py
CURRENT_FILE = STATE_DIR / "current.json"
QUESTS_FILE = STATE_DIR / "quests.json"
COMBAT_FILE = STATE_DIR / "combat.json"
FLAGS_FILE = STATE_DIR / "world-flags.json"
DRAMATIS_FILE = STATE_DIR / "dramatis-personae.json"
SETTINGS_FILE = STATE_DIR / "settings.json"
ACTIVITY_FILE = STATE_DIR / "dm-activity.json"  # written by desktop/agent.py

DISPLAY_KEYS = {
    "id", "name", "player", "race", "class", "subclass", "level", "xp",
    "hp", "ac", "speed", "initiative_bonus", "passive_perception",
    "conditions", "exhaustion", "death_saves",
    "abilities", "proficiency_bonus", "languages", "proficiencies",
    "skills", "save_proficiencies", "hit_dice",
    "features", "attacks", "spells", "inventory", "gold",
    "background", "alignment", "personality", "appearance",
}

app = FastAPI(title="Campaign Companion")
app.mount("/static", StaticFiles(directory=str(STATIC)), name="static")


@app.middleware("http")
async def no_cache_static(request: Request, call_next):
    # Local single-user app: stale cached JS/CSS costs more than re-fetching it.
    response = await call_next(request)
    response.headers["Cache-Control"] = "no-cache"
    return response


# ── Helpers ────────────────────────────────────────────────────────────────────

def read_json(path: Path) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return None


def char_display_subset(path: Path) -> dict | None:
    raw = read_json(path)
    if not raw or not isinstance(raw, dict) or "name" not in raw:
        return None
    return {k: v for k, v in raw.items() if k in DISPLAY_KEYS}


def load_characters() -> list[dict]:
    """Sheets of current party members only (in party order). Sheets for
    departed guests stay on disk as history but don't render."""
    party = (read_json(CURRENT_FILE) or {}).get("party", [])
    chars = []
    for path in sorted(CHARACTERS_DIR.glob("*.json")):
        subset = char_display_subset(path)
        if subset and subset.get("id") in party:
            chars.append(subset)
    order = {pc_id: i for i, pc_id in enumerate(party)}
    chars.sort(key=lambda c: order.get(c.get("id"), len(order)))
    return chars


def load_quests() -> list[dict]:
    data = read_json(QUESTS_FILE)
    if not data:
        return []
    visible = []
    for q in data.get("active", []):
        if not q.get("known_to_party", False):
            continue
        q = dict(q)
        q.pop("secret_truth", None)
        q.pop("obstacles", None)  # GM planning detail
        visible.append(q)
    return visible


def load_dramatis() -> list[dict]:
    """Who's Who cheat sheet. Only known_to_party entries, whitelisted keys."""
    data = read_json(DRAMATIS_FILE)
    if not data:
        return []
    visible = []
    for c in data.get("characters", []):
        if not c.get("known_to_party", False):
            continue
        visible.append({k: c[k] for k in ("name", "disposition", "note", "category") if k in c})
    return visible


def load_quest_hooks() -> list[dict]:
    """Not-yet-started adventures. Opt-in like world-flag facts: only hooks
    with a 'pitch' (player-facing sentence) are shown; drop the pitch when the
    table abandons or outgrows a hook and it vanishes while staying DM history."""
    data = read_json(QUESTS_FILE)
    if not data:
        return []
    return [
        {k: h[k] for k in ("title", "pitch") if k in h}
        for h in data.get("hooks", [])
        if h.get("pitch")
    ]


def load_world_flags() -> dict:
    data = read_json(FLAGS_FILE)
    if not data:
        return {}
    flags = data.get("flags", {})
    # Player display is opt-in: only flags with a 'fact' (a self-contained,
    # in-world sentence) reach the Known Facts panel. 'note' is DM history
    # shorthand and never shown.
    return {
        k: v["fact"]
        for k, v in flags.items()
        if v.get("value") is True and v.get("fact")
    }


def load_combat() -> dict | None:
    data = read_json(COMBAT_FILE)
    if not data or not data.get("active", False):
        return None
    return data


def load_feed(limit: int = 50) -> list[dict]:
    if not FEED_FILE.exists():
        return []
    entries = []
    try:
        lines = FEED_FILE.read_text(encoding="utf-8").splitlines()
        for line in lines[-limit:]:
            line = line.strip()
            if line:
                entries.append(json.loads(line))
    except Exception:
        pass
    return entries


def load_settings() -> dict:
    return campaign_lib.load_settings(ROOT)


def load_dm_activity() -> dict:
    """What the DM is doing right now — player-safe labels from desktop/agent.py."""
    data = read_json(ACTIVITY_FILE)
    if not isinstance(data, dict):
        return {"busy": False, "steps": []}
    return {"busy": bool(data.get("busy")), "steps": data.get("steps") or []}


def build_state_snapshot() -> dict:
    return {
        "dm_activity": load_dm_activity(),
        "characters": load_characters(),
        "current": read_json(CURRENT_FILE) or {},
        "quests": load_quests(),
        "quest_hooks": load_quest_hooks(),
        "world_flags": load_world_flags(),
        "dramatis": load_dramatis(),
        "combat": load_combat(),
        "feed": load_feed(50),
        "settings": load_settings(),
    }


def read_new_feed_lines(byte_pos: int, jsonl: Path | None = None) -> tuple[list[dict], int]:
    """Read new lines from a JSONL file (FEED_FILE by default) starting at
    byte_pos. Returns (entries, new_pos)."""
    jsonl = jsonl or FEED_FILE
    if not jsonl.exists():
        return [], byte_pos
    try:
        if jsonl.stat().st_size < byte_pos:
            byte_pos = 0  # file was truncated/rewritten — start over (client dedupes)
        with open(jsonl, "rb") as f:
            f.seek(byte_pos)
            new_bytes = f.read()
            new_pos = byte_pos + len(new_bytes)
        entries = []
        for line in new_bytes.decode("utf-8", errors="replace").splitlines():
            line = line.strip()
            if line:
                try:
                    entries.append(json.loads(line))
                except json.JSONDecodeError:
                    pass
        return entries, new_pos
    except Exception:
        return [], byte_pos


def build_sidebar_payload() -> dict:
    return {
        "quests": load_quests(),
        "quest_hooks": load_quest_hooks(),
        "world_flags": load_world_flags(),
        "dramatis": load_dramatis(),
        "current": read_json(CURRENT_FILE) or {},
    }


# ── Routes ─────────────────────────────────────────────────────────────────────

@app.get("/")
async def index():
    """First run has no API key yet, so the setup screen stands in for the table."""
    if not appconfig.is_ready():
        return FileResponse(str(STATIC / "setup.html"))
    return FileResponse(str(STATIC / "index.html"))


# ── Setup (first run) ─────────────────────────────────────────────────────────

def list_pregens() -> list[dict]:
    """Setup-screen card data for every character sheet on disk."""
    cards = []
    for path in sorted(CHARACTERS_DIR.glob("*.json")):
        raw = read_json(path)
        if not raw or not isinstance(raw, dict) or "name" not in raw:
            continue
        cards.append({
            "id": raw.get("id", path.stem),
            "name": raw["name"],
            "race": raw.get("race", ""),
            "class": raw.get("class", ""),
            "blurb": (raw.get("personality", {}).get("traits") or [""])[0],
        })
    return cards


def seat_party(party: list[dict]) -> list[str]:
    """Write the chosen characters into current.json:party and their player
    names into the sheets. Entries are {id, player}; unknown ids are refused
    so a typo can't seat a ghost."""
    known = {c["id"] for c in list_pregens()}
    ids = []
    for entry in party:
        pc_id = str(entry.get("id", ""))
        if pc_id not in known:
            raise HTTPException(status_code=400, detail=f"unknown character: {pc_id}")
        ids.append(pc_id)
        player = str(entry.get("player", "")).strip()
        sheet_path = CHARACTERS_DIR / f"{pc_id}.json"
        sheet = read_json(sheet_path)
        if player and sheet is not None:
            sheet["player"] = player
            sheet_path.write_text(json.dumps(sheet, indent=2, ensure_ascii=False) + "\n",
                                  encoding="utf-8")
    current = read_json(CURRENT_FILE) or {}
    current["party"] = ids
    CURRENT_FILE.write_text(json.dumps(current, indent=2, ensure_ascii=False) + "\n",
                            encoding="utf-8")
    return ids


def save_new_hero(sheet: dict) -> dict:
    """Validate a generated sheet, assign a unique id, write it, and return
    its picker card. Raises HTTPException on a malformed sheet."""
    if not isinstance(sheet, dict):
        raise HTTPException(status_code=400, detail="generated sheet is not an object")
    for key in ("name", "race", "class", "abilities", "hp"):
        if not sheet.get(key):
            raise HTTPException(status_code=400,
                                detail=f"generated sheet is missing '{key}'")
    slug = re.sub(r"[^a-z0-9]+", "-", sheet["name"].lower()).strip("-") or "hero"
    pc_id, n = f"pc-{slug}", 2
    while (CHARACTERS_DIR / f"{pc_id}.json").exists():
        pc_id, n = f"pc-{slug}-{n}", n + 1
    sheet["id"] = pc_id
    sheet.setdefault("player", "")
    (CHARACTERS_DIR / f"{pc_id}.json").write_text(
        json.dumps(sheet, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    return {
        "id": pc_id,
        "name": sheet["name"],
        "race": sheet.get("race", ""),
        "class": sheet.get("class", ""),
        "blurb": (sheet.get("personality", {}).get("traits") or [""])[0],
    }


@app.post("/api/heroes")
async def create_hero(request: Request):
    """Setup-screen character creation: free-text concept → saved sheet."""
    try:
        body = await request.json()
    except Exception:
        raise HTTPException(status_code=400, detail="invalid JSON")
    description = str(body.get("description", "")).strip()
    if not description:
        raise HTTPException(status_code=400, detail="Describe the hero first.")
    import agent
    try:
        sheet = await asyncio.to_thread(agent.generate_character, description)
    except agent.DMError as e:
        raise HTTPException(status_code=400, detail=str(e))
    return JSONResponse(save_new_hero(sheet))


def check_api_key(key: str) -> dict:
    """Ask OpenRouter whether a key works, so setup fails here and not mid-scene."""
    req = urllib.request.Request(
        "https://openrouter.ai/api/v1/key",
        headers={"Authorization": f"Bearer {key}"})
    # certifi, not system certs: python.org installs and frozen apps often
    # have no OpenSSL default CA path, and this must fail loud on a bad key,
    # never on a missing cert store.
    ctx = ssl.create_default_context(cafile=certifi.where())
    try:
        with urllib.request.urlopen(req, timeout=20, context=ctx) as resp:
            data = json.loads(resp.read().decode("utf-8")).get("data") or {}
        limit, usage = data.get("limit"), data.get("usage")
        if limit is not None and usage is not None:
            return {"ok": True, "credit": round(max(0.0, limit - usage), 2)}
        return {"ok": True, "credit": None}
    except urllib.error.HTTPError as e:
        if e.code in (401, 403):
            return {"ok": False,
                    "error": "OpenRouter didn't accept that key. Copy it again from "
                             "openrouter.ai/keys — it starts with 'sk-or-'."}
        return {"ok": False, "error": f"OpenRouter returned {e.code} checking the key."}
    except urllib.error.URLError:
        return {"ok": False,
                "error": "Couldn't reach OpenRouter. Check the internet connection."}


@app.get("/api/setup")
async def get_setup():
    return JSONResponse({
        "ready": appconfig.is_ready(),
        "has_key": bool(appconfig.api_key()),
        "campaign": (read_json(CURRENT_FILE) or {}).get("campaign", ""),
        "model": appconfig.model(),
        "models": [{"id": i, "label": label} for i, label in appconfig.MODEL_CHOICES],
        "pregens": list_pregens(),
        "party": (read_json(CURRENT_FILE) or {}).get("party", []),
    })


@app.post("/api/setup")
async def post_setup(request: Request):
    try:
        body = await request.json()
    except Exception:
        raise HTTPException(status_code=400, detail="invalid JSON")
    key = str(body.get("api_key", "")).strip()
    if key:
        result = await asyncio.to_thread(check_api_key, key)
        if not result["ok"]:
            raise HTTPException(status_code=400, detail=result["error"])
    elif not appconfig.api_key():
        raise HTTPException(status_code=400, detail="An OpenRouter API key is required.")
    else:
        result = {"credit": None}

    appconfig.save(api_key=key or None,
                   model=str(body.get("model") or "").strip() or None)
    name = str(body.get("campaign_name", "")).strip()
    if name:
        appconfig.set_campaign_name(name)

    party = body.get("party")
    if isinstance(party, list) and party:
        seat_party(party)

    # Open the session so the players are greeted instead of facing a blank feed.
    if body.get("start_session"):
        await SAY_QUEUE.put(
            "We're starting. Do the session start procedure, then greet us with a "
            "short recap and ask what we want to do."
            + (" The players already chose their characters on the setup screen "
               "(see current.json:party) — introduce those heroes in the opening "
               "scene instead of asking who's playing." if party else ""))
    return JSONResponse({"ok": True, "credit": result.get("credit")})


# ── Developer settings (hidden behind #dev) ───────────────────────────────────

@app.get("/api/dev")
async def get_dev():
    return JSONResponse({**appconfig.dev_settings(),
                         "registry": prompt_registry.registry(),
                         "models": [{"id": i, "label": label}
                                    for i, label in appconfig.MODEL_CHOICES]})


@app.post("/api/dev")
async def post_dev(request: Request):
    try:
        body = await request.json()
    except Exception:
        raise HTTPException(status_code=400, detail="invalid JSON")
    unknown = set(body) - set(appconfig.DEV_DEFAULTS)
    if unknown:
        raise HTTPException(status_code=400, detail=f"unknown fields: {sorted(unknown)}")

    if "prompts" in body:
        chosen = body["prompts"]
        if not isinstance(chosen, dict):
            raise HTTPException(status_code=400, detail="prompts must be an object")
        for role, variant in chosen.items():
            if role not in prompt_registry.ROLES:
                raise HTTPException(status_code=400, detail=f"unknown role: {role}")
            if variant not in prompt_registry.variants(role):
                raise HTTPException(
                    status_code=400,
                    detail=f"{role} has no variant {variant!r} — add "
                           f"prompts/{role}/{variant}.md first")
    if "role_models" in body:
        role_models = body["role_models"]
        if not isinstance(role_models, dict):
            raise HTTPException(status_code=400, detail="role_models must be an object")
        for role, model_id in role_models.items():
            if role not in prompt_registry.ROLES:
                raise HTTPException(status_code=400, detail=f"unknown role: {role}")
            if not isinstance(model_id, str):
                raise HTTPException(status_code=400,
                                    detail=f"model for {role} must be a string")

    for field in ("history_tokens", "recursion_limit"):
        if field in body and not (isinstance(body[field], int) and body[field] > 0):
            raise HTTPException(status_code=400, detail=f"{field} must be a positive int")
    if "verbose" in body and not isinstance(body["verbose"], bool):
        raise HTTPException(status_code=400, detail="verbose must be a boolean")

    appconfig.save(**body)
    return JSONResponse({**appconfig.dev_settings(),
                         "registry": prompt_registry.registry()})


@app.get("/api/devlog")
async def get_devlog():
    """Last 200 tool call/result entries for the Dev Log sidebar."""
    if not DEVLOG_FILE.exists():
        return JSONResponse([])
    entries = []
    for line in DEVLOG_FILE.read_text(encoding="utf-8").splitlines()[-200:]:
        try:
            entries.append(json.loads(line))
        except json.JSONDecodeError:
            pass
    return JSONResponse(entries)


@app.post("/api/dev/reset-thread")
async def reset_thread():
    """Drop the DM's conversation, keeping all campaign state — a clean A/B arm."""
    import agent
    await asyncio.to_thread(agent.reset_thread)
    campaign_lib.append_feed(ROOT, "The DM takes a moment to gather their notes.",
                             type="system")
    return JSONResponse({"ok": True})


@app.get("/api/state")
async def state():
    return JSONResponse(build_state_snapshot())


@app.get("/api/settings")
async def get_settings():
    return JSONResponse(load_settings())


@app.post("/api/settings")
async def post_settings(request: Request):
    try:
        body = await request.json()
    except Exception:
        raise HTTPException(status_code=400, detail="invalid JSON")
    if not isinstance(body, dict):
        raise HTTPException(status_code=400, detail="expected an object")
    settings = load_settings()
    unknown = set(body) - set(campaign_lib.DEFAULT_SETTINGS)
    if unknown:
        raise HTTPException(status_code=400, detail=f"unknown settings: {sorted(unknown)}")
    settings.update(body)
    SETTINGS_FILE.parent.mkdir(parents=True, exist_ok=True)
    SETTINGS_FILE.write_text(json.dumps(settings, indent=2, ensure_ascii=False) + "\n",
                             encoding="utf-8")
    return JSONResponse(settings)


PORTRAIT_TYPES = {"image/png": ".png", "image/jpeg": ".jpg", "image/webp": ".webp"}
PORTRAIT_MAX_BYTES = 10 * 1024 * 1024


def save_portrait(pc_id: str, content_type: str, data: bytes) -> Path:
    """Write a portrait for an existing character. Raises ValueError on bad input."""
    if not (CHARACTERS_DIR / f"{pc_id}.json").exists():
        raise ValueError(f"no such character: {pc_id}")  # also blocks path traversal
    ext = PORTRAIT_TYPES.get(content_type)
    if not ext:
        raise ValueError(f"unsupported image type: {content_type or 'unknown'} (png/jpeg/webp)")
    if not data or len(data) > PORTRAIT_MAX_BYTES:
        raise ValueError("image is empty or over 10 MB")
    IMAGES_DIR.mkdir(parents=True, exist_ok=True)
    # drop other-extension variants so the old image can't shadow the new one
    for old_ext in PORTRAIT_TYPES.values():
        if old_ext != ext:
            (IMAGES_DIR / f"{pc_id}{old_ext}").unlink(missing_ok=True)
    path = IMAGES_DIR / f"{pc_id}{ext}"
    path.write_bytes(data)
    return path


@app.post("/api/portraits/{pc_id}")
async def upload_portrait(pc_id: str, request: Request):
    try:
        save_portrait(pc_id, request.headers.get("content-type", ""), await request.body())
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    return JSONResponse({"ok": True, "id": pc_id})


@app.get("/api/portraits/{pc_id}")
async def portrait(pc_id: str):
    # Build list of candidate stems: the id itself, then player-name variants
    stems = [pc_id]
    char_file = CHARACTERS_DIR / f"{pc_id}.json"
    if char_file.exists():
        char = read_json(char_file)
        if char and char.get("player"):
            player = char["player"].lower().replace(" ", "-")
            stems.append(f"pc-{player}")
            stems.append(player)

    for stem in stems:
        for ext in (".png", ".jpg", ".jpeg", ".webp"):
            candidate = IMAGES_DIR / f"{stem}{ext}"
            if candidate.exists():
                return FileResponse(str(candidate))
    raise HTTPException(status_code=404, detail="Portrait not found")


# ── Player input → the DM ─────────────────────────────────────────────────────
# The chat box sends a message; it lands in the feed immediately as a "player"
# entry, then a single worker runs it through the LangGraph DM (desktop/agent.py)
# one turn at a time. Serialising turns is what keeps two DMs from writing
# campaign state at once.

SAY_QUEUE: asyncio.Queue = asyncio.Queue()

DM_BUSY = False

# A sitting that ends by closing the laptop never says "let's wrap". When the
# table comes back after a long gap, the DM's next turn is nudged to do the
# session-wrap bookkeeping quietly and reopen with a short recap.
IDLE_GAP_HOURS = 6


def idle_gap_hours() -> float | None:
    """Hours since the newest chronicle entry; None for an empty feed."""
    entries = load_feed(1)
    ts = entries[-1].get("ts") if entries else None
    if not ts:
        return None
    from datetime import datetime
    try:
        # campaign_lib stamps "...Z"; fromisoformat only takes that on 3.11+
        last = datetime.fromisoformat(ts.replace("Z", "+00:00"))
        return (datetime.now(last.tzinfo) - last).total_seconds() / 3600
    except ValueError:
        return None


def idle_nudge(gap: float) -> str:
    return (f"(Out of character, from the app: the table is back after about "
            f"{int(gap)} hours away. If the previous sitting was never wrapped, "
            "quietly do the session-wrap bookkeeping first — session log, "
            "rolling recap, XP; see .claude/skills/session-wrap/SKILL.md — "
            "then greet the players with a 2-3 sentence recap before answering "
            "what they say below.)\n\n")


async def dm_worker():
    global DM_BUSY
    while True:
        text = await SAY_QUEUE.get()
        DM_BUSY = True
        try:
            import agent  # imported lazily: langgraph is slow to load
            # The agent blocks on network and tool I/O, so keep it off the loop.
            await asyncio.to_thread(agent.run_turn, text)
        except Exception as e:
            import agent
            message = str(e) if isinstance(e, agent.DMError) else (
                "The DM hit an unexpected problem and skipped that. "
                "Try saying it again.")
            campaign_lib.append_feed(ROOT, message, type="system")
            if not isinstance(e, agent.DMError):
                traceback.print_exc()
        finally:
            DM_BUSY = False
            SAY_QUEUE.task_done()


@app.on_event("startup")
async def start_worker():
    # An app killed mid-turn leaves dm-activity.json claiming busy forever.
    try:
        ACTIVITY_FILE.parent.mkdir(parents=True, exist_ok=True)
        ACTIVITY_FILE.write_text('{"busy": false, "steps": []}\n', encoding="utf-8")
    except OSError:
        pass
    asyncio.create_task(dm_worker())


@app.post("/api/say")
async def say(request: Request):
    try:
        body = await request.json()
    except Exception:
        raise HTTPException(status_code=400, detail="invalid JSON")
    text = str(body.get("text", "")).strip()[:2000]
    if not text:
        raise HTTPException(status_code=400, detail="text required")
    if not appconfig.api_key():
        raise HTTPException(status_code=503,
                            detail="No OpenRouter API key set — open Settings.")
    # One turn at a time, visibly: a message sent mid-turn used to queue
    # silently and land after the reply, which read as the DM ignoring it
    # (table request). The chat box disables itself while the DM works; this
    # guard covers a second device or a stale page.
    if DM_BUSY or SAY_QUEUE.qsize():
        raise HTTPException(status_code=409,
                            detail="The DM is still working on the last message "
                                   "— wait for the reply.")
    gap = idle_gap_hours()  # before the append below becomes the newest entry
    campaign_lib.append_feed(ROOT, text, type="player")
    if gap and gap > IDLE_GAP_HOURS:
        text = idle_nudge(gap) + text
    await SAY_QUEUE.put(text)
    return JSONResponse({"ok": True, "queued": SAY_QUEUE.qsize()})


@app.get("/api/dm")
async def dm_status():
    """Lets the chat box show that the DM is still thinking."""
    return JSONResponse({"busy": DM_BUSY, "queued": SAY_QUEUE.qsize()})


@app.get("/events")
async def events(request: Request):
    async def generator():
        byte_pos = FEED_FILE.stat().st_size if FEED_FILE.exists() else 0
        devlog_pos = DEVLOG_FILE.stat().st_size if DEVLOG_FILE.exists() else 0
        # No-spoiler rule: combat.json changes (HP drain, conditions) must not hit
        # the players' screen before the narration that explains them. Hold the
        # update and flush it with the next feed entry.
        combat_pending = False

        try:
            async for changes in awatch(str(STATE_DIR), str(CHARACTERS_DIR)):
                if await request.is_disconnected():
                    break

                for _change_type, changed_path in changes:
                    path = Path(changed_path)

                    if path.name == "player-feed.jsonl":
                        new_entries, byte_pos = read_new_feed_lines(byte_pos)
                        for entry in new_entries:
                            yield {
                                "event": "feed_entry",
                                "data": json.dumps(entry),
                            }
                        if new_entries and combat_pending:
                            combat_pending = False
                            yield {
                                "event": "combat_update",
                                "data": json.dumps(load_combat()),
                            }

                    elif path.parent == IMAGES_DIR:
                        yield {
                            "event": "portrait_update",
                            "data": json.dumps({"stem": path.stem}),
                        }

                    elif path.parent == CHARACTERS_DIR and path.suffix == ".json":
                        subset = char_display_subset(path)
                        if subset:
                            yield {
                                "event": "character_update",
                                "data": json.dumps(subset),
                            }

                    elif path.name == "combat.json":
                        combat = load_combat()
                        if combat is None:
                            # combat ended — safe to clear the bar immediately
                            combat_pending = False
                            yield {
                                "event": "combat_update",
                                "data": json.dumps(combat),
                            }
                        else:
                            combat_pending = True

                    elif path.name == "current.json":
                        current = read_json(CURRENT_FILE) or {}
                        yield {
                            "event": "state_update",
                            "data": json.dumps(current),
                        }

                    elif path.name == "dm-activity.json":
                        yield {
                            "event": "dm_activity",
                            "data": json.dumps(load_dm_activity()),
                        }

                    elif path.name == "dev-log.jsonl":
                        new_entries, devlog_pos = read_new_feed_lines(
                            devlog_pos, DEVLOG_FILE)
                        for entry in new_entries:
                            yield {
                                "event": "dev_log",
                                "data": json.dumps(entry),
                            }

                    elif path.name == "settings.json":
                        yield {
                            "event": "settings_update",
                            "data": json.dumps(load_settings()),
                        }

                    elif path.name in ("quests.json", "world-flags.json", "dramatis-personae.json"):
                        yield {
                            "event": "sidebar_update",
                            "data": json.dumps(build_sidebar_payload()),
                        }
        except asyncio.CancelledError:
            pass

    return EventSourceResponse(generator())


# ── Entry point ────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    uvicorn.run("server:app", host="0.0.0.0", port=8765, reload=False, app_dir=str(Path(__file__).parent))
