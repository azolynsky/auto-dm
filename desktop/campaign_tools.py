#!/usr/bin/env python3
"""
The campaign tool surface — what any DM backend gets to call.

These are the tools the manual documents: read/write/edit files under
campaign/, list them, and run the tools in tools/ (dice, narrate, char_update,
combat_tracker...). They live here rather than in agent.py because three
different loops need the same surface — the OpenRouter ReAct graph, the local
`claude` CLI over MCP, and the Claude Agent SDK's in-process MCP server. See
docs/backends.md.

Nothing here knows which model is calling it. The docstrings are the usage
contract (they are what the model reads), the guardrails are unconditional, and
role_tools() carries the per-role firewalls — including the Narrator's, which
is why every backend now enforces invariant #7 identically.
"""
from __future__ import annotations

import contextvars
import datetime
import functools
import inspect
import io
import json
import sys
import threading
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import config  # noqa: E402
import prompts  # noqa: E402

MAX_READ = 60_000          # chars returned by read_file before truncating

# Only the campaign tools are reachable — there is no general shell.
TOOL_SCRIPTS = ("dice.py", "check_resolver.py", "combat_tracker.py",
                "char_update.py", "narrate.py", "budget_recap.py")

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


TOOLS = [read_file, write_file, edit_file, list_files, run_tool]

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

# ── Per-turn flags ────────────────────────────────────────────────────────────
# run_tool sets these; agent.py reads them to decide whether a turn ever
# reached the players. Functions rather than exported globals: `from
# campaign_tools import _narrated` would copy the value at import time and then
# never see a push land.

def begin_turn() -> None:
    """Reset the narration flags. Called once per player turn."""
    global _narrated, _narrator_ok
    _narrated = False
    _narrator_ok = False


def allow_narration() -> None:
    """The narrator has been consulted — narration pushes are unlocked."""
    global _narrator_ok
    _narrator_ok = True


def narration_allowed() -> bool:
    return _narrator_ok


def narrated() -> bool:
    """True once a narrate.py push has landed this turn."""
    return _narrated
