"""
Shared plumbing for the campaign tools and webapp server.

Campaign root resolution (in order):
  1. CAMPAIGN_ROOT env var — explicit override; tests use it
  2. campaigns/active.json — the active-adventure pointer, written by
     tools/set_campaign.py during session-start step 0 (or when a new
     campaign is created); this is the normal path during play
  3. <repo>/campaign — legacy single-campaign location, kept as a fallback

All campaign state lives under that root: state/, characters/, sessions/,
npcs/, world/, factions/, house-rules.md. The code in tools/ and webapp/
never hardcodes campaign or character specifics.

Feed contract — every entry in state/player-feed.jsonl is:
  {id, ts, type, text, location, session[, effects]}
where `effects` is a list of short mechanical strings ("Goblin1 takes 7
damage (now 3 HP)") rendered by the web companion as subtext under the
prose that explains them. Tools that change state during play queue
effects (queue_effect) instead of posting them to the feed directly;
narrate.py drains the queue (drain_effects) and attaches them to the next
narration entry, so mechanics never land on the players' screen before
the story does.
"""
from __future__ import annotations

import json
import os
import re
import sys
import uuid
from datetime import datetime, timezone
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent

# Live adventure saves nest two levels down: campaigns/<system>/<slug>/.
# The template at campaigns/starter/ is one level, so save scans never match it.
CAMPAIGNS_DIR = REPO / "campaigns"

# The active-adventure pointer. Session-start step 0 (a conversation, not
# terminal work) writes it via tools/set_campaign.py; every tool and the
# webapp then resolve the campaign from it with no env var needed.
ACTIVE_FILE = CAMPAIGNS_DIR / "active.json"

FEED_TYPES = ("narration", "scene_change", "system", "player", "combat")

# Table settings — steering knobs the players/DM flip in the webapp Settings
# tab (written to state/settings.json). The DM LLM reads these at session
# start and sees them echoed in every narrate.py result. What each one means
# is documented in CLAUDE.md "Table settings".
DEFAULT_SETTINGS = {
    "rules_strictness": "flexible",   # "strict" (RAW, no fudging outcomes) | "flexible" (Director may soften per house rules)
    "beginner_mode": False,           # DM may suggest options/reminders to help newer players decide
    "show_rolls": False,              # public dice outcomes appear as subtext in the chronicle
    "kid_friendly": False,            # keep descriptions of violence/horror gentle
    "narration_style": "standard",    # "brief" | "standard" | "cinematic"
    "custom_rules": "",               # free-text house rules, read as if part of house-rules.md "Active"
}


def slugify(name: str) -> str:
    """Directory-safe slug for a campaign or system name."""
    slug = re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")
    if not slug:
        sys.exit(f"can't make a directory name out of {name!r}")
    return slug


def list_campaigns(system: str | None = None, sort: str = "last_played") -> list[dict]:
    """Discover adventure saves under campaigns/<system>/<slug>/.

    Returns [{slug, system, name, path, last_played}] — name and system read
    from state/current.json, last_played from that file's mtime (state writes
    touch it every session). `system` filters to one system slug; `sort` is
    "last_played" (newest first), "name", or "system" (system then name).
    """
    saves = []
    active = get_active()
    for current_file in sorted(CAMPAIGNS_DIR.glob("*/*/state/current.json")):
        save_dir = current_file.parent.parent
        try:
            current = json.loads(current_file.read_text(encoding="utf-8"))
        except Exception:
            continue
        try:
            path = save_dir.relative_to(REPO)
        except ValueError:
            path = save_dir
        entry = {
            "slug": save_dir.name,
            "system": current.get("system", save_dir.parent.name),
            "name": current.get("campaign", save_dir.name),
            "path": path.as_posix(),
            "last_played": datetime.fromtimestamp(
                current_file.stat().st_mtime, tz=timezone.utc
            ).isoformat().replace("+00:00", "Z"),
            "active": active is not None and save_dir.resolve() == active.resolve(),
        }
        if system and entry["system"] != system:
            continue
        saves.append(entry)
    if sort == "name":
        saves.sort(key=lambda s: s["name"].lower())
    elif sort == "system":
        saves.sort(key=lambda s: (s["system"], s["name"].lower()))
    else:  # last_played
        saves.sort(key=lambda s: s["last_played"], reverse=True)
    return saves


