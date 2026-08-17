#!/usr/bin/env python3
"""
Deterministic character-sheet mutations, so the Bookkeeper never does
resource arithmetic in its head (the dice.py invariant, applied to state).

Usage:
    python tools/char_update.py hp --char Mira --damage 6
    python tools/char_update.py hp --char Mira --heal 7
    python tools/char_update.py hp --char Mira --temp 5
    python tools/char_update.py slot --char Relthus --use 1
    python tools/char_update.py slot --char Relthus --restore 1
    python tools/char_update.py slot --char Relthus --long-rest
    python tools/char_update.py item --char Relthus --add "Potion of healing" --qty 2
    python tools/char_update.py item --char Relthus --remove Arrows --qty 3
    python tools/char_update.py gold --char Mira --amount -5
    python tools/char_update.py condition --char Mira --add poisoned
    python tools/char_update.py condition --char Mira --remove poisoned

--char matches the sheet's "id" or "name" (case-insensitive). Every command
prints the resulting state as JSON and queues a player-visible effect for
the next narrate.py call (no-spoiler rule) — pass --quiet to skip the effect
for changes the players shouldn't see surfaced.

Rules applied deterministically:
  - damage hits temp HP first; current HP floors at 0
  - healing clamps to max and never touches temp
  - slot use fails loudly at 0 remaining; restore clamps to max
  - long rest: all slots to max, HP to max, temp to 0
  - item remove fails loudly if the count isn't there; qty 0 deletes the entry
  - gold fails loudly if the purse can't cover it

During active combat, HP and conditions for combatants are authoritative in
combat.json — this tool refuses those and points at combat_tracker.py.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import campaign_lib


def find_sheet(root: Path, who: str) -> Path:
    chars = root / "characters"
    for path in sorted(chars.glob("*.json")) if chars.is_dir() else []:
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            continue
        if who.lower() in (str(data.get("id", "")).lower(),
                           str(data.get("name", "")).lower()):
            return path
    raise SystemExit(f"no character sheet matches: {who}")


def in_active_combat(root: Path, name: str) -> bool:
    try:
        state = json.loads((root / "state" / "combat.json").read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return False
    return state.get("active") and any(
        o.get("name", "").lower() == name.lower() for o in state.get("order", [])
    )


def save_sheet(path: Path, data: dict) -> None:
    path.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n",
                    encoding="utf-8")


def finish(root: Path, result: dict, effect: str | None, quiet: bool) -> None:
    if effect and not quiet:
        campaign_lib.queue_effect(root, effect)
        result["effect_queued"] = effect
    print(json.dumps(result, ensure_ascii=False))


def cmd_hp(args, root: Path, path: Path, data: dict) -> None:
    if in_active_combat(root, data["name"]):
        raise SystemExit(
            f"{data['name']} is in active combat — HP is authoritative in "
            "combat.json; use combat_tracker.py damage/heal/sethp instead."
        )
    hp = data["hp"]
    hp.setdefault("temp", 0)
    effect = None
    if args.damage is not None:
        absorbed = min(hp["temp"], args.damage)
        hp["temp"] -= absorbed
        hp["current"] = max(0, hp["current"] - (args.damage - absorbed))
        effect = f"{data['name']} takes {args.damage} damage (now {hp['current']}/{hp['max']} HP)"
        if absorbed:
            effect += f" — {absorbed} absorbed by temporary HP"
        if hp["current"] == 0:
            effect += " — DOWN"
    elif args.heal is not None:
        before = hp["current"]
        hp["current"] = min(hp["max"], hp["current"] + args.heal)
        effect = f"{data['name']} regains {hp['current'] - before} HP (now {hp['current']}/{hp['max']})"
    elif args.temp is not None:
        # 5e: temp HP doesn't stack — keep the higher value
        hp["temp"] = max(hp["temp"], args.temp)
        effect = f"{data['name']} gains {hp['temp']} temporary HP"
    elif args.set is not None:
        hp["current"] = max(0, min(hp["max"], args.set))
    else:
        raise SystemExit("hp: pass one of --damage/--heal/--temp/--set")
    save_sheet(path, data)
    finish(root, {"action": "hp", "who": data["name"], "hp": hp}, effect, args.quiet)


def cmd_slot(args, root: Path, path: Path, data: dict) -> None:
    slots = data.get("spells", {}).get("slots", {})
    effect = None
    if args.long_rest:
        for s in slots.values():
            s["remaining"] = s["max"]
        hp = data["hp"]
        hp["current"], hp["temp"] = hp["max"], 0
        effect = f"{data['name']} completes a long rest — HP and spell slots restored"
    else:
        lvl = str(args.use if args.use is not None else args.restore)
        if lvl == "None":
            raise SystemExit("slot: pass one of --use/--restore/--long-rest")
        if lvl not in slots:
            raise SystemExit(f"{data['name']} has no level-{lvl} slots")
        s = slots[lvl]
        if args.use is not None:
            if s["remaining"] < 1:
                raise SystemExit(
                    f"{data['name']} has no level-{lvl} slots remaining ({s['remaining']}/{s['max']})"
                )
            s["remaining"] -= 1
            effect = f"{data['name']} expends a level-{lvl} spell slot ({s['remaining']}/{s['max']} left)"
        else:
            s["remaining"] = min(s["max"], s["remaining"] + 1)
    save_sheet(path, data)
    finish(root, {"action": "slot", "who": data["name"], "slots": slots,
                  "hp": data["hp"] if args.long_rest else None},
           effect, args.quiet)


def cmd_item(args, root: Path, path: Path, data: dict) -> None:
    inv = data.setdefault("inventory", [])
    name = args.add or args.remove
    if not name:
        raise SystemExit("item: pass --add or --remove")
    entry = next((i for i in inv if i["item"].lower() == name.lower()), None)
    if args.add:
        if entry:
            entry["qty"] += args.qty
        else:
            entry = {"item": args.add, "qty": args.qty}
            inv.append(entry)
        effect = f"{data['name']} gains {args.add} ×{args.qty}" if args.qty > 1 \
            else f"{data['name']} gains {args.add}"
    else:
        if entry is None or entry["qty"] < args.qty:
            have = entry["qty"] if entry else 0
            raise SystemExit(f"{data['name']} has {have} × {name}, can't remove {args.qty}")
        entry["qty"] -= args.qty
        if entry["qty"] == 0:
            inv.remove(entry)
        effect = f"{data['name']} uses {name}" if args.qty == 1 \
            else f"{data['name']} uses {name} ×{args.qty}"
    save_sheet(path, data)
    finish(root, {"action": "item", "who": data["name"],
                  "item": name, "qty": entry["qty"] if entry in inv else 0},
           effect, args.quiet)


def cmd_gold(args, root: Path, path: Path, data: dict) -> None:
    before = data.get("gold", 0)
    after = before + args.amount
    if after < 0:
        raise SystemExit(f"{data['name']} has {before} gp, can't spend {-args.amount}")
    data["gold"] = after
    verb = "gains" if args.amount >= 0 else "spends"
    effect = f"{data['name']} {verb} {abs(args.amount)} gp (now {after} gp)"
    save_sheet(path, data)
    finish(root, {"action": "gold", "who": data["name"], "gold": after}, effect, args.quiet)


def cmd_condition(args, root: Path, path: Path, data: dict) -> None:
    if in_active_combat(root, data["name"]):
        raise SystemExit(
            f"{data['name']} is in active combat — use combat_tracker.py condition instead."
        )
    conds = data.setdefault("conditions", [])
    effect = None
    if args.add:
        if args.add not in conds:
            conds.append(args.add)
        effect = f"{data['name']} is {args.add}"
    elif args.remove:
        if args.remove in conds:
            conds.remove(args.remove)
        effect = f"{data['name']} is no longer {args.remove}"
    else:
        raise SystemExit("condition: pass --add or --remove")
    save_sheet(path, data)
    finish(root, {"action": "condition", "who": data["name"], "conditions": conds},
           effect, args.quiet)


def main() -> int:
    p = argparse.ArgumentParser(description="Deterministic character-sheet updates.")
    sub = p.add_subparsers(dest="cmd", required=True)

    def base(name):
        s = sub.add_parser(name)
        s.add_argument("--char", required=True, help="character id or name")
        s.add_argument("--quiet", action="store_true",
                       help="don't queue a player-visible effect")
        return s

    s = base("hp")
    s.add_argument("--damage", type=int); s.add_argument("--heal", type=int)
    s.add_argument("--temp", type=int); s.add_argument("--set", type=int)
    s.set_defaults(func=cmd_hp)

    s = base("slot")
    s.add_argument("--use", type=int); s.add_argument("--restore", type=int)
    s.add_argument("--long-rest", action="store_true")
    s.set_defaults(func=cmd_slot)

    s = base("item")
    s.add_argument("--add"); s.add_argument("--remove")
    s.add_argument("--qty", type=int, default=1)
    s.set_defaults(func=cmd_item)

    s = base("gold")
    s.add_argument("--amount", type=int, required=True,
                   help="delta: positive gains, negative spends")
    s.set_defaults(func=cmd_gold)

    s = base("condition")
    s.add_argument("--add"); s.add_argument("--remove")
    s.set_defaults(func=cmd_condition)

    args = p.parse_args()
    root = campaign_lib.resolve_root()
    path = find_sheet(root, args.char)
    data = json.loads(path.read_text(encoding="utf-8"))
    args.func(args, root, path, data)
    return 0


if __name__ == "__main__":
    sys.exit(main())
