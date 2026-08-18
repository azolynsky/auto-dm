#!/usr/bin/env python3
"""
The DM brain: a LangGraph ReAct agent on OpenRouter, replacing the
`claude -p --continue` worker.

Same contract as the CLI it replaces — take one player message, run the loop
with file and campaign-tool access, and leave the player-facing result in the
chronicle via narrate.py. The loop, tool dispatch, retries and history live in
LangGraph; this module only supplies the tools, the prompt and the guardrails.

History persists in a LangGraph SQLite checkpoint under the campaign, so a
session survives closing the app.

Nothing campaign-specific lives here — the DM's knowledge is CLAUDE.md plus the
files it reads itself.

Self-check:  python desktop/agent.py --selftest
"""
from __future__ import annotations

import io
import json
import re
import sqlite3
import sys
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import config  # noqa: E402
import prompts  # noqa: E402

sys.path.insert(0, str(config.BUNDLE / "tools"))
import campaign_lib  # noqa: E402

OPENROUTER_URL = "https://openrouter.ai/api/v1"
THREAD_ID = "dm"           # one running conversation per campaign
RECURSION_LIMIT = 80       # graph steps per turn (~40 tool round trips)
HISTORY_TOKENS = 120_000   # history resent per request, before trimming
MAX_READ = 60_000          # chars returned by read_file before truncating

# Only the campaign tools are reachable — there is no general shell.
TOOL_SCRIPTS = ("dice.py", "check_resolver.py", "combat_tracker.py",
                "char_update.py", "narrate.py", "budget_recap.py")


class DMError(RuntimeError):
    """Something the player needs to see on the table screen."""


# ── Guardrails ────────────────────────────────────────────────────────────────

def resolve_path(path: str, *, write: bool) -> Path:
    """Map a manual-style path to disk.

    'campaign/...' lands in the player's campaign directory (writable, and
    outside the read-only app bundle); anything else is reference content.
    """
    p = Path(config.norm_path(path) or ".")
    if p.is_absolute() or ".." in p.parts:
        raise ValueError("use plain repo-relative paths, e.g. campaign/state/current.json")
    if p.parts and p.parts[0] == "campaign":
        base = config.CAMPAIGN.resolve()
        target = base.joinpath(*p.parts[1:])
    elif write:
        raise ValueError("writes are only allowed under campaign/")
    else:
        base = config.BUNDLE.resolve()
        target = base / p
    target = target.resolve()
    if target != base and not target.is_relative_to(base):
        raise ValueError("path escapes its root")
    return target


# ── Live activity (player-safe) ───────────────────────────────────────────────
# While a turn runs, every tool call publishes a fixed label to
# state/dm-activity.json; the server streams it to the chat so the table sees
# which role is working. Labels are canned strings only — never file paths,
# dice labels, or arguments — so nothing here can leak a secret or an outcome.

ROLE_ACTIVITY = {
    "director": "The Director is deciding what the world does",
    "rules-lawyer": "The Rules Lawyer is checking the rules",
    "narrator": "The Narrator is finding the words",
    "bookkeeper": "The Bookkeeper is opening the ledger",
    "continuity-checker": "The Continuity Checker is comparing notes",
    "session-prep": "The DM is sketching what comes next",
    "prose-editor": "The Prose Editor is polishing the wording",
}

TOOL_ACTIVITY = {
    "dice.py": "Rolling dice",
    "check_resolver.py": "Rolling a check",
    "combat_tracker.py": "Running the combat tracker",
    "char_update.py": "Updating a character sheet",
    "narrate.py": "Writing the scene",
    "budget_recap.py": "Reviewing the story so far",
}

_steps: list[str] = []


def _activity(step: str | None, *, busy: bool = True) -> None:
    global _steps
    if not busy:
        _steps = []
    elif step and (not _steps or _steps[-1] != step):
        _steps.append(step)
        del _steps[:-30]
    else:
        return  # nothing new to show
    try:
        path = config.CAMPAIGN / "state" / "dm-activity.json"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps({"busy": busy, "steps": _steps[-8:]}),
                        encoding="utf-8")
    except OSError:
        pass  # cosmetics only — never fail a turn over the spinner


