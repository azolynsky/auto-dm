#!/usr/bin/env python3
"""
The prompt registry — resolves which prompt text each role runs on.

Content lives in prompts/ (see prompts/README.md). Selection lives in the app
config under "prompts": {role: variant}, editable from the Developer section of
Settings, so a variant can be A/B tested without touching code.

Resolution:
  dm     — prompts/dm/<variant>.md, prepended to CLAUDE.md. No fallback.
  others — prompts/<role>/<variant>.md if it exists, else the shipped
           .claude/agents/<role>.md. So .claude/agents/ stays the single source
           of truth until someone actually wants an alternative.
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import config  # noqa: E402

PROMPTS_DIR = config.BUNDLE / "prompts"
AGENTS_DIR = config.BUNDLE / ".claude" / "agents"

# "dm" is this harness's own adapter; the rest mirror .claude/agents/*.md.
ROLES = ("dm", "director", "narrator", "rules-lawyer", "bookkeeper",
         "continuity-checker", "session-prep", "prose-editor")

DEFAULT_VARIANT = "default"


def variants(role: str) -> list[str]:
    """Selectable variants for a role. 'default' first; it always exists."""
    found = sorted(p.stem for p in (PROMPTS_DIR / role).glob("*.md"))
    if role != "dm" and DEFAULT_VARIANT not in found:
        found.insert(0, DEFAULT_VARIANT)  # the .claude/agents/ original
    elif DEFAULT_VARIANT in found:
        found.remove(DEFAULT_VARIANT)
        found.insert(0, DEFAULT_VARIANT)
    return found


def selected(role: str) -> str:
    return (config.load().get("prompts") or {}).get(role) or DEFAULT_VARIANT


def resolve(role: str) -> Path:
    """The prompt file this role should actually run on."""
    if role not in ROLES:
        raise ValueError(f"unknown role: {role}")
    variant = PROMPTS_DIR / role / f"{selected(role)}.md"
    if variant.exists():
        return variant
    fallback = PROMPTS_DIR / role / f"{DEFAULT_VARIANT}.md"
    if fallback.exists():
        return fallback
    if role == "dm":
        raise FileNotFoundError(f"no dm prompt found in {PROMPTS_DIR / 'dm'}")
    return AGENTS_DIR / f"{role}.md"


AGENT_PATH = re.compile(r"^\.claude/agents/([a-z-]+)\.md$")


def override_for(path: str) -> Path | None:
    """Redirect a read of .claude/agents/<role>.md to the selected variant.

    The DM asks for the path the manual documents and gets the variant's bytes
    back, so nothing in the manual has to know an A/B test is running.
    """
    match = AGENT_PATH.match(config.norm_path(path))
    if not match:
        return None
    role = match.group(1)
    if role not in ROLES or selected(role) == DEFAULT_VARIANT:
        return None
    resolved = resolve(role)
    return resolved if resolved.is_relative_to(PROMPTS_DIR) else None


def registry() -> list[dict]:
    """What the Developer settings panel renders."""
    return [{"role": r, "selected": selected(r), "variants": variants(r),
             "source": str(resolve(r).relative_to(config.BUNDLE))} for r in ROLES]


if __name__ == "__main__":
    for entry in registry():
        print(f"{entry['role']:20} {entry['selected']:12} "
              f"{','.join(entry['variants']):28} → {entry['source']}")