def get_active() -> Path | None:
    """The save the active-adventure pointer names, or None if unset/stale."""
    try:
        data = json.loads(ACTIVE_FILE.read_text(encoding="utf-8"))
        path = Path(data["path"])
        if not path.is_absolute():
            path = REPO / path
        if (path / "state" / "current.json").exists():
            return path
    except Exception:
        pass
    return None


def set_active(save_dir: Path) -> dict:
    """Point the active-adventure file at a save. Returns what was written."""
    current = json.loads((save_dir / "state" / "current.json").read_text(encoding="utf-8"))
    try:
        path = save_dir.relative_to(REPO)
    except ValueError:
        path = save_dir
    record = {
        "path": path.as_posix(),
        "slug": save_dir.name,
        "system": current.get("system", "unknown"),
        "name": current.get("campaign", save_dir.name),
        "set_at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
    }
    ACTIVE_FILE.parent.mkdir(parents=True, exist_ok=True)
    ACTIVE_FILE.write_text(json.dumps(record, indent=2, ensure_ascii=False) + "\n",
                           encoding="utf-8")
    return record


def resolve_root() -> Path:
    env = os.environ.get("CAMPAIGN_ROOT")
    if env:
        return Path(env)
    active = get_active()
    if active is not None:
        return active
    root = REPO / "campaign"
    if root.is_dir():
        return root
    sys.exit(
        "No active adventure selected.\n"
        "Pick one:     python tools/set_campaign.py <slug>\n"
        "List saves:   python tools/list_campaigns.py\n"
        "Start one:    python tools/new_campaign.py --name 'My Campaign'\n"
        "(CAMPAIGN_ROOT env var overrides the pointer when set.)"
    )


def _feed_context(root: Path) -> tuple[str, str]:
    """(location, session) for feed entries. Never raises."""
    try:
        current = json.loads((root / "state" / "current.json").read_text(encoding="utf-8"))
        loc = current.get("location", {}).get("specific", "unknown")
    except Exception:
        loc = "unknown"
    sessions = sorted((root / "sessions").glob("session-[0-9]*.md"), reverse=True)
    return loc, (sessions[0].stem if sessions else "unknown")


def append_feed(root: Path, text: str, type: str = "narration",
                effects: list[str] | None = None) -> dict:
    """Append one standardized entry to the player feed. Returns the entry."""
    loc, session = _feed_context(root)
    entry = {
        "id": uuid.uuid4().hex,
        "ts": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        "type": type,
        "text": text,
        "location": loc,
        "session": session,
    }
    if effects:
        entry["effects"] = effects
    feed = root / "state" / "player-feed.jsonl"
    feed.parent.mkdir(parents=True, exist_ok=True)
    with open(feed, "a", encoding="utf-8") as f:
        f.write(json.dumps(entry, ensure_ascii=False) + "\n")
    return entry


def load_settings(root: Path) -> dict:
    """Current table settings, with defaults for anything unset."""
    settings = dict(DEFAULT_SETTINGS)
    try:
        data = json.loads((root / "state" / "settings.json").read_text(encoding="utf-8"))
        settings.update({k: v for k, v in data.items() if k in DEFAULT_SETTINGS})
    except Exception:
        pass
    return settings


def queue_public_effects(texts: list[str]) -> None:
    """Queue effects only if the table's show_rolls setting is on.

    Used by the dice tools for open-roll mode. Safe with no campaign
    present (bare tool use) — it just does nothing.
    """
    try:
        root = resolve_root()
    except SystemExit:
        return
    if load_settings(root).get("show_rolls"):
        for t in texts:
            queue_effect(root, t)


def queue_effect(root: Path, text: str) -> None:
    """Queue a mechanical change for the next narration instead of spoiling it now."""
    pending = root / "state" / "pending-effects.jsonl"
    pending.parent.mkdir(parents=True, exist_ok=True)
    with open(pending, "a", encoding="utf-8") as f:
        f.write(json.dumps(text, ensure_ascii=False) + "\n")


def drain_effects(root: Path) -> list[str]:
    """Return and clear all queued effects."""
    pending = root / "state" / "pending-effects.jsonl"
    if not pending.exists():
        return []
    effects = []
    for line in pending.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            effects.append(str(json.loads(line)))
        except json.JSONDecodeError:
            pass
    pending.unlink()
    return effects