def _read_activity(path: str) -> str | None:
    p = config.norm_path(path)
    if p.startswith(".claude/agents/"):
        return ROLE_ACTIVITY.get(Path(p).stem, "The DM is consulting a specialist")
    if p.startswith(".claude/skills/"):
        return "The DM is checking a procedure"
    if p.startswith("rules/"):
        return "Consulting the rulebooks"
    if p.startswith("campaign/characters/"):
        return "Reviewing a character sheet"
    if p.startswith("campaign/"):
        return "Reading the campaign notes"
    return None


# ── Tools ─────────────────────────────────────────────────────────────────────
# Docstrings are what the model sees, so they carry the usage rules.

_narrated = False   # set when a narrate.py push lands; read once per turn


def _tool_error(e: Exception) -> str:
    return f"error: {type(e).__name__}: {e}"


def read_file(path: str) -> str:
    """Read a text file, e.g. campaign/state/current.json, rules/srd-reference.md,
    or .claude/agents/director.md. Paths are repo-relative, never absolute."""
    _activity(_read_activity(path))
    try:
        target = prompts.override_for(path) or resolve_path(path, write=False)
        text = target.read_text(encoding="utf-8", errors="replace")
        return text[:MAX_READ] + ("\n…(truncated)" if len(text) > MAX_READ else "")
    except FileNotFoundError:
        return f"error: no such file: {path}"
    except (ValueError, OSError) as e:
        return _tool_error(e)


def write_file(path: str, content: str) -> str:
    """Write a file under campaign/, creating or replacing it whole. For a small
    state change prefer edit_file, which won't clobber the rest of the file."""
    _activity("The Bookkeeper is updating the records")
    try:
        target = resolve_path(path, write=True)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(content, encoding="utf-8")
        return f"wrote {path} ({len(content)} chars)"
    except (ValueError, OSError) as e:
        return _tool_error(e)


def edit_file(path: str, old_text: str, new_text: str) -> str:
    """Replace one exact, unique string in a file under campaign/. old_text must
    match the file byte for byte and appear exactly once."""
    _activity("The Bookkeeper is updating the records")
    try:
        target = resolve_path(path, write=True)
        text = target.read_text(encoding="utf-8")
        hits = text.count(old_text)
        if hits == 0:
            return "error: old_text not found — read the file and match it exactly"
        if hits > 1:
            return f"error: old_text appears {hits} times — include more surrounding context"
        target.write_text(text.replace(old_text, new_text, 1), encoding="utf-8")
        return f"edited {path}"
    except FileNotFoundError:
        return f"error: no such file: {path}"
    except (ValueError, OSError) as e:
        return _tool_error(e)


def list_files(pattern: str) -> str:
    """List files matching a glob, e.g. campaign/npcs/recurring/*/ or
    campaign/sessions/*.md."""
    try:
        parts = Path(config.norm_path(pattern)).parts
        if ".." in parts:
            raise ValueError("no '..' in patterns")
        if parts and parts[0] == "campaign":
            base, rel, prefix = config.CAMPAIGN, Path(*parts[1:] or ("*",)), "campaign/"
        else:
            base, rel, prefix = config.BUNDLE, Path(*parts or ("*",)), ""
        found = sorted(prefix + str(p.relative_to(base)) for p in base.glob(str(rel)))
        return "\n".join(found[:400]) or "(nothing matched)"
    except (ValueError, OSError) as e:
        return _tool_error(e)


