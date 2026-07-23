---
name: onboarding
description: Set up this repo for a brand-new table — install dependencies, create a campaign from the starter template, run session 0 (characters, tone, settings), and start the web companion. Use when someone has just forked/cloned the repo, asks "how do I start", "set up a new campaign", or wants to reset and start over.
---

# Onboarding a new table

You are helping someone go from a fresh clone to a playable table. Work
through the phases in order, but skip anything already done — check first,
don't redo. Steps in the same phase that don't depend on each other (e.g.
installing dependencies and talking through tone) can run in parallel.

## Phase 1 — health check

1. Confirm the tools run: `python tools/dice.py 1d20 --label "smoke test"`.
2. Install webapp dependencies if needed: `pip install -r webapp/requirements.txt`.
3. Run the test suite: `python3 -m unittest discover -s tests`. All green before proceeding.

## Phase 2 — create the campaign

1. If `campaign/` already exists, STOP and ask: this repo has an active
   campaign. Never replace it without an explicit, separately-confirmed
   request (new_campaign.py --force destroys it).
2. Ask for a campaign name, then:
   ```bash
   python tools/new_campaign.py --name "<their name>"
   ```
3. The starter campaign is the village of **Emberwick** with one hook quest
   ("The Cold Lantern") and two pregen PCs (`pc-fighter`, `pc-cleric`).
   Ask whether they want to play that, reskin it, or start from their own
   setting — everything in `campaign/` is theirs to edit.

## Phase 3 — session 0

1. **Characters.** For each player: use the pregens as-is (rename them!), or
   build fresh sheets per `docs/character-schema.md`. Write each to
   `campaign/characters/<id>.json`. Portraits: easiest is the webapp —
   click a character card → "Set portrait…" in the full sheet uploads a
   png/jpg/webp into `campaign/characters/images/` (dropping a file named
   by character id into that folder works too).
2. **Seat the party.** Add the character ids to `campaign/state/current.json`
   `party[]` — the webapp orders cards by this list.
3. **Tone.** Talk through lines/veils, lethality, PC death. Record the
   answers in `campaign/world/overview.md` "Tone targets" and
   `campaign/house-rules.md` "Tone agreements".
4. **Table settings.** Open the webapp Settings tab (⚙) — or edit
   `campaign/state/settings.json` — and set: rules strictness, beginner
   mode, public rolls, kid-friendly, narration style. See CLAUDE.md "Table
   settings" for what each does.
5. **Calendar.** Pick an in-game date format and set `in_game_date` in
   `campaign/state/current.json`.

## Phase 4 — first light

1. Start the web companion and open it:
   ```bash
   python webapp/server.py &
   open http://localhost:8765
   ```
2. Confirm the players can see their character cards and the empty chronicle.
3. Push a welcome line so the screen isn't blank:
   ```bash
   python tools/narrate.py "The chronicle of <campaign name> begins." --type system
   ```
4. Hand off: tell them to say **"Let's start session 1"** (the DM manual's
   session-start procedure takes it from there), or run it now if they're ready.

## If they're migrating an existing campaign

Point `campaign/` at their data instead of the starter: their directory needs
`state/`, `characters/`, `sessions/` (see `campaigns/starter/` for the full
shape). Alternatively set `CAMPAIGN_ROOT` to its path.
