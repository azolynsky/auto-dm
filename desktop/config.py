#!/usr/bin/env python3
"""
Where the desktop app keeps its two pieces of state: the OpenRouter key and
the player's campaigns (side by side under campaigns/<slug>/, with the
active one named in config.json).

In the repo, the campaign lives at <repo>/campaign. In an installed app the
bundle is read-only, so both move to the OS's per-user app directory. Nothing
here knows anything about a particular campaign.
"""
from __future__ import annotations

import json
import os
import shutil
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
# The registry table only — pure data, no implementation. Importing a backend
# from here would close a loop (backends read config to resolve a role's
# model), and would drag langgraph or the Agent SDK into every config read.
from backends import base as backends_base  # noqa: E402

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


def _load_config_file() -> dict:
    try:
        return json.loads(CONFIG_FILE.read_text(encoding="utf-8"))
    except Exception:
        return {}


# Campaigns live side by side under APP_DIR/campaigns/<slug>/; config.json's
# "campaign" key names the active one. The slug is internal and stable — the
# display name lives in each campaign's state/current.json ("campaign" field)
# and is set by the setup screen. Honour an explicit CAMPAIGN_ROOT (tests,
# running from a checkout) exactly like tools/campaign_lib.py does.
#
# CAMPAIGN is a per-process constant on purpose: the companion server, the DM
# agent thread, and the tools' env are all rooted in it at import/startup, so
# changing campaigns means relaunching the app (desktop/app.py does), never
# re-rooting a live process.
CAMPAIGN = Path(os.environ["CAMPAIGN_ROOT"]) if os.environ.get("CAMPAIGN_ROOT") \
    else APP_DIR / "campaigns" / (_load_config_file().get("campaign") or "table-1")

# The fallback for a role with no shipped default. There is deliberately no
# single "global model" setting: every role's model is picked individually.
FALLBACK_MODEL = "google/gemini-3.7-flash"

# Shown on the setup screen. OpenRouter ids verified against
# openrouter.ai/api/v1/models — anything else can be typed in by hand, so this
# list never becomes a cage. The OpenRouter lineup was picked by head-to-head
# DM stress tests (2026-08-18): rules judgment, dice honesty, secret-keeping,
# cost, and latency.
#
# An id of the form "<backend>:<model>" names where the role runs; the grammar
# and the backend table are in docs/backends.md. The claude-agent backend spawns
# the `claude` binary already installed on this machine and uses its own login,
# so it spends subscription usage rather than API credit — there is no
# Claude-over-API path here on purpose.
MODEL_CHOICES = [
    ("google/gemini-3.7-flash", "Gemini 3.7 Flash — recommended, fast live play"),
    ("~deepseek/deepseek-v4-flash-latest", "DeepSeek V4 Flash — sharpest rulings, cheapest, slower"),
    ("openai/gpt-5.6-luna-pro", "GPT-5.6 Luna Pro — careful, costs more"),
    ("claude-agent:haiku", "Claude on this Mac: Haiku — fastest, no API cost"),
    ("claude-agent:sonnet", "Claude on this Mac: Sonnet — balanced, no API cost"),
    ("claude-agent:opus", "Claude on this Mac: Opus — strong judgment, slower"),
    ("claude-agent:fable", "Claude on this Mac: Fable — most capable, slowest"),
]

# Always name the model. A bare "claude-agent" still resolves, but it passes no
# model flag, so the role silently inherits whatever the machine's own Claude
# Code is set to (a `model` key in ~/.claude/settings.json, else the CLI
# default) — which changes under the app without warning. The picker offers only
# the explicit ids for that reason.


def parse_model(model_id: str) -> tuple[str, str]:
    """(backend name, backend-local model) for a configured id."""
    return backends_base.parse_model(model_id)


def backend_of(model_id: str) -> str:
    return parse_model(model_id)[0]


def supports_dm(model_id: str) -> bool:
    """Can this id drive the orchestrator loop?

    Asked of the backend registry rather than hard-coded, so a backend with no
    way to hand a tool call back is kept out of the DM picker by construction
    instead of by a rule someone has to remember.
    """
    spec = backends_base.info(backend_of(model_id))
    return bool(spec and spec.supports_dm)


def on_subscription(model_id: str) -> bool:
    """True when this id runs on the machine's Claude login, not paid credit."""
    spec = backends_base.info(backend_of(model_id))
    return bool(spec and spec.subscription)


