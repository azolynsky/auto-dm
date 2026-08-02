#!/usr/bin/env python3
"""
Resolve a Strike! roll with a real d6. Strike-specific (d6 tiers, Skilled/
Unskilled outcome tables, Miss Tokens) — other systems have their own
resolver under tools/<system>/.

Attack roll (tactical combat):
    python tools/strike/check_resolver.py --attack --label "Wolverine claws vs Hammer1"
    python tools/strike/check_resolver.py --attack --mode advantage

Skill roll (everything else):
    python tools/strike/check_resolver.py --skill "Mind Reading" \\
        --char <save>/characters/emma-frost.json
    python tools/strike/check_resolver.py --skill-roll --unskilled --label "guard bluff"

The attack output includes `with_miss_token` — what the result would become
if the player spends a Miss Token (+1 after seeing the roll). The resolver
never spends the token itself; that's a Bookkeeper edit to the sheet.
"""
from __future__ import annotations

import argparse
import json
import sys
from dataclasses import asdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import campaign_lib
import dice

ATTACK_TIERS = {
    6: "critical",   # Effect + 2x damage
    5: "solid",      # damage + Effect
    4: "solid",
    3: "glancing",   # damage OR Effect
    2: "miss",       # + Miss Token
    1: "miss-strike",  # + Miss Token + Strike
}

TIER_TEXT = {
    "critical": "Critical Hit: Effect + 2x damage",
    "solid": "Solid Hit: damage + Effect",
    "glancing": "Glancing Hit: damage OR Effect (attacker's choice)",
    "miss": "Miss — gain a Miss Token",
    "miss-strike": "Miss — gain a Miss Token AND a Strike",
}

SKILLED_OUTCOMES = {
    6: "Success + Bonus",
    5: "Success",
    4: "Success",
    3: "Success + Cost",
    2: "Twist",
    1: "Twist + Cost",
}

UNSKILLED_OUTCOMES = {
    6: "Success + learn the Skill OR Bonus",
    5: "Success",
    4: "Success + Cost",
    3: "Twist",
    2: "Twist",
    1: "Twist + Cost",
}


def attack_tier(die: int) -> str:
    return ATTACK_TIERS[die]


def skill_outcome(die: int, skilled: bool) -> str:
    return (SKILLED_OUTCOMES if skilled else UNSKILLED_OUTCOMES)[die]


def load_char(path: Path) -> dict:
    # utf-8 explicitly: strike sheets carry glyphs (✸ ∆ ⚡) that the Windows
    # default codepage can't decode.
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def find_skill(char: dict, name: str) -> dict | None:
    wanted = name.lower().strip()
    for entry in char.get("skills", []):
        if entry.get("name", "").lower().strip() == wanted:
            return entry
    return None


def resolve_attack(mode: str, label: str | None) -> dict:
    roll = dice.do_roll("1d6", mode, None)
    die = roll.kept[0]
    tier = attack_tier(die)
    hit = tier in ("critical", "solid", "glancing")
    upgraded = attack_tier(min(die + 1, 6)) if die < 6 else None
    result = {
        "kind": "attack",
        "label": label,
        "mode": mode,
        "dice": roll.dice,
        "die": die,
        "tier": tier,
        "result": TIER_TEXT[tier],
        "hit": hit,
        "crit": tier == "critical",
        "grants_miss_token": not hit,
        "grants_strike": tier == "miss-strike",
        "with_miss_token": TIER_TEXT[upgraded] if upgraded and upgraded != tier else None,
    }
    if label:
        campaign_lib.queue_public_effects([f"🎲 {label}: {die} — {TIER_TEXT[tier]}"])
    return result


def resolve_skill(skilled: bool, mode: str, label: str | None,
                  trick: str | None = None) -> dict:
    roll = dice.do_roll("1d6", mode, None)
    die = roll.kept[0]
    outcome = skill_outcome(die, skilled)
    result = {
        "kind": "skill",
        "label": label,
        "mode": mode,
        "skilled": skilled,
        "dice": roll.dice,
        "die": die,
        "outcome": outcome,
        "success": outcome.startswith("Success"),
    }
    if trick:
        result["trick"] = trick
        result["trick_note"] = "spend an Action Point to auto-succeed with this Trick instead of rolling"
    if label:
        campaign_lib.queue_public_effects([f"🎲 {label}: {die} — {outcome}"])
    return result


def main() -> int:
    p = argparse.ArgumentParser()
    g = p.add_mutually_exclusive_group(required=True)
    g.add_argument("--attack", action="store_true", help="roll on the attack table")
    g.add_argument("--skill", help="skill name — looked up on the sheet given via --char")
    g.add_argument("--skill-roll", action="store_true",
                   help="bare skill roll without a sheet (with --skilled/--unskilled)")
    p.add_argument("--char", help="path to character JSON (for --skill lookup)")
    sk = p.add_mutually_exclusive_group()
    sk.add_argument("--skilled", action="store_true")
    sk.add_argument("--unskilled", action="store_true")
    p.add_argument("--mode", default="normal",
                   choices=["normal", "advantage", "disadvantage"])
    p.add_argument("--label", default=None, help="player-readable roll label")
    args = p.parse_args()

    if args.attack:
        result = resolve_attack(args.mode, args.label)
    elif args.skill:
        if not args.char:
            raise SystemExit("--skill needs --char (or use --skill-roll --skilled/--unskilled)")
        char = load_char(Path(args.char))
        entry = find_skill(char, args.skill)
        # Unlisted skill = Unskilled; listed skills are Skilled unless marked otherwise.
        skilled = bool(entry.get("skilled", True)) if entry else False
        trick = entry.get("trick") if entry else None
        label = args.label or f"{char.get('name', 'PC')} {args.skill}" \
            + ("" if skilled else " (unskilled)")
        result = resolve_skill(skilled, args.mode, label, trick)
        result["skill"] = args.skill
        result["character"] = char.get("name")
    else:
        if not (args.skilled or args.unskilled):
            raise SystemExit("--skill-roll needs --skilled or --unskilled")
        result = resolve_skill(args.skilled, args.mode, args.label)

    print(json.dumps(result, indent=2, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())
