#!/usr/bin/env python3
"""
Where the desktop app keeps its two pieces of state: the OpenRouter key and
the player's campaign.

In the repo, the campaign lives at <repo>/campaign. In an installed app the
bundle is read-only, so both move to the OS's per-user app directory. Nothing
here knows anything about a particular campaign.
"""
from __future__ import annotations

import json
import os
import shutil
import sys
from pathlib import Path

# Reference content (rules/, .claude/, tools/, campaigns/starter/, CLAUDE.md) is
# read from the PyInstaller bundle when frozen, else from the repo checkout.
BUNDLE = Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parent.parent))

APP_NAME = "Auto-DM"


def norm_path(path: str) -> str:
    """Strip a leading './' without eating the dot of a dotted path.

    str.lstrip('./') would turn '.claude/agents/narrator.md' into
    'claude/agents/narrator.md', because lstrip takes a character set.
    """
    p = path.strip()
    while p.startswith("./"):
        p = p[2:]
    return p


def app_dir() -> Path:
    if sys.platform == "darwin":
        base = Path.home() / "Library" / "Application Support"
    elif os.name == "nt":
        base = Path(os.environ.get("APPDATA", Path.home() / "AppData" / "Roaming"))
    else:
        base = Path(os.environ.get("XDG_DATA_HOME", Path.home() / ".local" / "share"))
    return base / APP_NAME


APP_DIR = app_dir()
CONFIG_FILE = APP_DIR / "config.json"
# Honour an explicit CAMPAIGN_ROOT (tests, multiple tables, running from a
# checkout) exactly like tools/campaign_lib.py does.
CAMPAIGN = Path(os.environ["CAMPAIGN_ROOT"]) if os.environ.get("CAMPAIGN_ROOT") \
    else APP_DIR / "campaign"

DEFAULT_MODEL = "anthropic/claude-sonnet-5"

# Shown on the setup screen. Ids verified against openrouter.ai/api/v1/models —
# anything else can be typed in by hand, so this list never becomes a cage.
MODEL_CHOICES = [
    ("anthropic/claude-sonnet-5", "Claude Sonnet 5 — recommended, best balance"),
    ("anthropic/claude-opus-5", "Claude Opus 5 — sharpest DM, costs more"),
    ("anthropic/claude-haiku-4.5", "Claude Haiku 4.5 — cheapest, simpler scenes"),
    ("google/gemini-3.1-pro-preview", "Gemini 3.1 Pro"),
    ("openai/gpt-5.2", "GPT-5.2"),
]


# Developer knobs — hidden behind the #dev reveal in the app's Settings. Kept
# out of the players' Table Settings on purpose: these change how the DM is
# built, not how it plays.
DEV_DEFAULTS = {
    "model": DEFAULT_MODEL,
    "prompts": {},            # {role: variant} — see desktop/prompts.py
    "history_tokens": 120_000,
    "recursion_limit": 80,
}


def dev_settings() -> dict:
    cfg = load()
    return {k: cfg.get(k, default) for k, default in DEV_DEFAULTS.items()}


def load() -> dict:
    try:
        return json.loads(CONFIG_FILE.read_text(encoding="utf-8"))
    except Exception:
        return {}


def save(**fields) -> dict:
    cfg = load()
    cfg.update({k: v for k, v in fields.items() if v is not None})
    APP_DIR.mkdir(parents=True, exist_ok=True)
    CONFIG_FILE.write_text(json.dumps(cfg, indent=2) + "\n", encoding="utf-8")
    # The file holds an API key: keep it owner-only.
    try:
        CONFIG_FILE.chmod(0o600)
    except OSError:
        pass
    return cfg


def api_key() -> str:
    return os.environ.get("OPENROUTER_API_KEY") or load().get("api_key", "")


def model() -> str:
    return load().get("model") or DEFAULT_MODEL


def is_ready() -> bool:
    """True once the app has a key and a campaign with a seated party — i.e.
    setup is done. ensure_campaign() recreates the campaign files at every
    boot, so their existence alone can't mean setup ran; an unseated party is
    the mark of a table that hasn't picked its heroes yet."""
    if not api_key():
        return False
    try:
        current = json.loads(
            (CAMPAIGN / "state" / "current.json").read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return False
    return bool(current.get("party"))


def ensure_campaign() -> Path:
    """Create the campaign from the bundled starter template on first launch."""
    if (CAMPAIGN / "state" / "current.json").exists():
        return CAMPAIGN
    template = BUNDLE / "campaigns" / "starter"
    if not (template / "state" / "current.json").exists():
        raise SystemExit(f"starter template missing from the bundle: {template}")
    CAMPAIGN.parent.mkdir(parents=True, exist_ok=True)
    shutil.copytree(template, CAMPAIGN)
    return CAMPAIGN


def set_campaign_name(name: str) -> None:
    path = CAMPAIGN / "state" / "current.json"
    current = json.loads(path.read_text(encoding="utf-8"))
    current["campaign"] = name
    path.write_text(json.dumps(current, indent=2, ensure_ascii=False) + "\n",
                    encoding="utf-8")
