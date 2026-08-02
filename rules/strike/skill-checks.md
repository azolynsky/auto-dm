# Strike! — skills and non-combat resolution

Everything outside tactical combat runs on single d6 rolls against outcome
tables. No DCs, no modifiers to the die — difficulty lives in the fiction and
in the Twists/Costs the GM attaches.

## When to roll

Say what you're doing and what you intend the outcome to be; agree with the
GM which Skill applies. **Say yes or let them roll** — if there's no
interesting failure, just say yes. If the right approach would simply work
(searching where the thing actually is), it works without a roll. If there's
nothing to find, don't roll.

Run rolls through the active system's resolver:
`python tools/strike/check_resolver.py --skill --char <sheet> --skill "<name>"`
(or `--skilled` / `--unskilled` for NPCs and ad-hoc rolls).

## Outcome tables

| d6 | Skilled | Unskilled |
|----|---------|-----------|
| 6 | Success + Bonus | Success + **learn the Skill** OR Bonus |
| 5 | Success | Success |
| 4 | Success | Success + Cost |
| 3 | Success + Cost | Twist |
| 2 | Twist | Twist |
| 1 | Twist + Cost | Twist + Cost |

- **Success** — you get your stated intent.
- **Bonus** — a little extra, player's suggestion welcome.
- **Cost** — a temporary penalty: a Condition, a Flaw on an item or
  information, an owed Favor, Disadvantage on a linked follow-up. Offer an
  in-character choice when appropriate.
- **Twist** — the situation *changes* (not just "no"). See the Twist List in
  `gm-reference.md`.

## Skills and Tricks

