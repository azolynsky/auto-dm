#!/usr/bin/env python3
"""
The Claude backend: the `claude` binary this machine already has, driven through
claude-agent-sdk so the campaign tools live in-process.

The same login and the same models as running `claude -p` by hand — no API key
is read and none is needed. What the library form adds is a tool channel that
doesn't leave the process: a tool call is a Python call, not a pipe round trip
to a separate MCP server, so the activity labels and dev-log entries the tools
already write land exactly as they do on the OpenRouter path.

One `claude` process per exchange, about 2-3s. Holding a live ClaudeSDKClient
open between turns would save that, at the cost of a long-lived subprocess per
role; it is the upgrade if start-up ever shows up next to a model call, which
against a 10-50s consult it doesn't.
"""
from __future__ import annotations

import asyncio
import json
import shutil
import sys
import threading
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import config  # noqa: E402

from .base import AgentSpec, Backend, BackendError, ToolSpec  # noqa: E402

MCP_NAME = "campaign"
RUN_TIMEOUT = 900


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


def _sync(coro):
    """Run a coroutine from sync code, whatever thread we're on.

    consult_pair calls two specialists from two threads, and either may land
    here. A thread with no event loop can use asyncio.run directly; one that
    already has a loop running needs a thread of its own, because asyncio.run
    refuses to nest.
    """
    try:
        asyncio.get_running_loop()
    except RuntimeError:
        return asyncio.run(coro)

    box: dict = {}

    def target() -> None:
        try:
            box["value"] = asyncio.run(coro)
        except BaseException as e:  # noqa: BLE001 — re-raised on the caller
            box["error"] = e
    worker = threading.Thread(target=target, daemon=True)
    worker.start()
    worker.join()
    if "error" in box:
        raise box["error"]
    return box.get("value")


def _sdk_tool(spec: ToolSpec):
    """Wrap one campaign tool as an SDK MCP tool.

    The name, description and schema come from the ToolSpec, so the model sees
    the same contract here as on every other backend. The implementation is
    synchronous and does real file work, so it runs on a worker thread rather
    than blocking the event loop that is also reading the CLI's output.
    """
    from claude_agent_sdk import tool

    @tool(spec.name, spec.description, spec.schema)
    async def handler(args: dict) -> dict:
        try:
            result = await asyncio.to_thread(spec.fn, **(args or {}))
        except Exception as e:  # noqa: BLE001
            # A raised exception would kill the in-process server; the tools
            # return error strings for everything they expect, so anything
            # landing here is a bug worth telling the model about verbatim.
            result = f"error: {type(e).__name__}: {e}"
        return {"content": [{"type": "text", "text": str(result)}]}

    return handler


class ClaudeAgentBackend(Backend):
    name = "claude-agent"

    def available(self) -> str | None:
        try:
            import claude_agent_sdk  # noqa: F401
        except ImportError:
            return ("The Claude Agent SDK isn't installed — run "
                    "`pip install claude-agent-sdk`, or pick another model in "
                    "Settings.")
        if not claude_binary():
            return ("Claude Code isn't installed on this machine (or the app "
                    "can't see it) — install it, or pick an API model in "
                    "Settings.")
        return None

    # ── history ──────────────────────────────────────────────────────────────
    # Claude Code owns the transcript; we keep the id that names it, in a
    # campaign state file so closing the app doesn't lose the session.

    def _session_file(self, spec: AgentSpec) -> Path:
        return config.CAMPAIGN / "state" / f"claude-agent-{spec.thread}.json"

    def _session_id(self, spec: AgentSpec) -> str | None:
        try:
            return json.loads(self._session_file(spec)
                              .read_text(encoding="utf-8")).get("session_id")
        except (OSError, ValueError):
            return None

    def _remember(self, spec: AgentSpec, session_id: str) -> None:
        path = self._session_file(spec)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps({"session_id": session_id}) + "\n",
                        encoding="utf-8")

    def is_fresh(self, spec: AgentSpec) -> bool:
        return not (spec.stateful and self._session_id(spec))

    def reset(self, spec: AgentSpec) -> None:
        self._session_file(spec).unlink(missing_ok=True)

    # ── running ──────────────────────────────────────────────────────────────

    def _options(self, spec: AgentSpec):
        from claude_agent_sdk import ClaudeAgentOptions, create_sdk_mcp_server

        server = create_sdk_mcp_server(
            name=MCP_NAME, version="1.0.0",
            tools=[_sdk_tool(t) for t in spec.tools])
        resume = self._session_id(spec) if spec.stateful else None
        return ClaudeAgentOptions(
            system_prompt=spec.system_prompt,
            # No built-in tools at all. Every capability arrives through the
            # campaign server, which is where the guardrails and the
            # motivations firewall live — Claude Code's own Read would walk
            # straight past them.
            tools=[],
            mcp_servers={MCP_NAME: server},
            allowed_tools=[f"mcp__{MCP_NAME}__{t.name}" for t in spec.tools],
            # Nothing can prompt: the allow-list is the whole surface and the
            # table is not sitting at a terminal to answer.
            permission_mode="bypassPermissions",
            # Don't inherit the user's own CLAUDE.md, settings, or subagents —
            # this run is the game, not their working directory.
            setting_sources=None,
            model=spec.model or None,
            max_turns=spec.turn_limit,
            cwd=str(config.BUNDLE),
            add_dirs=[str(config.CAMPAIGN)],
            env={"CAMPAIGN_ROOT": str(config.CAMPAIGN)},
            cli_path=claude_binary(),
            resume=resume,
        )

    async def _run(self, spec: AgentSpec, message: str) -> str:
        from claude_agent_sdk import (AssistantMessage, ClaudeSDKClient,
                                      ResultMessage, TextBlock)

        chunks: list[str] = []
        session_id = None
        async with ClaudeSDKClient(options=self._options(spec)) as client:
            await client.query(message)
            async for msg in client.receive_response():
                if isinstance(msg, AssistantMessage):
                    chunks = [b.text for b in msg.content
                              if isinstance(b, TextBlock)]
                elif isinstance(msg, ResultMessage):
                    session_id = getattr(msg, "session_id", None)
        if spec.stateful and session_id:
            self._remember(spec, session_id)
        return "\n".join(c for c in chunks if c).strip()

    def run(self, spec: AgentSpec, message: str) -> str:
        if (reason := self.available()):
            raise BackendError(reason)
        try:
            return _sync(asyncio.wait_for(self._run(spec, message),
                                          timeout=RUN_TIMEOUT))
        except BackendError:
            raise
        except asyncio.TimeoutError as e:
            raise BackendError(f"the local Claude took over {RUN_TIMEOUT}s on "
                               f"the {spec.role} and was stopped.") from e
        except Exception as e:
            raise BackendError(f"local Claude failed on the {spec.role}: "
                               f"{type(e).__name__}: {str(e)[:300]}") from e


BACKEND = ClaudeAgentBackend
