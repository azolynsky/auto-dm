#!/usr/bin/env python3
"""
Real dice roller. Claude must call this for every die — never roll mentally.

Usage:
    python dice.py 1d20+5
    python dice.py 1d20+5 --mode advantage
    python dice.py 1d20-2 --mode disadvantage
    python dice.py 4d6 --mode drop-lowest        # ability score gen
    python dice.py 1d20+7 --mode advantage --label "Alex stealth check"

Batch several rolls in ONE call (one label per expression, in order):
    python dice.py 1d20+5 1d8+3 --label "rapier to-hit" --label "rapier damage"

Output: one JSON object for a single expression, a JSON array for a batch.
The positional mode argument ("python dice.py 1d20 advantage") still works.

If the table setting show_rolls is on, labeled rolls are queued as public
effects for the next narration (see campaign_lib.queue_effect).
"""
from __future__ import annotations

import argparse
import json
import random
import re
import sys
from dataclasses import dataclass, asdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))  # tools importable from anywhere
import campaign_lib

# Use secrets-backed RNG so rolls are not reproducible / not LLM-influenceable.
_rng = random.SystemRandom()

DICE_RE = re.compile(r"^\s*(\d*)d(\d+)\s*([+-]\s*\d+)?\s*$", re.IGNORECASE)
MODES = ("normal", "advantage", "disadvantage", "drop-lowest")


@dataclass
class Roll:
    expression: str
    label: str | None
    mode: str  # "normal" | "advantage" | "disadvantage" | "drop-lowest"
    dice: list[int]
    kept: list[int]
    modifier: int
    total: int
    crit: bool | None  # True nat 20, False nat 1, None otherwise (only meaningful for 1d20)
    note: str | None = None


def parse(expr: str) -> tuple[int, int, int]:
    m = DICE_RE.match(expr)
    if not m:
        raise SystemExit(f"bad dice expression: {expr!r} (try '1d20+5' or '2d6')")
    count = int(m.group(1)) if m.group(1) else 1
    sides = int(m.group(2))
    mod = int(m.group(3).replace(" ", "")) if m.group(3) else 0
    if count < 1 or sides < 2 or count > 100:
        raise SystemExit("dice out of range")
    return count, sides, mod


def roll_one(sides: int) -> int:
    return _rng.randint(1, sides)


def do_roll(expr: str, mode: str, label: str | None) -> Roll:
    count, sides, mod = parse(expr)

    if mode in ("advantage", "disadvantage"):
        if count != 1 or sides != 20:
            raise SystemExit("advantage/disadvantage only valid on 1d20")
        a, b = roll_one(20), roll_one(20)
        dice = [a, b]
        kept = [max(a, b)] if mode == "advantage" else [min(a, b)]
    elif mode == "drop-lowest":
        if count < 2:
            raise SystemExit("drop-lowest needs at least 2 dice")
        dice = [roll_one(sides) for _ in range(count)]
        kept = sorted(dice)[1:]
    else:
        dice = [roll_one(sides) for _ in range(count)]
        kept = dice[:]

    subtotal = sum(kept)
    total = subtotal + mod

    crit: bool | None = None
    if count == 1 and sides == 20 and mode in ("normal", "advantage", "disadvantage"):
        k = kept[0]
        if k == 20:
            crit = True
        elif k == 1:
            crit = False

    return Roll(
        expression=expr,
        label=label,
        mode=mode,
        dice=dice,
        kept=kept,
        modifier=mod,
        total=total,
        crit=crit,
    )


def public_roll_text(roll: Roll) -> str:
    crit_tag = " — NAT 20!" if roll.crit is True else (" — nat 1" if roll.crit is False else "")
    return f"🎲 {roll.label}: {roll.total}{crit_tag}"


def maybe_publish(rolls: list[Roll]) -> None:
    """Queue labeled rolls as public effects when the table wants open rolls."""
    campaign_lib.queue_public_effects([public_roll_text(r) for r in rolls if r.label])


def pretty_line(roll: Roll) -> str:
    tag = f"[{roll.label}] " if roll.label else ""
    crit_tag = ""
    if roll.crit is True:
        crit_tag = "  ** NAT 20 **"
    elif roll.crit is False:
        crit_tag = "  ** NAT 1 **"
    return (
        f"{tag}{roll.expression} ({roll.mode}): "
        f"rolled {roll.dice} -> kept {roll.kept} "
        f"{'+' if roll.modifier >= 0 else ''}{roll.modifier} = {roll.total}{crit_tag}"
    )


def main() -> int:
    p = argparse.ArgumentParser(description="Real dice roller for 5e.")
    p.add_argument("expressions", nargs="+",
                   help="e.g. 1d20+5, 2d6 — several expressions roll as a batch")
    p.add_argument("--mode", default="normal", choices=MODES,
                   help="applies to every expression in the batch")
    p.add_argument("--label", action="append", default=None,
                   help="what a roll is for; repeat per expression, in order")
    p.add_argument("--pretty", action="store_true", help="human-readable output")
    args = p.parse_args()

    # Back-compat: "dice.py 1d20+5 advantage" (positional mode)
    exprs = list(args.expressions)
    if len(exprs) > 1 and exprs[-1] in MODES:
        args.mode = exprs.pop()

    labels = args.label or []
    rolls = [do_roll(expr, args.mode, labels[i] if i < len(labels) else None)
             for i, expr in enumerate(exprs)]

    maybe_publish(rolls)

    if args.pretty:
        for roll in rolls:
            print(pretty_line(roll))
    elif len(rolls) == 1:
        print(json.dumps(asdict(rolls[0])))
    else:
        print(json.dumps([asdict(r) for r in rolls]))
    return 0


if __name__ == "__main__":
    sys.exit(main())
