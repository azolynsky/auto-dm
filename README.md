# Auto-DM — an LLM game master

A repository for running a 5e tabletop campaign with an LLM (Claude Code, Codex, …) as the DM. Fork it, run one command, and start your own table.

## Why this exists

LLM-as-DM drifts. Improvised state is forgotten between sessions, dice rolls are quietly fudged, NPCs change eye color twice, the town that was "two days east" is suddenly next door. This repo grounds the LLM in **real files** for state and **real tools** for randomness, and splits the DM brain into specialized subagents so each one stays focused.

## Start your own campaign

```bash
git clone <your fork>
cd auto-dm
pip install -r webapp/requirements.txt
claude     # or: codex
```

Then say: **"Set me up — run onboarding."** The `onboarding` skill installs anything missing, creates your campaign from the starter template (`python tools/new_campaign.py --name "..."` under the hood), walks a session 0 (characters, tone, table settings), and starts the web companion. The starter campaign — the village of Emberwick and the Cold Lantern mystery, with two pregen PCs — is ready to play or reskin.

To continue an existing campaign, just say: **"Let's continue the campaign."**

## Code vs. campaign

The engine and the table are separate. Generic, campaign-agnostic code and reference:

```
auto-dm/
├── CLAUDE.md          # DM operating manual — read every session
├── AGENTS.md          # symlink → CLAUDE.md (Codex/other LLMs read the same file)
├── rules/             # Generic 5e/SRD reference (srd-reference, combat-flow, skill-checks)
├── docs/              # character-schema.md
├── tools/             # dice, check_resolver, combat_tracker, narrate, budget_recap, new_campaign
├── tests/             # unittest suite for tools + webapp (stdlib only)
├── webapp/            # Player web companion (FastAPI + SSE)
├── campaigns/starter/ # Forkable template campaign
└── .claude/           # agents/ (six role prompts) + skills/ (procedures)
```

Everything about *your* table lives in one directory, created from the template:

```
campaign/
├── house-rules.md     # Your table's rulings and tone agreements
├── characters/        # PC sheets (JSON) + portraits in images/
├── state/             # current.json, quests, world-flags, combat, settings, player feed
├── sessions/          # Per-session logs + rolling recap
├── npcs/              # NPC entity folders (summary/voice/motivations per NPC)
├── world/             # Setting overview, lore, location folders
└── factions/          # Faction entity folders
```

Tools and webapp find the campaign at `<repo>/campaign`, or wherever `CAMPAIGN_ROOT` points. You can swap DM LLMs mid-campaign — all state is plain JSON/Markdown, all tools are plain Python, and the agent/skill prompts are readable by any LLM (see "Multi-LLM operation" in `CLAUDE.md`).

## Architecture

**Six subagents** (in `.claude/agents/`):
- **Rules Lawyer** — what the rules say (read-only)
- **Bookkeeper** — the only agent that writes state
- **Director** — what the world does (DM brain; the only reader of `motivations.md`/`secrets.md`)
- **Narrator** — renders outcomes as prose (firewalled from secrets)
- **Continuity Checker** — flags contradictions
- **Session Prep** — between-session preparation

**Skills** (in `.claude/skills/`):
onboarding, combat-encounter, skill-check, spellcasting, leveling-up, session-wrap, encounter-building.

**Tools** (in `tools/`) — all emit standardized JSON:
- `dice.py` — cryptographic-randomness dice roller; batches several rolls per call.
- `check_resolver.py` — pulls modifiers from a character sheet and rolls against a DC.
- `combat_tracker.py` — initiative, monster HP, conditions; posts combat banners to the feed.
- `narrate.py` — pushes player-facing prose to the web companion, attaching queued mechanical effects as subtext (players read the story before the numbers).
- `budget_recap.py` — keeps the rolling recap within its character budget.
- `new_campaign.py` — creates `campaign/` from `campaigns/starter/`.

## Web companion

A webpage the players watch during the session: character cards with live HP (click a portrait for the full sheet — saves, skills, spells, full inventory), the narration feed (streamed via SSE as the DM calls `narrate.py`, with mechanical changes as subtext under the prose), the quest log (party-known quests only — `secret_truth` never leaves the server), an initiative bar during combat, and a ⚙ **Settings** tab where the table tunes the DM: rules strictness (strict vs. hand-of-god), beginner guidance, public dice rolls, kid-friendly narration, narration length, and free-text house rules.

```bash
pip install -r webapp/requirements.txt   # first time only
python webapp/server.py                  # then open http://localhost:8765
```

## Tests

```bash
python3 -m unittest discover -s tests
```

Stdlib-only (no pytest). Covers the dice roller, check resolver, combat tracker, narration feed + effects queue, and — most importantly — the webapp's secrecy redaction, so a refactor can't accidentally leak GM-only fields to the players' screen. State-writing tools are tested against a temp directory via the `CAMPAIGN_ROOT` env override; the suite never touches live campaign state.

## The hard rules

Listed in `CLAUDE.md`. The short version: never roll dice mentally, never advance state without updating files, never fudge.

## Attribution

Game-rules reference content in `rules/` derives from the System Reference Document 5.1, © Wizards of the Coast LLC, used under the Creative Commons Attribution 4.0 International license (CC-BY-4.0). This project is unaffiliated with Wizards of the Coast.
