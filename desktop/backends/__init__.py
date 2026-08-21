#!/usr/bin/env python3
"""
The backend registry — name to running instance.

    from backends import for_role
    backend, model = for_role("narrator")

Implementations are imported lazily, on first use of that backend. Two reasons:
importing config must never drag in langgraph or the Agent SDK, and a table
that runs everything on its Claude subscription shouldn't pay OpenRouter's
import cost at startup (or vice versa).

config is imported lazily too, for a third reason: config reads the registry
data in .base to build its settings picker, so a module-level import here would
close the loop.
"""
from __future__ import annotations

import importlib
import sys
import threading
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from .base import (BACKENDS, AgentSpec, Backend,  # noqa: E402,F401
                   BackendError, ToolSpec, info, parse_model)

_instances: dict[str, Backend] = {}
_lock = threading.Lock()


def get(name: str) -> Backend:
    """The backend registered under `name`, instantiated once per process."""
    spec = info(name)
    if spec is None:
        known = ", ".join(b.name for b in BACKENDS)
        raise BackendError(f"unknown backend {name!r} — known: {known}")
    with _lock:
        if name not in _instances:
            module = importlib.import_module(f"backends.{spec.module}")
            _instances[name] = module.BACKEND()
        return _instances[name]


def for_role(role: str) -> tuple[Backend, str]:
    """The backend and model one role runs on, per the user's config."""
    import config
    name, model = parse_model(config.role_model(role))
    return get(name), model


def availability() -> dict[str, str | None]:
    """Per-backend readiness, for the settings panel: None means ready.

    Instantiating a backend to ask is the point — a backend that can't even
    import (missing dependency) reports that as its reason rather than
    breaking the panel.
    """
    out: dict[str, str | None] = {}
    for spec in BACKENDS:
        try:
            out[spec.name] = get(spec.name).available()
        except Exception as e:  # noqa: BLE001 — a broken backend is a status
            out[spec.name] = f"unavailable: {type(e).__name__}: {e}"
    return out
