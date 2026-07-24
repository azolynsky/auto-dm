---
name: combat-encounter
description: Run a combat encounter from initiative through end-of-fight. Use whenever combat starts, on every turn during combat, and to wrap up after the last enemy falls or surrenders.
---

# Running combat

Combat is the highest-state-density part of the game. Use this skill as the procedure spine.

## Starting

1. **Establish surprise.** Anyone unaware of the threat is surprised on their first turn. A hidden creature can surprise by Stealth (PCs) vs passive Perception (NPCs), or vice versa.
2. **Roll initiative — with monster HP inline** (third field). One command starts the whole encounter and posts the "⚔ Combat!" banner to the players' feed:
   ```bash
   python tools/combat_tracker.py start --participants "Ren:+3" "Bel:+1" "Goblin1:+2:7" "Goblin2:+2:7" "Goblin3:+2:7"
   ```
   Modifier = Dex bonus + any feature (Alert = +5; Advantage from a feature → roll twice via dice.py and keep higher manually). Use `sethp` only for HP discovered mid-fight.
3. **Narrator** establishes the scene (positions, terrain, light, distances).

## Each turn

Order: top of initiative → bottom → repeat.

### PC turn
1. **Apply start-of-turn effects** (regen, ongoing saves to end conditions).
2. **STOP. Ask the player what they do.** State whose turn it is and their current HP. Do not assume, guess, or auto-resolve their action. Wait for explicit declaration.
   Example: `It's Ren's turn (14 HP). What do you do?`
3. Once they declare: Rules Lawyer validates mechanics if anything is non-obvious.
4. Roll via `tools/dice.py`; Bookkeeper applies; Narrator describes.
5. Advance: `python tools/combat_tracker.py next`

### NPC/monster turn
1. **Apply start-of-turn effects.**
2. **Director decides intent** based on the monster's intelligence, motivation, and tactical position.
3. **Rules Lawyer validates** if non-obvious.
4. **Roll each attack, then describe it before the next.** Batch one attack's to-hit and damage into a single `dice.py` call (discard the damage on a miss); never collapse multiple *attacks* into one summary — each lands in prose before the next is rolled.
5. **Bookkeeper applies** damage/conditions/movement.
6. **Narrator describes each attack as it lands** — hit or miss, in full prose, before proceeding to the next roll.
7. Advance: `python tools/combat_tracker.py next`

### Feed discipline (no spoilers)

`combat_tracker.py damage/heal/condition` do NOT post to the players' feed — they queue effects. The next `narrate.py` call attaches them as subtext under the prose. So the rhythm is: **resolve mechanics → narrate** — and the players see "the goblin crumples" *with* "Goblin1 takes 6 damage — DOWN" beneath it, never the numbers first. Narrate every resolved beat so queued effects never go stale.

## Common micro-procedures

### Attack roll
```bash
# to-hit and damage in ONE call; ignore the damage result on a miss
python tools/dice.py 1d20+5 1d8+3 --label "Ren rapier vs Goblin1" --label "rapier damage"
# on crit (nat 20): roll the extra crit dice
python tools/dice.py 1d8 --label "rapier CRIT bonus"
```

### Saving throw
```bash
python tools/check_resolver.py --char campaign/characters/<id>.json --save dex --dc 15
```

### Concentration check on damage
DC = max(10, ⌊damage / 2⌋). Roll Con save.

### Death saves
At 0 HP:
```bash
python tools/dice.py 1d20 normal --label "Ren death save"
```
Track successes/failures in the character JSON (`death_saves.successes`/`failures`). 3 successes = stable. 3 failures = dead. Nat 20 = pop up at 1 HP. Nat 1 = 2 failures. Damage taken at 0 HP = 1 failure (2 if crit), or instant death if damage ≥ max HP.

## Ending

When the last enemy is down, surrendered, or fled:

1. `python tools/combat_tracker.py end`
2. **Bookkeeper syncs** final HP from `campaign/state/combat.json` to character JSONs.
3. **Bookkeeper resets** combat.json to inactive shape.
4. **Bookkeeper updates time** in `campaign/state/current.json` (combat is ~6s per round, but most players want to skip ahead — usually 5–10 minutes total elapsed including aftermath, looting, first aid).
5. **Award XP** per `encounter-building` skill.
6. **Narrator describes** the aftermath, then prompts the players.

## Pitfalls to avoid

- **Forgetting reactions.** Opportunity attacks, Shield, Counterspell, Hellish Rebuke. Each creature has 1 per round, refreshing at start of their turn.
- **Forgetting end-of-turn saves** (poisoned, restrained from web spell, etc.).
- **Letting Concentration slip silently.** When a concentrator takes damage, prompt the Con save before continuing.
- **Lethality drift.** Goblins shouldn't roleplay as tactical geniuses — they have Int 10 at best. Run dumb monsters dumb.