def model_choices(role: str | None = None) -> list:
    """The models a role can actually be set to.

    Offering the dm a backend that can't drive the loop would be offering a
    setting that cannot work: the setup screen would save it and role_model()
    would silently ignore it. Don't render the choice.
    """
    if role == "dm":
        return [(i, label) for i, label in MODEL_CHOICES if supports_dm(i)]
    return list(MODEL_CHOICES)


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
    return _load_config_file()


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
    if role == "dm" and not supports_dm(picked):
        # Saved by hand or carried over from a role swap — don't boot broken.
        return FALLBACK_MODEL
    return picked


def model() -> str:
    """The DM orchestrator's model — role_models["dm"].

    AUTODM_MODEL mirrors OPENROUTER_API_KEY: an env override so tools like
    tools/sandbox.py can pit models against each other without touching config.
    """
    return os.environ.get("AUTODM_MODEL") or role_model("dm")


def configured_roles() -> list[str]:
    """Every role with a model, shipped defaults plus the user's overrides.

    The authoritative role list lives in prompts.ROLES, which can't be imported
    here (prompts reads config). These keys are the same set in practice, and
    a role missing from both has no model to pay for anyway.
    """
    return sorted({*DEV_DEFAULTS["role_models"],
                   *(load().get("role_models") or {})})


def needs_api_key() -> bool:
    """Does this table need an OpenRouter key at all?

    Only if some role is set to spend credit. A table running entirely on the
    machine's Claude login has nothing to pay for and must not be asked for a
    key it doesn't have.
    """
    return any(not on_subscription(role_model(role))
               for role in configured_roles())


