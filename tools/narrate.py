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
import datetime
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


def entries_behind(root: Path, filename: str) -> int:
    """How many narration/scene_change entries landed since the given state
    file was last written. The DM sees this on every narrate call — the
    players are reading the sidebar while the chronicle moves, so drift is
    loud."""
    target = root / "state" / filename
    feed = root / "state" / "player-feed.jsonl"
    if not target.exists() or not feed.exists():
        return 0
    cutoff = datetime.datetime.fromtimestamp(
        target.stat().st_mtime, datetime.timezone.utc
    ).isoformat().replace("+00:00", "Z")
    n = 0
    for line in feed.read_text().splitlines():
        try:
            e = json.loads(line)
        except json.JSONDecodeError:
            continue
        if e.get("type") in ("narration", "scene_change") and e.get("ts", "") > cutoff:
            n += 1
    return n


STOPWORDS = {"the", "dark", "black", "king", "lady", "lord", "old", "young"}

# Banned-habit reflexes from .claude/agents/narrator.md that recur despite the
# list. Narrow, high-precision regexes only — this gate blocks publishing, so
# a false positive costs a rewrite while a miss costs nothing new.
STYLE_PATTERNS = [
    (r"\blike (?:a|an|two|some)?\s?(?:man|men|woman|women|boy|boys|girl|girls|"
     r"child|children|person|people|sailor|soldier|merchant|schoolboy)s?\b",
     "action-vs-action simile ('like a man ...-ing') — say the plain thing instead"),
    (r"\bthe way (?:he|she|they|it)\b(?:'d| would)?",
     "'the way X does Y' comparison — a simile in costume; say what actually happens"),
    (r"\b(?:landslide|avalanche|rockslide)\b",
     "landslide-family comparison — banned outright (table, sessions 7 and 11)"),
    (r"\bcracks? (?:his|her|their) knuckles\b|\brolls? (?:his|her|their) shoulders\b"
     r"|\bcocks? an eyebrow\b|\b(?:a|the) breath (?:he|she|they|it)\b",
     "stock body-language tic — give a gesture that's theirs, or none"),
    (r"^[^\"“]*\bwhat (?:do you (?:want|wish) to do|would you like to do|"
     r"do you do)\b",
     "out-of-world prompt to the players — end on the scene, not a menu; "
     "the table decides what to do without being asked (table request)"),
    (r"(?:^\s*(?:[-•*]|\d+[.)])\s.+\n?){2,}\s*\Z",
     "closing option menu — narration never ends in a bullet list of choices; "
     "if beginner guidance is needed, give it out-of-character in one sentence"),
]


def style_violations(text: str) -> list:
    """Match prose against the recurring banned-habit patterns. Returns
    [{'match': ..., 'why': ...}] — used to block publishing until rewritten."""
    hits = []
    for pattern, why in STYLE_PATTERNS:
        for m in re.finditer(pattern, text, re.IGNORECASE | re.MULTILINE):
            hits.append({"match": m.group(0), "why": why})
    return hits


def sidebar_mentions(root: Path, text: str) -> dict:
    """Who's Who notes for every character named in this narration. Echoed
    back so the DM re-reads each note at the exact moment it could have just
    become wrong — the enforcement behind 'keep the sidebar honest'."""
    dramatis = root / "state" / "dramatis-personae.json"
    if not dramatis.exists():
        return {}
    try:
        chars = json.loads(dramatis.read_text()).get("characters", [])
    except json.JSONDecodeError:
        return {}
    low = text.lower()
    hits = {}
    for c in chars:
        name = c.get("name", "")
        tokens = [w for w in re.findall(r"[A-Za-z']{4,}", name)
                  if w.lower() not in STOPWORDS] or [name]
        if any(re.search(r"\b" + re.escape(t.lower()) + r"\b", low) for t in tokens):
            hits[name] = c.get("note", "")
    return hits


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
    p.add_argument("--intent", default=None,
                   help="what the players actually said/did that prompted this beat; "
                        "stored in the archive for the end-of-campaign book, never shown in-game")
    p.add_argument("--force-style", action="store_true",
                   help="publish despite banned-style matches (deliberate use only)")
    args = p.parse_args()

    raw = sys.stdin.read() if args.text == "-" else args.text
    text = normalize(raw)
    if not text:
        print("narrate.py: text is empty after normalization; nothing pushed", file=sys.stderr)
        return 1

    if args.type in ("narration", "scene_change") and not args.force_style:
        hits = style_violations(text)
        if hits:
            print(json.dumps({
                "published": False,
                "STYLE_BLOCK": "Prose matches the Narrator's banned-habits list. "
                               "Rewrite the flagged lines and push again "
                               "(--force-style only for a deliberate false positive).",
                "violations": hits,
            }, ensure_ascii=False))
            return 1

    root = campaign_lib.resolve_root()
    effects = campaign_lib.drain_effects(root) + args.effect
    entry = campaign_lib.append_feed(root, text, type=args.type, effects=effects,
                                     intent=args.intent)

    out = {"entry": entry, "settings": campaign_lib.load_settings(root)}
    behind = entries_behind(root, "quests.json")
    cast_behind = entries_behind(root, "dramatis-personae.json")
    out["quests_sidebar"] = f"quests.json last written {behind} chronicle entries ago"
    out["whos_who_sidebar"] = (
        f"dramatis-personae.json last written {cast_behind} chronicle entries ago"
    )
    mentions = sidebar_mentions(root, text)
    if mentions:
        out["sidebar_check"] = mentions
        out["sidebar_check_hint"] = (
            "These Who's Who notes are on the players' screen for characters in "
            "this narration. If this beat made any of them wrong, update "
            "dramatis-personae.json NOW, before the next narration."
        )
    warnings = []
    if behind >= 6:
        warnings.append(
            "quests.json is STALE — the players are looking at an outdated quests sidebar."
        )
    if cast_behind >= 15:
        warnings.append(
            "dramatis-personae.json (Who's Who) is STALE — cast notes no longer match "
            "what the players have seen happen."
        )
    if warnings:
        out["DM_WARNING"] = " ".join(warnings) + (
            " Run the Bookkeeper and sync before the next narration."
        )
    print(json.dumps(out, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())
