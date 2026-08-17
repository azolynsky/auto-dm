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
import runpy
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


# ── Tools ─────────────────────────────────────────────────────────────────────
# Docstrings are what the model sees, so they carry the usage rules.

_narrated = False   # set when a narrate.py push lands; read once per turn


def _tool_error(e: Exception) -> str:
    return f"error: {type(e).__name__}: {e}"


def read_file(path: str) -> str:
    """Read a text file, e.g. campaign/state/current.json, rules/srd-reference.md,
    or .claude/agents/director.md. Paths are repo-relative, never absolute."""
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


def run_tool(tool: str, args: list[str], stdin: str | None = None) -> str:
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
    script = config.BUNDLE / "tools" / tool
    # ponytail: swapping sys.argv/stdout in-process is fine while the queue
    # serialises turns. Needs a subprocess if turns ever overlap — but note a
    # frozen app has no python interpreter to spawn, hence runpy.
    out, err = io.StringIO(), io.StringIO()
    saved_argv, saved_stdin = sys.argv, sys.stdin
    sys.argv = [tool] + [str(a) for a in (args or [])]
    if stdin is not None:
        sys.stdin = io.StringIO(stdin)
    code = 0
    try:
        with redirect_stdout(out), redirect_stderr(err):
            try:
                runpy.run_path(str(script), run_name="__main__")
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
        """Trim history to the token budget without orphaning a tool result.

        end_on=("human","tool") plus start_on="human" is what keeps every tool
        message attached to the assistant turn that requested it — a dangling
        tool result is a 400 from every provider.
        """
        return {"llm_input_messages": trim_messages(
            state["messages"], max_tokens=budget,
            token_counter=count_tokens_approximately,
            strategy="last", start_on="human", end_on=("human", "tool"),
            include_system=False, allow_partial=False)}

    _agent = create_react_agent(model, TOOLS, prompt=system_prompt(),
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

    fresh = not (agent.get_state(run_config).values or {}).get("messages")
    turn = ([HumanMessage(content=session_brief())] if fresh else []) \
        + [HumanMessage(content=player_message)]

    _narrated = False
    try:
        result = agent.invoke({"messages": turn}, config=run_config)
    except DMError:
        raise
    except Exception as e:
        if type(e).__name__ == "GraphRecursionError":
            raise DMError("The DM got stuck working on that. Try saying it again, "
                          "more simply.") from e
        raise _friendly(e) from e

    final = ""
    for message in reversed(result.get("messages", [])):
        if message.__class__.__name__ == "AIMessage":
            final = message.text() if callable(getattr(message, "text", None)) \
                else str(message.content or "")
            break

    # A turn that never reached the chronicle is a blank screen for the players.
    if not _narrated:
        prose = players_text(final)
        if prose:
            campaign_lib.append_feed(config.CAMPAIGN, prose, type="narration")

    return {"narrated": _narrated, "fresh_session": fresh, "reply": final[:2000]}


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
