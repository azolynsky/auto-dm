#!/usr/bin/env python3
"""
The claude-cli backend: literally `claude -p`, on the Claude login this machine
already has.

One subprocess per exchange. The role's prompt file becomes `--system-prompt`
and the task (pre-read brief included) the prompt argument, so a role runs
identically here and on OpenRouter and can be switched either way without
touching prompts.

The campaign tools reach it over a stdio MCP server (tools/mcp_server.py),
scoped to the role by AUTODM_ROLE. That is what lets the orchestrator run here
at all: `claude -p` has no way to hand a tool call back to this process, but it
speaks MCP, and MCP is a tool channel. Built-in file and shell tools are denied
outright — the campaign tools carry the guardrails, and Claude Code's own Read
would walk straight past the motivations firewall.
"""
from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import uuid
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import config  # noqa: E402

from .base import AgentSpec, Backend, BackendError  # noqa: E402

CONSULT_TIMEOUT = 300
DM_TIMEOUT = 900

# Claude Code's own tools, all refused. Every capability a role needs arrives
# through the campaign MCP server instead, which is where the firewalls are.
BUILTINS_DENIED = ["Bash", "Read", "Write", "Edit", "NotebookEdit", "Glob",
                   "Grep", "WebFetch", "WebSearch", "Task", "TodoWrite"]

MCP_NAME = "campaign"


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


def mcp_command() -> list[str]:
    """How to launch the campaign MCP server as a child process.

    A frozen app has no python interpreter to hand a script to — sys.executable
    is the app binary — so it re-executes itself with the flag desktop/app.py
    dispatches on.
    """
    if getattr(sys, "frozen", False):
        return [sys.executable, "--mcp-server"]
    return [sys.executable, str(config.BUNDLE / "tools" / "mcp_server.py")]


def mcp_config(role: str) -> str:
    """The --mcp-config payload: one stdio server, scoped to this role."""
    command, *args = mcp_command()
    return json.dumps({"mcpServers": {MCP_NAME: {
        "type": "stdio",
        "command": command,
        "args": args,
        "env": {"CAMPAIGN_ROOT": str(config.CAMPAIGN),
                "AUTODM_BUNDLE": str(config.BUNDLE),
                "AUTODM_ROLE": role,
                "PATH": os.environ.get("PATH", "")},
    }}})


class ClaudeCliBackend(Backend):
    name = "claude-cli"
    label = "Claude Code on this Mac (CLI)"
    supports_dm = True

    def available(self) -> str | None:
        if not claude_binary():
            return ("Claude Code isn't installed on this machine (or the app "
                    "can't see it) — install it, or pick an API model in "
                    "Settings.")
        return None

    # ── history ──────────────────────────────────────────────────────────────
    # The CLI keeps the transcript; we only keep the id that names it. Held in
    # a campaign state file rather than memory so closing the app doesn't lose
    # the session, matching what the OpenRouter checkpoint gives.

    def _session_file(self, spec: AgentSpec) -> Path:
        return config.CAMPAIGN / "state" / f"claude-cli-{spec.thread}.json"

    def _session_id(self, spec: AgentSpec) -> str | None:
        try:
            return json.loads(self._session_file(spec)
                              .read_text(encoding="utf-8")).get("session_id")
        except (OSError, ValueError):
            return None

    def is_fresh(self, spec: AgentSpec) -> bool:
        return not (spec.stateful and self._session_id(spec))

    def reset(self, spec: AgentSpec) -> None:
        self._session_file(spec).unlink(missing_ok=True)

    # ── running ──────────────────────────────────────────────────────────────

    def run(self, spec: AgentSpec, message: str) -> str:
        binary = claude_binary()
        if not binary:
            raise BackendError(self.available() or "claude CLI not found")

        allowed = [f"mcp__{MCP_NAME}__{t.name}" for t in spec.tools]
        cmd = [binary, "-p", message,
               "--system-prompt", spec.system_prompt,
               "--output-format", "text",
               # An explicit allow-list plus a deny-list, so a non-interactive
               # run never blocks on a permission prompt and never gets more
               # reach than the role needs.
               "--allowed-tools", " ".join(allowed),
               "--disallowed-tools", " ".join(BUILTINS_DENIED),
               # Our server only. Without this the run also inherits whatever
               # MCP servers the user has configured for their own Claude Code,
               # which is someone else's tool surface inside our game.
               "--strict-mcp-config"]
        if spec.tools:
            cmd += ["--mcp-config", mcp_config(spec.role)]
        if spec.model:
            cmd += ["--model", spec.model]

        resumed = self._session_id(spec) if spec.stateful else None
        session_id = resumed or str(uuid.uuid4())
        if spec.stateful:
            cmd += ["--resume", session_id] if resumed \
                else ["--session-id", session_id]

        timeout = DM_TIMEOUT if spec.stateful else CONSULT_TIMEOUT
        try:
            done = subprocess.run(cmd, capture_output=True, text=True,
                                  timeout=timeout, cwd=str(config.BUNDLE))
        except FileNotFoundError as e:
            raise BackendError(
                "the claude CLI isn't on this machine's PATH — install Claude "
                "Code or switch this role to an API model in Settings.") from e
        except subprocess.TimeoutExpired as e:
            raise BackendError(f"the local claude CLI took over {timeout}s on "
                               f"the {spec.role} and was stopped.") from e

        out = (done.stdout or "").strip()
        if done.returncode != 0 or not out:
            detail = (done.stderr or "").strip()[:300] or f"exit {done.returncode}"
            raise BackendError(f"the local claude CLI failed on the "
                               f"{spec.role}: {detail}")
        if spec.stateful and not resumed:
            # Only after a run that actually succeeded: recording the id for a
            # session the CLI never created would make every later turn try to
            # resume nothing.
            path = self._session_file(spec)
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(json.dumps({"session_id": session_id}) + "\n",
                            encoding="utf-8")
        return out


BACKEND = ClaudeCliBackend
