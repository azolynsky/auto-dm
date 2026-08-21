#!/usr/bin/env python3
"""
The DM brain: the orchestrator loop, the specialist pipeline, and the table
rules that hold whichever model is thinking.

Take one player message, run the loop with file and campaign-tool access, and
leave the player-facing result in the chronicle via narrate.py. What actually
runs the loop is a backend (desktop/backends/, docs/backends.md) — OpenRouter,
the local `claude -p`, or the local Claude Agent SDK — chosen per role from
config. This module knows nothing about any of them beyond the interface: it
hands over a spec and a message and gets text back.

What stays here is everything that is true regardless of who is thinking: the
session brief, the per-role information silo, the narration gate, the
never-narrated fallback, and the out-of-character register. History belongs to
the backend, because only the backend knows where it is kept.

Nothing campaign-specific lives here — the DM's knowledge is CLAUDE.md plus the
files it reads itself.

Self-check:  python desktop/agent.py --selftest
"""
from __future__ import annotations

import json
import re
import sys
import threading
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import backends  # noqa: E402
import config  # noqa: E402
import prompts  # noqa: E402
from backends import AgentSpec, BackendError, ToolSpec  # noqa: E402

sys.path.insert(0, str(config.BUNDLE / "tools"))
import campaign_lib  # noqa: E402
import campaign_tools  # noqa: E402
from campaign_tools import (ROLE_ACTIVITY, TOOLS,  # noqa: E402,F401
                            _activity, _devlog, _logged, _thread, _utcnow,
                            allow_narration, begin_turn, edit_file, list_files,
                            narrated, read_file, resolve_path, role_tools,
                            run_tool, write_file)

THREAD_ID = "dm"           # one running conversation per campaign
DM_TURN_LIMIT = 40         # tool round trips in one player turn


class DMError(RuntimeError):
    """Something the player needs to see on the table screen."""


def consult_pair(first_role: str, first_task: str,
                 second_role: str, second_task: str) -> str:
    """Consult TWO specialists at the same time and get both answers back.

    Use this whenever a beat needs two independent specialists — almost always
    director + rules-lawyer, where "what does the world do?" and "what check
    resolves this?" can both be written from the player's intent. Running them
    together costs the table one wait instead of two.

    Only serialize (two separate consult_role calls) when the second task
    genuinely cannot be written until the first answers — e.g. the narrator,
    which needs the Director's decision and the roll outcomes.
    """
    out: dict = {}

    def run(slot: str, role: str, task: str) -> None:
        out[slot] = consult_role(role, task)

    threads = [threading.Thread(target=run, args=("first", first_role, first_task)),
               threading.Thread(target=run, args=("second", second_role, second_task))]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    return (f"=== {first_role} ===\n{out.get('first', '(no reply)')}\n\n"
            f"=== {second_role} ===\n{out.get('second', '(no reply)')}")


# ── Role subagents ────────────────────────────────────────────────────────────
# The manual's Director/Narrator/Rules-Lawyer/Bookkeeper pipeline as actual
# separate agents: each consult_role call runs a one-shot agent on that role's
# prompt file and its own backend and model, with no chat history — which is
# the point: the orchestrator's context stops absorbing every file the
# specialists read.

SUB_ROLES = tuple(r for r in prompts.ROLES if r != "dm")
SUB_TURN_LIMIT = 16

# Roles that must not sit between a player's message and their narration.
_AFTER_NARRATION_ROLES = ("continuity-checker", "prose-editor", "session-prep")


role_model = config.role_model


def spec_for(role: str, model: str) -> AgentSpec:
    """The AgentSpec one role runs under, on any backend.

    The whole per-role configuration in one place: which prompt, which tools,
    how many round trips, and whether it keeps history. A backend reads this
    and nothing else about the role, which is why swapping one backend for
    another cannot change what a role is allowed to do.
    """
    if role == "dm":
        return AgentSpec(
            role="dm", model=model, system_prompt=system_prompt(),
            tools=tuple(ToolSpec.of(fn) for fn in DM_TOOLS),
            turn_limit=int(config.load().get("recursion_limit") or 0) // 2
            or DM_TURN_LIMIT,
            stateful=True, thread=THREAD_ID)
    return AgentSpec(
        role=role, model=model,
        system_prompt=prompts.resolve(role).read_text(encoding="utf-8"),
        tools=tuple(ToolSpec.of(fn) for fn in role_tools(role)),
        turn_limit=SUB_TURN_LIMIT, stateful=False)



