# 5e SRD — quick reference

Authoritative source: the System Reference Document 5.1, © Wizards of the
Coast LLC, used under the Creative Commons Attribution 4.0 International
license (CC-BY-4.0). This project is unaffiliated with Wizards of the Coast. This file is a working
cheat sheet for the Rules Lawyer agent. **When in doubt, defer to the full SRD
text in `rules/srd/` over what's written here** — grep it, don't guess — and
add corrections.

## Ability checks

`d20 + ability modifier (+ proficiency if proficient with a skill or tool)`
Compare against the DC. Ties go to the defender / status quo.

| DC | Difficulty |
|----|------------|
| 5  | Very easy |
| 10 | Easy |
| 15 | Medium |
| 20 | Hard |
| 25 | Very hard |
| 30 | Nearly impossible |

Advantage = roll twice, take higher. Disadvantage = take lower. They cancel
1-for-1 — multiple sources do **not** stack, you're just "with" or "without."

Passive check = 10 + all modifiers that would normally apply. Used silently
(perception, insight).

## Saving throws

Same as ability checks but vs a fixed save DC or spell DC.

Spell save DC = 8 + proficiency + spellcasting ability modifier.
Spell attack bonus = proficiency + spellcasting ability modifier.

## Attacks

`d20 + ability mod + proficiency (if proficient with weapon)` vs target AC.
Natural 20 = automatic hit AND a critical (roll damage dice twice, then add modifiers once).
Natural 1 = automatic miss.

Damage on a crit: roll all damage dice twice, sum, then add modifiers.

## Action economy (per turn in combat)

- 1 action (Attack, Cast a Spell, Dash, Disengage, Dodge, Help, Hide, Ready, Search, Use an Object, or class-specific)
- 1 bonus action (only if a feature grants one)
- 1 reaction (per round, not per turn — refreshes at start of your turn)
- Movement up to your speed, splittable around actions
- "Free" object interaction: 1 per turn (draw weapon, open unlocked door, etc.)

## Death saves

At 0 HP: down but not dead.
Each turn at 0 HP: roll d20.
- 10+ = success
- <10 = failure
- Natural 20 = pop up at 1 HP
- Natural 1 = 2 failures
- 3 successes = stable (unconscious at 0)
- 3 failures = dead
- Taking damage at 0 HP = 1 failure (2 if crit). Damage ≥ max HP at 0 HP = instant death.

## Concentration

Spells with Concentration drop if you:
- Cast another concentration spell
- Are incapacitated, killed, or fall unconscious
- Take damage — Con save vs DC max(10, half damage taken)

## Rest

- **Short rest** (1 hour): spend Hit Dice (`1dN + Con mod`) to heal. Some features recharge.
- **Long rest** (8 hours, ≤2 of which can be light activity): full HP, half your total HD recovered (min 1), all spell slots, most resources reset. Can only benefit from one long rest per 24 hours.

## Cover

- Half cover: +2 AC and Dex saves
- Three-quarters: +5 AC and Dex saves
- Total cover: can't be targeted directly

## Conditions (compact)

- **Blinded** — auto-fail sight checks; attacks vs you have advantage, your attacks have disadvantage
- **Charmed** — can't attack the charmer; charmer has advantage on social checks vs you
- **Deafened** — auto-fail hearing checks
- **Frightened** — disadvantage on checks/attacks while source is in sight; can't move closer
- **Grappled** — speed 0; ends if grappler is incapacitated or you're moved away
- **Incapacitated** — no actions or reactions
- **Invisible** — attacks vs you have disadvantage, your attacks have advantage; heavily obscured
- **Paralyzed** — incapacitated, can't move/speak, auto-fail Str/Dex saves; attacks vs have advantage; melee hits crit
- **Petrified** — like paralyzed + resistant to all damage + immune to poison/disease
- **Poisoned** — disadvantage on attacks and checks
- **Prone** — disadvantage on attacks; melee attacks vs you have advantage, ranged have disadvantage
- **Restrained** — speed 0; disadvantage on attacks and Dex saves; attacks vs you have advantage
- **Stunned** — incapacitated, can't move, speak only falteringly; auto-fail Str/Dex saves; advantage to hit
- **Unconscious** — incapacitated + prone + drops what it holds; auto-fail Str/Dex saves; advantage to hit; melee hits crit

## Exhaustion

| Level | Effect |
|-------|--------|
| 1 | Disadvantage on ability checks |
| 2 | Speed halved |
| 3 | Disadvantage on attacks and saves |
| 4 | HP max halved |
| 5 | Speed 0 |
| 6 | Death |

Long rest with food/water removes 1 level.

## Movement

- Walking = 1 ft per ft of speed.
- Difficult terrain = 2 ft per ft.
- Climb/swim = 2 ft per ft (unless you have a climb/swim speed).
- Standing from prone = half your speed.
- Jumping: long = Str score ft running, half standing; high = 3 + Str mod ft running, half standing.

## Encumbrance (optional but recommended)

- Carry capacity = Str × 15 lb.
- Beyond Str × 5, speed -10 (encumbered) — only if using variant encumbrance.

See `combat-flow.md` and `skill-checks.md` for procedural details.