# The CLI-args parameter must not be named "args": langchain's schema
# inference silently drops fields named args/kwargs, leaving a v__args
# placeholder the model fills and the call then rejects.
def run_tool(tool: str, argv: list[str], stdin: str | None = None) -> str:
    """Run a campaign tool with CLI arguments exactly as CLAUDE.md documents them.

    Available: dice.py, check_resolver.py, combat_tracker.py, char_update.py,
    narrate.py, budget_recap.py. Examples:
      run_tool("dice.py", ["1d20+5", "1d8+3", "--label", "to-hit", "--label", "damage"])
      run_tool("narrate.py", ["-"], stdin="The gate groans open…")
      run_tool("combat_tracker.py", ["damage", "--who", "Goblin1", "--amount", "6"])
      run_tool("char_update.py", ["hp", "--char", "Mira", "--heal", "7"])
    Pass multi-paragraph or quote-bearing prose through stdin with args ["-"].
    """
    global _narrated
    if tool not in TOOL_SCRIPTS:
        return f"error: unknown tool {tool!r}; available: {', '.join(TOOL_SCRIPTS)}"
    _activity(TOOL_ACTIVITY.get(tool))
    script = config.BUNDLE / "tools" / tool
    # ponytail: swapping sys.argv/stdout in-process is fine while the queue
    # serialises turns. Needs a subprocess if turns ever overlap — but note a
    # frozen app has no python interpreter to spawn, hence in-process exec.
    out, err = io.StringIO(), io.StringIO()
    saved_argv, saved_stdin = sys.argv, sys.stdin
    sys.argv = [tool] + [str(a) for a in (argv or [])]
    if stdin is not None:
        sys.stdin = io.StringIO(stdin)
    code = 0
    try:
        with redirect_stdout(out), redirect_stderr(err):
            try:
                # Not runpy.run_path: in the frozen app PyInstaller's import
                # finder claims every path under the bundle, so run_path hunts
                # for a __main__ module inside the .py file and dies with
                # "can't find '__main__' module". compile/exec sidesteps the
                # import machinery entirely.
                exec(compile(script.read_text(encoding="utf-8"),
                             str(script), "exec"),
                     {"__name__": "__main__", "__file__": str(script)})
            except SystemExit as e:   # every tool ends in sys.exit(main())
                code = e.code if isinstance(e.code, int) else 0
    except Exception as e:
        return f"error running {tool}: {type(e).__name__}: {e}"
    finally:
        sys.argv, sys.stdin = saved_argv, saved_stdin
    body = out.getvalue().strip() or err.getvalue().strip() or "(no output)"
    if tool == "narrate.py" and code == 0:
        _narrated = True
    return body if code == 0 else f"exit {code}\n{body}"


TOOLS = [read_file, write_file, edit_file, list_files, run_tool]


# ── Role subagents ────────────────────────────────────────────────────────────
# The manual's Director/Narrator/Rules-Lawyer/Bookkeeper pipeline as actual
# separate agents: each consult_role call runs a one-shot ReAct agent on that
# role's prompt file and (optionally) its own model, with no chat history —
# which is the point: the orchestrator's context stops absorbing every file
# the specialists read.

SUB_ROLES = tuple(r for r in prompts.ROLES if r != "dm")
SUB_RECURSION_LIMIT = 32


def role_model(role: str) -> str:
    return ((config.load().get("role_models") or {}).get(role)
            or config.DEV_DEFAULTS["role_models"].get(role)
            or config.model())


def role_tools(role: str) -> list:
    """Bookkeeper is the only role that writes; the Narrator's reads are
    firewalled (invariant #7); everyone else reads and runs tools."""
    if role == "bookkeeper":
        return TOOLS
    if role == "narrator":
        base_read = read_file

        def read_file_safe(path: str) -> str:
            """Read a text file, e.g. campaign/state/current.json or an entity's
            summary.md/voice.md. Paths are repo-relative. motivations.md and
            secrets.md are GM-eyes-only and will be refused."""
            if Path(config.norm_path(path)).name in ("motivations.md", "secrets.md"):
                return ("error: that file is GM-eyes-only (the motivations "
                        "firewall) — narrate from what the players have earned "
                        "on screen")
            return base_read(path)

        return [read_file_safe, list_files, run_tool]
    return [read_file, list_files, run_tool]


_sub_agents: dict = {}


def _build_sub_agent(role: str):
    key = (role, role_model(role), prompts.selected(role), config.api_key()[-6:])
    if key not in _sub_agents:
        from langchain_openai import ChatOpenAI
        from langgraph.prebuilt import create_react_agent
        model = ChatOpenAI(
            model=role_model(role), api_key=config.api_key(),
            base_url=OPENROUTER_URL, timeout=600,
            default_headers={"HTTP-Referer": "https://github.com/auto-dm",
                             "X-Title": "Auto-DM"})
        _sub_agents[key] = create_react_agent(
            model, role_tools(role),
            prompt=_cached_system(prompts.resolve(role).read_text(encoding="utf-8")),
            # No trimming (consults are one-shot), but the same rolling cache
            # breakpoints: a consult that reads five entity files re-sends
            # them on every step, and repeat consults of the same role within
            # the cache TTL start from a warm system prompt.
            pre_model_hook=lambda state: {
                "llm_input_messages": _mark_cache(state["messages"])})
    return _sub_agents[key]


