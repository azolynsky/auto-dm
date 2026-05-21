# D&D campaign — Claude Code DM

A repository for running a Dungeons & Dragons 5e campaign with Claude Code as DM, for Alex and a friend.

## Why this exists

LLM-as-DM drifts. Improvised state is forgotten between sessions, dice rolls are quietly fudged, NPCs change eye color twice, the town that was "two days east" is suddenly next door. This repo grounds Claude in **real files** for state and **real tools** for randomness, and splits the DM brain into specialized subagents so each one stays focused.

## How to play

```bash
cd /path/to/dnd
claude     # or: codex
```

Then: **"Let's continue the campaign."** The LLM reads its entry-point manual (`CLAUDE.md` for Claude, `AGENTS.md` for Codex — they're the same file), the recap, and current state, then picks up where you left off.

You can swap DMs mid-campaign (e.g., run out of Claude credits, switch to Codex). All state lives in plain JSON/MD files in this repo, all tools are plain Python scripts, and the "subagent" and "skill" files in `.claude/` are just role prompts and procedural recipes any LLM can read. See the "Multi-LLM operation" section of `CLAUDE.md` for details.

For the very first session: **"Let's run session 0 — character creation."** Walk through `characters/SCHEMA.md` to fill in `pc-alex.json` and `pc-friend.json`.

## Structure

```
dnd/
├── CLAUDE.md                   # DM operating manual — read every session
├── AGENTS.md                   # symlink → CLAUDE.md (so Codex/other LLMs read the same file)
├── README.md
├── rules/                      # SRD reference + house rules (slow-moving canon)
├── world/                      # Setting, regions, lore (slow-moving canon)
├── characters/                 # PC sheets in JSON (Bookkeeper writes)
├── npcs/                       # NPC stats and notes
├── monsters/                   # Encountered creature stat blocks
├── state/                      # Live state (current.json, quests, world-flags, combat)
├── sessions/                   # Per-session logs + rolling recap
├── tools/                      # dice.py, check_resolver.py, combat_tracker.py
└── .claude/
    ├── agents/                 # Six subagents
    └── skills/                 # Six procedural skills
```

## Architecture

**Six subagents** (in `.claude/agents/`):
- **Rules Lawyer** — what the rules say (read-only)
- **Bookkeeper** — the only agent that writes state
- **Director** — what the world does (DM brain)
- **Narrator** — renders outcomes as prose
- **Continuity Checker** — flags contradictions
- **Session Prep** — between-session preparation

**Six skills** (in `.claude/skills/`):
combat-encounter, skill-check, spellcasting, leveling-up, session-wrap, encounter-building.

**Three tools** (in `tools/`):
- `dice.py` — cryptographic-randomness dice roller. Every roll.
- `check_resolver.py` — pulls modifiers from a character sheet and rolls.
- `combat_tracker.py` — initiative order, monster HP, conditions.

## The hard rules

Listed in `CLAUDE.md`. The short version: never roll dice mentally, never advance state without updating files, never fudge.

## First-time setup

1. Open this folder in Claude Code.
2. Run a session-0: character creation. Fill in `characters/pc-alex.json` and `characters/pc-friend.json` per `characters/SCHEMA.md`.
3. Edit `world/overview.md` "Tone targets" with what you and your friend want.
4. Edit `rules/house-rules.md` if there are any options you want on.
5. Start session 1.

## What's already filled in

The setting is the Sword Coast (Forgotten Realms) starting in **Phandalin**. The hook is loosely Lost Mine of Phandelver — Gundren Rockseeker hired the party to escort supplies. Strip or replace freely; nothing here is load-bearing if you want a different campaign.
