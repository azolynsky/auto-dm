#!/usr/bin/env python3
"""
Combat tracker. Stores per-encounter state in state/combat.json.

Usage:
    python combat_tracker.py start --participants "Alex:+3" "Friend:+1" "Goblin1:+2" "Goblin2:+2"
    python combat_tracker.py status
    python combat_tracker.py damage --who Goblin1 --amount 7
    python combat_tracker.py heal --who Alex --amount 4
    python combat_tracker.py condition --who Friend --add prone
    python combat_tracker.py condition --who Friend --remove prone
    python combat_tracker.py next            # advance turn
    python combat_tracker.py end             # clear encounter

This deliberately stores HP for monsters here, not in characters/. PC HP
belongs in state/current.json and should be synced by the Bookkeeper at
end-of-encounter, not on every hit (otherwise concurrent edits get messy).
"""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
STATE = ROOT / "state" / "combat.json"
DICE = ROOT / "tools" / "dice.py"


def load() -> dict:
    if not STATE.exists():
        return {"active": False, "round": 0, "turn_index": 0, "order": [], "log": []}
    with open(STATE) as f:
        return json.load(f)


def save(state: dict) -> None:
    STATE.parent.mkdir(parents=True, exist_ok=True)
    with open(STATE, "w") as f:
        json.dump(state, f, indent=2)


def roll_init(modifier: int) -> int:
    out = subprocess.check_output(
        [sys.executable, str(DICE), f"1d20{modifier:+d}", "normal", "--label", "initiative"]
    )
    return json.loads(out)["total"]


def cmd_start(args) -> None:
    order = []
    for spec in args.participants:
        name, _, mod_s = spec.partition(":")
        mod = int(mod_s) if mod_s else 0
        init = roll_init(mod)
        order.append({"name": name, "init": init, "mod": mod, "hp": None, "max_hp": None, "conditions": []})
    order.sort(key=lambda x: (-x["init"], -x["mod"]))
    state = {"active": True, "round": 1, "turn_index": 0, "order": order, "log": []}
    state["log"].append(f"Combat started. Initiative: " + ", ".join(f"{o['name']}({o['init']})" for o in order))
    save(state)
    print(json.dumps(state, indent=2))


def cmd_status(args) -> None:
    print(json.dumps(load(), indent=2))


def find(state: dict, who: str) -> dict:
    for o in state["order"]:
        if o["name"].lower() == who.lower():
            return o
    raise SystemExit(f"not in initiative: {who}")


def cmd_damage(args) -> None:
    s = load()
    p = find(s, args.who)
    if p["hp"] is None:
        p["hp"] = (p["max_hp"] or 0)
    p["hp"] -= args.amount
    line = f"{args.who} takes {args.amount} damage (now {p['hp']} HP)"
    if p["hp"] <= 0:
        line += " — DOWN"
    s["log"].append(line)
    save(s)
    print(line)


def cmd_heal(args) -> None:
    s = load()
    p = find(s, args.who)
    p["hp"] = (p["hp"] or 0) + args.amount
    if p["max_hp"] is not None:
        p["hp"] = min(p["hp"], p["max_hp"])
    line = f"{args.who} healed {args.amount} (now {p['hp']} HP)"
    s["log"].append(line)
    save(s)
    print(line)


def cmd_sethp(args) -> None:
    s = load()
    p = find(s, args.who)
    p["hp"] = args.current
    if args.max is not None:
        p["max_hp"] = args.max
    save(s)
    print(json.dumps(p, indent=2))


def cmd_condition(args) -> None:
    s = load()
    p = find(s, args.who)
    if args.add:
        if args.add not in p["conditions"]:
            p["conditions"].append(args.add)
        s["log"].append(f"{args.who} gains {args.add}")
    if args.remove:
        p["conditions"] = [c for c in p["conditions"] if c != args.remove]
        s["log"].append(f"{args.who} no longer {args.remove}")
    save(s)
    print(json.dumps(p, indent=2))


def cmd_next(args) -> None:
    s = load()
    if not s["active"]:
        raise SystemExit("no active combat")
    s["turn_index"] += 1
    if s["turn_index"] >= len(s["order"]):
        s["turn_index"] = 0
        s["round"] += 1
        s["log"].append(f"--- Round {s['round']} ---")
    current = s["order"][s["turn_index"]]
    s["log"].append(f"Turn: {current['name']}")
    save(s)
    print(f"Round {s['round']} — {current['name']}'s turn")


def cmd_end(args) -> None:
    s = load()
    s["active"] = False
    s["log"].append("Combat ended.")
    save(s)
    print("ended")


def main() -> int:
    p = argparse.ArgumentParser()
    sub = p.add_subparsers(dest="cmd", required=True)

    s = sub.add_parser("start"); s.add_argument("--participants", nargs="+", required=True); s.set_defaults(func=cmd_start)
    sub.add_parser("status").set_defaults(func=cmd_status)
    s = sub.add_parser("damage"); s.add_argument("--who", required=True); s.add_argument("--amount", type=int, required=True); s.set_defaults(func=cmd_damage)
    s = sub.add_parser("heal"); s.add_argument("--who", required=True); s.add_argument("--amount", type=int, required=True); s.set_defaults(func=cmd_heal)
    s = sub.add_parser("sethp"); s.add_argument("--who", required=True); s.add_argument("--current", type=int, required=True); s.add_argument("--max", type=int); s.set_defaults(func=cmd_sethp)
    s = sub.add_parser("condition"); s.add_argument("--who", required=True); s.add_argument("--add"); s.add_argument("--remove"); s.set_defaults(func=cmd_condition)
    sub.add_parser("next").set_defaults(func=cmd_next)
    sub.add_parser("end").set_defaults(func=cmd_end)

    args = p.parse_args()
    args.func(args)
    return 0


if __name__ == "__main__":
    sys.exit(main())
