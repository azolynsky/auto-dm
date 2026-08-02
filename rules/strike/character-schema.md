# Strike! character JSON schema

Every strike PC matches this shape so `tools/strike/check_resolver.py`, the
Bookkeeper, and the webapp can read it mechanically. Sheets live in
`campaign/characters/<id>.json`; reusable heroes live in
`roster/strike/characters/` and are copied in with `tools/roster.py`.

The exemplar below is abridged from a real sheet (a psychic
controller). Where other sheets diverge, the field notes say how.

```json
{
  "id": "emma-frost",
  "name": "Emma Frost",
  "player": "",
  "class": "Necromancer",
  "role": "Controller",
  "level": 4,
  "flavor": "Mutation: Telepathy",
  "notes": "Estranged heiress; ex-Hellfire Club; joined the X-Men.",
  "complications": ["Poor impulse control", "Can't resist a stinging put down"],

  "skills": [
    { "name": "Top Class Breeding, Darling", "skilled": true, "trick": "Cool under pressure" },
    { "name": "Wealth x 2", "skilled": true },
    { "name": "Mind Reading", "skilled": true },
    { "name": "Head Games", "skilled": true, "trick": "Erode Confidence" }
  ],

  "kit": {
    "name": "The Psychic",
    "always": [
      "Sense surface emotions",
      "Know if someone is deceptive",
      "Sense mental incursion"
    ],
    "powers": [
      {
        "name": "Mind Control",
        "bonus": "Control for concentration",
        "success": "Pick 1 (2 w/ cost): sight only, full attention, they have Disad, they read your mind",
        "twist": "KOd, faked out, bonded",
        "cost": "Both are Exhausted"
      },
      {
        "name": "Scout",
        "text": "When you go ahead to scout, make a skill roll and consult the scout table."
      }
    ]
  },

  "hp": { "max": 10, "current": 10 },
  "speed": 6,
  "resist": 1,
  "reach": "1",
  "opportunity": "2✸",
  "save": "4+",
  "attack_table_rider": null,

  "action_points": 1,
  "miss_tokens": 0,
  "strikes": 0,
  "conditions": [],

  "powers": [
    {
      "name": "Withering Look",
      "frequency": "at-will",
      "range": "HTH or R5",
      "damage": "2✸",
      "effect": "This is your Basic Attack.",
      "tags": ["basic-attack"]
    },
    {
      "name": "Psychic Mark",
      "frequency": "always-on",
      "effect": "First hit on each non-Stooge enemy applies your Psychic Mark. When such an enemy is Taken Out, all enemies within R3 of it and all Marked enemies take ✸1 and must Save or be Distracted until end of their next turn."
    },
    {
      "name": "Command the Weak-minded",
      "frequency": "encounter",
      "range": "R10",
      "damage": null,
      "effect": "Affects one Standard enemy. They must Save or be Dominated for the encounter.",
      "used": false
    },
    {
      "name": "Befuddle",
      "frequency": "always-on",
      "range": "B",
      "effect": "Boost: when you roll 3+ to attack, knock the target Prone or slide them 6 squares.",
      "tags": ["boost"]
    }
  ],

  "role_actions": [
    {
      "name": "Sap Strength",
      "frequency": "at-will",
      "range": "R5",
      "effect": "Target is Weakened (half damage, round down), save ends."
    },
    {
      "name": "Rally",
      "frequency": "encounter",
      "effect": "Spend 1 Action Point: heal 4 HP, regain one Encounter power."
    }
  ],
  "appearance": ""
}
```

Field notes:

- **`hp.current` may go negative** (down to −5 = Taken Out). `hp.max` is
  usually 10. No temp HP, hit dice, or death saves in this system.
- **`reach` / `opportunity` / `save` are strings** — sheets carry glyphs and
  per-character values (`"1⚡"`, `"2✸⚡"`, `"3+"`). Keep `✸` (damage), `∆`
  (encounter/miss-related), `⚡` (character-specific rider) verbatim; they
  are display text, never parsed.
- **`attack_table_rider`** — optional string when a sheet modifies the
  standard attack table (e.g. `"+ heal 1 on any 3+"` for a regenerator).
  `null` for the standard table.
- **`powers[].frequency`** ∈ `at-will` · `encounter` · `2x-encounter` ·
  `always-on` · `constant` · `reaction` · `stance` · `special` · `free`.
  **Stances**: one may be active at a time, switch once/turn free; put the
  stance's attack FX in `effect` and its while-active bonus in `passive`.
  Encounter powers carry `used: false` — the Bookkeeper flips it on use
  (for `2x-encounter`, use `false` → `1` → `true`) and resets at encounter
  end (or via Rally).
- **`buddy`** — optional. Some classes run a second unit (e.g. a Buddies
  striker with a pet): `{name, hp {max, current}, notes}`. Track the buddy's
  HP/statuses separately; the buddy's powers live in the main `powers[]`
  list tagged by name.
- **`kit.powers[]`** are structured (`bonus`/`success`/`twist`/`cost`) when
  the sheet gives the four outcomes, or freeform (`text`) when it doesn't.
- **`skills[].skilled`** is almost always `true` (you list what you're good
  at); an explicit `false` entry documents a known-but-unskilled area.
  `trick` is optional.
- **`action_points`** persists between sessions (1–3 at session start —
  Bookkeeper tops up to 1 if lower). **`miss_tokens`** and **`strikes`**
  reset at end of each fight (strikes convert to conditions first — see
  `combat-flow.md`).
- **Bookkeeper is the only writer.** Mid-combat monster HP lives in
  `campaign/state/combat.json`; PC HP edits go here.
- NPC/monster statblocks use a different shape: `statblock-schema.md`.
