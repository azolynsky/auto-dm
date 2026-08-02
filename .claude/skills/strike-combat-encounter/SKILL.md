---
name: strike-combat-encounter
description: Run a Strike! tactical combat from setup through end-of-fight — d6 attack tiers, Miss Tokens, Strikes, statuses, Rally, monster hit thresholds and Miss Triggers. Use whenever combat starts in a strike campaign, on every turn during combat, and to wrap up after the fight.
---

# Running Strike! combat

Procedure spine. Rules detail: `rules/strike/strike-reference.md` (attack
table, going down, chases) and `rules/strike/combat-flow.md` (turn
structure, statuses). Enemies come from `campaign/npcs/*/stats.json`
(shape: `rules/strike/statblock-schema.md`).

## Starting

1. **Set the scene**: battlefield, 1–2 pieces of interesting terrain, who's
   where. Note any scenario Miss Triggers.
2. **Start the tracker with listed order** (Strike! has no initiative
   rolls — players first in an order they choose, then enemies, unless the
   fiction says otherwise):
   ```bash
   python tools/combat_tracker.py start --order listed --participants "Wolverine::10" "Kitty::8" "Hammer1::6" "Elite1::4"
   ```
   Third field = HP. For hit-box units (Stooges/Goons), use **HP = number
   of hit boxes** and deal **1 per attack that meets the hit threshold**
   (e.g. a `1✸`-threshold Goon with 6 boxes → HP 6; a `4✸` Elite takes a
   hit only from 4+ damage in one attack). HP-tracked champions use real
   HP and real damage.
3. Anyone entering Winded/Exhausted: Disadvantage on attacks in round 1.
4. **Narrator** establishes the scene; the banner is already in the feed.

## Each PC turn

1. Start-of-turn effects; Ongoing damage (0 HP from Ongoing → one final
   action first). If down: Comeback Roll (d6 via dice.py: 1–2 lose 2 HP,
   3–4 nothing, 5–6 regain 1 and act).
2. **STOP. Ask the player.** State whose turn, HP, Action Points, Miss
   Tokens, active statuses. They get an Attack action, a Role action, and
   a Move, any order (Dazed: one action total).
3. Resolve attacks:
   ```bash
   python tools/strike/check_resolver.py --attack --mode normal --label "Wolverine claws vs Hammer1"
   ```
   Read the tier: 6 crit (FX + 2× damage) · 4–5 solid · 3 glancing
   (damage OR FX, attacker picks) · 2/1 miss. Apply the sheet's
   `attack_table_rider` if any. **Offer Miss Token spends** — the output's
   `with_miss_token` shows what +1 would buy; spending is the player's
   post-roll choice, Bookkeeper decrements `miss_tokens`.
4. **On any player miss: check the target's Miss Trigger** and resolve it.
5. Bookkeeper applies: monster hits/HP via `combat_tracker.py damage`,
   PC-side bookkeeping (miss_tokens, strikes, `used` flags on encounter
   powers, action_points on Rally/triggers) on the sheet. Narrator
   describes. `combat_tracker.py next`.
6. End of turn: Saving Throws (d6, sheet's `save`, default 4+; Harried =
   Disadvantage) against each save-ends effect.

## Each enemy turn

1. Director decides intent from the statblock's traits and the fiction.
2. Enemy attacks use the same resolver (`--attack`); enemies don't
   accumulate Miss Tokens/Strikes unless their block says so. Damage to
   PCs: `combat_tracker.py damage` (sync to sheets at end of fight).
3. Statuses on/off: `combat_tracker.py condition --who X --add dazed`.
4. Champions with multi-turn initiative ("act on 7/5/3") get each of those
   turns in the listed order — put them in the list once per action slot.

## Always in play

- **Opportunities** (2✸ or the sheet's value): leaving reach without
  shifting, ranged adjacent, Marked violations, gaining Flying adjacent.
- **Rally** (encounter, own turn, even while down): spend 1 AP → +4 HP and
  regain one Class encounter power (some sheets differ — read them).
- **Advantage/Disadvantage**: `--mode advantage|disadvantage` on the
  resolver (flanking/prone → melee Adv; cover/concealment → attackers
  Disad). One of each cancels; nothing stacks.
- **Improvised attacks**: 3 damage, GM-set effect, no power needed.

## Ending

1. `python tools/combat_tracker.py end` — posts the wrap-up banner.
2. **Strikes → conditions** per PC: 2–3 Winded · 4 Exhausted · 5+ Injured.
   Write conditions to sheets; zero out `strikes` and `miss_tokens`.
3. Reset encounter powers' `used` to false; sync PC HP from the tracker
   back to the sheets (Bookkeeper).
4. Narrator closes the scene; Bookkeeper logs the fight in the session log.

## If it turns into a chase

Use the chase subsystem in `rules/strike/strike-reference.md` — secret
action pick + prediction, opposed d6s with range modifiers, Danger Level.
