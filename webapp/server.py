#!/usr/bin/env python3
"""
D&D Campaign Web Companion — FastAPI server.

Serves a read-only player-facing view of:
  - Character sheets (from characters/pc-*.json)
  - Live narration feed (from state/player-feed.jsonl, written by tools/narrate.py)
  - Quest log (known_to_party=True only, secret_truth stripped)
  - Current state: location, date, weather
  - Combat tracker (when active)

Start: python webapp/server.py
Opens on: http://localhost:8765
"""
import asyncio
import json
import sys
from pathlib import Path
from typing import Any

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

ROOT = Path(__file__).resolve().parent.parent
STATIC = Path(__file__).resolve().parent / "static"
CHARACTERS_DIR = ROOT / "characters"
IMAGES_DIR = CHARACTERS_DIR / "images"
STATE_DIR = ROOT / "state"
SESSIONS_DIR = ROOT / "sessions"

FEED_FILE = STATE_DIR / "player-feed.jsonl"
CURRENT_FILE = STATE_DIR / "current.json"
QUESTS_FILE = STATE_DIR / "quests.json"
COMBAT_FILE = STATE_DIR / "combat.json"
FLAGS_FILE = STATE_DIR / "world-flags.json"
DRAMATIS_FILE = STATE_DIR / "dramatis-personae.json"

DISPLAY_KEYS = {
    "id", "name", "player", "race", "class", "subclass", "level", "xp",
    "hp", "ac", "speed", "initiative_bonus", "passive_perception",
    "conditions", "exhaustion", "death_saves",
    "abilities", "proficiency_bonus", "languages", "proficiencies",
    "features", "attacks", "spells", "inventory", "gold",
    "background", "alignment", "personality", "appearance",
}

app = FastAPI(title="D&D Companion")
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


def load_characters() -> list[dict]:
    chars = []
    for path in sorted(CHARACTERS_DIR.glob("pc-*.json")):
        raw = read_json(path)
        if raw:
            chars.append({k: v for k, v in raw.items() if k in DISPLAY_KEYS})
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


def build_state_snapshot() -> dict:
    return {
        "characters": load_characters(),
        "current": read_json(CURRENT_FILE) or {},
        "quests": load_quests(),
        "world_flags": load_world_flags(),
        "dramatis": load_dramatis(),
        "combat": load_combat(),
        "feed": load_feed(50),
    }


def read_new_feed_lines(byte_pos: int) -> tuple[list[dict], int]:
    """Read new lines from FEED_FILE starting at byte_pos. Returns (entries, new_pos)."""
    if not FEED_FILE.exists():
        return [], byte_pos
    try:
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


def char_display_subset(path: Path) -> dict | None:
    raw = read_json(path)
    if not raw:
        return None
    return {k: v for k, v in raw.items() if k in DISPLAY_KEYS}


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

                    elif path.name.startswith("pc-") and path.suffix == ".json":
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
