#!/usr/bin/env python3
"""
Append a Narrator prose entry to <campaign>/state/player-feed.jsonl.
The FastAPI server watches this file and streams new entries via SSE to the
web companion.

Usage:
    python tools/narrate.py "Your prose here."
    python tools/narrate.py "Scene changed." --type scene_change
    python tools/narrate.py "Combat begins." --type system
    python tools/narrate.py - <<'EOF'          # read prose from stdin —
    Long prose with "quotes" and $shell chars,  # no escaping headaches
    multiple paragraphs, anything.
    EOF

Mechanical changes queued by other tools (combat damage, public rolls) are
drained from state/pending-effects.jsonl and attached to this entry as
`effects` — the web companion shows them as subtext under the prose, so
the story lands before the numbers. Add extra one-off effects inline:

    python tools/narrate.py "The potion works." --effect "Ren regains 7 HP (now 21/28)"

Output: the appended feed entry as JSON, plus the current table settings
(from the webapp Settings tab) so the DM notices steering changes mid-session.
"""
import argparse
import json
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import campaign_lib


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
    p.add_argument("text", help="Prose text (no leading '> '), or '-' to read from stdin")
    p.add_argument(
        "--type",
        default="narration",
        choices=["narration", "scene_change", "system", "player"],
        help="Entry type (default: narration)",
    )
    p.add_argument("--effect", action="append", default=[],
                   help="mechanical change to show as subtext; repeatable")
    args = p.parse_args()

    raw = sys.stdin.read() if args.text == "-" else args.text
    text = normalize(raw)
    if not text:
        print("narrate.py: text is empty after normalization; nothing pushed", file=sys.stderr)
        return 1

    root = campaign_lib.resolve_root()
    effects = campaign_lib.drain_effects(root) + args.effect
    entry = campaign_lib.append_feed(root, text, type=args.type, effects=effects)

    print(json.dumps({"entry": entry, "settings": campaign_lib.load_settings(root)},
                     ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())
