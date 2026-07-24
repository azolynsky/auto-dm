#!/usr/bin/env python3
"""
Resolve a skill check or saving throw against a DC, using a real dice roll.

Usage:
    python check_resolver.py --char campaign/characters/<id>.json \\
        --skill stealth --dc 15
    python check_resolver.py --char campaign/characters/<id>.json \\
        --save dex --dc 14 --mode advantage

Picks the right modifier from the character sheet, calls dice.py, prints JSON.
"""
from __future__ import annotations

import argparse
import json
import sys
from dataclasses import asdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import campaign_lib
import dice

ABILITY_TO_SAVES = {"str", "dex", "con", "int", "wis", "cha"}

SKILL_TO_ABILITY = {
    "acrobatics": "dex",
    "animal_handling": "wis",
    "arcana": "int",
    "athletics": "str",
    "deception": "cha",
    "history": "int",
    "insight": "wis",
    "intimidation": "cha",
    "investigation": "int",
    "medicine": "wis",
    "nature": "int",
    "perception": "wis",
    "performance": "cha",
    "persuasion": "cha",
    "religion": "int",
    "sleight_of_hand": "dex",
    "stealth": "dex",
    "survival": "wis",
}


def ability_mod(score: int) -> int:
    return (score - 10) // 2


def load_char(path: Path) -> dict:
    with open(path) as f:
        return json.load(f)


def get_skill_bonus(char: dict, skill: str) -> tuple[int, str]:
    skill = skill.lower().replace(" ", "_")
    if skill not in SKILL_TO_ABILITY:
        raise SystemExit(f"unknown skill: {skill}")
    ab = SKILL_TO_ABILITY[skill]
    score = char["abilities"][ab]
    bonus = ability_mod(score)
    prof = char.get("proficiency_bonus", 2)
    skills = char.get("skills", {})
    if skills.get(skill) == "expertise":
        bonus += 2 * prof
    elif skills.get(skill) == "proficient":
        bonus += prof
    return bonus, ab


def get_save_bonus(char: dict, ability: str) -> int:
    ability = ability.lower()
    if ability not in ABILITY_TO_SAVES:
        raise SystemExit(f"unknown save: {ability}")
    score = char["abilities"][ability]
    bonus = ability_mod(score)
    prof = char.get("proficiency_bonus", 2)
    if ability in char.get("save_proficiencies", []):
        bonus += prof
    return bonus


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--char", required=True, help="path to character JSON")
    g = p.add_mutually_exclusive_group(required=True)
    g.add_argument("--skill", help="e.g. stealth, perception")
    g.add_argument("--save", help="e.g. dex, wis")
    g.add_argument("--ability", help="raw ability check, e.g. str")
    p.add_argument("--dc", type=int, required=True)
    p.add_argument("--mode", default="normal", choices=["normal", "advantage", "disadvantage"])
    args = p.parse_args()

    char = load_char(Path(args.char))
    name = char.get("name", "PC")

    if args.skill:
        bonus, ab = get_skill_bonus(char, args.skill)
        label = f"{name} {args.skill} check ({ab})"
    elif args.save:
        bonus = get_save_bonus(char, args.save)
        ab = args.save
        label = f"{name} {args.save.upper()} save"
    else:
        ab = args.ability.lower()
        bonus = ability_mod(char["abilities"][ab])
        label = f"{name} {ab.upper()} check"

    roll = dice.do_roll(f"1d20{bonus:+d}", args.mode, label)
    result = {
        "character": name,
        "label": label,
        "dc": args.dc,
        "bonus": bonus,
        "roll": asdict(roll),
        "success": roll.total >= args.dc,
        "margin": roll.total - args.dc,
    }
    campaign_lib.queue_public_effects([
        f"🎲 {label}: {roll.total} vs DC {args.dc} — {'success' if result['success'] else 'failure'}"
    ])
    print(json.dumps(result, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
