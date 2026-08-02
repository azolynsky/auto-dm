# Strike! — classes, roles, and kits (summary)

A strike character is **Class | Role** plus a non-combat **Kit**. Classes and
kits at this table are homebrew-authored (the roster's sheets are the worked
examples — see `roster/strike/characters/`); this file explains the shape so
new ones can be built consistently. It deliberately does not reproduce the
published book's class and power lists.

## Class

The combat chassis: your attacks and encounter powers. A class contributes:

- a **Basic Attack** flavor (what your 2✸ At-Will looks like),
- 2–4 more **At-Will** or **always-on** powers (marks, stances, auras),
- 2–4 **Encounter** powers (the big swings — carry `used` flags),
- sometimes an **attack-table rider** or unusual vitals (Resist, Save 3+).

Power budget guide (from the roster examples, level 4): total ~8–10 powers
including role actions; damage values 2✸ at-will, 3✸ encounter; effects do
the interesting work, not the numbers.

## Role

What you do for the team. The four classic roles and their flavor:

- **Defender** — sticky; marks, punishes, soaks. Role actions force enemies
  to deal with you ("Choose Your Enemies", "You're mine!").
- **Striker** — single-target damage and mobility.
- **Controller** — battlefield shape: slides, zones, statuses ("Mass
  Hypnosis", "Psychic Static", "Sap Strength").
- **Leader (Support)** — healing, repositioning allies, action grants
  ("Psychic Surge", "Oh no you don't!").

Every character gets **Rally** (encounter — spend 1 AP: heal 4 HP, regain
one Class Encounter power) plus 1–3 role actions marked as such
(`role_actions[]` on the sheet).

## Kit

The non-combat package (see `skill-checks.md` § Kits): a theme name, 2–4
always-on abilities, and 1–4 powers — structured (BONUS/SUCCESS/TWIST/COST)
or freeform roll-and-consult. The kit is where a hero's out-of-combat
identity lives; it should overlap the character's skills, not duplicate them.

## Levels

Sheets record `level`; at this table advancement is milestone-based and
handled narratively (new tricks, powers, or kit entries by table agreement).
There is no XP track in the schema.
