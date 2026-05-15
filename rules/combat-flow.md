# Combat flow

## Starting an encounter

1. **Surprise check.** Anyone unaware of the threat doesn't act on round 1 turn 1 (can't move, act, or react until their next turn). Hidden creatures vs unaware ones cause surprise.
2. **Roll initiative.** `tools/combat_tracker.py start --participants "Alex:+3" "Friend:+1" ...` Modifier is the Dex bonus (+ any Alert / advantage feature).
3. **Establish positions** in narrative terms ("Alex is 30 ft from the goblin behind cover").

## Each round

For each participant in initiative order:

1. Apply start-of-turn effects (saving throws to end ongoing effects, regeneration, lair actions on init 20).
2. Player declares intent. Director decides what's possible; Rules Lawyer checks mechanics.
3. Movement, action, bonus action, and one free object interaction in any order.
4. Reactions occur outside the turn-holder's window (e.g. opportunity attacks).
5. Apply end-of-turn effects.
6. Advance with `combat_tracker.py next`.

## Opportunity attacks

Triggered when a hostile creature leaves your reach **without** Disengaging or teleporting. One melee attack, uses your reaction.

## Two-weapon fighting

If you take the Attack action with a light melee weapon, you can use your bonus action to attack with a different light melee weapon in your other hand. No ability mod to the off-hand damage (unless negative).

## Grappling and shoving

Both replace one attack of the Attack action.

- **Grapple**: contested Athletics (attacker) vs Athletics or Acrobatics (target's choice).
- **Shove**: contested same way; on win, push 5 ft or knock prone.

## Spells in combat

- **Casting time = 1 action**: takes your action.
- **Casting time = 1 bonus action**: takes your bonus action AND you can only cast a cantrip with your remaining action that turn (no other leveled spells that turn).
- **Casting time = 1 reaction**: takes your reaction.
- **Concentration**: see SRD reference.

## Damage and HP

- Track monster HP in `combat.json` via `combat_tracker.py damage`.
- Track PC HP there too **during** combat (don't write to character sheets every hit). Sync to character JSON at end-of-encounter.
- Resistance halves damage (after other math). Vulnerability doubles. Immunity zeroes. Apply resistance/vulnerability/immunity in that order: math, then resist, then vulnerable, then immune.
- Temp HP is a separate pool; damage drains it first, doesn't stack — taking new temp HP replaces.

## Ending an encounter

1. `combat_tracker.py end`
2. Bookkeeper syncs final PC HP, spell slots used, ammo, item charges to character sheets.
3. Bookkeeper updates `state/current.json` (time passed: ~6s × round count, plus any aftermath).
4. Narrator describes the aftermath.
5. If applicable, award XP per `encounter-building` skill.

## Lair / legendary actions

If a creature has them, run lair actions on initiative count 20 (losing ties), and legendary actions trigger after another creature's turn. Track legendary action budget in `combat.json` notes.
