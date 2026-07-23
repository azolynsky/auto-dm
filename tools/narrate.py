#!/usr/bin/env python3
"""
Append a Narrator prose entry to state/player-feed.jsonl.
The FastAPI server watches this file and streams new entries via SSE to the web companion.

Usage:
    python tools/narrate.py "Your prose here."
    python tools/narrate.py "Scene changed." --type scene_change
    python tools/narrate.py "Combat begins." --type system
"""
import argparse
import json
import os
import re
import sys
import uuid
from datetime import datetime, timezone
from pathlib import Path

# DND_ROOT overrides the campaign root (used by tests; also lets one clone
# host multiple campaign directories).
ROOT = Path(os.environ.get("DND_ROOT") or Path(__file__).resolve().parent.parent)
FEED = ROOT / "state" / "player-feed.jsonl"
CURRENT = ROOT / "state" / "current.json"


def normalize(text: str) -> str:
    """Standardize prose for the chronicle feed.

    The feed renders as plain text (pre-wrap), so markdown syntax shows up
    literally. Strip the artifacts LLM DMs habitually paste in: leading
    blockquote '>' markers, **bold**/*italic*/_underscore_ emphasis, and
    '#' headers. Also tidy whitespace: no trailing spaces, at most one
    blank line between paragraphs.
    """
    lines = []
    for line in text.splitlines():
        line = re.sub(r"^\s*>\s?", "", line)          # blockquote marker
        line = re.sub(r"^\s*#{1,6}\s+", "", line)     # markdown header
        lines.append(line.rstrip())
    out = "\n".join(lines)
    out = re.sub(r"\*\*(.+?)\*\*", r"\1", out)        # **bold**
    out = re.sub(r"(?<![\w*])\*([^*\n]+)\*(?![\w*])", r"\1", out)  # *italic*
    out = re.sub(r"(?<!\w)_([^_\n]+)_(?!\w)", r"\1", out)          # _emphasis_
    out = re.sub(r"\n{3,}", "\n\n", out)              # collapse blank runs
    return out.strip()


def main() -> int:
    p = argparse.ArgumentParser(description="Push player-facing narration to the web companion.")
    p.add_argument("text", help="Prose text (no leading '> ')")
    p.add_argument(
        "--type",
        default="narration",
        choices=["narration", "scene_change", "system", "player"],
        help="Entry type (default: narration)",
    )
    args = p.parse_args()

    text = normalize(args.text)
    if not text:
        print("narrate.py: text is empty after normalization; nothing pushed", file=sys.stderr)
        return 1

    # Read context — fail gracefully, never block narration
    try:
        current = json.loads(CURRENT.read_text(encoding="utf-8"))
        loc = current.get("location", {}).get("specific", "unknown")
        session_files = sorted(
            (ROOT / "sessions").glob("session-[0-9]*.md"), reverse=True
        )
        session = session_files[0].stem if session_files else "unknown"
    except Exception:
        loc, session = "unknown", "unknown"

    entry = {
        "id": uuid.uuid4().hex,
        "ts": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        "type": args.type,
        "text": text,
        "location": loc,
        "session": session,
    }
    line = json.dumps(entry, ensure_ascii=False)

    FEED.parent.mkdir(parents=True, exist_ok=True)
    with open(FEED, "a", encoding="utf-8") as f:
        f.write(line + "\n")

    print(line)
    return 0


if __name__ == "__main__":
    sys.exit(main())
