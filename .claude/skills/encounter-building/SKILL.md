---
name: encounter-building
description: Build (or evaluate) a combat encounter — CR math, XP budgets, monster mix, terrain considerations, expected outcome. Use in prep, or on the fly when the Director wants to escalate.
---

# Encounter building

## XP thresholds per character (PHB 82)

| Char level | Easy | Medium | Hard | Deadly |
|------------|------|--------|------|--------|
| 1  | 25  | 50  | 75  | 100 |
| 2  | 50  | 100 | 150 | 200 |
| 3  | 75  | 150 | 225 | 400 |
| 4  | 125 | 250 | 375 | 500 |
| 5  | 250 | 500 | 750 | 1100 |
| 6  | 300 | 600 | 900 | 1400 |
| 7  | 350 | 750 | 1100 | 1700 |
| 8  | 450 | 900 | 1400 | 2100 |
| 9  | 550 | 1100 | 1600 | 2400 |
| 10 | 600 | 1200 | 1900 | 2800 |

Sum per-character thresholds for the party.

## Encounter XP budget

`party_threshold` (sum across PCs at the chosen difficulty) determines the budget.

## Monster XP by CR (compact)

| CR | XP |
|----|----|
| 0   | 10  |
| 1/8 | 25  |
| 1/4 | 50  |
| 1/2 | 100 |
| 1   | 200 |
| 2   | 450 |
| 3   | 700 |
| 4   | 1100 |
| 5   | 1800 |
| 6   | 2300 |
| 7   | 2900 |
| 8   | 3900 |
| 9   | 5000 |
| 10  | 5900 |

## Multiplier for groups

When summing monster XP for difficulty calc only, apply:

| Count | Multiplier |
|-------|------------|
| 1   | ×1 |
| 2   | ×1.5 |
| 3–6 | ×2 |
| 7–10 | ×2.5 |
| 11–14 | ×3 |
| 15+ | ×4 |

If party is < 3 PCs, bump the multiplier up one row. If party is 6+, drop one row.

For **XP awarded** to players, use the raw XP without the multiplier.

## Procedure

1. Pick difficulty (Easy / Medium / Hard / Deadly).
2. Look up `party_threshold` = sum of per-PC thresholds.
3. Pick monsters with a total **adjusted** XP (after multiplier) ≤ `party_threshold`.
4. Sanity check: a single CR > party level monster against a small party is a TPK risk. Cap solo monster CR at `party_level + 2`.
5. Don't forget terrain. Cover, elevation, choke points, hazards. A "Hard" fight on open ground can be a Medium one in a corridor.

## Example

Party of 2 at level 2. Medium threshold = 100 + 100 = 200.

- 4 goblins (CR 1/4 each = 50 XP × 4 = 200 raw, ×2 multiplier = 400 adjusted) → Hard-Deadly.
- 2 goblins + 1 wolf (50 + 50 + 50 = 150 raw, ×2 = 300 adjusted) → Hard.
- 3 goblins (50 × 3 = 150 raw, ×2 = 300 adjusted) → Hard.
- 2 goblins (50 × 2 = 100 raw, ×1.5 = 150 adjusted) → Medium-ish. Solid choice for a normal road encounter.

## Awarding XP

Use **raw** monster XP (no multiplier). Sum across encounter. Divide by number of PCs. Award equally.

Roleplay-only sessions: award nothing (milestone) or a flat amount per "scene of consequence" — house rule decision.

## Calibration

Watch for:
- Action economy mismatch — many low-CR monsters can crush a small party (more attacks, more chances to crit).
- Damage spikes — a single high-damage attack can drop a PC instantly. Avoid in early sessions.
- Save-or-suck spells in monster blocks (Hold Person, Banshee Wail) — escalate the fight from "interesting" to "lethal" fast.
