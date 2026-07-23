#!/usr/bin/env python3
"""
Real dice roller. Claude must call this for every die — never roll mentally.

Usage:
    python dice.py 1d20+5
    python dice.py 1d20+5 advantage
    python dice.py 1d20-2 disadvantage
    python dice.py 2d6+3
    python dice.py 4d6 drop-lowest          # ability score gen
    python dice.py 1d20+7 advantage --label "Alex stealth check"

Output is a single JSON object on stdout so other tools / agents can parse it.
"""
from __future__ import annotations

import argparse
import json
import random
import re
import secrets
import sys
from dataclasses import dataclass, asdict

# Use secrets-backed RNG so rolls are not reproducible / not LLM-influenceable.
_rng = random.SystemRandom()

DICE_RE = re.compile(r"^\s*(\d*)d(\d+)\s*([+-]\s*\d+)?\s*$", re.IGNORECASE)


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


def main() -> int:
    p = argparse.ArgumentParser(description="Real dice roller for D&D 5e.")
    p.add_argument("expression", help="e.g. 1d20+5, 2d6, 8d6")
    p.add_argument(
        "mode",
        nargs="?",
        default="normal",
        choices=["normal", "advantage", "disadvantage", "drop-lowest"],
    )
    p.add_argument("--label", default=None, help="what this roll is for")
    p.add_argument("--pretty", action="store_true", help="human-readable output")
    args = p.parse_args()

    roll = do_roll(args.expression, args.mode, args.label)

    if args.pretty:
        tag = f"[{roll.label}] " if roll.label else ""
        crit_tag = ""
        if roll.crit is True:
            crit_tag = "  ** NAT 20 **"
        elif roll.crit is False:
            crit_tag = "  ** NAT 1 **"
        print(
            f"{tag}{roll.expression} ({roll.mode}): "
            f"rolled {roll.dice} -> kept {roll.kept} "
            f"{'+' if roll.modifier >= 0 else ''}{roll.modifier} = {roll.total}{crit_tag}"
        )
    else:
        print(json.dumps(asdict(roll)))
    return 0


if __name__ == "__main__":
    sys.exit(main())