Skills are freeform, invented at creation and learned in play (e.g. "Wealth
x 2", "Claw Fighting", "Catholic Hierarchy"). **General vs Specific**: a
general skill rolls with Disadvantage against a specific one's domain.

**Tricks** ride on skills ("TRICK: Cool under pressure"): the reliable
signature move. Spend an Action Point to **automatically succeed** with a
Trick instead of rolling.

**Learning**: roll a 6 Unskilled and forgo the Bonus → learn the Skill. With
Advantage/Disadvantage: a 5 and a 6, or two 6s. Opposed vs a Skilled
opponent: roll a 6 and win or tie. Some skills are Restricted — ask the GM.

## Advantage / Disadvantage

Roll twice, take higher/lower. Sources don't stack; one of each = roll
normally. Skilled vs Unskilled in opposition: the Unskilled side rolls with
Disadvantage.

## Opposed Rolls

Each side rolls a die (apply Adv/Disad; Unskilled side has Disad).

- **Win by 3+**: win completely.
- **Win by 1–2**: you get what you want, but the loser picks one: their hold
  on it is insecure · it costs them more than expected · it costs you less
  than expected · you get something extra (maybe part of your intent, maybe
  not).
- **Tie**: neither side gets what they want. A player may spend an Action
  Point to break a tie.

## Linked Rolls

A preparatory roll with its own skill and intent, resolved as a basic skill
roll. Success generates **Advantage** on the future roll; a Cost may
generate **Disadvantage** on it; a Twist is a normal Twist.

## Helping

Helper rolls a die; if it's **higher than the primary's roll**, the primary
gets +1. Multiple helpers resolve lowest to highest. Unskilled helpers roll
with Disadvantage.

## Group rolls

- Everyone must pass → worst-positioned player rolls; others Help.
- Only one must pass → best-positioned player rolls; others Help.
- Individual stakes → roll individually.

## Kits

A Kit is a package of non-combat powers (e.g. "The Psychic"). Kit powers are
either **always-on** abilities (no roll — "sense surface emotions") or
**rolled powers** with structured outcomes:

- **BONUS** — what a 6 adds.
- **SUCCESS** — what success means for this power.
- **TWIST** — this power's characteristic Twist.
- **COST** — this power's characteristic Cost.

Some kits use freeform powers instead ("when you scout ahead, roll and
consult the table"). Resolve on the standard Skilled table unless the power
says otherwise.

## Conditions (narrative)

Minor conditions give **Disadvantage** to their domain:

- **Angry** — social situations and concentration.
- **Winded** — physical tasks. Winded ×3 = Exhausted.
- **Lost Confidence** — skills relating to one ability; related Tricks
  unusable.
- **Exhausted** — ALL tasks.

**Major conditions**: −1 to all rolls, cumulative.

Recovery: Angry/minor mental — take time to cool off (not while holding
another minor condition). Winded — rest 10 minutes and drink. Lost
Confidence — succeed despite Disadvantage. Exhausted — long rest somewhere
safe. Major physical — doctor's aid + a full day's rest. Major mental —
defeat or back down from the cause. Major other — GM's discretion.

## Action Points

Start each session with at least 1, at most 3. Earn one by: doing something
cool (GM award) · using a Complication or Flaw — take a Twist instead of
rolling, get yourself into trouble when no roll was needed, or break an
Opposed-Roll tie against yourself.

Spend one to: gain Advantage from a related Skill · auto-succeed with a
Trick · Rally or use your Action Trigger (combat) · prevent a Team Conflict
loss · bring a Relationship into play (GM decides how it appears).

## Wealth

Money is tiered. To buy, compare your Wealth tier to the price tier:

| d6 | Below your Wealth | At your Wealth | Over your Wealth |
|----|----|----|----|
| 6 | S + Bonus | S + Bonus | S |
| 5 | S + Bonus | S | S + Cost |
| 4 | S | S + Cost | S + 2 Costs |
| 3 | S | S + 2 Costs | Twist |
| 2 | S + Cost | Twist | Twist + Flaw |
| 1 | S + 2 Costs | Twist + Flaw | Twist + Flaw |

**Short** or **Broke**: act one Wealth tier lower. Short ×3 = Broke; Broke
stacks. **Cash Parcel**: spend one to buy an item of equal or lower tier.
Increase Wealth: invest a Cash Parcel of (target tier + 1). Recover from
Short: work a week or spend a Cash Parcel equal to unpenalized Wealth; from
Broke: work a year or increase Wealth as above.

## Team Conflict

Extended group struggles (a siege, an investigation race, a war of rumor).

**Setup**: each player picks an action; team rolls **Advance** and
**Defense** dice (A and D), adding action bonuses. GM rolls A and D with the
opposition's bonuses. Compare your A to their D and vice versa:

- **Draw** (both D's hold): conflict continues.
- **Push** (both A's win): both sides take a hit; continues.
- **Win / Loss** (both rolls beat theirs / yours): over.
- **Tie on both**: Surprising Twist! Conflict ends. On a double-tie roll d6:
  6 Love · 5 Astounding Discovery · 4 a Third Power enters · 3 Natural
  Disaster · 2 Horrifying Act of Evil · 1 Death.

Taking a hit: gain a Strike or lose a trait (other side picks). Spend an
Action Point on a loss: your team takes 1 hit instead, opponent removes a
Strike or recovers a trait, conflict continues.

**Basic actions**: Progress +2A · Block +2D · Reckless Effort +3A and take a
hit · Take One for the Team +3D and owe a personal Concession (once per
player per conflict).
**Advancing**: All-Out Effort +3A −1D · Calculated Risk +3A, extra hit on a
Draw · Win At All Costs +4A and take an unrecoverable Strike · Targeted
Effort +2A, enemy takes a hit on a Draw.
**Defense**: Total Defense +3D −1A · Prepare +2D −1A now, +1A next round ·
Observe +1D +1A and scout one enemy roll next round · Recover +1D and remove
a Strike or regain a trait.

**Preparatory actions** (one per player, rolled before the conflict):
Fortify, Stock Up, Scout, Play the Long Game, Inspire, Seize the Advantage —
each: 5–6 strong benefit, 3–4 lesser, 1–2 gives −1A in round 1 (see
`gm-reference.md` for the exact tables).

**Conditions in Team Conflict**: each minor condition or relevant Flaw on
the party → Disadvantage on one team roll; each Major → −1 to one roll each
round.

**Aftermath** — win or lose: 2–3 team Strikes → each PC takes a minor
condition; 4+ → a Major. Players win: 1–2 Strikes owe a Minor Concession,
3–4 a Major, 5+ both. Players lose with opponent holding ≥1 Strike: pick
from the Opposed-Roll loser list as if you'd lost by 1–2.
