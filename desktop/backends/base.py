#!/usr/bin/env python3
"""
What a backend is, and what it gets handed.

A backend runs an agent loop: system prompt in, tool calls out, final text
back. Which model it thinks with, and whether that costs OpenRouter credit or
rides your Claude subscription, is the backend's business and nobody else's.
See docs/backends.md for the contract this file implements.

Deliberately free of app imports so config.py can name the registry without a
cycle.
"""
from __future__ import annotations

import inspect
import types
import typing
from abc import ABC, abstractmethod
from collections.abc import Callable
from dataclasses import dataclass, field

# ── Tools ─────────────────────────────────────────────────────────────────────
# The same Python function reaches a model three ways: bound directly into a
# LangGraph node, wrapped in an in-process MCP server for the Agent SDK, or
# served over a stdio pipe to the `claude` CLI. Only the schema needs deriving;
# the docstring is already the usage contract.

_SCALARS = {str: "string", int: "integer", float: "number", bool: "boolean"}


def _type_schema(annotation) -> dict:
    """JSON Schema for one parameter's annotation.

    Covers what the tool surface actually uses: scalars, list[str], and
    `X | None`. An unrecognised annotation degrades to a string rather than
    raising — a tool that takes an odd argument is still better than a tool
    the model can't see at all.
    """
    origin = typing.get_origin(annotation)
    if origin in (typing.Union, types.UnionType):
        inner = [a for a in typing.get_args(annotation) if a is not type(None)]
        return _type_schema(inner[0]) if len(inner) == 1 else {"type": "string"}
    if origin in (list, tuple):
        args = typing.get_args(annotation)
        return {"type": "array", "items": _type_schema(args[0]) if args
                else {"type": "string"}}
    if annotation is dict or origin is dict:
        return {"type": "object"}
    return {"type": _SCALARS.get(annotation, "string")}


@dataclass(frozen=True)
class ToolSpec:
    """One campaign tool, in a form any backend can bind."""

    name: str
    description: str
    schema: dict
    fn: Callable

    @classmethod
    def of(cls, fn: Callable) -> ToolSpec:
        """Derive a spec from the function itself.

        Name, docstring and signature are the single source of truth, so a
        tool never drifts from the schema three backends advertise for it.
        `_logged` wraps every tool with functools.wraps, which is what keeps
        the signature and docstring readable through the decorator.
        """
        hints = typing.get_type_hints(fn)
        props: dict = {}
        required: list[str] = []
        for name, param in inspect.signature(fn).parameters.items():
            props[name] = _type_schema(hints.get(name, str))
            if param.default is inspect.Parameter.empty:
                required.append(name)
        return cls(
            name=fn.__name__,
            description=inspect.cleandoc(fn.__doc__ or fn.__name__),
            schema={"type": "object", "properties": props,
                    "required": required, "additionalProperties": False},
            fn=fn,
        )


# ── The spec a backend runs ───────────────────────────────────────────────────

@dataclass(frozen=True)
class AgentSpec:
    """One configured agent: a role, its model, its prompt, its tools.

    A specialist consult and a DM turn differ only here, which is why one
    `run()` serves both: a consult is `stateful=False` with a role's tool
    subset, the orchestrator is `stateful=True` with the whole surface.
    """

    role: str
    model: str                 # backend-local id, prefix already stripped
    system_prompt: str
    tools: tuple[ToolSpec, ...] = ()
    turn_limit: int = 32       # tool round trips before giving up
    stateful: bool = False     # keep history across run() calls
    thread: str = "dm"         # which conversation, when stateful

    @property
    def callables(self) -> list[Callable]:
        return [t.fn for t in self.tools]


class BackendError(RuntimeError):
    """A backend couldn't run — carries text safe to show at the table."""


class Backend(ABC):
    """Runs an agent loop. One instance per process; `run` must be reentrant.

    Reentrancy is not optional: `consult_pair` fires two specialists from two
    threads, and both may land on the same backend.
    """

    name: str = ""          # registry key, and the model-id prefix
    label: str = ""         # what the settings picker shows
    supports_dm: bool = False

    def available(self) -> str | None:
        """None when ready to run, else a sentence naming the fix."""
        return None

    @abstractmethod
    def run(self, spec: AgentSpec, message: str) -> str:
        """Run one exchange and return the final assistant text.

        Called again on the same `stateful=True` spec, it continues that
        conversation — which is what the never-narrated fallback nudge needs.
        """

    def is_fresh(self, spec: AgentSpec) -> bool:
        """True when this conversation has no history yet.

        The caller sends the session brief on a fresh thread and skips it
        otherwise, so this is the one thing it needs to know about a history
        it deliberately doesn't own.
        """
        return True

    def reset(self, spec: AgentSpec) -> None:
        """Forget a stateful conversation. No-op where there is none."""


# ── Registry data ─────────────────────────────────────────────────────────────
# Names, labels, and DM support live here as data so config.py can build the
# settings picker without importing any implementation (and so importing
# config never drags in langgraph or the Agent SDK).

@dataclass(frozen=True)
class BackendInfo:
    name: str
    label: str
    module: str
    supports_dm: bool
    subscription: bool = False   # rides the user's Claude login, not credit
    aliases: tuple[str, ...] = field(default_factory=tuple)


BACKENDS: tuple[BackendInfo, ...] = (
    BackendInfo("openrouter", "OpenRouter", "openrouter", supports_dm=True),
    BackendInfo("claude-cli", "Claude Code on this Mac (CLI)", "claude_cli",
                supports_dm=True, subscription=True),
    BackendInfo("claude-agent", "Claude Code on this Mac (SDK)", "claude_agent",
                supports_dm=True, subscription=True),
)

DEFAULT_BACKEND = "openrouter"

_BY_NAME = {info.name: info for info in BACKENDS}


def parse_model(model_id: str) -> tuple[str, str]:
    """Split a configured id into (backend name, backend-local model).

    Splits on the FIRST colon and only accepts the head if it names a
    registered backend — so an OpenRouter id that carries its own colon
    (`deepseek/deepseek-v4-flash-latest:free`) stays intact, and a bare id
    still means OpenRouter.

        parse_model("claude-agent:opus")      -> ("claude-agent", "opus")
        parse_model("google/gemini-3.7-flash") -> ("openrouter", "google/...")
        parse_model("claude-cli")             -> ("claude-cli", "")
    """
    head, _, tail = str(model_id or "").strip().partition(":")
    if head in _BY_NAME:
        return head, tail.strip()
    return DEFAULT_BACKEND, str(model_id or "").strip()


def info(name: str) -> BackendInfo | None:
    return _BY_NAME.get(name)
