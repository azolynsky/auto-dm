---
name: leveling-up
description: Walk a player through gaining a level — HP, proficiency, features, spells, ASIs/feats. Updates character JSON and session log. Use when a PC hits an XP threshold (or whenever milestone leveling triggers).
---

# Leveling up

## When it happens

- **XP leveling**: cross threshold in PHB 15 (300 → level 2, 900 → 3, etc.). Bookkeeper notices and prompts.
- **Milestone leveling**: DM declares it. Note the trigger event in the session log.

Don't auto-apply. Walk the player through.

## Steps (in order)

1. **Confirm class progression** the player wants (if multiclassing-eligible).
2. **Update class level and total level.**
3. **HP gain.** Two options:
   - **Fixed average**: hit die avg + Con mod (rounded up the first time, alternating thereafter). For d8: average 5 → "5 + Con mod each level". Boring but reliable.
   - **Roll**: `python tools/dice.py 1d8 normal --label "HP for Ren level 3"`. Add Con mod. Minimum gain = 1. Risk a low roll for chance at a higher one.
   - Add to `hp.max` AND `hp.current` (you also heal up the new HP if at full).
4. **Proficiency bonus.** Updates at 5, 9, 13, 17 (+1 each step from 2 → 6). Update `proficiency_bonus`.
5. **Class features.** Look up the class table. Common at low levels:
   - L2 — class feature (Cunning Action for Rogue, Action Surge for Fighter, etc.)
   - L3 — subclass pick + first subclass feature
   - L4, 8, 12, 16, 19 — **Ability Score Improvement** (ASI) or feat
   - L5 — Extra Attack (martials), 3rd-level spells (full casters)
6. **Spells.**
   - Add 1 known/prepared as class allows.
   - New highest spell level: add slots.
   - For prepared casters (Cleric, Druid, Wizard): re-prepare list (= caster level + ability mod, min 1).
7. **Hit dice.** `hit_dice.total += 1`. Remaining doesn't reset; it bumps by 1.
8. **Update derived stats**:
   - Initiative bonus (Dex mod, plus features)
   - Passive perception (10 + Wis mod + Perception prof)
   - Spell save DC = 8 + prof + ability mod
   - Spell attack = prof + ability mod
   - Attack bonuses (prof + ability mod for proficient weapons)
9. **Record in session log.** "Ren levels to 3 (Rogue / Arcane Trickster): HP 12 → 19, gains Mage Hand Legerdemain and 2nd-level spell slots."

## ASI vs feat (level 4, 8, 12, 16, 19)

Player chooses:
- **+2 to one ability** OR **+1 to two abilities** (max 20)
- **A feat** (PHB or extended; check with DM)

Update ability scores, recompute derived stats.

## Multiclassing

Requires 13+ in the relevant ability of both classes (and the original). Use multiclass spellcaster table for combined slots if both classes cast.

## Output

After applying, summarize:

```
Ren is now Level 3 Rogue (Arcane Trickster).
- HP: 12 → 19 (rolled 1d8, got 5; +2 Con)
- Proficiency bonus: still +2 (next bump at L5)
- New feature: Arcane Trickster — cast Mage Hand, learn 3 wizard cantrips + 3 1st-level wizard spells, INT-based
- Spell slots: 2 × 1st-level
- Saved: campaign/characters/<id>.json
```
