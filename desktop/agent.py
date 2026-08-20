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

import contextvars
import datetime
import functools
import inspect
import io
import json
import re
import shutil
import sqlite3
import subprocess
import sys
import threading
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
        target = config.CAMPAIGN.joinpath(*p.parts[1:])
    elif write:
        raise ValueError("writes are only allowed under campaign/")
    else:
        target = config.BUNDLE / p
    # No resolve()-based containment check: the absolute/".." screens above
    # already pin the target under its root, and the frozen bundle reaches its
    # data files through PyInstaller's own symlinks (Frameworks -> Resources),
    # which resolve() would misread as an escape.
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
        shown = _steps[-8:]
        path.write_text(json.dumps({"busy": busy, "steps": shown}),
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
_narrator_ok = False  # set when the narrator role is consulted this turn —
                      # narration/scene_change pushes are refused without it,
                      # so player-facing prose always comes from the narrator


def _tool_error(e: Exception) -> str:
    return f"error: {type(e).__name__}: {e}"


# Every tool call and its result, appended to state/dev-log.jsonl for the web
# companion's Dev Log sidebar. Always on: it's the flight recorder for "why
# did the DM do that", and the trim keeps it from growing without bound.
DEVLOG_MAX_BYTES = 400_000
DEVLOG_KEEP = 200

# Which agent is at the keyboard, named for the log's "thread" column: a role
# name inside a consult_role subagent, "main" for the DM orchestrator. A
# ContextVar, not a global, because langgraph runs a response's tool calls in a
# thread pool that copies the calling context per task — so two consults running
# at once each see their own value.
_thread = contextvars.ContextVar("devlog_thread", default="main")

# ponytail: one lock for the whole log file. Parallel consults append here from
# several threads, and the size trim rewrites the file wholesale — without this,
# a 6KB entry can interleave mid-line or a trim can drop a concurrent append.
# A few writes a second, so contention is noise.
_log_lock = threading.Lock()

# run_tool swaps process-global sys.argv/sys.stdin (see its comment).
_tool_lock = threading.Lock()


def _utcnow() -> datetime.datetime:
    return datetime.datetime.now(datetime.timezone.utc)


def _stamp(t: datetime.datetime) -> str:
    # Milliseconds, not seconds: parallel calls inside one turn are the whole
    # reason for the timestamps, and they overlap well under a second.
    return t.isoformat(timespec="milliseconds")


def _devlog(tool: str, args: dict, result,
            started: datetime.datetime | None = None) -> None:
    try:
        finished = _utcnow()
        started = started or finished
        path = config.CAMPAIGN / "state" / "dev-log.jsonl"
        path.parent.mkdir(parents=True, exist_ok=True)
        entry = {"started": _stamp(started),
                 "finished": _stamp(finished),
                 "ms": round((finished - started).total_seconds() * 1000),
                 "thread": _thread.get(),
                 "tool": tool,
                 "args": {k: str(v)[:2000] for k, v in args.items()},
                 "result": str(result)[:4000]}
        with _log_lock:
            with path.open("a", encoding="utf-8") as f:
                f.write(json.dumps(entry, ensure_ascii=False) + "\n")
            if path.stat().st_size > DEVLOG_MAX_BYTES:
                lines = path.read_text(encoding="utf-8").splitlines()[-DEVLOG_KEEP:]
                path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    except OSError:
        pass  # diagnostics only — never fail a turn over the log


def _logged(fn):
    """Record calls and results in the dev log. functools.wraps keeps the
    signature and docstring, which is what langchain builds the schema from."""
    sig = inspect.signature(fn)

    @functools.wraps(fn)
    def wrapper(*a, **kw):
        started = _utcnow()
        result = fn(*a, **kw)
        try:
            bound = sig.bind(*a, **kw)
            _devlog(fn.__name__, dict(bound.arguments), result, started)
        except TypeError:
            _devlog(fn.__name__, {"raw": [*a, kw]}, result, started)
        return result
    return wrapper


@_logged
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


@_logged
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


@_logged
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


@_logged
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


def _narrate_type(argv: list[str] | None) -> str:
    """The --type a narrate.py call will publish as (default: narration)."""
    argv = [str(a) for a in (argv or [])]
    try:
        return argv[argv.index("--type") + 1]
    except (ValueError, IndexError):
        return "narration"


# The CLI-args parameter must not be named "args": langchain's schema
# inference silently drops fields named args/kwargs, leaving a v__args
# placeholder the model fills and the call then rejects.
@_logged
def run_tool(tool: str, argv: list[str], stdin: str | None = None) -> str:
    """Run a campaign tool with CLI arguments exactly as CLAUDE.md documents them.

    Available: dice.py, check_resolver.py, combat_tracker.py, char_update.py,
    narrate.py, budget_recap.py. Examples:
      run_tool("dice.py", ["1d20+5", "1d8+3", "--label", "to-hit", "--label", "damage"])
      run_tool("narrate.py", ["-"], stdin="The gate groans open…")
      run_tool("combat_tracker.py", ["damage", "--who", "Goblin1", "--amount", "6"])
      run_tool("char_update.py", ["hp", "--char", "Mira", "--heal", "7"])
      run_tool("check_resolver.py", ["--char", "Mira", "--save", "con", "--dc", "10"])
    --char takes a character id or name, not a file path.
    Pass multi-paragraph or quote-bearing prose through stdin with args ["-"].
    """
    global _narrated
    if tool not in TOOL_SCRIPTS:
        return f"error: unknown tool {tool!r}; available: {', '.join(TOOL_SCRIPTS)}"
    if tool == "narrate.py" and not _narrator_ok and _narrate_type(argv) in (
            "narration", "scene_change"):
        return ("error: player-facing prose must come from the narrator — "
                "consult_role('narrator', ...) with the Director's decision and "
                "the roll outcomes, then push what it returns. (--type system "
                "table announcements don't need the narrator.)")
    _activity(TOOL_ACTIVITY.get(tool))
    script = config.BUNDLE / "tools" / tool
    # ponytail: the tool scripts run in-process because a frozen app has no
    # python interpreter to subprocess out to — which means swapping the
    # process-global sys.argv/sys.stdin/stdout. Parallel consults can each call
    # a tool at once, so the swap window is serialised under _tool_lock; the
    # scripts are milliseconds, and it's the model calls that need to overlap.
    # A subprocess per call is the upgrade if tool runtime ever dominates.
    out, err = io.StringIO(), io.StringIO()
    code = 0
    with _tool_lock:
        saved_argv, saved_stdin = sys.argv, sys.stdin
        sys.argv = [tool] + [str(a) for a in (argv or [])]
        if stdin is not None:
            sys.stdin = io.StringIO(stdin)
        try:
            with redirect_stdout(out), redirect_stderr(err):
                try:
                    # Not runpy.run_path: in the frozen app PyInstaller's import
                    # finder claims every path under the bundle, so run_path
                    # hunts for a __main__ module inside the .py file and dies
                    # with "can't find '__main__' module". compile/exec
                    # sidesteps the import machinery entirely.
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


TOOLS = [read_file, write_file, edit_file, list_files, run_tool]


# ── Role subagents ────────────────────────────────────────────────────────────
# The manual's Director/Narrator/Rules-Lawyer/Bookkeeper pipeline as actual
# separate agents: each consult_role call runs a one-shot ReAct agent on that
# role's prompt file and (optionally) its own model, with no chat history —
# which is the point: the orchestrator's context stops absorbing every file
# the specialists read.

SUB_ROLES = tuple(r for r in prompts.ROLES if r != "dm")
SUB_RECURSION_LIMIT = 32

# Roles that must not sit between a player's message and their narration.
_AFTER_NARRATION_ROLES = ("continuity-checker", "prose-editor", "session-prep")


role_model = config.role_model


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
                refusal = ("error: that file is GM-eyes-only (the motivations "
                           "firewall) — narrate from what the players have "
                           "earned on screen")
                _devlog("read_file", {"path": path}, refusal, _utcnow())
                return refusal
            return base_read(path)

        # No run_tool: the narrator returns prose for the DM to publish —
        # with narrate.py it double-posted (observed s14) and it has no
        # other tool business (no dice, no state writes).
        return [read_file_safe, list_files]
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


# Tools a claude-cli specialist may use inside its own agent loop. The
# narrator gets NONE: the motivations firewall (invariant #7) is a tool-level
# guarantee here, and `claude -p` has no per-file hook to enforce it — with no
# file access it can only work from its pre-read brief, which is what it does
# on OpenRouter anyway. The bookkeeper is the only writer, same as role_tools.
_CLI_ROLE_TOOLS = {
    "narrator": [],
    "bookkeeper": ["Read", "Glob", "Grep", "Edit", "Write"],
}
_CLI_DEFAULT_TOOLS = ["Read", "Glob", "Grep"]
CLI_TIMEOUT = 300


def claude_binary() -> str | None:
    """Path to the claude CLI, or None if it isn't installed.

    A GUI-launched .app gets a bare PATH (/usr/bin:/bin:/usr/sbin:/sbin), not
    the login shell's — so PATH lookup alone finds nothing even when `claude`
    works fine in a terminal. Check the usual install locations too.
    """
    found = shutil.which("claude")
    if found:
        return found
    for candidate in (Path.home() / ".local/bin/claude",
                      Path("/opt/homebrew/bin/claude"),
                      Path("/usr/local/bin/claude"),
                      Path.home() / ".claude/local/claude",
                      Path.home() / ".npm-global/bin/claude"):
        if candidate.is_file():
            return str(candidate)
    return None


def _consult_via_cli(role: str, task: str, model: str) -> str:
    """Run one specialist through `claude -p` on this machine.

    Uses the user's own Claude subscription instead of OpenRouter. The role's
    prompt file becomes the system prompt and the task (brief included) the
    user turn — the same contract the OpenRouter path uses, so a role can be
    switched either way without touching its prompt.
    """
    binary = claude_binary()
    if not binary:
        return ("error: the claude CLI isn't installed on this machine (or the "
                "app can't see it) — install Claude Code, or switch this role "
                "back to an API model in Settings.")
    prompt_file = prompts.resolve(role)
    tools = _CLI_ROLE_TOOLS.get(role, _CLI_DEFAULT_TOOLS)
    cmd = [binary, "-p", task,
           "--system-prompt", prompt_file.read_text(encoding="utf-8"),
           "--output-format", "text",
           # Explicit allow-list, so a non-interactive run never blocks on a
           # permission prompt and never gets more reach than the role needs.
           "--allowed-tools", " ".join(tools),
           "--disallowed-tools", "Bash WebFetch WebSearch Task"]
    if tools:
        cmd += ["--add-dir", str(config.CAMPAIGN), "--add-dir", str(config.BUNDLE)]
    if alias := config.cli_model_alias(model):
        cmd += ["--model", alias]
    try:
        done = subprocess.run(cmd, capture_output=True, text=True,
                              timeout=CLI_TIMEOUT, cwd=str(config.BUNDLE))
    except FileNotFoundError:
        return ("error: the claude CLI isn't on this machine's PATH — install "
                "Claude Code or switch this role back to an API model in "
                "Settings.")
    except subprocess.TimeoutExpired:
        return (f"error: the local claude CLI took over {CLI_TIMEOUT}s on the "
                f"{role} and was stopped.")
    out = (done.stdout or "").strip()
    if done.returncode != 0 or not out:
        detail = (done.stderr or "").strip()[:300] or f"exit {done.returncode}"
        return f"error running the local claude CLI for the {role}: {detail}"
    return out


def _final_text(result: dict) -> str:
    for message in reversed(result.get("messages", [])):
        if message.__class__.__name__ == "AIMessage":
            return message.text() if callable(getattr(message, "text", None)) \
                else str(message.content or "")
    return ""


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
    global _narrator_ok
    if role not in SUB_ROLES:
        return f"error: unknown role {role!r}; available: {', '.join(SUB_ROLES)}"
    if not task.strip():
        return "error: task is empty — tell the specialist what you need"
    # Checkpoint roles are free AFTER the beat lands (players are reading) and
    # ruinous before it (players are staring at nothing): a continuity check
    # measured 69s ahead of a narration once. Same rule the manual states for
    # bookkeeping — never block a player's turn.
    if role in _AFTER_NARRATION_ROLES and not _narrated:
        return (f"error: the {role} runs after the beat is on screen, not "
                "before it — push this beat's narration first, then consult "
                "it in the same turn (the players read while it works).")
    if role == "narrator":
        _narrator_ok = True  # unlocks narration pushes for the rest of the turn
    _activity(ROLE_ACTIVITY.get(role, "The DM is consulting a specialist"))
    brief = _consult_brief(role, task)
    if brief:
        task = (f"{task}\n\n# Pre-read state (current as of this consult — "
                f"do NOT re-read these files)\n{brief}")
    token = _thread.set(role)
    try:
        model = role_model(role)
        if config.is_cli_model(model):
            return _consult_via_cli(role, task, model)
        result = _build_sub_agent(role).invoke(
            {"messages": [{"role": "user", "content": task}]},
            config={"recursion_limit": SUB_RECURSION_LIMIT})
    except Exception as e:
        if type(e).__name__ == "GraphRecursionError":
            return f"error: the {role} got stuck — break the task into smaller pieces"
        return f"error consulting {role}: {_friendly(e)}"
    finally:
        _thread.reset(token)
    return _final_text(result) or "(no reply)"


DM_TOOLS = TOOLS + [consult_role, consult_pair]


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
    global _narrated, _narrator_ok
    if not config.api_key():
        raise DMError("No OpenRouter API key is set yet — open Settings and paste one.")

    from langchain_core.messages import HumanMessage, ToolMessage

    _narrated = False
    _narrator_ok = False
    _activity("The DM is thinking it over")
    try:
        agent = build_agent()
        run_config = {"configurable": {"thread_id": THREAD_ID},
                      "recursion_limit": int(config.load().get("recursion_limit")
                                             or RECURSION_LIMIT)}

        history = (agent.get_state(run_config).values or {}).get("messages") or []
        # A turn interrupted mid-tool (app killed, crash) leaves an AIMessage's
        # tool_calls without ToolMessages, which bricks the thread: the provider
        # requires results immediately after the calling message. Heal by
        # writing synthetic results AS the tools node — that supersedes the
        # graph's pending tasks in a new checkpoint, so the run resumes clean.
        # (No RemoveMessage surgery: deleting around pending task writes is what
        # used to re-brick the thread.)
        answered = {m.tool_call_id for m in history
                    if getattr(m, "tool_call_id", None)}
        unanswered = [tc for m in history
                      for tc in (getattr(m, "tool_calls", None) or [])
                      if tc["id"] not in answered]
        if unanswered:
            # Truthful, not "the tool never ran": run_tool mutates state BEFORE
            # the result is checkpointed, so a killed app may have applied the
            # change already. Telling the model it never ran invites a re-apply
            # (that's how a PC once took the same poison damage twice).
            agent.update_state(run_config, {"messages": [
                ToolMessage(content="(the app was closed mid-turn — this call "
                                    "was interrupted and may or may not have "
                                    "taken effect; re-read campaign state "
                                    "before redoing any state change)",
                            tool_call_id=tc["id"])
                for tc in unanswered
            ]}, as_node="tools")

        fresh = not history
        turn = ([HumanMessage(content=session_brief())] if fresh else []) \
            + [HumanMessage(content=player_message)]

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
        if not _narrated and not ooc and not players_text(final, quoted_only=True):
            _activity("The Narrator is finding the words")
            try:
                result = agent.invoke({"messages": [HumanMessage(
                    content="(From the app: that turn never reached the "
                            "players' screen — nothing was published. Consult "
                            "the narrator with the decision and roll outcomes "
                            "you already have, then push its prose with "
                            "narrate.py. Do not redo state changes you have "
                            "already applied.)")]}, config=run_config)
                final = _final_text(result) or final
            except Exception:
                pass  # the fallback below still tells the table something

        # A turn that never reached the chronicle is a blank screen for the
        # players — but the DM's own reply is orchestrator text, not the
        # Narrator's prose: it skips the style gate and has published
        # out-of-character chatter ("1. Maera is deceased…") as in-world
        # narration. Only a real blockquote (the manual's player layer) lands
        # as narration, and only if it passes the same gate narrate.py applies;
        # anything else is a visibly out-of-character table note.
        if not _narrated:
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
