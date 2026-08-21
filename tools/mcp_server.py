#!/usr/bin/env python3
"""
The campaign tools as an MCP server, over stdio.

This is how a Claude that isn't inside the desktop app reaches the table: the
`claude-cli` backend points `claude -p --mcp-config` at it, and so can any
other MCP client — an interactive `claude` in a terminal, Codex, another
harness. CLAUDE.md promises the campaign is portable across LLMs; this is that
promise with a socket on it.

    # one-off, against the repo campaign
    python tools/mcp_server.py

    # registered for a terminal claude
    claude mcp add campaign -- python tools/mcp_server.py

Environment:
    CAMPAIGN_ROOT   which campaign to serve (same as every other tool here)
    AUTODM_ROLE     serve only that role's tools; omit for the full surface
    AUTODM_BUNDLE   repo/bundle root, if this file has been moved away from it

The role scoping is the point of AUTODM_ROLE, not a convenience: a narrator
served the full surface could read motivations.md and publish its own prose.
Served its own subset it gets the firewalled read and no publishing tool, which
is the same guarantee the in-process backends give.
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

BUNDLE = Path(os.environ.get("AUTODM_BUNDLE")
              or Path(__file__).resolve().parent.parent)
sys.path.insert(0, str(BUNDLE / "desktop"))

import agent  # noqa: E402
import campaign_tools  # noqa: E402
import config  # noqa: E402
import prompts  # noqa: E402
from backends.base import ToolSpec  # noqa: E402


def tool_specs(role: str | None) -> list[ToolSpec]:
    """The tools to serve: one role's subset, or the whole DM surface.

    The DM surface includes consult_role and consult_pair, and it has to: an
    orchestrator that can't reach its specialists can't consult the narrator,
    so it can't publish a beat — the gate refuses prose that didn't come from
    the Narrator. Serving it the file tools alone produced a DM that argued
    with the gate and got its own complaint published.

    Those two run the backends, so serving them here means this process runs
    them: a specialist on `claude-cli` spawns its own `claude` and its own copy
    of this server, one level down. Bounded at that — specialists don't
    consult.
    """
    if role:
        return [ToolSpec.of(fn) for fn in campaign_tools.role_tools(role)]
    return [ToolSpec.of(fn) for fn in agent.DM_TOOLS]


def build_server(role: str | None = None):
    from mcp.server.fastmcp import FastMCP

    label = f"the {role}" if role else "the DM"
    server = FastMCP(
        name="campaign",
        # Per-request INFO lines go to stderr, which the parent captures and
        # shows the table if the run fails — one "Processing request" line per
        # tool call buries the actual error.
        log_level="WARNING",
        instructions=(
            f"The live D&D campaign at {config.CAMPAIGN}, served for {label}. "
            "Paths are repo-relative (campaign/state/current.json, "
            "rules/srd-reference.md). Every random outcome must go through "
            "run_tool('dice.py', ...) — never decide a roll yourself."),
    )
    for spec in tool_specs(role):
        # FastMCP derives the schema from the signature, which is the same
        # source ToolSpec.of reads, so both paths advertise one contract.
        server.add_tool(spec.fn, name=spec.name, description=spec.description)
    return server


def main() -> int:
    role = os.environ.get("AUTODM_ROLE") or None
    if role and role not in prompts.ROLES:
        print(f"unknown AUTODM_ROLE: {role}", file=sys.stderr)
        return 2
    if not config.CAMPAIGN.exists():
        # stderr, not stdout: stdout is the protocol stream.
        print(f"no campaign at {config.CAMPAIGN} — set CAMPAIGN_ROOT",
              file=sys.stderr)
        return 2
    build_server(None if role == "dm" else role).run(transport="stdio")
    return 0


if __name__ == "__main__":
    sys.exit(main())
