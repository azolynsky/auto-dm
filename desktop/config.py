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

# The fallback for a role with no shipped default. There is deliberately no
# single "global model" setting: every role's model is picked individually.
FALLBACK_MODEL = "google/gemini-3.7-flash"

# Shown on the setup screen. Ids verified against openrouter.ai/api/v1/models —
# anything else can be typed in by hand, so this list never becomes a cage.
# Lineup picked by head-to-head DM stress tests (2026-08-18): rules judgment,
# dice honesty, secret-keeping, cost, and latency.
MODEL_CHOICES = [
    ("google/gemini-3.7-flash", "Gemini 3.7 Flash — recommended, fast live play"),
    ("~deepseek/deepseek-v4-flash-latest", "DeepSeek V4 Flash — sharpest rulings, cheapest, slower"),
    ("openai/gpt-5.6-luna-pro", "GPT-5.6 Luna Pro — careful, costs more"),
    ("claude-cli:haiku", "Claude Code on this Mac: Haiku — fastest, no API cost"),
    ("claude-cli:sonnet", "Claude Code on this Mac: Sonnet — balanced, no API cost"),
    ("claude-cli:opus", "Claude Code on this Mac: Opus — strong judgment, slower"),
    ("claude-cli:fable", "Claude Code on this Mac: Fable — most capable, slowest"),
]

# A role model of "claude-cli:<alias>" runs that specialist through the
# `claude -p` CLI on this machine instead of OpenRouter — the user's own Claude
# subscription, no API spend. Specialist roles fit it exactly: one-shot task
# in, answer out, and Claude Code reads the campaign files itself. The dm
# orchestrator can't: it drives our own tools (dice, narrate, consult) through
# structured tool-calling, which `claude -p` has no way to hand back.
#
# Always name the model. A bare "claude-cli" still works for a hand-written
# config, but it passes no --model flag, so the role silently inherits whatever
# the machine's own Claude Code is set to (a `model` key in ~/.claude/
# settings.json, else the CLI default) — which changes under the app without
# warning. The picker offers only the explicit ids for that reason.
CLI_MODEL = "claude-cli"


def is_cli_model(model: str) -> bool:
    return str(model).split(":", 1)[0].strip() == CLI_MODEL


def cli_model_alias(model: str) -> str | None:
    """The `--model` alias in a claude-cli id, or None for the CLI default."""
    parts = str(model).split(":", 1)
    return parts[1].strip() or None if len(parts) == 2 else None


# Developer knobs — hidden behind the #dev reveal in the app's Settings. Kept
# out of the players' Table Settings on purpose: these change how the DM is
# built, not how it plays.
DEV_DEFAULTS = {
    "prompts": {},            # {role: variant} — see desktop/prompts.py
    # {role: model id} — every role, including the dm orchestrator, has its own
    # model; a user's saved role_models entry overrides the default here.
    # Background roles take DeepSeek's judgment over its latency; LIVE-LOOP
    # roles stay fast because the table waits on them — measured 2026-08-19:
    # DeepSeek director consults ran 60-180s/beat vs ~half that on Gemini
    # flash. The narrator moved into the live loop the same day (it now writes
    # every beat, no more inline DM prose), and re-measured on the same scene
    # it was 11.7s on flash vs 27-276s on DeepSeek with no drop in prose
    # quality — the 2026-08-18 bake-off that picked DeepSeek predates both the
    # pre-read brief and the mechanics style gate. Prose roles that still run
    # off the clock (prose-editor, session-prep) keep DeepSeek.
    "role_models": {
        "dm": FALLBACK_MODEL,
        "narrator": FALLBACK_MODEL,
        "director": FALLBACK_MODEL,
        "rules-lawyer": FALLBACK_MODEL,
        "bookkeeper": "~deepseek/deepseek-v4-flash-latest",
        "continuity-checker": "~deepseek/deepseek-v4-flash-latest",
        "session-prep": "~deepseek/deepseek-v4-flash-latest",
        "prose-editor": "google/gemini-3.7-flash",
    },
    "history_tokens": 120_000,
    "recursion_limit": 80,
}


def dev_settings() -> dict:
    cfg = load()
    settings = {k: cfg.get(k, default) for k, default in DEV_DEFAULTS.items()}
    # Effective per-role models: shipped defaults under the user's picks, so the
    # dev panel shows what each role will actually run on.
    settings["role_models"] = {**DEV_DEFAULTS["role_models"],
                               **(cfg.get("role_models") or {})}
    return settings


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


def role_model(role: str) -> str:
    """The model one role runs on: the user's pick, else the shipped default."""
    cfg = load()
    picked = ((cfg.get("role_models") or {}).get(role)
              # A config from before per-role models had one global "model" key;
              # honour it for the dm so an existing install keeps its choice.
              or (cfg.get("model") if role == "dm" else None)
              or DEV_DEFAULTS["role_models"].get(role)
              or FALLBACK_MODEL)
    if role == "dm" and is_cli_model(picked):
        # Saved by hand or carried over from a role swap — don't boot broken.
        return FALLBACK_MODEL
    return picked


def model() -> str:
    """The DM orchestrator's model — role_models["dm"].

    AUTODM_MODEL mirrors OPENROUTER_API_KEY: an env override so tools like
    tools/sandbox.py can pit models against each other without touching config.
    """
    return os.environ.get("AUTODM_MODEL") or role_model("dm")


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