# What each role's brief carries — the information silo. GM-side roles get
# the full state; the narrator's view excludes everything with GM-only fields
# (quests.json carries secret_truth and unrevealed quests, world-flags notes
# and dramatis-personae's known_to_party=false entries pre-stage reveals);
# the rules-lawyer gets mechanics context only.
_GM_ROLES = ("director", "bookkeeper", "continuity-checker", "session-prep")
_GM_STATE = ("state/current.json", "state/settings.json", "house-rules.md",
             "state/quests.json", "state/world-flags.json",
             "state/dramatis-personae.json", "sessions/recap.md")
_BRIEF_FILES = {
    **{role: _GM_STATE for role in _GM_ROLES},
    "rules-lawyer": ("state/current.json", "state/settings.json",
                     "house-rules.md"),
    "narrator": ("state/current.json", "state/settings.json",
                 "house-rules.md", "sessions/recap.md"),
    "prose-editor": (),
}


def _entity_folders() -> list:
    """Every entity folder on disk, as (path-from-campaign, Path)."""
    found = []
    for group in ("npcs/recurring", "npcs/one-shot", "world/locations",
                  "factions"):
        for folder in sorted((config.CAMPAIGN / group).glob("*")):
            if folder.is_dir() and not folder.name.startswith("_"):
                found.append((f"{group}/{folder.name}", folder))
    return found


def _named_in(task: str, folders: list) -> list:
    """Entity folders this task actually mentions — by id or by display name.

    present_entities drifts (invariant #2 gets missed under time pressure);
    the task text is the live signal for who is in the beat, so the brief
    pre-loads them and the specialist doesn't glob to find their voice.md.
    """
    low = task.lower()
    hits = []
    for rel, folder in folders:
        ident = folder.name
        if ident.lower() in low or ident.replace("-", " ").lower() in low:
            hits.append((rel, folder))
            continue
        summary = folder / "summary.md"
        try:  # display name from the H1, e.g. "# Maera Thistle"
            for line in summary.read_text(encoding="utf-8").splitlines():
                if line.startswith("# ") and line[2:].strip().lower() in low:
                    hits.append((rel, folder))
                    break
        except OSError:
            continue
    return hits


