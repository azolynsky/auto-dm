#!/usr/bin/env python3
"""
The OpenRouter backend: a LangGraph ReAct loop over an OpenAI-compatible
endpoint, paid for with OpenRouter credit.

This is the original DM brain, now one backend among several. Everything
LangGraph-shaped lives here — the graph, the SQLite checkpoint, history
trimming, prompt-cache breakpoints, and healing a conversation that was
interrupted mid-tool. None of that is visible to agent.py, which asks for a
turn and gets text back.
"""
from __future__ import annotations

import contextlib
import sqlite3
import sys
import threading
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import config  # noqa: E402

from .base import AgentSpec, Backend, BackendError  # noqa: E402

OPENROUTER_URL = "https://openrouter.ai/api/v1"
HISTORY_TOKENS = 120_000   # history resent per request, before trimming
REQUEST_TIMEOUT = 600

# ── Prompt caching ────────────────────────────────────────────────────────────
# A ReAct turn re-sends the whole prompt on every tool round trip, so caching
# is the difference between paying for CLAUDE.md + history once per turn and
# once per step. OpenRouter forwards Anthropic-style cache_control breakpoints
# (reads bill at ~10% of input); providers with automatic prefix caching
# (OpenAI, Gemini) ignore the markers, so one code path serves every model.

CACHE_CONTROL = {"type": "ephemeral"}


def cached_system(text: str):
    """A system message whose whole text sits behind a cache breakpoint."""
    from langchain_core.messages import SystemMessage
    return SystemMessage(content=[
        {"type": "text", "text": text, "cache_control": CACHE_CONTROL}])


def mark_cache(messages: list, spots: int = 2) -> list:
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


def _final_text(result: dict) -> str:
    for message in reversed(result.get("messages", [])):
        if message.__class__.__name__ == "AIMessage":
            return message.text() if callable(getattr(message, "text", None)) \
                else str(message.content or "")
    return ""


def friendly(e: Exception, model: str) -> BackendError:
    """Turn a provider error into something readable at the table."""
    import openai
    if isinstance(e, openai.AuthenticationError):
        return BackendError("The DM can't sign in to OpenRouter — the API key "
                            "looks wrong or expired. Check it in Settings.")
    if isinstance(e, openai.RateLimitError):
        return BackendError("OpenRouter is rate-limiting us. Wait a few seconds "
                            "and say that again.")
    if isinstance(e, openai.APIConnectionError):
        return BackendError("The DM can't reach OpenRouter — check the internet "
                            "connection.")
    if isinstance(e, openai.APIStatusError):
        if e.status_code == 402:
            return BackendError("Your OpenRouter account is out of credit, so "
                                "the DM can't think. Top it up at openrouter.ai "
                                "and try again.")
        if e.status_code == 404:
            return BackendError(f"OpenRouter doesn't have the model '{model}'. "
                                "Pick another one in Settings.")
        return BackendError(f"OpenRouter returned {e.status_code}: {str(e)[:300]}")
    return BackendError(f"The DM hit an unexpected error: "
                        f"{type(e).__name__}: {str(e)[:300]}")


# ── The thread file ───────────────────────────────────────────────────────────
# History trimming deletes checkpoints, and SQLite keeps the freed pages rather
# than handing them back to the filesystem — so the thread file only ever grows.
# One campaign's reached 793MB around 9.7MB of live checkpoints: 200,712 free
# pages out of 203,071. VACUUM reclaims all of it with nothing lost, so do it
# whenever the file is mostly hole.

# Two conditions, so neither a small file nor a merely fragmented one is
# rewritten: the file must be more hole than data, AND the hole must be worth
# reclaiming on its own (5k pages is ~20MB at SQLite's 4KB default).
VACUUM_MIN_FREE_PAGES = 5_000
VACUUM_FREE_RATIO = 0.5


def reclaim(path: Path) -> None:
    """Shrink a bloated checkpoint file. Safe to call on every connect.

    Its own short-lived connection: VACUUM can't run inside a transaction, and
    the saver's connection is handed to langgraph. Any failure is ignored — a
    thread file we couldn't shrink still works, and this is disk hygiene, not
    correctness.
    """
    if not path.exists():
        return
    try:
        with contextlib.closing(sqlite3.connect(str(path))) as conn:
            conn.isolation_level = None
            pages = conn.execute("pragma page_count").fetchone()[0]
            free = conn.execute("pragma freelist_count").fetchone()[0]
            if (free >= VACUUM_MIN_FREE_PAGES
                    and free > pages * VACUUM_FREE_RATIO):
                conn.execute("vacuum")
    except sqlite3.Error:
        pass


