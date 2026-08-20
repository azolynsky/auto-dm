#!/usr/bin/env python3
"""
Auto-DM as a desktop app.

Starts the companion server on a loopback port and shows it in a native webview
window — WKWebView on macOS, WebView2 on Windows — so there is no terminal and
no browser to open. The player needs one thing: an OpenRouter API key, which the
setup screen collects on first launch.

    python desktop/app.py
"""
from __future__ import annotations

import os
import socket
import subprocess
import sys
import threading
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import config  # noqa: E402

WINDOW_TITLE = "Auto-DM"
CAMPAIGN_MENU_TITLE = "Campaign"


def relaunch() -> None:
    """Replace this process with a fresh copy of itself.

    The whole app is campaign-scoped — the server's path constants, the
    CAMPAIGN_ROOT env, the DM's conversation thread — so a campaign change
    boots clean instead of re-rooting a live process. We set CAMPAIGN_ROOT
    ourselves at startup; drop it so the fresh process derives the new
    campaign from config.json rather than inheriting the old root."""
    os.environ.pop("CAMPAIGN_ROOT", None)
    argv = sys.argv if getattr(sys, "frozen", False) else [sys.executable] + sys.argv
    if os.name == "nt":
        # execv on Windows detaches oddly from the console; spawn-and-exit.
        subprocess.Popen(argv)
        return
    os.execv(argv[0], argv)


def move_after_app_menu(bar, title: str) -> bool:
    """Move the named top-level item of an NSMenu bar to index 1 — right
    after the application menu. No-op when the bar or item is missing."""
    if bar is None:
        return False
    item = bar.itemWithTitle_(title)
    if item is None:
        return False
    bar.removeItem_(item)
    bar.insertItem_atIndex_(item, 1)
    return True


def promote_campaign_menu() -> None:
    """Put Campaign ahead of pywebview's built-in Edit/View menus.

    pywebview appends custom menus after its built-ins and offers no
    ordering hook; disabling the built-ins instead would take the Edit menu
    — and ⌘C/⌘V in the chat input — with it. So reorder the live menu bar
    once, via the main runloop: AppKit isn't thread-safe and webview.start
    funcs run off-main."""
    if sys.platform != "darwin":
        return

    import AppKit
    from PyObjCTools import AppHelper

    AppHelper.callAfter(
        lambda: move_after_app_menu(
            AppKit.NSApplication.sharedApplication().mainMenu(),
            CAMPAIGN_MENU_TITLE))


def campaign_menu(on_new, on_switch) -> list:
    """The native Campaign menu: new, then one entry per campaign, the
    active one checked. Built once per process — every campaign change
    relaunches, so the menu is always fresh."""
    import webview.menu as wm

    campaigns = config.list_campaigns()
    labels = [label for _, label in campaigns]
    items = [wm.MenuAction("New Campaign", on_new), wm.MenuSeparator()]
    for slug, label in campaigns:
        if labels.count(label) > 1:  # two unnamed tables: show the slug too
            label = f"{label} ({slug})"
        mark = "✓  " if slug == config.CAMPAIGN.name else "     "
        items.append(wm.MenuAction(mark + label, lambda s=slug: on_switch(s)))
    return [wm.Menu(CAMPAIGN_MENU_TITLE, items)]


def free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def wait_for_server(port: int, timeout: float = 60.0) -> bool:
    """Poll until the server accepts connections. Importing langgraph is slow."""
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        with socket.socket() as s:
            s.settimeout(0.5)
            if s.connect_ex(("127.0.0.1", port)) == 0:
                return True
        time.sleep(0.15)
    return False


def main() -> int:
    # An external CAMPAIGN_ROOT pins the root from outside (tests, sandboxes);
    # the Campaign menu is hidden then, because a switch written to config.json
    # would silently not take effect. Decide before we set the env ourselves.
    external_root = bool(os.environ.get("CAMPAIGN_ROOT"))

    # The campaign has to exist before the server imports, because
    # campaign_lib.resolve_root() refuses to start without one.
    config.ensure_campaign()
    os.environ.setdefault("CAMPAIGN_ROOT", str(config.CAMPAIGN))

    try:
        import uvicorn
        import webview
    except ImportError as e:
        sys.exit(f"Missing dependency: {e.name}\n"
                 f"Install with: pip install -r "
                 f"{Path(__file__).parent / 'requirements.txt'}")

    sys.path.insert(0, str(config.BUNDLE / "webapp"))
    import server

    # A random loopback port avoids clashing with a companion server the table
    # may already have running. AUTODM_PORT pins it when debugging.
    port = int(os.environ.get("AUTODM_PORT") or free_port())

    def serve() -> None:
        uvicorn.run(server.app, host="127.0.0.1", port=port, log_level="warning")

    threading.Thread(target=serve, daemon=True).start()
    if not wait_for_server(port):
        sys.exit("The companion server didn't start. Run `python desktop/app.py` "
                 "from a terminal to see why.")

    switching = threading.Event()
    window = webview.create_window(
        f"{WINDOW_TITLE} — {config.campaign_label(config.CAMPAIGN)}",
        f"http://127.0.0.1:{port}", width=1400, height=900, min_size=(900, 600))

    def change_to(slug: str) -> None:
        if slug == config.CAMPAIGN.name:
            return
        config.set_active_campaign(slug)
        switching.set()
        window.destroy()  # unblocks webview.start(); relaunch happens below

    menu = [] if external_root else campaign_menu(
        on_new=lambda: change_to(config.create_campaign()),
        on_switch=change_to)

    # blocks until the window closes; the server thread is a daemon
    webview.start(func=promote_campaign_menu, menu=menu)
    if switching.is_set():
        relaunch()
    return 0


if __name__ == "__main__":
    sys.exit(main())
