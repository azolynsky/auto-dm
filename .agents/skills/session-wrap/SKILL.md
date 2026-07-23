---
name: session-wrap
description: End-of-session procedure — write the session log, update the rolling recap, sync state, award XP. Use when the table breaks for the night (or when the DM declares the session over).
---

# Session wrap

## 1. Finalize state

Before writing prose, make sure live state is current.

- Sync combat.json final HP to character sheets if combat ended without a `combat_tracker.py end`.
- Confirm `campaign/state/current.json` — location, in-game date, time of day.
- Confirm `campaign/state/quests.json` — anything new, completed, or progressed.
- Add any new `campaign/state/world-flags.json` flags the party flipped.

## 2. Write the session log

Append to `campaign/sessions/session-NN.md` (create if new). Structure:

```markdown
# Session NN — <short evocative title>

**Real date**: 2026-05-14
**In-game**: 3rd of Mirtul, 1492 DR, afternoon
**Location at start**: Stonehill Inn, Phandalin
**Location at end**: Cragmaw Hideout, second cave

## Recap

(One paragraph: what happened, in past tense, neutral voice.)

## Beats

- Party left Phandalin at dawn following the goblin trail north.
- Ambushed by 4 goblins on the Triboar Trail. Killed all 4. Ren dropped to 0 HP at one point; stabilized.
- Found Cragmaw Hideout. Snuck past the wolves. Captured a goblin (Yeemik).
- Yeemik offered a deal: kill Klarg the bugbear and Yeemik gives the party Sildar. Party agreed pragmatically.

## NPCs introduced / changed

- **Yeemik** (goblin): captured, currently allied-of-convenience. Hidden truth: will betray at first opportunity. See campaign/npcs/one-shot/yeemik.md.
- **Sildar Hallwinter**: located, alive, bound, 6 HP. Knows about Gundren's capture.

## Loot

- 30 gp, 2 healing potions (now Ren 1, Bel 1)
- Sildar carries a journal (not yet read)

## State changes

- World flag: `cragmaw_hideout_partially_explored` = true
- Quest: "Find Gundren" — Yeemik confirms Gundren was taken to Cragmaw Castle, not the hideout
- Time elapsed: ~10 hours
```

Keep beats factual. The Narrator's flourishes were in real time; the log is for future-you.

## 3. Update the rolling recap

`campaign/sessions/recap.md` is the **summary of summaries**. Edit it (don't append) to stay short — aim for under 500 words total covering the campaign so far.

Pattern:

```markdown
# Campaign so far

The party met in Neverwinter when the dwarf Gundren Rockseeker hired them to
escort supplies to Phandalin. On the road, they were ambushed by goblins and
found that Gundren had been captured. They've since...

## Open threads

- Gundren still captive; location: Cragmaw Castle (per Yeemik)
- Redbrand gang in Phandalin (unaddressed)
- Sildar wants escort back to Phandalin
- Mystery of Wave Echo Cave / Forge of Spells

## What the party knows that the world doesn't think they know

- The Cult of the Dragon agent in Neverwinter watched them leave
```

The "what the party knows" / "what the party doesn't know yet" split is gold for the Director next session.

## 4. Award XP (if using XP)

Sum CR-based XP from `encounter-building` skill across the session's encounters. Divide by number of PCs. Award equally.

Or skip XP entirely and use milestone leveling. House rule it in `campaign/house-rules.md`.

Update `xp` on each character sheet.

## 5. Run the Continuity Checker

Invoke `continuity-checker` agent. Fix any flagged errors before they calcify.

## 6. Note things for prep

Append to `campaign/sessions/prep-NNN.md` (one ahead of current) — "the party intends to assault Klarg next session; will probably approach via the central cave."

Hand off to `session-prep` agent during downtime before next session.
