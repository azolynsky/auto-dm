#!/usr/bin/env python3
"""
Combat tracker. Stores per-encounter state in <campaign>/state/combat.json.

Usage:
    python combat_tracker.py start --participants "Ren:+3" "Goblin1:+2:7" "Goblin2:+2:7" --pcs Ren
        # optional third field = starting/max HP — saves a sethp call per monster
        # --pcs: comma-separated player-controlled names, for combatants
        # without a sheet to bind to
    python combat_tracker.py status
    python combat_tracker.py damage --who Goblin1 --amount 7
    python combat_tracker.py heal --who Ren --amount 4
    python combat_tracker.py condition --who Ren --add prone
    python combat_tracker.py condition --who Ren --remove prone
    python combat_tracker.py declare --who Ren --action "swings at the goblin"
    python combat_tracker.py next            # advance turn
    python combat_tracker.py end             # clear encounter

Every command prints one JSON object (status prints the full state).

A player's turn is theirs: when start/next lands on a player-controlled
combatant who can act, the turn is LATCHED (state["pending"]) and
damage/heal/condition/next all refuse until `declare` records what the
player said their character does. See "The player's turn is theirs" below.

Feed discipline: start/end post a system banner to the player feed
immediately. Damage/heal/conditions do NOT — they queue as effects that
attach to the next narrate.py call, so the players read the story before
the numbers (no spoilers).

Participants who resolve to a character sheet in <campaign>/characters/
(by id, filename, full name, or unique name word — "Balasar" finds
"Balasar Dawnshield") are BOUND to it at start: the sheet's id is stamped
into the order entry as char_id, HP and conditions load from the sheet
(an explicit spec HP overrides current HP; max always comes from the
sheet), and every damage/heal/sethp/condition mirrors back to the sheet
through that binding — the sidebar and combat panel always show live HP
without a separate sync step, and a bound sheet can never drift silently.
Bound participants are player-controlled automatically; --pcs covers
combatants without sheets.
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


def sheet_for(entry: dict) -> Path | None:
    """The character sheet a combatant is bound to, or None (a monster).

    Binding is by char_id, stamped at start. A stamped id that no longer
    resolves is a loud error, never a silent no-op. Entries from a combat
    started before char_id existed fall back to name matching."""
    root = campaign_lib.resolve_root()
    cid = entry.get("char_id")
    if cid:
        path = campaign_lib.match_sheet(root, cid)
        if path is None:
            raise SystemExit(
                f"{entry['name']} is bound to sheet '{cid}' which no longer exists")
        return path
    return campaign_lib.match_sheet(root, entry["name"])


def sync_sheet(entry: dict) -> None:
    """Mirror a combatant's live HP and conditions to their character sheet.

    combat.json is authoritative during combat; the sheet (which the sidebar
    and char_update.py read) must never drift from it."""
    path = sheet_for(entry)
    if path is None or entry["hp"] is None:
        return
    with open(path) as f:
        data = json.load(f)
    data["hp"]["current"] = max(0, entry["hp"])
    data["conditions"] = list(entry["conditions"])
    with open(path, "w") as f:
        json.dump(data, f, indent=2)
        f.write("\n")


def parse_participant(spec: str) -> dict:
    """"Name", "Name:+3", or "Name:+3:7" (init modifier, starting HP)."""
    name, _, rest = spec.partition(":")
    mod_s, _, hp_s = rest.partition(":")
    mod = int(mod_s) if mod_s else 0
    hp = int(hp_s) if hp_s else None
    max_hp = hp
    conditions: list = []
    char_id = None
    path = campaign_lib.match_sheet(campaign_lib.resolve_root(), name)
    if path is not None:
        with open(path) as f:
            data = json.load(f)
        char_id = str(data.get("id") or path.stem)
        conditions = list(data.get("conditions", []))
        if hp is None:
            hp = data["hp"]["current"]
        # spec HP overrides current HP; max always comes from the sheet
        max_hp = data["hp"]["max"]
    init = dice.do_roll(f"1d20{mod:+d}", "normal", f"{name} initiative").total
    entry = {"name": name, "init": init, "mod": mod,
             "hp": hp, "max_hp": max_hp, "conditions": conditions, "pc": False}
    if char_id:
        entry["char_id"] = char_id
    return entry


def cmd_start(args) -> None:
    order = [parse_participant(spec) for spec in args.participants]
    pcs = {n.strip().lower() for n in (args.pcs or "").split(",") if n.strip()}
    for o in order:
        # A bound combatant is someone's character — never act for them.
        o["pc"] = bool(o.get("char_id")) or o["name"].lower() in pcs
    order.sort(key=lambda x: (-x["init"], -x["mod"]))
    state = {"active": True, "round": 1, "turn_index": 0, "order": order, "log": []}
    state["log"].append("Combat started. Initiative: " + ", ".join(f"{o['name']}({o['init']})" for o in order))
    pending = set_pending(state)
    save(state)
    for o in order:
        if o.get("char_id"):
            sync_sheet(o)  # converge sheets with any spec-HP overrides now
    campaign_lib.append_feed(
        campaign_lib.resolve_root(),
        "⚔ Combat! Initiative: " + " → ".join(f"{o['name']} ({o['init']})" for o in order),
        type="system",
    )
    result = {"action": "start", "round": 1,
              "turn": order[0]["name"], "order": order}
    if pending:
        result["pc_turn"] = True
        result["STOP"] = stop_message(pending["who"])
    out(result)


def cmd_status(args) -> None:
    print(json.dumps(load(), indent=2))


def find(state: dict, who: str) -> dict:
    for o in state["order"]:
        if o["name"].lower() == who.lower():
            return o
    raise SystemExit(f"not in initiative: {who}")


# ── The player's turn is theirs ────────────────────────────────────────────────
# `next` used to hand back a STOP sentence and hope. It got ignored once: a
# player answered a STOP with a musing about the inn's front door, and the DM
# filled the blank with a longsword swing, rolled it, and published it. So the
# STOP is a latch now — while a player-controlled combatant's turn is pending,
# nothing in this file will move.

# Conditions that leave a character with no action to declare. Their turn is a
# death save or nothing, so gating on a player's answer would just stall.
NO_ACTION = ("unconscious", "paralyzed", "petrified", "stunned")


def can_act(entry: dict) -> bool:
    if entry.get("hp") is not None and entry["hp"] <= 0:
        return False
    return not any(c.lower().startswith(NO_ACTION)
                   for c in entry.get("conditions", []))


def set_pending(state: dict) -> dict | None:
    """Latch the turn if it belongs to a player who can act."""
    state.pop("pending", None)
    current = state["order"][state["turn_index"]]
    if current.get("pc") and can_act(current):
        state["pending"] = {"who": current["name"], "round": state["round"]}
    return state.get("pending")


def stop_message(who: str) -> str:
    return (f"{who} is player-controlled — ask the player what they do, then "
            f"record it with `declare --who {who} --action \"...\"`. Nothing "
            f"else in this tool will move until you do. Do not act for them.")


def require_declared(state: dict, action: str) -> None:
    """Refuse to change combat while a player still owes an answer."""
    pending = state.get("pending")
    if not pending:
        return
    who = pending["who"]
    raise SystemExit(
        f"REFUSED ({action}): it is {who}'s turn and {who} is player-controlled "
        f"with no declared action. Ask the player what {who} does and record "
        f'their answer:\n    combat_tracker.py declare --who {who} --action '
        f'"<what the player said>"\nIf their message was not an action — a '
        f"question, an aside, a musing — publish a system note that re-asks. "
        f"Do not choose for them, and do not narrate an action they never took."
    )


def cmd_damage(args) -> None:
    s = load()
    require_declared(s, "damage")
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
    sync_sheet(p)
    campaign_lib.queue_effect(campaign_lib.resolve_root(), line)
    out({"action": "damage", "who": p["name"], "amount": args.amount,
         "hp": p["hp"], "max_hp": p["max_hp"], "down": down})


def cmd_heal(args) -> None:
    s = load()
    require_declared(s, "heal")
    p = find(s, args.who)
    p["hp"] = (p["hp"] or 0) + args.amount
    if p["max_hp"] is not None:
        p["hp"] = min(p["hp"], p["max_hp"])
    line = f"{p['name']} healed {args.amount} (now {p['hp']} HP)"
    s["log"].append(line)
    save(s)
    sync_sheet(p)
    campaign_lib.queue_effect(campaign_lib.resolve_root(), line)
    out({"action": "heal", "who": p["name"], "amount": args.amount,
         "hp": p["hp"], "max_hp": p["max_hp"]})


def cmd_sethp(args) -> None:
    s = load()
    p = find(s, args.who)
    p["hp"] = args.current
    if args.max is not None:
        p["max_hp"] = args.max
    s["log"].append(f"{p['name']} HP set to {p['hp']}/{p['max_hp']}")
    save(s)
    sync_sheet(p)
    out({"action": "sethp", "who": p["name"], "hp": p["hp"], "max_hp": p["max_hp"]})


def cmd_condition(args) -> None:
    s = load()
    require_declared(s, "condition")
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
    sync_sheet(p)
    out({"action": "condition", "who": p["name"], "conditions": p["conditions"]})


def cmd_next(args) -> None:
    s = load()
    if not s["active"]:
        raise SystemExit("no active combat")
    require_declared(s, "next")
    s["turn_index"] += 1
    if s["turn_index"] >= len(s["order"]):
        s["turn_index"] = 0
        s["round"] += 1
        s["log"].append(f"--- Round {s['round']} ---")
    current = s["order"][s["turn_index"]]
    s["log"].append(f"Turn: {current['name']}")
    pending = set_pending(s)
    save(s)
    result = {"action": "next", "round": s["round"], "turn": current["name"]}
    if pending:
        result["pc_turn"] = True
        result["STOP"] = stop_message(current["name"])
    out(result)


def cmd_declare(args) -> None:
    """Record what the player said their character does, and unlatch the turn."""
    s = load()
    p = find(s, args.who)
    pending = s.get("pending")
    if not pending:
        raise SystemExit(
            f"nothing pending — it is {s['order'][s['turn_index']]['name']}'s "
            "turn and no player declaration is owed")
    if pending["who"].lower() != p["name"].lower():
        raise SystemExit(f"{pending['who']} owes the declaration, not {p['name']}")
    s.pop("pending")
    s["log"].append(f"{p['name']} declares: {args.action}")
    save(s)
    out({"action": "declare", "who": p["name"], "declared": args.action,
         "round": s["round"]})


def cmd_end(args) -> None:
    s = load()
    rounds = s.get("round", 0)
    s.pop("pending", None)
    s["active"] = False
    s["log"].append("Combat ended.")
    save(s)
    campaign_lib.append_feed(campaign_lib.resolve_root(), "⚔ Combat over.", type="system")
    out({"action": "end", "rounds": rounds})


def main() -> int:
    p = argparse.ArgumentParser()
    sub = p.add_subparsers(dest="cmd", required=True)

    s = sub.add_parser("start"); s.add_argument("--participants", nargs="+", required=True); s.add_argument("--pcs", help="comma-separated names that are player-controlled; 'next' flags their turns STOP"); s.set_defaults(func=cmd_start)
    sub.add_parser("status").set_defaults(func=cmd_status)
    s = sub.add_parser("damage"); s.add_argument("--who", required=True); s.add_argument("--amount", type=int, required=True); s.set_defaults(func=cmd_damage)
    s = sub.add_parser("heal"); s.add_argument("--who", required=True); s.add_argument("--amount", type=int, required=True); s.set_defaults(func=cmd_heal)
    s = sub.add_parser("sethp"); s.add_argument("--who", required=True); s.add_argument("--current", type=int, required=True); s.add_argument("--max", type=int); s.set_defaults(func=cmd_sethp)
    s = sub.add_parser("condition"); s.add_argument("--who", required=True); s.add_argument("--add"); s.add_argument("--remove"); s.set_defaults(func=cmd_condition)
    sub.add_parser("next").set_defaults(func=cmd_next)
    s = sub.add_parser("declare"); s.add_argument("--who", required=True); s.add_argument("--action", required=True, help="what the player said their character does, in their words"); s.set_defaults(func=cmd_declare)
    sub.add_parser("end").set_defaults(func=cmd_end)

    args = p.parse_args()
    args.func(args)
    return 0


if __name__ == "__main__":
    sys.exit(main())