def _final_text(result: dict) -> str:
    for message in reversed(result.get("messages", [])):
        if message.__class__.__name__ == "AIMessage":
            return message.text() if callable(getattr(message, "text", None)) \
                else str(message.content or "")
    return ""


def consult_role(role: str, task: str) -> str:
    """Delegate to a specialist role agent — this harness's native subagent
    mechanism from the manual. Roles: director, narrator, rules-lawyer,
    bookkeeper, continuity-checker, session-prep, prose-editor. Each runs on
    its role prompt from .claude/agents/ (and its own model, if configured)
    with file and campaign-tool access, and returns its final answer.

    The specialist has NO chat history and NO memory between calls — put
    everything it needs in `task`: the beat, what the player said, relevant
    entity paths, dice results, and decisions already made. The narrator
    cannot read motivations.md/secrets.md; the bookkeeper is the only role
    that can write files. Independent consults can happen in parallel by
    calling this tool multiple times in one response.
    """
    if role not in SUB_ROLES:
        return f"error: unknown role {role!r}; available: {', '.join(SUB_ROLES)}"
    if not task.strip():
        return "error: task is empty — tell the specialist what you need"
    _activity(ROLE_ACTIVITY.get(role, "The DM is consulting a specialist"))
    try:
        result = _build_sub_agent(role).invoke(
            {"messages": [{"role": "user", "content": task}]},
            config={"recursion_limit": SUB_RECURSION_LIMIT})
    except Exception as e:
        if type(e).__name__ == "GraphRecursionError":
            return f"error: the {role} got stuck — break the task into smaller pieces"
        return f"error consulting {role}: {_friendly(e)}"
    return _final_text(result) or "(no reply)"


DM_TOOLS = TOOLS + [consult_role]


# ── Prompt and briefing ───────────────────────────────────────────────────────

def system_prompt() -> str:
    """The selected dm adapter, then the operating manual."""
    adapter = prompts.resolve("dm").read_text(encoding="utf-8")
    manual = (config.BUNDLE / "CLAUDE.md").read_text(encoding="utf-8")
    return adapter + "\n" + manual


# ── Prompt caching ────────────────────────────────────────────────────────────
# A ReAct turn re-sends the whole prompt on every tool round trip, so caching
# is the difference between paying for CLAUDE.md + history once per turn and
# once per step. OpenRouter forwards Anthropic-style cache_control breakpoints
# (reads bill at ~10% of input); providers with automatic prefix caching
# (OpenAI, Gemini) ignore the markers, so one code path serves every model.

CACHE_CONTROL = {"type": "ephemeral"}


def _cached_system(text: str):
    """A system message whose whole text sits behind a cache breakpoint."""
    from langchain_core.messages import SystemMessage
    return SystemMessage(content=[
        {"type": "text", "text": text, "cache_control": CACHE_CONTROL}])


def _mark_cache(messages: list, spots: int = 2) -> list:
    """Copy `messages` with cache breakpoints on the newest `spots` markable
    ones (non-empty text content). Two rolling breakpoints let Anthropic's
    backward prefix lookup find last step's cache even after a long tool
    result lands between them. Never mutates the checkpointed originals."""
    marked = list(messages)
    left = spots
    for i in range(len(marked) - 1, -1, -1):
        if left == 0:
            break
        content = marked[i].content
        if isinstance(content, str) and content.strip():
            new = [{"type": "text", "text": content,
                    "cache_control": CACHE_CONTROL}]
        elif (isinstance(content, list) and content
                and isinstance(content[-1], dict)
                and content[-1].get("type") == "text" and content[-1].get("text")):
            new = content[:-1] + [{**content[-1], "cache_control": CACHE_CONTROL}]
        else:
            continue  # empty content (e.g. a pure tool-call AIMessage) — skip
        marked[i] = marked[i].model_copy(update={"content": new})
        left -= 1
    return marked


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
    return ("Session start. Here is the current state — the manual's session-start "
            "reads, inlined. Read any entity folders you still need.\n\n"
            + "\n\n".join(chunks))


# ── The agent ─────────────────────────────────────────────────────────────────

_agent = None
_agent_key: tuple | None = None


