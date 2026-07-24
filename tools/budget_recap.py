#!/usr/bin/env python3
"""
Character-budget report for the rolling recap (or any summary file).

Why: `sessions/recap.md` is loaded every session. If it grows unbounded,
the LLM's context fills with stale summary instead of fresh per-entity
detail. This tool reports current vs. target so you can trim deliberately.

Usage:
    python tools/budget_recap.py
    python tools/budget_recap.py --target 5000
    python tools/budget_recap.py --path sessions/recap.md --target 5000
    python tools/budget_recap.py --json
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import campaign_lib

DEFAULT_TARGET = 5000  # characters


def report(path: Path, target: int) -> dict:
    if not path.exists():
        raise SystemExit(f"not found: {path}")
    text = path.read_text()
    chars = len(text)
    words = len(text.split())
    lines = text.count("\n") + (0 if text.endswith("\n") else 1)
    ratio = chars / target if target > 0 else 0.0

    if ratio < 0.7:
        status = "under"
        suggestion = "plenty of room — add detail if useful"
    elif ratio < 0.95:
        status = "ok"
        suggestion = "in budget"
    elif ratio < 1.1:
        status = "near"
        suggestion = "approaching budget — start compressing the oldest sections"
    else:
        status = "over"
        suggestion = f"over budget by {chars - target} chars — trim now"

    return {
        "path": str(path),
        "target_chars": target,
        "current_chars": chars,
        "ratio": round(ratio, 3),
        "word_count": words,
        "line_count": lines,
        "status": status,
        "suggestion": suggestion,
    }


def pretty(r: dict) -> str:
    bar_len = 40
    filled = min(int(r["ratio"] * bar_len), bar_len)
    bar = "█" * filled + "░" * (bar_len - filled)
    return (
        f"recap budget — {r['path']}\n"
        f"  [{bar}]  {r['current_chars']:>5}/{r['target_chars']:<5} chars  "
        f"({r['ratio']*100:.0f}%)\n"
        f"  words: {r['word_count']}, lines: {r['line_count']}\n"
        f"  status: {r['status'].upper()}\n"
        f"  → {r['suggestion']}"
    )


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--path", default=None, help="defaults to <campaign>/sessions/recap.md")
    p.add_argument("--target", type=int, default=DEFAULT_TARGET, help="character budget")
    p.add_argument("--json", action="store_true", help="emit JSON instead of pretty")
    args = p.parse_args()

    path = Path(args.path) if args.path else campaign_lib.resolve_root() / "sessions" / "recap.md"
    r = report(path, args.target)
    if args.json:
        print(json.dumps(r, indent=2))
    else:
        print(pretty(r))
    return 0 if r["status"] != "over" else 1


if __name__ == "__main__":
    sys.exit(main())
