---
name: onboarding
description: Set up a new adventure — install dependencies if needed, create a save from the starter template under the chosen rule system, run session 0 (characters, tone, settings), and start the web companion. Use for a fresh clone, when the table chooses "start a new adventure" at session start (CLAUDE.md step 0), when someone asks "how do I start", or wants to reset and start over.
---

# Onboarding a new adventure

You are helping someone go from a fresh clone (or an existing table that wants
a new adventure) to a playable session. Work through the phases in order, but
skip anything already done — check first, don't redo. Steps in the same phase
that don't depend on each other (e.g. installing dependencies and talking
through tone) can run in parallel.

## Phase 1 — health check

Skip this whole phase if other adventures already exist and play has worked before.

1. Confirm the tools run: `python tools/dice.py 1d20 --label "smoke test"`.
2. Install webapp dependencies if needed: `pip install -r webapp/requirements.txt`.
3. Run the test suite: `python3 -m unittest discover -s tests`. All green before proceeding.

## Phase 2 — create the adventure save

1. Adventures live side by side under `campaigns/<system>/<slug>/` — creating a
   new one never touches the others. (`python tools/list_campaigns.py` shows
   what exists.)
2. Ask which **rule system** — offer the systems registered in
   `rules/systems.json`. Today that's D&D 5e (`dnd5e`) and Strike!
   (`strike`, a fast d6 tactical system with reusable heroes in
   `roster/strike/` — mention that a ready-made X-Men roster exists).
3. Ask for a **campaign name**, then:
   ```bash
   python tools/new_campaign.py --name "<their name>" --system <slug>
   ```
   The new save becomes the active adventure automatically
   (`campaigns/active.json`) — every tool and the webapp now point at it.
4. The starter template is the village of **Emberwick** with one hook quest
   ("The Cold Lantern") and two pregen PCs (`pc-fighter`, `pc-cleric`).
   Ask whether they want to play that, reskin it, or start from their own
   setting — everything in their save is theirs to edit.

## Phase 3 — session 0

1. **Characters.** For each player: use the pregens as-is (rename them!), or
   run the system's character-creation skill (per `rules/systems.json`
   `skills` — for dnd5e: `dnd5e-character-creation`). Sheets are written to
   the save's `characters/<id>.json`. Portraits: easiest is the webapp —
   click a character card → "Set portrait…" in the full sheet uploads a
   png/jpg/webp into the save's `characters/images/` (dropping a file named
   by character id into that folder works too).
2. **Seat the party.** Add the character ids to the save's
   `state/current.json` `party[]` — the webapp orders cards by this list.
3. **Tone.** Talk through lines/veils, lethality, PC death. Record the
   answers in the save's `world/overview.md` "Tone targets" and
   `house-rules.md` "Tone agreements".
4. **Table settings.** Open the webapp Settings tab (⚙) — or edit the save's
   `state/settings.json` — and set: rules strictness, beginner mode, public
   rolls, kid-friendly, narration style. See CLAUDE.md "Table settings" for
   what each does.
5. **Calendar.** Pick an in-game date format and set `in_game_date` in the
   save's `state/current.json`.

## Phase 4 — first light

1. Start the web companion (it reads the active-adventure pointer) and open it:
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

Place their data at `campaigns/<system>/<slug>/`: the directory needs
`state/`, `characters/`, `sessions/` (see `campaigns/starter/` for the full
shape), and `state/current.json` should carry `"system"` so the right rules
load. Activate it with `python tools/set_campaign.py <slug>` (a directory
outside `campaigns/` works too — pass its path, or set `CAMPAIGN_ROOT`).
