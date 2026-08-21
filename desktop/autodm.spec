# -*- mode: python ; coding: utf-8 -*-
"""
PyInstaller spec for the Auto-DM desktop app.

    pyinstaller desktop/autodm.spec

The campaign tools are shipped as SOURCE files and executed in-process (see
desktop/campaign_tools.py), because a frozen app has no python interpreter to
subprocess out to. For the same reason the bundled binary answers to
`--mcp-server`: the claude-cli backend needs to launch tools/mcp_server.py as a
child process, and re-executing itself is the only interpreter it has.
Reference content (rules/, .claude/, prompts/, CLAUDE.md, the
starter campaign) ships read-only; the player's own campaign is created in their
app-data directory on first launch.
"""
import os

from PyInstaller.utils.hooks import collect_all

# Paths in a spec resolve against the CWD, not the spec file, so anchor
# everything to the repo root explicitly.
HERE = os.path.abspath(SPECPATH)           # noqa: F821 — injected by PyInstaller
ROOT = os.path.dirname(HERE)


def repo(*parts):
    return os.path.join(ROOT, *parts)


datas = [
    (repo("webapp", "static"), "webapp/static"),
    (repo("tools"), "tools"),               # run via runpy, so keep the .py source
    (repo("rules"), "rules"),
    (repo("docs"), "docs"),
    (repo("prompts"), "prompts"),
    (repo(".claude", "agents"), ".claude/agents"),
    (repo(".claude", "skills"), ".claude/skills"),
    (repo("campaigns"), "campaigns"),   # every prewritten world template
    (repo("CLAUDE.md"), "."),
]
binaries = []
hiddenimports = [
    "campaign_lib", "config", "prompts", "agent", "campaign_tools", "server",
    # Backends load by name at first use, so nothing imports them statically.
    "backends", "backends.base", "backends.openrouter", "backends.claude_cli",
    "backends.claude_agent",
    "mcp_server",   # app.py --mcp-server re-executes this binary into it
    "uvicorn.protocols.http.h11_impl", "uvicorn.protocols.websockets.auto",
    "uvicorn.lifespan.on", "uvicorn.loops.auto",
]

# LangChain/LangGraph resolve providers and serializers dynamically, and the
# MCP/Agent SDKs load transports the same way, so let the hooks pull in what
# static analysis misses. claude_agent_sdk and mcp are optional at runtime —
# a build without them just leaves the claude-agent backend reporting itself
# unavailable, which is what its available() is for.
for package in ("langgraph", "langgraph_checkpoint", "langchain_core",
                "langchain_openai", "openai", "webview",
                "claude_agent_sdk", "mcp"):
    try:
        pkg_datas, pkg_binaries, pkg_hidden = collect_all(package)
    except Exception as e:
        print(f"autodm.spec: collect_all({package}) skipped: {e}")
        continue
    datas += pkg_datas
    binaries += pkg_binaries
    hiddenimports += pkg_hidden

a = Analysis(
    [os.path.join(HERE, "app.py")],
    pathex=[repo("tools"), repo("webapp"), HERE],
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    runtime_hooks=[],
    excludes=["tkinter", "matplotlib", "numpy", "pytest", "IPython"],
    noarchive=False,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz, a.scripts, [],
    exclude_binaries=True,
    name="Auto-DM",
    icon="autodm.ico",      # Windows; regenerate both via make_icons.py
    console=False,          # no terminal window
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
)
coll = COLLECT(exe, a.binaries, a.datas, strip=False, upx=False, name="Auto-DM")

app = BUNDLE(                # a no-op off macOS
    coll,
    name="Auto-DM.app",
    icon="autodm.icns",
    bundle_identifier="dev.autodm.app",
    info_plist={
        "CFBundleShortVersionString": "0.1.0",
        "NSHighResolutionCapable": True,
        # Talks to openrouter.ai, and serves itself over loopback HTTP.
        "NSAppTransportSecurity": {"NSAllowsLocalNetworking": True},
    },
)
