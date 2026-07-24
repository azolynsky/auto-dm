---
name: spellcasting
description: Resolve a spell cast — slot consumption, attack/save mechanics, concentration, counterspell timing, components. Use whenever a PC or NPC casts.
---

# Spellcasting

## Steps for any cast

1. **Confirm the slot.** The caster expends a spell slot of the spell's level or higher (cantrips: no slot). Bookkeeper decrements `campaign/characters/<id>.json:spells.slots`.
2. **Check the casting time.**
   - Action: takes the action. Done normally.
   - Bonus action: takes the bonus action. **You cannot cast a leveled spell with your action that turn** — only a cantrip.
   - Reaction: must have a trigger (e.g. Shield triggers on being hit).
   - Longer: ritual or 1-minute+ casts are interruptible by damage / loss of concentration / hostile creature.
3. **Components.** V (verbal), S (somatic), M (material). If silenced → no V. If hands full / restrained → no S unless a free hand. M can be replaced by a focus / component pouch (unless costed or consumed).
4. **Targets and range.** Check spell description. AoE: count squares from origin point.
5. **Resolution:**
   - **Spell attack**: caster rolls `1d20 + spell attack bonus` vs target AC.
     ```bash
     python tools/dice.py 1d20+6 normal --label "Fire Bolt attack"
     ```
   - **Saving throw**: target rolls vs spell save DC.
     ```bash
     python tools/check_resolver.py --char campaign/characters/<id>.json --save wis --dc 14
     ```
   - **Auto-effect**: applies as written, no roll.
6. **Damage / effect.** Roll damage dice. Halve on save unless spell says otherwise.
7. **Concentration.** If the spell requires concentration, set `active_effects` on the caster in `campaign/state/current.json` (or in `combat.json` during combat).

## Concentration

- One concentration spell at a time. Casting a new one drops the old one.
- Taking damage triggers a Con save: DC = max(10, ⌊damage / 2⌋).
- Falling unconscious or being incapacitated drops concentration.
- Death drops it too (obviously).

## Counterspell timing

When a creature you can see within 60 ft casts a spell, you can use your reaction to cast Counterspell.

- If the target spell is ≤ the slot level you used for Counterspell: auto-counter.
- If higher: ability check. `1d20 + your spellcasting ability mod`, DC = 10 + target spell's level.

Counterspell on Counterspell is legal. Resolve outer-most last.

## Spell slot recovery

- **Long rest**: all slots reset (most classes).
- **Short rest**: Warlock slots refresh. Wizard Arcane Recovery once per long rest. Druid Natural Recovery, etc.

Bookkeeper handles this — see `bookkeeper.md`.

## Multiclass spell slots

Use the multiclass spellcaster table (PHB 165). Slots are unified across casting classes; known/prepared spells track per class.

## Common rulings

- **Twinned Spell**: only on a spell that targets a single creature and has no AoE option. Fireball can't be twinned. Hold Person can.
- **Quickened Spell**: changes casting time to bonus action. Same-turn cantrip restriction applies (you can use your action for a cantrip OR something non-spell — not a second leveled spell).
- **War Caster**: lets you cast a spell as the opportunity attack. The spell must target only the leaving creature and have a casting time of 1 action.
- **Subtle Spell**: removes V and S — useful to bypass Counterspell (the counterspell-er has to see you casting to react).
