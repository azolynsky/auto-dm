# Character JSON schema

Every PC and significant NPC should match this shape so `tools/check_resolver.py`
and the Bookkeeper agent can read them mechanically. Sheets live in
`campaign/characters/<id>.json`; the webapp shows every sheet in that folder,
ordered by `campaign/state/current.json` `party[]`.

```json
{
  "id": "pc-kestrel",
  "name": "Character name",
  "player": "Player name",
  "race": "Half-Elf",
  "class": "Rogue",
  "subclass": "Arcane Trickster",
  "level": 1,
  "xp": 0,
  "alignment": "Chaotic Good",
  "background": "Charlatan",

  "abilities": {
    "str": 10, "dex": 16, "con": 12,
    "int": 14, "wis": 10, "cha": 14
  },
  "proficiency_bonus": 2,
  "save_proficiencies": ["dex", "int"],

  "skills": {
    "stealth": "expertise",
    "sleight_of_hand": "expertise",
    "perception": "proficient",
    "deception": "proficient",
    "investigation": "proficient"
  },

  "ac": 14,
  "hp": { "max": 9, "current": 9, "temp": 0 },
  "hit_dice": { "size": "d8", "total": 1, "remaining": 1 },
  "speed": 30,
  "initiative_bonus": 3,
  "passive_perception": 12,

  "languages": ["Common", "Elvish", "Thieves' Cant"],
  "proficiencies": {
    "armor": ["light"],
    "weapons": ["simple", "hand crossbows", "longswords", "rapiers", "shortswords"],
    "tools": ["thieves' tools", "disguise kit"]
  },

  "features": [
    { "name": "Sneak Attack", "source": "Rogue 1", "uses": "1/turn", "detail": "+1d6 once per turn under conditions" },
    { "name": "Second Wind", "source": "Fighter 1", "uses": { "max": 1, "remaining": 1, "per": "short rest" } },
    { "name": "Thieves' Cant", "source": "Rogue 1" }
  ],

  "attacks": [
    {
      "name": "Rapier",
      "type": "melee",
      "to_hit": "+5",
      "damage": "1d8+3 piercing",
      "properties": ["finesse"]
    },
    {
      "name": "Shortbow",
      "type": "ranged",
      "to_hit": "+5",
      "damage": "1d6+3 piercing",
      "range": "80/320"
    }
  ],

  "spells": {
    "ability": null,
    "save_dc": null,
    "attack_bonus": null,
    "slots": {},
    "known": []
  },

  "inventory": [
    { "item": "Rapier", "qty": 1 },
    { "item": "Shortbow", "qty": 1, "ammo": 20 },
    { "item": "Thieves' tools", "qty": 1 },
    { "item": "Burglar's pack", "qty": 1 }
  ],
  "gold": 15,

  "conditions": [],
  "exhaustion": 0,
  "death_saves": { "successes": 0, "failures": 0 },

  "personality": {
    "traits": [],
    "ideals": [],
    "bonds": [],
    "flaws": []
  },
  "notes": ""
}
```

Rules of the road:

- **Bookkeeper is the only writer.** Other agents read, but never edit. Concurrent edits cause drift.
- **Mid-combat HP for PCs lives in `campaign/state/combat.json`**, not here. Sync at end of encounter.
- **Spell slots tick down** when used, **reset** on long rest. Bookkeeper handles both.
- **Feature `uses`** is a plain string when it's just a note ("1/turn"), or `{max, remaining, per}` when it's a tracked pool — the Bookkeeper decrements `remaining` on use and resets on the matching rest, and the webapp shows availability pips.
- **Inventory uses items with `qty`** — never edit prose lists, always structured entries.
