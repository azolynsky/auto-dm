---
name: skill-check
description: Resolve a player's attempt to do something uncertain — climb, sneak, persuade, pick a lock, recall lore, sense motive. Decides whether to roll, what DC, and runs the resolver.
---

# Skill checks

## Decide first: roll or not?

See `rules/skill-checks.md` "When to call for a roll". You need all three:

1. Meaningful chance of failure
2. Failure is interesting (not "nothing happens")
3. Plausible success

If yes to all three, roll. Otherwise narrate.

## Pick the DC

Default 15. Adjust by ±5. Common buckets:

- **DC 10** — a journeyman could do it nine times out of ten
- **DC 15** — an experienced adult, half the time
- **DC 20** — a master, occasionally
- **DC 25** — heroic
- **DC 30** — legendary, near impossible

Don't roll to set the DC. Pick it from the situation.

## Identify advantage/disadvantage

One source flips the dice. Multiple sources of the same don't stack. One of each cancels.

Triggers in `rules/skill-checks.md` "Advantage / disadvantage triggers".

The Help action grants advantage when an ally could plausibly assist.

## Run the roll

```bash
python tools/check_resolver.py \
    --char campaign/characters/<id>.json \
    --skill stealth \
    --dc 15 \
    --mode advantage
```

Modes: `normal`, `advantage`, `disadvantage`.
Output is JSON with `success`, `margin`, and the full roll.

For ability checks without a skill, use `--ability str` (or dex, etc.). For saves use `--save dex`.

## Interpret margin

- **Crit success (nat 20)** on skill checks isn't a rule. Don't auto-succeed impossible tasks. But if it was already possible, the margin can be huge → exceptional result.
- **Margin ≥ 5** = clean success, often with a bonus detail.
- **Margin 0–4** = success with a cost or complication if appropriate.
- **Margin -1 to -4** = failure but close — partial info, alerted but not caught.
- **Margin ≤ -5** = clear failure.

## Group checks

When the whole party tries together: each rolls; ≥ half succeed = group succeeds.

## Contested checks

Both sides roll. Higher total wins. Ties = defender / status quo.

## Use passive checks when

- Hidden checks the players shouldn't know are happening (perception while walking).
- Long-duration repeated tasks (lookouts on watch).
- Want to avoid telegraphing.

Passive = 10 + all relevant mods. Advantage = +5, disadvantage = -5.

## Anti-patterns

- "Roll Perception" with no context. Always tie the roll to a stated action.
- Rolling the same check multiple times "to try again". One roll per attempt unless conditions change.
- Letting a Persuasion roll override stated NPC motivation. Persuasion sets the ceiling.
