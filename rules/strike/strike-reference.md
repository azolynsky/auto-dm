# Strike! — quick reference

Strike! is © Jim McGarva (strikerpg.com) and is **not** open-licensed, so this
project carries no full rules text. This file and its siblings are the table's
condensed working reference, built from the table's own reference sheets. When
a ruling isn't covered here, make one, write it into `campaign/house-rules.md`
under "Active", and use it consistently (CLAUDE.md invariant #3).

Core resolution: **one d6** for everything. No modifiers to the die except
Advantage/Disadvantage and rare flat bonuses (Miss Tokens, Helping).

## Attack rolls (tactical combat)

| d6 | Result |
|----|--------|
| 6 | **Critical Hit**: Effect AND 2 × damage |
| 4–5 | **Solid Hit**: damage AND Effect |
| 3 | **Glancing Hit**: damage OR Effect (attacker's choice) |
| 2 | **Miss** — gain a Miss Token |
| 1 | **Miss** — gain a Miss Token AND a Strike |

- Some characters modify this table (e.g. a healing-factor rider adds
  "heal 1" to every 3+). Check the sheet's `attack_table_rider`.
- **Miss Tokens**: spend one *after* seeing a future attack roll for +1 to it
  (or turn a rolled 1 into a 3 by also taking a Strike). Post-roll currency —
  never applied automatically.
- Damage is **fixed** (e.g. `2✸`), never rolled. A crit doubles it.

## Advantage / Disadvantage

Roll twice, take higher (Advantage) or lower (Disadvantage). Multiple sources
don't stack; one of each cancels to a normal roll.

- Flanking or target prone → melee attacks have Advantage.
- Cover or concealment → attacks against you have Disadvantage.

## Hit points and going down

- At or below **0 HP**: **Incapacitated** (prone, stunned, some of your
  effects end).
- At or below **−5 HP**: **Taken Out**.
- **Comeback Roll** (while down, on your turn): 1–2 lose 2 HP · 3–4 nothing ·
  5–6 regain 1 HP and take your turn.
- **Rally** (Encounter, no action, own turn only — usable even Incapacitated
  or Dominated): spend an Action Point → regain 4 HP and regain one expended
  Encounter power from your Class (not a Role Action).

## Saving throws

Roll a d6 at end of turn per save-ends effect; success on **4+** unless the
sheet says otherwise (some characters save on 3+). Harried gives Disadvantage
on saves.

## Opportunities

Grant an Opportunity (take 2 damage, or the enemy's listed Opportunity value)
when you:
- leave a square within an enemy's reach without shifting and without moving
  closer to them;
- gain the Flying status adjacent to an enemy;
- make a ranged attack adjacent to an enemy;
- are Marked and attack without including the Marker, or shift while adjacent
  to the Marker.

## Strikes → conditions (per combat/conflict)

| Individual Strikes | Condition earned |
|----|----|
| 0–1 | none |
| 2–3 | Winded |
| 4 | Exhausted |
| 5+ | Injured |

Winded/Exhausted entering a fight: Disadvantage on attack rolls in the first
round. Major conditions: −1 to all rolls.

## Common powers (every character)

- **Melee Basic Attack** (At-Will, 2✸) · **Ranged Basic Attack** (At-Will, R5, 2✸)
- **Charge** (At-Will): move up to speed to a square adjacent to a creature
  (each square closer, no difficult terrain) and Melee Basic Attack it.
- **Rally** (see above).
- **Assess** (At-Will): roll a die, ask the GM that many questions from the
  lists — about an enemy (HP? powers? traits? carrying anything strange?) or
  the encounter (who's in charge? what can I use? what can they use? hidden
  doors/traps/enemies?).

## Improvising

Improvised attacks deal 3 damage with a GM-determined effect. Non-attack
improvisation uses the basic skill rules (`skill-checks.md`).

## Chases

Runners flee; Chasers pursue. Ranges: Close ↔ Medium ↔ Far. Closer than
Close = caught; farther than Far = escaped. Each round:

1. Runners secretly pick an action; Chasers predict one. Correct prediction:
   Chasers get Advantage. Opposite prediction (per the chart): Disadvantage.
2. Each side rolls (Range Modifier: Chasers −1 at Close, +1 at Far). Resolve
   by the Runners' action:

- **Flee** — Runners win: range +1. Chasers win: range −1. Tie: no change.
- **Double Back** — Runners win: range set to Far. Chasers win: range −1.
  Tie: at Close Runners lose; at Medium no change. (Not usable at Far.)
- **Set Up** — Runners win: Runner Advantage next move. Chasers win: range −1
  and Runner Advantage next move. Tie: no change.
- **Risk** — Runners roll first; 3 or lower crash and lose. Above 3: Chasers
  give up (range +2) or follow and roll — 3 or less (ignoring Range Modifier)
  means Runners win, else compare as Flee.
- **Hide** — chase ends; resolve as an Opposed Roll (Runners get the +1 at
  Far instead of Chasers). Tie: hidden but pinned down. (Not usable at Close.)

Prediction chart (Chasers have, after prediction): Flee/Flee Adv; Flee/Hide
Disad; Flee/Double-Back Disad; Hide/Flee Disad; Hide/Hide Adv; Double-Back/
Flee Disad; Double-Back/Double-Back Adv; Set-Up/Set-Up Adv; Set-Up/Risk
Disad; Risk/Set-Up Disad; Risk/Risk Adv.

- **Danger Level** (0–2): roll ≤ Danger Level (ignoring Range Modifier) →
  crash. Round winner may raise or lower it by 1.
- **Shooting**: a shooter out-rolling their opponent gives them −1; a rolled
  6 takes one opponent out of the chase (Injured). Shooting while driving:
  both have Disadvantage.
- **Team Strikes owed** if the losing side had N players: <N none · N–2N
  Minor Concession · 2N–3N Major Concession · 3N+ Pyrrhic Victory.

See `combat-flow.md` for the full turn structure and status list,
`skill-checks.md` for everything non-combat, `gm-reference.md` for GM tables.