def _checkpointer():
    from langgraph.checkpoint.sqlite import SqliteSaver
    path = config.CAMPAIGN / "state" / "dm-thread.sqlite"
    path.parent.mkdir(parents=True, exist_ok=True)
    saver = SqliteSaver(sqlite3.connect(str(path), check_same_thread=False))
    saver.setup()
    return saver


def build_agent():
    """The ReAct graph. Cached until the model or a prompt variant changes."""
    global _agent, _agent_key
    cfg = config.load()
    key = (config.model(), prompts.selected("dm"), config.api_key()[-6:],
           cfg.get("history_tokens"), cfg.get("recursion_limit"))
    if _agent is not None and _agent_key == key:
        return _agent

    from langchain_core.messages.utils import (count_tokens_approximately,
                                               trim_messages)
    from langchain_openai import ChatOpenAI
    from langgraph.prebuilt import create_react_agent

    model = ChatOpenAI(
        model=config.model(),
        api_key=config.api_key(),
        base_url=OPENROUTER_URL,
        timeout=600,
        default_headers={"HTTP-Referer": "https://github.com/auto-dm",
                         "X-Title": "Auto-DM"},
    )

    budget = int(cfg.get("history_tokens") or HISTORY_TOKENS)

    def keep_recent(state):
        """Trim history to the token budget without orphaning a tool result,
        then place the rolling cache breakpoints.

        Hysteresis, not a hard ceiling: trimming every call moves the window
        forward a little each turn, which changes the prompt prefix and voids
        the provider's prompt cache on the entire history. Instead history
        grows untouched until it exceeds the budget, then gets cut hard to
        half — one cache re-write, then a long stable stretch.

        end_on=("human","tool") plus start_on="human" is what keeps every tool
        message attached to the assistant turn that requested it — a dangling
        tool result is a 400 from every provider.
        """
        messages = state["messages"]
        if count_tokens_approximately(messages) > budget:
            messages = trim_messages(
                messages, max_tokens=budget // 2,
                token_counter=count_tokens_approximately,
                strategy="last", start_on="human", end_on=("human", "tool"),
                include_system=False, allow_partial=False)
        return {"llm_input_messages": _mark_cache(messages)}

    _agent = create_react_agent(model, DM_TOOLS,
                                prompt=_cached_system(system_prompt()),
                                pre_model_hook=keep_recent,
                                checkpointer=_checkpointer())
    _agent_key = key
    return _agent


def _friendly(e: Exception) -> DMError:
    """Turn a provider error into something readable at the table."""
    import openai
    if isinstance(e, openai.AuthenticationError):
        return DMError("The DM can't sign in to OpenRouter — the API key looks wrong "
                       "or expired. Check it in Settings.")
    if isinstance(e, openai.RateLimitError):
        return DMError("OpenRouter is rate-limiting us. Wait a few seconds and say "
                       "that again.")
    if isinstance(e, openai.APIConnectionError):
        return DMError("The DM can't reach OpenRouter — check the internet connection.")
    if isinstance(e, openai.APIStatusError):
        if e.status_code == 402:
            return DMError("Your OpenRouter account is out of credit, so the DM can't "
                           "think. Top it up at openrouter.ai and try again.")
        if e.status_code == 404:
            return DMError(f"OpenRouter doesn't have the model '{config.model()}'. "
                           "Pick another one in Settings.")
        return DMError(f"OpenRouter returned {e.status_code}: {str(e)[:300]}")
    return DMError(f"The DM hit an unexpected error: {type(e).__name__}: {str(e)[:300]}")


LABEL_LINE = re.compile(r"^\s*(\[[A-Z][A-Z ]+\]|roll:|result:)", re.M)


def players_text(text: str) -> str:
    """Best-effort player-facing prose from a reply that never called narrate.py.

    Prefers the blockquote layer the manual mandates; failing that, strips the
    DM-layer label lines so the table gets prose rather than [DIRECTOR] notes.
    """
    quoted = [ln.lstrip()[2:] for ln in text.splitlines() if ln.lstrip().startswith("> ")]
    if quoted:
        return "\n".join(quoted).strip()
    return "\n".join(ln for ln in text.splitlines()
                     if ln.strip() and not LABEL_LINE.match(ln)).strip()


