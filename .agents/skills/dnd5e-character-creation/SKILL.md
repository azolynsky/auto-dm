---
name: dnd5e-character-creation
description: Guide a player through creating a D&D 5e character — abilities, race, class, background, derived stats, equipment, spells — and write the finished sheet as campaign character JSON. Use during session 0 of a dnd5e campaign, when a new player joins, or when someone wants to replace a dead or retired PC.
---

# Creating a D&D 5e character

You are walking one player through building a character. Keep it conversational —
one decision at a time, never a wall of questions. The finished product is a JSON
sheet matching `rules/dnd5e/character-schema.md`, written to
`<save>/characters/<id>.json` (the active save's `characters/` folder).

Rules source: `rules/dnd5e/srd/` — races in `01_Races/`, classes in
`02_Classes/`, backgrounds in `03_Backgrounds`, equipment in `04_Equipment`,
spells in `07_Spells/Spells_Each/`. Grep, don't guess. SRD content only, unless
the table's house rules say otherwise.

## 0. Concept first

Ask what they want to *play*, not what stats they want: "a sneaky ex-noble", "a
big kind wall of muscle". One sentence is enough — it drives every default you
offer below. If they already know 5e and rattle off "hill dwarf life cleric",
skip ahead and just confirm choices.

## 1. Ability scores

Offer the table's method (check `house-rules.md`; default: standard array).

- **Standard array**: 15, 14, 13, 12, 10, 8 — assign to STR/DEX/CON/INT/WIS/CHA.
- **Point buy** (27 points, scores 8–15 before racial bonuses).
- **Rolled**: `python tools/dice.py 4d6 4d6 4d6 4d6 4d6 4d6 --mode drop-lowest --label "ability scores"`
  — player assigns results. Roll honestly; no rerolls unless house rules allow.

Advise placement from their concept (the sneaky one wants DEX, the wall wants STR/CON).

## 2. Race

Offer the SRD races (`rules/dnd5e/srd/01_Races/`). Apply ability increases,
speed, size, darkvision, languages, and racial traits to your working sheet.

## 3. Class (level 1 unless the campaign starts higher)

Offer the SRD classes (`rules/dnd5e/srd/02_Classes/`). Record:

- **Hit die and HP**: max die + CON mod at level 1.
- **Saving throw proficiencies** → `save_proficiencies`.
- **Skill choices** (from the class list) → `skills` as `"proficient"`.
- **Armor/weapon/tool proficiencies** → `proficiencies`.
- **Level-1 features** → `features[]` (with `uses` objects for per-rest resources).
- **Spellcasting** if any: slots, cantrips, known/prepared spells → `spells`
  (per the class table; spell save DC = 8 + prof + casting mod, attack = prof + casting mod).

## 4. Background

SRD default is Acolyte; most tables allow building a simple custom background
(two skills, a tool or language, a small kit). Record skills, and prompt for
`personality` (traits/ideals/bonds/flaws) — one or two honest lines each, or
skip and fill in during play.

## 5. Equipment

Class + background starting equipment (or starting gold if the table prefers
buying). Fill `inventory[]` (structured `{item, qty}` entries), `gold`, and
`attacks[]` for weapons carried (to_hit = prof + STR/DEX mod as appropriate;
finesse/ranged use DEX).

## 6. Derive the numbers

- `proficiency_bonus`: +2 at level 1.
- `ac`: armor worn + DEX mod (cap per armor type), or 10 + DEX unarmored
  (13 + DEX mage armor, 10 + DEX + CON barbarian, 10 + DEX + WIS monk).
- `initiative_bonus`: DEX mod.
- `passive_perception`: 10 + Perception bonus.
- `hp` / `hit_dice` per class and level.
- Double-check every skill in `skills` maps to the right ability.

## 7. Write the sheet and seat the character

1. Write the JSON to the active save's `characters/<id>.json` (`id` pattern:
   `pc-<name>`, lowercase, hyphenated). Validate the shape against
   `rules/dnd5e/character-schema.md` — every top-level key present.
2. Add the id to `state/current.json` `party[]` (Bookkeeper).
3. Sanity-check with a real roll:
   `python tools/dnd5e/check_resolver.py --char "<active save>/characters/<id>.json" --skill perception --dc 10`
   — if it errors, the sheet has a schema problem; fix it now.
4. Portrait (optional): webapp → character card → "Set portrait…", or drop an
   image named by character id into `characters/images/`.
5. Read the finished character back to the player in one short paragraph —
   concept, the numbers that matter, and their opening hook.
