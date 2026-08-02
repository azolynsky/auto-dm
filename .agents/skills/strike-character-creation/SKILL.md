---
name: strike-character-creation
description: Guide a player through getting a Strike! hero — pick one from the reusable roster or build a new one (class, role, skills, tricks, kit, powers) — and write the finished sheet as campaign character JSON. Use during session 0 of a strike campaign, when a new player joins, or when someone wants to replace a retired hero.
---

# Getting a Strike! hero

Two paths — offer both. Strike! characters are fast to build, but the roster
makes starting even faster.

## Path A: pick from the roster

1. `python tools/roster.py list` — show the players what exists (name,
   class | role, level, portrait). Describe each hero in a sentence.
2. When a player picks: `python tools/roster.py import --char <id>`.
   The sheet and portrait land in the campaign; the roster copy stays
   pristine for other campaigns.
3. Let the player personalize: rename `player`, adjust `notes`, swap a
   skill or trick if they want. The Bookkeeper edits the campaign copy.
4. Add the character id to `campaign/state/current.json:party[]`.

## Path B: build a new hero

Read `rules/strike/character-schema.md` (the JSON shape) and
`rules/strike/classes-and-roles.md` (what class/role/kit mean) first.
Build in conversation, one step at a time:

1. **Concept.** One sentence: who are they, what do they do, what's their
   deal. In a licensed setting, check the table is happy with the power
   level of existing roster heroes and match it.
2. **Class | Role.** Class = combat chassis (attacks + encounter powers);
   Role = team job (Defender/Striker/Controller/Leader). Homebrew classes
   are normal at this table — pattern-match a roster sheet with a similar
   fantasy.
3. **Vitals.** Defaults: HP 10, Speed 6, Resist 0–1, Reach 1,
   Opportunity 2✸, Save 4+. Deviations must be paid for by concept (a
   tough hero might get HP 13 + Save 3+ but fewer powers — see Colossus).
4. **Skills (5–8) + Tricks (1–3).** Freeform, flavorful, broad-but-not-
   everything ("Former Street Thief", not "Crime"). Tricks are signature
   moves a player can auto-succeed with for an Action Point.
5. **Complications (2).** Things that get them into trouble; using one
   earns an Action Point. Phrase them so the player wants to invoke them.
6. **Kit.** A named non-combat package: 1–3 always-on lines + 2–3 powers
   (structured BONUS/SUCCESS/TWIST/COST, or freeform text). Token-economy
   kits (see Cyclops's Determination, Nightcrawler's Daredevil Tokens) are
   great for driving play.
7. **Powers.** Basic attack (2✸) + ~4 at-wills + ~3 encounter powers +
   1–3 role actions + Rally. Damage stays flat (2✸ at-will / 3✸
   encounter); the interest lives in effects. Level 4 heroes on this
   roster run 8–12 powers total.
8. **Write the JSON** to `campaign/characters/<id>.json` per the schema —
   UTF-8, glyphs (✸ ∆ ⚡) welcome. Sanity-check by running a skill roll:
   `python tools/strike/check_resolver.py --skill "<a skill>" --char <path>`.
9. **Portrait** (optional): drop an image at
   `campaign/characters/images/<id>.jpg` or upload via the webapp sheet.
10. Add the id to `party[]`. If the hero should be reusable in future
    campaigns: `python tools/roster.py export --char <id>`.

## Session-0 table talk

While building, capture into `campaign/`: tone agreements
(`house-rules.md`), setting anchors (`world/overview.md`), and the
relationships between the chosen heroes (a line each in their `notes`).
Relationships matter mechanically — spending an Action Point can bring one
into play.
