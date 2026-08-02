# Strike! — tactical combat flow

Procedural companion to `strike-reference.md`. Combat runs on a grid (theater
of the mind works too — track adjacency, ranges, and zones narratively).

## Setup

1. Determine sides and battlefield (1–2 pieces of interesting terrain earn
   their keep). Note any scenario Miss Triggers.
2. Start the tracker with **listed order**, not rolled initiative:
   `python tools/combat_tracker.py start --order listed --participants ...`
   Strike! has no initiative rolls — the table agrees on an order (commonly
   players first in an order of their choosing, then enemies; alternate
   per-side if the fight calls for it).
3. Entering combat Winded or Exhausted: Disadvantage on attack rolls in the
   first round.

## On your turn (in order)

1. Resolve start-of-turn effects; take Ongoing damage. (If Ongoing damage
   would bring you to 0 HP, you get one final action first.)
2. Use your **Attack action**, **Role action**, and **Move action** — one of
   each, any order. (Dazed: only one action total.)
3. Roll **Saving Throws** (4+ unless your sheet says otherwise) against each
   save-ends effect on you.
4. Resolve end-of-turn effects.

Moves: **Move** up to speed · **Shift** 1 square (safe) · stand from Prone
(move action). Slowed = speed 2, cannot Shift.

## Attacks

Roll per the attack table in `strike-reference.md`. Damage is fixed; Effects
(FX) are per-power. Glancing (3): attacker picks damage OR effect. Crit (6):
effect + double damage.

- **Boosts** (`<B>` powers): riders that trigger on a roll condition (e.g.
  "when you roll 3+ to attack, knock the target Prone or slide 6"). Always on
  unless expended by their own wording.
- **Stances**: some characters know stances — start combat in one, switch
  once per turn (free). A stance adds an FX to the basic attack and a passive
  while you're in it.
- **Miss Triggers** (enemies): many statblocks have a reaction that fires
  when a player misses them. Check the statblock on every player miss.

## Action Points

- Start each session with at least 1, at most 3. GM awards 1 for something
  cool; using a Complication or Flaw earns one.
- In combat, spend to: **Rally** (regain 4 HP + one expended Class Encounter
  power — no action, own turn only, works while Incapacitated/Dominated) or
  use your **Action Trigger** (per sheet).

## Going down

At/below 0 HP: **Incapacitated** (Prone + Stunned; some of your effects
end). At/below −5: **Taken Out**. On your turn while down, make the
**Comeback Roll**: 1–2 lose 2 HP · 3–4 nothing · 5–6 regain 1 HP and take
your turn.

## Statuses

"No O/M" = grants no Opportunities and Miss Effects don't trigger off it.
MBA/RBA = Melee/Ranged Basic Attack.

- **Blinded** — your attacks Disad; melee vs you Adv. No O/M.
- **Bloodied** — below half HP. No inherent effect.
- **Dazed** — one action per turn. No O/M.
- **Distracted** — no Role Actions. No O/M.
- **Dominated** — dominator dictates your actions. No O/M.
- **Frenzied** — roll d6: 1 Dominated · 2 run at origin, MBA with Disad if in
  range · 3–4 charge origin (or run + RBA it) · 5–6 normal turn, Basic
  Attacks only.
- **Flying** — no melee to or from non-Flyers; no Opportunities either way
  with non-Flyers.
- **Grabbed** — Immobilized until escape. No O/M.
- **Guarded** — attackers treat 6s as 5s and 4s as 3s.
- **Harried** — Disad on Saving Throws, escape rolls, panic rolls.
- **Immobilized** — cannot move.
- **Incapacitated** — Prone + Stunned; some of your effects end.
- **Invisible** — can't be attacked except when you attack.
- **Marked** — grant an Opportunity if you attack without including the
  Marker or shift while adjacent to it.
- **Ongoing X** — take X at start of turn (save ends unless stated). Would it
  drop you to 0: one final action first.
- **Panicked** — roll d6: 1 Dominated · 2 run from origin, RBA with Disad if
  in range · 3–4 take cover then RBA it (no cover: treat as 2) · 5–6 normal
  turn, Basic Attacks only.
- **Prone** — Slowed, stand as move action. No O/M.
- **Restrained** — Immobilized, Disad on attacks. No O/M.
- **Slowed** — speed 2, cannot Shift.
- **Stunned** — no actions, no flanking. No O/M.
- **Weakened** — half damage, round down.

Track statuses on the combat tracker (`condition` subcommand) for monsters
and on the sheet (`conditions[]`) for PCs.

## Bookkeeping during combat

- Monster HP/hits live in `campaign/state/combat.json` (the tracker).
  Stooges/Goons use **hit thresholds**: give them HP equal to their number of
  hit boxes and deal 1 per attack that meets the threshold (see
  `statblock-schema.md`).
- PC HP, Miss Tokens, Strikes, Action Points, and `used` flags on Encounter
  powers are Bookkeeper edits to the character sheet.
- Damage/heal/status changes queue as effects and surface under the next
  narration (`narrate.py`).

## End of fight

1. Count each PC's Strikes → condition per the table in
   `strike-reference.md`; write conditions to sheets; reset `strikes` to 0.
2. Reset `miss_tokens` to 0 (they don't persist past the fight).
3. Encounter powers: `used` resets when the encounter ends.
4. Sync PC HP from the tracker back to sheets; `combat_tracker.py end` posts
   the wrap-up banner.
