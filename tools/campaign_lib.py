"""
Shared plumbing for the campaign tools and webapp server.

Campaign root resolution (in order):
  1. CAMPAIGN_ROOT env var — used by tests and by anyone hosting multiple campaigns
  2. <repo>/campaign — the active campaign directory

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
import sys
import uuid
from datetime import datetime, timezone
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent

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


def resolve_root() -> Path:
    env = os.environ.get("CAMPAIGN_ROOT")
    if env:
        return Path(env)
    root = REPO / "campaign"
    if root.is_dir():
        return root
    sys.exit(
        "No active campaign found.\n"
        f"Expected {root} (or set CAMPAIGN_ROOT).\n"
        "Start one from the template:  python tools/new_campaign.py --name 'My Campaign'"
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