def _consult_brief(role: str = "", task: str = "") -> str:
    """State every consult otherwise re-reads cold (specialists are stateless).

    Injected into each consult's task so a Director/Rules-Lawyer round doesn't
    spend 30s+ rediscovering the scene file by file — the measured worst case
    was a consult burning ~70s guessing PC sheet paths (campaign/pcs/*.md …).
    Siloed by role via _BRIEF_FILES; present_entities' files ride along too —
    motivations.md and secrets.md ONLY for the director (invariant #7, the
    motivations firewall).
    """
    if role == "prose-editor":
        return ""  # style work needs the draft in the task, not the world
    parts = []
    default = ("state/current.json", "state/settings.json", "house-rules.md")
    for rel in _BRIEF_FILES.get(role, default):
        try:
            text = (config.CAMPAIGN / rel).read_text(encoding="utf-8").strip()
            parts.append(f"--- campaign/{rel}\n{text}")
        except OSError:
            continue
    if role in _GM_ROLES:
        logs = sorted((config.CAMPAIGN / "sessions").glob("session-*.md"))
        if logs:
            tail = logs[-1].read_text(encoding="utf-8")[-4000:]
            parts.append(f"--- campaign/sessions/{logs[-1].name} (tail)\n…{tail}")
    try:
        current = json.loads(
            (config.CAMPAIGN / "state" / "current.json").read_text(encoding="utf-8"))
        entities = current.get("present_entities") or []
    except (OSError, json.JSONDecodeError):
        entities = []
    names = ["summary.md"]
    if role == "director":
        names += ["motivations.md", "secrets.md"]
    elif role == "narrator":
        names.append("voice.md")
    all_folders = _entity_folders()
    in_scope = [(str(e), config.CAMPAIGN / str(e)) for e in entities
                if isinstance(e, str) and (config.CAMPAIGN / str(e)).is_dir()]
    for rel, folder in in_scope + _named_in(task, all_folders):
        for name in names:
            try:
                text = (folder / name).read_text(encoding="utf-8").strip()
                header = f"--- campaign/{rel}/{name}"
                if header not in "\n".join(parts):
                    parts.append(f"{header}\n{text}")
            except OSError:
                continue
    try:
        current = json.loads(
            (config.CAMPAIGN / "state" / "current.json").read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        current = {}
    party = set(current.get("party") or [])
    chars = config.CAMPAIGN / "characters"
    roster = []
    for p in sorted(chars.glob("*.json")) if chars.is_dir() else []:
        try:
            d = json.loads(p.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        # Live-loop roles get seated party members' full sheets inline —
        # they otherwise re-read them every single beat.
        if d.get("id") in party and role in ("director", "rules-lawyer",
                                             "narrator"):
            parts.append(f"--- campaign/characters/{p.name}\n"
                         + p.read_text(encoding="utf-8").strip())
        else:
            roster.append(f"campaign/characters/{p.name} — {d.get('name', '?')}"
                          f" ({d.get('race', '?')} {d.get('class', '?')}"
                          f" {d.get('level', '?')})")
    if roster:
        parts.append("--- PC sheets (exact paths — read for full stats)\n"
                     + "\n".join(roster))
    # Entity manifest: every folder that exists, so a role that needs one the
    # scene didn't pre-load reads exactly one file instead of globbing for it
    # (measured: 3 wasted glob rounds hunting an NPC's voice.md).
    manifest = []
    for rel, folder in all_folders:
        files = sorted(f.name for f in folder.glob("*.md")
                       if role == "director"
                       or f.name not in ("motivations.md", "secrets.md"))
        if files:
            manifest.append(f"campaign/{rel}/: " + ", ".join(files))
    if manifest:
        parts.append("--- Entities on file (read only if this beat needs one "
                     "not pre-loaded above)\n" + "\n".join(manifest))
    if role == "rules-lawyer":
        # It opened srd-reference.md and then globbed rules/srd/** on every
        # consult. The three table-level rules files are small; ship them, and
        # index the rule directories so a lookup is one read, not a hunt.
        for rel in ("srd-reference.md", "skill-checks.md", "combat-flow.md"):
            try:
                text = (config.BUNDLE / "rules" / rel).read_text(encoding="utf-8")
                parts.append(f"--- rules/{rel}\n{text.strip()}")
            except OSError:
                continue
        index = []
        for group in sorted((config.BUNDLE / "rules" / "srd").glob("*")):
            if not group.is_dir():
                continue
            files = sorted(f.name for f in group.glob("*.md"))
            # Spells/monsters/items are one-file-per-entry: name the hub, not
            # the thousand leaves.
            index.append(f"rules/srd/{group.name}/: " + (
                ", ".join(files) if len(files) <= 12
                else f"{len(files)} files incl. " + ", ".join(files[:6]) + " …"))
        if index:
            parts.append("--- rules/srd index (exact paths — no globbing)\n"
                         + "\n".join(index))
    return "\n\n".join(parts)


@_logged
def consult_role(role: str, task: str) -> str:
    """Delegate to a specialist role agent — this harness's native subagent
    mechanism from the manual. Roles: director, narrator, rules-lawyer,
    bookkeeper, continuity-checker, session-prep, prose-editor. Each runs on
    its role prompt from .claude/agents/ (and its own model, if configured)
    with file and campaign-tool access, and returns its final answer.

    The specialist has NO chat history and NO memory between calls — put
    everything it needs in `task`: the beat, what the player said, relevant
    entity paths, dice results, and decisions already made. Say explicitly
    which state changes are ALREADY APPLIED vs still to apply — a recap of
    resolved beats must not read as a change request. The narrator
    cannot read motivations.md/secrets.md; the bookkeeper is the only role
    that can write files. current.json, settings.json, house-rules.md, and
    the PC sheet paths are appended to `task` automatically — don't ask the
    specialist to read those. Independent consults MUST go out in parallel:
    multiple consult_role calls in one response. In particular, a rules
    question (DC, save type, condition effect) almost never depends on the
    Director's answer — fire director + rules-lawyer together.
    """
    if role not in SUB_ROLES:
        return f"error: unknown role {role!r}; available: {', '.join(SUB_ROLES)}"
    if not task.strip():
        return "error: task is empty — tell the specialist what you need"
    # Checkpoint roles are free AFTER the beat lands (players are reading) and
    # ruinous before it (players are staring at nothing): a continuity check
    # measured 69s ahead of a narration once. Same rule the manual states for
    # bookkeeping — never block a player's turn.
    if role in _AFTER_NARRATION_ROLES and not narrated():
        return (f"error: the {role} runs after the beat is on screen, not "
                "before it — push this beat's narration first, then consult "
                "it in the same turn (the players read while it works).")
    if role == "narrator":
        allow_narration()  # unlocks narration pushes for the rest of the turn
    _activity(ROLE_ACTIVITY.get(role, "The DM is consulting a specialist"))
    brief = _consult_brief(role, task)
    if brief:
        task = (f"{task}\n\n# Pre-read state (current as of this consult — "
                f"do NOT re-read these files)\n{brief}")
    token = _thread.set(role)
    try:
        backend, model = backends.for_role(role)
        reply = backend.run(spec_for(role, model), task)
    except BackendError as e:
        # A failed consult is the DM's problem to route around, not the
        # table's: hand it back as tool output so the orchestrator can try
        # another way instead of the turn dying here.
        return f"error consulting {role}: {e}"
    except Exception as e:  # noqa: BLE001 — same reasoning, unexpected shape
        return f"error consulting {role}: {type(e).__name__}: {str(e)[:300]}"
    finally:
        _thread.reset(token)
    return reply or "(no reply)"


DM_TOOLS = TOOLS + [consult_role, consult_pair]


# ── Prompt and briefing ───────────────────────────────────────────────────────

def system_prompt() -> str:
    """The selected dm adapter, then the operating manual."""
    adapter = prompts.resolve("dm").read_text(encoding="utf-8")
    manual = (config.BUNDLE / "CLAUDE.md").read_text(encoding="utf-8")
    return adapter + "\n" + manual


BRIEF_FILES = ("sessions/recap.md", "state/current.json", "state/quests.json",
               "state/world-flags.json", "state/settings.json",
               "state/dramatis-personae.json", "house-rules.md")


def session_brief() -> str:
    """The manual's session-start reads, inlined — saves a dozen round trips."""
    chunks = []

    def add(label: str, text: str, tail: bool = False) -> None:
        clipped = text[-12_000:] if tail else text[:12_000]
        chunks.append(f"### {label}\n```\n{clipped}\n```")

    for rel in BRIEF_FILES:
        path = config.CAMPAIGN / rel
        if path.exists():
            add(f"campaign/{rel}", path.read_text(encoding="utf-8"))
    for sheet in sorted((config.CAMPAIGN / "characters").glob("*.json")):
        add(f"campaign/characters/{sheet.name}", sheet.read_text(encoding="utf-8"))
    logs = sorted((config.CAMPAIGN / "sessions").glob("session-[0-9]*.md"))
    if logs:
        add(f"campaign/sessions/{logs[-1].name} (most recent)",
            logs[-1].read_text(encoding="utf-8"), tail=True)
    feed = config.CAMPAIGN / "state" / "player-feed.jsonl"
    if feed.exists():
        entries = feed.read_text(encoding="utf-8").splitlines()[-20:]
        add("campaign/state/player-feed.jsonl (last 20 entries — the exact prose "
            "the players last saw, and their words via `intent`)",
            "\n".join(entries), tail=True)
    return ("Session start. Here is the current state — the manual's session-start "
            "reads, inlined. Read any entity folders you still need. The feed tail "
            "is the ground truth for the live scene: if it shows facts missing from "
            "current.json (someone mid-conversation, an offer outstanding), have the "
            "Bookkeeper fold them in before the first beat, and if it ends on an "
            "unanswered player message, answer it.\n\n"
            + "\n\n".join(chunks))



LABEL_LINE = re.compile(r"^\s*(\[[A-Z][A-Z ]+\]|roll:|result:)", re.M)


def players_text(text: str, *, quoted_only: bool = False) -> str:
    """Best-effort player-facing prose from a reply that never called narrate.py.

    Prefers the blockquote layer the manual mandates; failing that (unless
    quoted_only), strips the DM-layer label lines so the table gets prose
    rather than [DIRECTOR] notes.
    """
    quoted = [ln.lstrip()[2:] for ln in text.splitlines() if ln.lstrip().startswith("> ")]
    if quoted:
        return "\n".join(quoted).strip()
    if quoted_only:
        return ""
    return "\n".join(ln for ln in text.splitlines()
                     if ln.strip() and not LABEL_LINE.match(ln)).strip()


def narrate_gate(prose: str) -> list:
    """narrate.py's style/mechanics violations for `prose` ([] if clean).

    The fallback path publishes without going through the tool, so it has to
    apply the same gate rather than trusting it happened upstream.
    """
    try:
        sys.path.insert(0, str(config.BUNDLE / "tools"))
        import narrate  # the tool module, not this function's caller
        return narrate.style_violations(prose)
    except Exception:
        return []  # never let the gate itself blank the players' screen


def _one_shot(system: str, message: str) -> str:
    """One exchange, no tools, no history — the setup screen's generators.

    Runs on whatever backend the dm is configured for, so a table living
    entirely on its Claude subscription can build characters and worlds without
    holding an OpenRouter key at all.
    """
    backend, model = backends.for_role("dm")
    if (reason := backend.available()):
        raise DMError(reason)
    spec = AgentSpec(role="dm", model=model, system_prompt=system,
                     tools=(), turn_limit=4, stateful=False)
    try:
        return backend.run(spec, message)
    except BackendError as e:
        raise DMError(str(e)) from e


def generate_character(description: str) -> dict:
    """One-shot LLM call: a player's free-text concept → a level-1 sheet in
    the campaign's exact JSON shape. Separate from the DM thread — this runs
    on the setup screen, before the table exists."""
    sheets = sorted((config.CAMPAIGN / "characters").glob("pc-*.json"))
    if not sheets:
        raise DMError("No example character sheet found to model the new hero on.")
    example = sheets[0].read_text(encoding="utf-8")

    system = (
        "You create Dungeons & Dragons 5e LEVEL 1 player characters. Reply with "
        "ONLY a JSON object — no prose, no markdown fences — in exactly the same "
        "shape as this example sheet:\n" + example + "\n"
        "Rules: level 1 with 0 xp; SRD 5.1 races, classes, and spells only; "
        "standard array (15,14,13,12,10,8) plus racial bonuses; derived numbers "
        "must be correct (AC, HP, saves, skills, initiative, passive perception, "
        "attack to-hit and damage); casters get correct level-1 slots and spells; "
        "personality.traits[0] is a single evocative sentence (it becomes the "
        "character's card blurb); give real ideals, bonds, and flaws that create "
        "adventure hooks; \"player\" is an empty string; set \"id\" to null — the "
        "app assigns it. Honor the player's concept, including names and details "
        "they specify; invent tastefully where they don't."
    )
    last_err = None
    for _ in range(2):
        raw = _one_shot(system, "Player's concept: " + description)
        text = re.sub(r"^```(?:json)?\s*|\s*```$", "", raw.strip())
        try:
            sheet = json.loads(text)
            if isinstance(sheet, dict):
                return sheet
            last_err = "not a JSON object"
        except json.JSONDecodeError as e:
            last_err = str(e)
    raise DMError(f"The DM couldn't write a valid character sheet ({last_err}). "
                  "Try describing the hero again.")


def generate_campaign(description: str) -> dict:
    """One-shot LLM call: the table's free-text pitch → a world package that
    server.apply_world_package writes into a freshly seeded campaign. Like
    generate_character, this runs on the setup screen, before the table
    exists. Examples come from the bundled starter so the shapes are stable
    regardless of what the active campaign currently holds."""
    starter = config.BUNDLE / "campaigns" / "starter"
    overview_example = (starter / "world" / "overview.md").read_text(encoding="utf-8")
    quest_example = json.dumps(
        (json.loads((starter / "state" / "quests.json")
                    .read_text(encoding="utf-8")).get("active") or [{}])[0],
        indent=2, ensure_ascii=False)

    system = (
        "You design the opening state of a Dungeons & Dragons 5e campaign for "
        "level 1 characters. Reply with ONLY a JSON object — no prose, no "
        "markdown fences — with exactly these fields:\n"
        "- campaign_name: a short evocative title\n"
        "- overview_md: markdown for world/overview.md — same scope and length "
        "as this example (keep the '## Tone targets' section):\n---\n"
        + overview_example + "\n---\n"
        "- lore_md: markdown, 2-4 short paragraphs of world history and myth "
        "the DM can draw on\n"
        "- regions_md: markdown, a bullet list of 3-5 nearby regions/places "
        "with one line each (only the starting settlement is detailed; the "
        "rest are references)\n"
        "- current: {in_game_date, time_of_day, weather, location: {region, "
        "settlement, specific}} — `specific` is the exact opening spot, e.g. "
        "a tavern common room\n"
        "- location: {name, summary_md, secrets_md} — the starting settlement. "
        "summary_md is player-safe color (layout, notable folk, mood); "
        "secrets_md is GM-only truth about what's really going on there\n"
        "- npc: {name, summary_md, voice_md, motivations_md, dramatis_note} — "
        "the quest-giver the party meets first. voice_md: how they talk, with "
        "2-3 sample lines. motivations_md is GM-only: what they want, what "
        "they'd never do, what they're hiding. dramatis_note: ONE player-safe "
        "sentence for the Who's Who panel\n"
        "- quest: the opening quest, exactly this shape (secret_truth and "
        "obstacles are GM-only; known_to_party true):\n" + quest_example + "\n"
        "- hooks: a list of 1-2 {id, title, pitch, summary} adventure seeds on "
        "the horizon — pitch is one player-facing sentence, summary is GM "
        "shorthand\n"
        "Rules: playable at level 1 (small, personal stakes); the opening "
        "quest must be resolvable in one or two sessions; no stat blocks; "
        "plain markdown without wikilinks; every *_md field is a complete "
        "file body starting with a '# ' heading. Honor the table's pitch — "
        "genre, tone, names they give — and invent tastefully where they "
        "don't. If the pitch is empty, surprise them with something fresh "
        "that is NOT a sleepy farming village."
    )
    pitch = description.strip() or "(none — DM's choice)"
    last_err = None
    for _ in range(2):
        raw = _one_shot(system, "The table's pitch: " + pitch)
        text = re.sub(r"^```(?:json)?\s*|\s*```$", "", raw.strip())
        try:
            pkg = json.loads(text)
            if isinstance(pkg, dict):
                return pkg
            last_err = "not a JSON object"
        except json.JSONDecodeError as e:
            last_err = str(e)
    raise DMError(f"The DM couldn't write a valid world ({last_err}). "
                  "Try the pitch again.")


def _is_ooc(msg: str) -> bool:
    """True when the WHOLE message is out-of-character — parenthetical asides
    with nothing in-character between or after them. A mixed message like
    "(make this nice) Mira approaches the dogs" is an in-character turn that
    carries a steering aside, and still gets the narrator backstops."""
    rest = msg.strip()
    while rest.startswith("("):
        depth = 0
        for i, ch in enumerate(rest):
            if ch == "(":
                depth += 1
            elif ch == ")":
                depth -= 1
                if depth == 0:
                    rest = rest[i + 1:].lstrip()
                    break
        else:
            return True  # unclosed paren — nothing in-character follows
    return not rest


def run_turn(player_message: str) -> dict:
    """One player turn. Publishes to the chronicle; returns a small summary."""
    backend, model = backends.for_role("dm")
    if (reason := backend.available()):
        raise DMError(reason)
    spec = spec_for("dm", model)

    begin_turn()
    _activity("The DM is thinking it over")
    try:
        # A fresh conversation gets the session brief ahead of the message; a
        # resumed one already has it. Asking the backend is the only thing this
        # function needs to know about a history it deliberately doesn't own.
        fresh = backend.is_fresh(spec)
        opening = (session_brief() + "\n\n") if fresh else ""

        try:
            final = backend.run(spec, opening + player_message)
        except BackendError as e:
            raise DMError(str(e)) from e

        # A wholly out-of-character message — the manual's "(...)" register:
        # rules questions, steering requests, table talk — wants a direct
        # answer, not a scene. Don't nudge the narrator into manufacturing
        # prose for it; the fallback below publishes the DM's reply as a
        # system note, which IS the answer. Mixed messages (an aside followed
        # by a character action) are in-character turns and keep the backstops.
        ooc = _is_ooc(player_message)

        # The turn ended without the beat reaching the players. Observed live:
        # the DM took the Director's decision, then stopped — no narrator
        # consult, no push, nothing on screen. One nudge on the same thread
        # (it still has the decision and the rolls) costs nothing on the happy
        # path and saves the turn on the unhappy one.
        if not narrated() and not ooc and not players_text(final, quoted_only=True):
            _activity("The Narrator is finding the words")
            try:
                final = backend.run(spec, (
                    "(From the app: that turn never reached the players' "
                    "screen — nothing was published. Consult the narrator with "
                    "the decision and roll outcomes you already have, then push "
                    "its prose with narrate.py. Do not redo state changes you "
                    "have already applied.)")) or final
            except Exception:
                pass  # the fallback below still tells the table something

        # A turn that never reached the chronicle is a blank screen for the
        # players — but the DM's own reply is orchestrator text, not the
        # Narrator's prose: it skips the style gate and has published
        # out-of-character chatter ("1. Maera is deceased…") as in-world
        # narration. Only a real blockquote (the manual's player layer) lands
        # as narration, and only if it passes the same gate narrate.py applies;
        # anything else is a visibly out-of-character table note.
        if not narrated():
            # An OOC turn never mints narration from the fallback — the reply
            # goes out as an explicitly out-of-character system note.
            quoted = "" if ooc else players_text(final, quoted_only=True)
            gate = narrate_gate(quoted) if quoted else []
            if quoted and not gate:
                campaign_lib.append_feed(config.CAMPAIGN, quoted,
                                         type="narration")
            else:
                # Silence is the one unacceptable outcome: a player who gets
                # no reply can't tell a lost turn from a slow one. Say so.
                campaign_lib.append_feed(
                    config.CAMPAIGN,
                    players_text(final) or
                    "(The DM lost the thread on that one — say it again and "
                    "it'll pick up from here.)",
                    type="system")
                _devlog("turn_unnarrated",
                        {"gate": [g["why"] for g in gate]},
                        (final or "(empty reply)")[:800], _utcnow())

        return {"narrated": narrated(), "fresh_session": fresh, "reply": final[:2000]}
    finally:
        _activity(None, busy=False)


def reset_thread() -> None:
    """Forget the conversation but keep all campaign state (a fresh session).

    Every backend, not just the one the dm currently runs on: a table that
    switched backends mid-campaign has a stale conversation parked in the other
    one, and "new session" has to mean it everywhere.
    """
    spec = spec_for("dm", "")
    for info in backends.BACKENDS:
        try:
            backends.get(info.name).reset(spec)
        except Exception:
            pass  # a backend that can't even load has no history to forget


# ── Self-check ────────────────────────────────────────────────────────────────

def _selftest() -> None:
    """Covers what breaks silently: the write guard, tool whitelist, prose cleanup."""
    assert resolve_path("campaign/state/current.json", write=True) \
        .is_relative_to(config.CAMPAIGN.resolve())
    assert resolve_path("rules/x.md", write=False).is_relative_to(config.BUNDLE.resolve())

    for bad, why in (("rules/srd.md", "reference tree is read-only"),
                     ("/etc/passwd", "absolute path"),
                     ("campaign/../../secrets", "traversal"),
                     ("../CLAUDE.md", "traversal")):
        try:
            resolve_path(bad, write=True)
        except ValueError:
            pass
        else:
            raise AssertionError(f"write to {bad!r} must be refused ({why})")

    assert "unknown tool" in run_tool("rm", ["-rf", "/"])
    assert "error" in write_file("rules/pwned.md", "x")
    assert not (config.BUNDLE / "rules" / "pwned.md").exists()

    assert players_text("[DIRECTOR] hidden\n> The door opens.\n> Dust falls.") \
        == "The door opens.\nDust falls."
    assert players_text("[BOOKKEEPER] hp\nresult: 4\nThe door opens.") == "The door opens."

    assert "1d20" in run_tool("dice.py", ["1d20"])
    assert narrated() is False, "dice.py must not count as a narration"

    # Dotted paths must survive normalisation — the DM reads its own role
    # prompts from .claude/agents/, and a naive lstrip('./') eats that dot.
    for path in (".claude/agents/narrator.md", "./.claude/agents/narrator.md"):
        assert resolve_path(path, write=False).name == "narrator.md", path
        assert "error" not in read_file(path)[:40].lower(), path
    assert ".claude/agents/director.md" in list_files(".claude/agents/*.md")

    # The registry must resolve every role to a file that exists on disk.
    for entry in prompts.registry():
        assert prompts.resolve(entry["role"]).exists(), entry
    assert prompts.override_for("rules/srd.md") is None
    assert prompts.override_for(".claude/agents/../../etc/passwd.md") is None
    print("agent selftest: ok")


if __name__ == "__main__":
    if "--selftest" in sys.argv:
        _selftest()
    else:
        print(json.dumps(run_turn(" ".join(sys.argv[1:]) or "Hello?"), indent=2))