def generate_character(description: str) -> dict:
    """One-shot LLM call: a player's free-text concept → a level-1 sheet in
    the campaign's exact JSON shape. Separate from the DM thread — this runs
    on the setup screen, before the table exists."""
    if not config.api_key():
        raise DMError("No OpenRouter API key is set yet — open Settings and paste one.")
    from langchain_core.messages import HumanMessage
    from langchain_openai import ChatOpenAI

    sheets = sorted((config.CAMPAIGN / "characters").glob("pc-*.json"))
    if not sheets:
        raise DMError("No example character sheet found to model the new hero on.")
    example = sheets[0].read_text(encoding="utf-8")

    model = ChatOpenAI(
        model=config.model(), api_key=config.api_key(), base_url=OPENROUTER_URL,
        timeout=300,
        default_headers={"HTTP-Referer": "https://github.com/auto-dm",
                         "X-Title": "Auto-DM"},
    )
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
        try:
            raw = model.invoke([_cached_system(system),
                                HumanMessage(content="Player's concept: " + description)])
        except Exception as e:
            raise _friendly(e) from e
        text = re.sub(r"^```(?:json)?\s*|\s*```$", "", str(raw.content).strip())
        try:
            sheet = json.loads(text)
            if isinstance(sheet, dict):
                return sheet
            last_err = "not a JSON object"
        except json.JSONDecodeError as e:
            last_err = str(e)
    raise DMError(f"The DM couldn't write a valid character sheet ({last_err}). "
                  "Try describing the hero again.")


def run_turn(player_message: str) -> dict:
    """One player turn. Publishes to the chronicle; returns a small summary."""
    global _narrated
    if not config.api_key():
        raise DMError("No OpenRouter API key is set yet — open Settings and paste one.")

    from langchain_core.messages import HumanMessage

    agent = build_agent()
    run_config = {"configurable": {"thread_id": THREAD_ID},
                  "recursion_limit": int(config.load().get("recursion_limit")
                                         or RECURSION_LIMIT)}

    history = (agent.get_state(run_config).values or {}).get("messages") or []
    # A turn that crashed mid-tool leaves an AIMessage's tool_calls without
    # ToolMessages, which bricks the thread: the provider requires results
    # immediately after the calling message, so every later turn fails too.
    # Heal by dropping everything after the first unanswered call and closing
    # it out with synthetic results, so "say it again" actually works.
    answered = {m.tool_call_id for m in history if getattr(m, "tool_call_id", None)}
    dangling = next((i for i, m in enumerate(history)
                     if any(tc["id"] not in answered
                            for tc in getattr(m, "tool_calls", None) or [])), None)
    if dangling is not None:
        from langchain_core.messages import RemoveMessage, ToolMessage
        agent.update_state(run_config, {"messages": [
            RemoveMessage(id=m.id) for m in history[dangling + 1:]
        ] + [
            ToolMessage(content="(interrupted — the tool never ran)",
                        tool_call_id=tc["id"])
            for tc in history[dangling].tool_calls if tc["id"] not in answered
        ]})

    fresh = not history
    turn = ([HumanMessage(content=session_brief())] if fresh else []) \
        + [HumanMessage(content=player_message)]

    _narrated = False
    _activity("The DM is thinking it over")
    try:
        try:
            result = agent.invoke({"messages": turn}, config=run_config)
        except DMError:
            raise
        except Exception as e:
            if type(e).__name__ == "GraphRecursionError":
                raise DMError("The DM got stuck working on that. Try saying it "
                              "again, more simply.") from e
            raise _friendly(e) from e

        final = _final_text(result)

        # A turn that never reached the chronicle is a blank screen for the players.
        if not _narrated:
            prose = players_text(final)
            if prose:
                campaign_lib.append_feed(config.CAMPAIGN, prose, type="narration")

        return {"narrated": _narrated, "fresh_session": fresh, "reply": final[:2000]}
    finally:
        _activity(None, busy=False)


def reset_thread() -> None:
    """Forget the conversation but keep all campaign state (a fresh session)."""
    global _agent, _agent_key
    try:
        _checkpointer().delete_thread(THREAD_ID)
    except Exception:
        (config.CAMPAIGN / "state" / "dm-thread.sqlite").unlink(missing_ok=True)
    _agent = _agent_key = None


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
    assert _narrated is False, "dice.py must not count as a narration"

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
