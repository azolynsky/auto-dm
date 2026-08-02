---
name: skill-check
description: Resolve a player's attempt to do something uncertain — climb, sneak, persuade, pick a lock, recall lore, sense motive. Decides whether to roll and runs the active system's resolver.
---

# Skill checks

## Decide first: roll or not?

See the active system's skill-checks reference ("When to call for a roll") —
look up its `rules_dir` in `rules/systems.json` via the campaign's
`state/current.json:system` (dnd5e: `rules/dnd5e/skill-checks.md`;
strike: `rules/strike/skill-checks.md`).
You need all three:

1. Meaningful chance of failure
2. Failure is interesting (not "nothing happens")
3. Plausible success

If yes to all three, roll. Otherwise narrate. (Strike! states it as: **say
yes or let them roll.**)

## Identify advantage/disadvantage

One source flips the dice. Multiple sources of the same don't stack. One of
each cancels. Triggers live in the system's skill-checks reference. Helping
allies grant advantage (dnd5e Help action) or roll a Helping die (strike).

## Run the roll

Use the **active system's** `check_resolver` from `rules/systems.json` —
never another system's math.

### dnd5e — `tools/dnd5e/check_resolver.py`

Pick a DC first (don't roll to set it): 10 journeyman · 15 experienced,
half the time · 20 master, occasionally · 25 heroic · 30 legendary.

```bash
python tools/dnd5e/check_resolver.py \
    --char "<active save>/characters/<id>.json" \
    --skill stealth --dc 15 --mode advantage
```

`--ability str` for raw checks, `--save dex` for saves. Output JSON has
`success` and `margin`. Interpret margin: ≥5 clean success (maybe a bonus
detail) · 0–4 success with a cost · −1..−4 near miss (partial info) ·
≤−5 clear failure. Nat 20 isn't an auto-success on checks.

### strike — `tools/strike/check_resolver.py`

No DCs. The d6 outcome table does the interpretive work:

```bash
python tools/strike/check_resolver.py \
    --skill "Mind Reading" \
    --char "<active save>/characters/<id>.json" \
    --mode advantage
```

Skills not on the sheet roll Unskilled automatically; `--skill-roll
--skilled|--unskilled` for NPCs. The output's `outcome` (Success/Bonus/
Cost/Twist) is binding: a **Twist must change the situation**, a **Cost**
is a real temporary penalty (condition, flaw, favor, linked Disadvantage).
If the sheet lists a Trick for the skill, remind the player they may spend
an Action Point to auto-succeed instead of rolling. Opposed rolls, Linked
Rolls, Helping, group rolls: `rules/strike/skill-checks.md`.

## Group checks

- dnd5e: everyone rolls; ≥ half succeed = group succeeds.
- strike: everyone-must-pass → worst-positioned player rolls, others Help;
  only-one-must-pass → best-positioned rolls, others Help.

## Contested checks

- dnd5e: both roll, higher total wins, ties = defender/status quo.
- strike: Opposed Roll — win by 3+ clean; by 1–2 the loser picks a
  concession; tie = neither (an Action Point breaks a tie).

## Passive checks (dnd5e only)

Hidden or long-duration checks: passive = 10 + mods (advantage +5,
disadvantage −5). Strike! has no passive math — if there's nothing
interesting in a failure, just say what they notice.

## Anti-patterns

- "Roll Perception" with no context. Always tie the roll to a stated action.
- Rolling the same check multiple times "to try again". One roll per
  attempt unless conditions change.
- Letting a Persuasion roll override stated NPC motivation. Persuasion
  sets the ceiling. (Strike!: the NPC disposition table in
  `rules/strike/gm-reference.md` sets what's even rollable.)