class OpenRouterBackend(Backend):
    name = "openrouter"

    def __init__(self) -> None:
        self._graphs: dict = {}
        self._lock = threading.Lock()

    def available(self) -> str | None:
        if not config.api_key():
            return ("No OpenRouter API key is set yet — open Settings and "
                    "paste one.")
        return None

    # ── history ──────────────────────────────────────────────────────────────

    def _checkpointer(self):
        from langgraph.checkpoint.sqlite import SqliteSaver
        path = config.CAMPAIGN / "state" / "dm-thread.sqlite"
        path.parent.mkdir(parents=True, exist_ok=True)
        reclaim(path)
        saver = SqliteSaver(sqlite3.connect(str(path), check_same_thread=False))
        saver.setup()
        return saver

    def is_fresh(self, spec: AgentSpec) -> bool:
        if not spec.stateful:
            return True
        graph = self._graph(spec)
        state = graph.get_state(self._run_config(spec))
        return not ((state.values or {}).get("messages") or [])

    def reset(self, spec: AgentSpec) -> None:
        if not spec.stateful:
            return
        try:
            self._checkpointer().delete_thread(spec.thread)
        except Exception:
            (config.CAMPAIGN / "state" / "dm-thread.sqlite").unlink(missing_ok=True)
        with self._lock:
            self._graphs.clear()

    # ── the graph ────────────────────────────────────────────────────────────

    def _run_config(self, spec: AgentSpec) -> dict:
        return {"configurable": {"thread_id": spec.thread},
                "recursion_limit": spec.turn_limit * 2}

    def _graph(self, spec: AgentSpec):
        """The ReAct graph for this spec, cached until its inputs change."""
        key = (spec.role, spec.model, spec.stateful, spec.thread,
               hash(spec.system_prompt), config.api_key()[-6:],
               tuple(t.name for t in spec.tools))
        with self._lock:
            if key in self._graphs:
                return self._graphs[key]

        from langchain_core.messages.utils import (count_tokens_approximately,
                                                  trim_messages)
        from langchain_openai import ChatOpenAI
        from langgraph.prebuilt import create_react_agent

        model = ChatOpenAI(
            model=spec.model, api_key=config.api_key(),
            base_url=OPENROUTER_URL, timeout=REQUEST_TIMEOUT,
            default_headers={"HTTP-Referer": "https://github.com/auto-dm",
                             "X-Title": "Auto-DM"})

        budget = int(config.load().get("history_tokens") or HISTORY_TOKENS)

        def keep_recent(state):
            """Trim history to the token budget without orphaning a tool result,
            then place the rolling cache breakpoints.

            Hysteresis, not a hard ceiling: trimming every call moves the window
            forward a little each turn, which changes the prompt prefix and voids
            the provider's prompt cache on the entire history. Instead history
            grows untouched until it exceeds the budget, then gets cut hard to
            half — one cache re-write, then a long stable stretch.

            end_on=("human","tool") plus start_on="human" is what keeps every
            tool message attached to the assistant turn that requested it — a
            dangling tool result is a 400 from every provider.
            """
            messages = state["messages"]
            if count_tokens_approximately(messages) > budget:
                messages = trim_messages(
                    messages, max_tokens=budget // 2,
                    token_counter=count_tokens_approximately,
                    strategy="last", start_on="human", end_on=("human", "tool"),
                    include_system=False, allow_partial=False)
            return {"llm_input_messages": mark_cache(messages)}

        # A consult is one-shot, so there is nothing to trim — but it gets the
        # same rolling breakpoints: a consult that reads five entity files
        # re-sends them on every step, and repeat consults of the same role
        # inside the cache TTL start from a warm system prompt.
        hook = keep_recent if spec.stateful else (
            lambda state: {"llm_input_messages": mark_cache(state["messages"])})

        graph = create_react_agent(
            model, spec.callables, prompt=cached_system(spec.system_prompt),
            pre_model_hook=hook,
            checkpointer=self._checkpointer() if spec.stateful else None)
        with self._lock:
            self._graphs[key] = graph
        return graph

    # ── running ──────────────────────────────────────────────────────────────

    def _heal(self, graph, spec: AgentSpec) -> None:
        """Answer tool calls left dangling by a killed app.

        A turn interrupted mid-tool leaves an AIMessage's tool_calls without
        ToolMessages, which bricks the thread: the provider requires results
        immediately after the calling message. Heal by writing synthetic
        results AS the tools node — that supersedes the graph's pending tasks
        in a new checkpoint, so the run resumes clean. (No RemoveMessage
        surgery: deleting around pending task writes is what used to re-brick
        the thread.)
        """
        from langchain_core.messages import ToolMessage
        run_config = self._run_config(spec)
        history = (graph.get_state(run_config).values or {}).get("messages") or []
        answered = {m.tool_call_id for m in history
                    if getattr(m, "tool_call_id", None)}
        unanswered = [tc for m in history
                      for tc in (getattr(m, "tool_calls", None) or [])
                      if tc["id"] not in answered]
        if not unanswered:
            return
        # Truthful, not "the tool never ran": run_tool mutates state BEFORE the
        # result is checkpointed, so a killed app may have applied the change
        # already. Telling the model it never ran invites a re-apply (that's
        # how a PC once took the same poison damage twice).
        graph.update_state(run_config, {"messages": [
            ToolMessage(content="(the app was closed mid-turn — this call was "
                                "interrupted and may or may not have taken "
                                "effect; re-read campaign state before redoing "
                                "any state change)",
                        tool_call_id=tc["id"])
            for tc in unanswered
        ]}, as_node="tools")

    def run(self, spec: AgentSpec, message: str) -> str:
        if (reason := self.available()):
            raise BackendError(reason)
        from langchain_core.messages import HumanMessage

        graph = self._graph(spec)
        run_config = self._run_config(spec) if spec.stateful else {
            "recursion_limit": spec.turn_limit}
        if spec.stateful:
            self._heal(graph, spec)
        try:
            result = graph.invoke({"messages": [HumanMessage(content=message)]},
                                  config=run_config)
        except Exception as e:
            if type(e).__name__ == "GraphRecursionError":
                raise BackendError(
                    f"the {spec.role} got stuck — break the task into smaller "
                    "pieces") from e
            raise friendly(e, spec.model) from e
        return _final_text(result)


BACKEND = OpenRouterBackend
