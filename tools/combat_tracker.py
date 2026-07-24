#!/usr/bin/env python3
"""
Combat tracker. Stores per-encounter state in <campaign>/state/combat.json.

Usage:
    python combat_tracker.py start --participants "Ren:+3" "Goblin1:+2:7" "Goblin2:+2:7"
        # optional third field = starting/max HP — saves a sethp call per monster
    python combat_tracker.py status
    python combat_tracker.py damage --who Goblin1 --amount 7
    python combat_tracker.py heal --who Ren --amount 4
    python combat_tracker.py condition --who Ren --add prone
    python combat_tracker.py condition --who Ren --remove prone
    python combat_tracker.py next            # advance turn
    python combat_tracker.py end             # clear encounter

Every command prints one JSON object (status prints the full state).

Feed discipline: start/end post a system banner to the player feed
immediately. Damage/heal/conditions do NOT — they queue as effects that
attach to the next narrate.py call, so the players read the story before
the numbers (no spoilers).

This deliberately stores HP for monsters here, not in characters/. PC HP
belongs on the character sheets and should be synced by the Bookkeeper at
end-of-encounter, not on every hit (otherwise concurrent edits get messy).
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import campaign_lib
import dice


def state_file() -> Path:
    return campaign_lib.resolve_root() / "state" / "combat.json"


def load() -> dict:
    path = state_file()
    if not path.exists():
        return {"active": False, "round": 0, "turn_index": 0, "order": [], "log": []}
    with open(path) as f:
        return json.load(f)


def save(state: dict) -> None:
    path = state_file()
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w") as f:
        json.dump(state, f, indent=2)


def out(obj: dict) -> None:
    print(json.dumps(obj, ensure_ascii=False))


def parse_participant(spec: str) -> dict:
    """"Name", "Name:+3", or "Name:+3:7" (init modifier, starting HP)."""
    name, _, rest = spec.partition(":")
    mod_s, _, hp_s = rest.partition(":")
    mod = int(mod_s) if mod_s else 0
    hp = int(hp_s) if hp_s else None
    init = dice.do_roll(f"1d20{mod:+d}", "normal", f"{name} initiative").total
    return {"name": name, "init": init, "mod": mod,
            "hp": hp, "max_hp": hp, "conditions": []}


def cmd_start(args) -> None:
    order = [parse_participant(spec) for spec in args.participants]
    order.sort(key=lambda x: (-x["init"], -x["mod"]))
    state = {"active": True, "round": 1, "turn_index": 0, "order": order, "log": []}
    state["log"].append("Combat started. Initiative: " + ", ".join(f"{o['name']}({o['init']})" for o in order))
    save(state)
    campaign_lib.append_feed(
        campaign_lib.resolve_root(),
        "⚔ Combat! Initiative: " + " → ".join(f"{o['name']} ({o['init']})" for o in order),
        type="system",
    )
    out({"action": "start", "round": 1,
         "turn": order[0]["name"], "order": order})


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
    down = p["hp"] <= 0
    line = f"{p['name']} takes {args.amount} damage (now {p['hp']} HP)"
    if down:
        line += " — DOWN"
    s["log"].append(line)
    save(s)
    campaign_lib.queue_effect(campaign_lib.resolve_root(), line)
    out({"action": "damage", "who": p["name"], "amount": args.amount,
         "hp": p["hp"], "max_hp": p["max_hp"], "down": down})


def cmd_heal(args) -> None:
    s = load()
    p = find(s, args.who)
    p["hp"] = (p["hp"] or 0) + args.amount
    if p["max_hp"] is not None:
        p["hp"] = min(p["hp"], p["max_hp"])
    line = f"{p['name']} healed {args.amount} (now {p['hp']} HP)"
    s["log"].append(line)
    save(s)
    campaign_lib.queue_effect(campaign_lib.resolve_root(), line)
    out({"action": "heal", "who": p["name"], "amount": args.amount,
         "hp": p["hp"], "max_hp": p["max_hp"]})


def cmd_sethp(args) -> None:
    s = load()
    p = find(s, args.who)
    p["hp"] = args.current
    if args.max is not None:
        p["max_hp"] = args.max
    save(s)
    out({"action": "sethp", "who": p["name"], "hp": p["hp"], "max_hp": p["max_hp"]})


def cmd_condition(args) -> None:
    s = load()
    p = find(s, args.who)
    root = campaign_lib.resolve_root()
    if args.add:
        if args.add not in p["conditions"]:
            p["conditions"].append(args.add)
        s["log"].append(f"{p['name']} gains {args.add}")
        campaign_lib.queue_effect(root, f"{p['name']} is {args.add}")
    if args.remove:
        p["conditions"] = [c for c in p["conditions"] if c != args.remove]
        s["log"].append(f"{p['name']} no longer {args.remove}")
        campaign_lib.queue_effect(root, f"{p['name']} is no longer {args.remove}")
    save(s)
    out({"action": "condition", "who": p["name"], "conditions": p["conditions"]})


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
    out({"action": "next", "round": s["round"], "turn": current["name"]})


def cmd_end(args) -> None:
    s = load()
    rounds = s.get("round", 0)
    s["active"] = False
    s["log"].append("Combat ended.")
    save(s)
    campaign_lib.append_feed(campaign_lib.resolve_root(), "⚔ Combat over.", type="system")
    out({"action": "end", "rounds": rounds})


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