def is_ready() -> bool:
    """True once the app can run and has a campaign with a seated party — i.e.
    setup is done. ensure_campaign() recreates the campaign files at every
    boot, so their existence alone can't mean setup ran; an unseated party is
    the mark of a table that hasn't picked its heroes yet."""
    if needs_api_key() and not api_key():
        return False
    try:
        current = json.loads(
            (CAMPAIGN / "state" / "current.json").read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return False
    return bool(current.get("party"))


def campaigns_dir() -> Path:
    return APP_DIR / "campaigns"


def campaign_label(path: Path) -> str:
    """A campaign's display name, from its own state; the slug as fallback."""
    try:
        current = json.loads((path / "state" / "current.json").read_text(encoding="utf-8"))
        return str(current.get("campaign") or path.name)
    except (OSError, json.JSONDecodeError):
        return path.name


def list_campaigns() -> list[tuple[str, str]]:
    """(slug, display name) for every campaign on this machine."""
    root = campaigns_dir()
    return [(p.name, campaign_label(p))
            for p in (sorted(root.iterdir()) if root.is_dir() else [])
            if (p / "state" / "current.json").exists()]


def _starter_template() -> Path:
    template = BUNDLE / "campaigns" / "starter"
    if not (template / "state" / "current.json").exists():
        raise SystemExit(f"starter template missing from the bundle: {template}")
    return template


# ── World sources — the setup screen's "choose your world" ────────────────────

def list_world_templates() -> list[dict]:
    """Bundled prewritten worlds: every campaign directory under campaigns/.
    An optional template.json beside it ({name, blurb, order}) feeds its setup
    card and its place in the lineup; the directory name is the fallback."""
    root = BUNDLE / "campaigns"
    out = []
    for p in sorted(root.iterdir()) if root.is_dir() else []:
        if not (p / "state" / "current.json").exists():
            continue
        try:
            meta = json.loads((p / "template.json").read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            meta = {}
        try:
            order = int(meta.get("order", 99))
        except (TypeError, ValueError):
            order = 99
        out.append({"id": p.name,
                    "name": str(meta.get("name") or p.name.replace("-", " ").title()),
                    "blurb": str(meta.get("blurb") or ""),
                    "order": order})
    out.sort(key=lambda t: (t["order"], t["name"]))
    return out


def seed_campaign(source: Path) -> None:
    """Replace the active campaign's contents with a copy of `source` — a
    bundled template or another campaign on this machine.

    Refuses once the table is seated: an unseated party is the mark of a
    campaign that hasn't been played (see is_ready), and reseeding a played
    one would erase it. Replaces contents rather than the directory itself,
    so an externally pinned CAMPAIGN_ROOT (symlink, tests) stays valid."""
    if not (source / "state" / "current.json").exists():
        raise ValueError(f"not a campaign: {source}")
    if source.resolve() == CAMPAIGN.resolve():
        raise ValueError("a campaign can't be seeded from itself")
    try:
        current = json.loads(
            (CAMPAIGN / "state" / "current.json").read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        current = {}
    if current.get("party"):
        raise ValueError("this campaign has already started — "
                         "its world can't be swapped out")
    CAMPAIGN.mkdir(parents=True, exist_ok=True)
    for child in CAMPAIGN.iterdir():
        shutil.rmtree(child) if child.is_dir() else child.unlink()
    for child in source.iterdir():
        if child.name == "template.json":  # card metadata, not campaign state
            continue
        if child.is_dir():
            shutil.copytree(child, CAMPAIGN / child.name)
        else:
            shutil.copy2(child, CAMPAIGN / child.name)
    # World templates share the starter's pregen heroes (and their portraits,
    # which are most of the bundle's weight) rather than each shipping a copy.
    if not (CAMPAIGN / "characters").is_dir():
        shutil.copytree(_starter_template() / "characters",
                        CAMPAIGN / "characters")


def reset_for_new_table(root: Path | None = None) -> None:
    """Strip the previous table's traces from a copied campaign so a new
    group starts fresh: party unseated, player names blanked, session logs,
    chronicle, and the DM's conversation thread cleared. World state — quests,
    flags, entities, hero sheets — stays; it IS the world being re-run."""
    root = root or CAMPAIGN
    state = root / "state"
    for name in ("player-feed.jsonl", "dm-thread.sqlite",
                 "dev-log.jsonl", "dm-activity.json"):
        (state / name).unlink(missing_ok=True)
    (state / "combat.json").write_text(
        json.dumps({"active": False}) + "\n", encoding="utf-8")

    sessions = root / "sessions"
    if sessions.is_dir():
        for p in sessions.iterdir():
            shutil.rmtree(p) if p.is_dir() else p.unlink()
    sessions.mkdir(exist_ok=True)
    (sessions / "recap.md").write_text(
        "# Campaign so far\n\n"
        "Nothing yet — a new table is starting in a world that has been "
        "played before. Its quests, world flags, and entity files are "
        "established history; open a fresh story for this party on top of "
        "them.\n", encoding="utf-8")

    for sheet_path in sorted((root / "characters").glob("*.json")):
        try:
            sheet = json.loads(sheet_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        if sheet.get("player"):
            sheet["player"] = ""
            sheet_path.write_text(
                json.dumps(sheet, indent=2, ensure_ascii=False) + "\n",
                encoding="utf-8")

    current_file = state / "current.json"
    try:
        current = json.loads(current_file.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        current = {}
    current["party"] = []
    current_file.write_text(
        json.dumps(current, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8")


def create_campaign() -> str:
    """New campaign from the starter template; returns its slug.

    No name is asked for here: an unseated party sends the next boot to the
    setup screen, which names the campaign (set_campaign_name). The slug
    stays internal."""
    root = campaigns_dir()
    n = 1
    while (root / f"table-{n}").exists():
        n += 1
    target = root / f"table-{n}"
    root.mkdir(parents=True, exist_ok=True)
    shutil.copytree(_starter_template(), target,
                    ignore=shutil.ignore_patterns("template.json"))
    return target.name


def _campaign_path(slug: str) -> Path:
    """The directory of an existing campaign. Refuses path-shaped slugs, so
    a slug arriving from the web setup screen can't reach outside
    campaigns/."""
    if not slug or slug != Path(slug).name or slug in (".", ".."):
        raise ValueError(f"not a campaign slug: {slug!r}")
    path = campaigns_dir() / slug
    if not (path / "state" / "current.json").exists():
        raise ValueError(f"no campaign at {path}")
    return path


def _is_pristine(path: Path) -> bool:
    """A campaign that was created but never touched: no party, no chronicle,
    never named. Its contents are an exact template copy — nothing to lose."""
    try:
        current = json.loads(
            (path / "state" / "current.json").read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return False
    return (not current.get("party")
            and str(current.get("campaign") or "New Campaign") == "New Campaign"
            and not (path / "state" / "player-feed.jsonl").exists())


def set_active_campaign(slug: str) -> None:
    """Point config.json at another campaign. Takes effect on next launch —
    CAMPAIGN is a per-process constant (see its comment).

    Choosing "New Campaign" mints a fresh table before the setup screen can
    offer "continue" instead — so continuing another campaign from there
    would leave the untouched table behind, haunting every campaign list as
    one more "New Campaign". Switching away from a pristine table discards
    it; named, seeded, or played tables are always kept."""
    target = _campaign_path(slug)
    previous = CAMPAIGN
    save(campaign=slug)
    if (previous.resolve() != target.resolve()
            and previous.parent == campaigns_dir()
            and _is_pristine(previous)):
        shutil.rmtree(previous, ignore_errors=True)


def rename_campaign(slug: str, name: str) -> None:
    """Set any campaign's display name. The active one goes through
    set_campaign_name so the live window title and menu refresh too."""
    path = _campaign_path(slug)
    if path.resolve() == CAMPAIGN.resolve():
        set_campaign_name(name)
        return
    current_file = path / "state" / "current.json"
    current = json.loads(current_file.read_text(encoding="utf-8"))
    current["campaign"] = name
    current_file.write_text(json.dumps(current, indent=2, ensure_ascii=False) + "\n",
                            encoding="utf-8")


def trash_dir() -> Path:
    return APP_DIR / "trash"


def delete_campaign(slug: str) -> str:
    """Move a campaign to APP_DIR/trash — never a hard delete, so a slip of
    the mouse costs nothing. Returns the trash id restore_campaign takes.
    A same-volume rename: atomic, and the campaign is intact in the trash."""
    path = _campaign_path(slug)
    if path.resolve() == CAMPAIGN.resolve():
        raise ValueError("this campaign is the one you're setting up — "
                         "switch away from it first")
    trash_dir().mkdir(parents=True, exist_ok=True)
    stamp = time.strftime("%Y%m%d-%H%M%S")
    target, n = trash_dir() / f"{slug}.{stamp}", 2
    while target.exists():
        target, n = trash_dir() / f"{slug}.{stamp}.{n}", n + 1
    path.rename(target)
    return target.name


def restore_campaign(trash_id: str) -> str:
    """Bring a trashed campaign back; returns its (possibly re-minted) slug."""
    if not trash_id or trash_id != Path(trash_id).name:
        raise ValueError(f"not a trash id: {trash_id!r}")
    source = trash_dir() / trash_id
    if not (source / "state" / "current.json").exists():
        raise ValueError(f"nothing in the trash at {source}")
    slug = trash_id.split(".", 1)[0]
    target, n = campaigns_dir() / slug, 2
    while target.exists():
        target, n = campaigns_dir() / f"{slug}-{n}", n + 1
    target.parent.mkdir(parents=True, exist_ok=True)
    source.rename(target)
    return target.name


def _migrate_legacy_campaign() -> None:
    """Move the pre-multi-campaign layout (APP_DIR/campaign) into
    campaigns/<active slug>. A same-volume rename: atomic, idempotent, and a
    re-run after any crash converges. Skipped under an explicit CAMPAIGN_ROOT
    — that pins a root from outside; nothing here should move it."""
    legacy = APP_DIR / "campaign"
    if os.environ.get("CAMPAIGN_ROOT") \
            or not (legacy / "state" / "current.json").exists() \
            or (CAMPAIGN / "state" / "current.json").exists():
        return
    CAMPAIGN.parent.mkdir(parents=True, exist_ok=True)
    legacy.rename(CAMPAIGN)
    save(campaign=CAMPAIGN.name)


def ensure_campaign() -> Path:
    """Make the active campaign exist: adopt a legacy single-campaign install,
    else create from the bundled starter template on first launch."""
    _migrate_legacy_campaign()
    if (CAMPAIGN / "state" / "current.json").exists():
        return CAMPAIGN
    CAMPAIGN.parent.mkdir(parents=True, exist_ok=True)
    shutil.copytree(_starter_template(), CAMPAIGN,
                    ignore=shutil.ignore_patterns("template.json"))
    return CAMPAIGN


# The desktop shell registers a callback here so a rename can refresh the
# window title and Campaign menu of the live process. Those are built once at
# launch, and a brand-new campaign has no name yet at that point — the setup
# screen names it mid-process, in the server thread.
on_campaign_renamed = None

# Registered by the desktop shell so the setup screen can continue another
# campaign: called (with the new slug) after set_active_campaign, it schedules
# the relaunch that makes the switch take effect. Unset when there is no shell
# to relaunch (plain `python webapp/server.py`, or an externally pinned
# CAMPAIGN_ROOT) — the switch is then saved but needs a manual restart.
on_campaign_switched = None


def set_campaign_name(name: str) -> None:
    path = CAMPAIGN / "state" / "current.json"
    current = json.loads(path.read_text(encoding="utf-8"))
    current["campaign"] = name
    path.write_text(json.dumps(current, indent=2, ensure_ascii=False) + "\n",
                    encoding="utf-8")
    if on_campaign_renamed:
        on_campaign_renamed(name)
