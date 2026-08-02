# Strike! NPC/monster statblock schema

Enemy statblocks live in `campaign/npcs/recurring/<id>/stats.json` (or
`roster/strike/villains/<id>/stats.json` before import). One file holds an
**array** of units — villain teams usually field several types.

```json
[
  {
    "name": "U-Men Hammers",
    "color": "Red",
    "level": 4,
    "tier": "goon",
    "type": "Goon Brute",
    "move": 6,
    "hit_threshold": "1✸",
    "quantity": "4 / 5 / 6",
    "hits": ["A", "B", "C", "D", "E", "F"],
    "traits": [
      { "name": "Hydraulic Servos", "text": "When Slowed you Move 4. When Immobilized, Move 2. Free when Grabbed." },
      { "name": "Magnetic Stabilizers", "text": "Cannot be Thrown. Reduce Forced Movement by 1." }
    ],
    "powers": [
      { "name": "Servo Punch", "frequency": "at-will", "range": "HTH", "damage": "2✸", "effect": "Target is thrown 3 squares." },
      { "name": "Grappling Cables", "frequency": "at-will", "range": "HTH", "damage": "2✸", "effect": "Target is Grabbed." }
    ],
    "miss_trigger": {
      "frequency": "at-will",
      "text": "When an enemy misses you, gain a second hit (it takes 2 blows to take you out). Doesn't stack."
    }
  }
]
```

Field notes:

- **`tier`** ∈ `stooge` · `goon` · `elite` · `champion` — from weakest
  (Stooges drop to any hit) upward. `type` is the sheet's display line
  ("Stooge Leaders", "Goon Brute", "Goon Sniper").
- **`hit_threshold`** — damage in one attack needed to score **a hit** on
  this unit (`"1✸"` for fodder, `"4✸"` for leaders). These units don't track
  HP pools: they track **hits** — `hits[]` is the row of hit boxes from the
  sheet (letters are just box labels; count = hits to take the unit out).
  In `combat_tracker.py`, register the unit with HP = number of hit boxes
  and apply **1 damage per threshold-meeting attack** (Miss Triggers or
  traits can add or remove boxes).
- **`quantity`** — how many to field by party size (the sheets write
  "4 / 5 / 6" meaning 3/4/5 players). Display string, GM reads it.
- **`miss_trigger`** — fires when a **player misses** this unit. Check it on
  every player miss; it's the system's main source of enemy reactions.
- **Champions/solo villains** may instead carry `hp {max, current}`, `save`,
  and full PC-style fields — a champion statblock is closer to a PC sheet;
  include what the sheet gives.
- `powers[]` entries use the same shape as PC powers
  (`character-schema.md`), so the combat skill reads both identically.
