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
import sys
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "tools"))
import campaign_lib

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
STATIC = Path(__file__).resolve().parent / "static"
CHARACTERS_DIR = ROOT / "characters"
IMAGES_DIR = CHARACTERS_DIR / "images"
STATE_DIR = ROOT / "state"

FEED_FILE = STATE_DIR / "player-feed.jsonl"
CURRENT_FILE = STATE_DIR / "current.json"
QUESTS_FILE = STATE_DIR / "quests.json"
COMBAT_FILE = STATE_DIR / "combat.json"
FLAGS_FILE = STATE_DIR / "world-flags.json"
DRAMATIS_FILE = STATE_DIR / "dramatis-personae.json"
SETTINGS_FILE = STATE_DIR / "settings.json"

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
    """Every character sheet, party members first (in party order)."""
    party = (read_json(CURRENT_FILE) or {}).get("party", [])
    chars = []
    for path in sorted(CHARACTERS_DIR.glob("*.json")):
        subset = char_display_subset(path)
        if subset:
            chars.append(subset)
    order = {pc_id: i for i, pc_id in enumerate(party)}
    chars.sort(key=lambda c: (order.get(c.get("id"), len(order)), c.get("name", "")))
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
        visible.append({k: c[k] for k in ("name", "disposition", "note") if k in c})
    return visible


def load_world_flags() -> dict:
    data = read_json(FLAGS_FILE)
    if not data:
        return {}
    flags = data.get("flags", {})
    return {k: v.get("note", k) for k, v in flags.items() if v.get("value") is True}


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


def build_state_snapshot() -> dict:
    return {
        "characters": load_characters(),
        "current": read_json(CURRENT_FILE) or {},
        "quests": load_quests(),
        "world_flags": load_world_flags(),
        "dramatis": load_dramatis(),
        "combat": load_combat(),
        "feed": load_feed(50),
        "settings": load_settings(),
    }


def read_new_feed_lines(byte_pos: int) -> tuple[list[dict], int]:
    """Read new lines from FEED_FILE starting at byte_pos. Returns (entries, new_pos)."""
    if not FEED_FILE.exists():
        return [], byte_pos
    try:
        if FEED_FILE.stat().st_size < byte_pos:
            byte_pos = 0  # feed was truncated/rewritten — start over (client dedupes by id)
        with open(FEED_FILE, "rb") as f:
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
        "world_flags": load_world_flags(),
        "dramatis": load_dramatis(),
        "current": read_json(CURRENT_FILE) or {},
    }


# ── Routes ─────────────────────────────────────────────────────────────────────

@app.get("/")
async def index():
    return FileResponse(str(STATIC / "index.html"))


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


@app.get("/events")
async def events(request: Request):
    async def generator():
        byte_pos = FEED_FILE.stat().st_size if FEED_FILE.exists() else 0

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
                        yield {
                            "event": "combat_update",
                            "data": json.dumps(combat),
                        }

                    elif path.name == "current.json":
                        current = read_json(CURRENT_FILE) or {}
                        yield {
                            "event": "state_update",
                            "data": json.dumps(current),
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
    uvicorn.run("server:app", host="127.0.0.1", port=8765, reload=False, app_dir=str(Path(__file__).parent))
