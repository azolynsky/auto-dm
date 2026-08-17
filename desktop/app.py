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
import sys
import threading
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import config  # noqa: E402

WINDOW_TITLE = "Auto-DM"


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

    webview.create_window(WINDOW_TITLE, f"http://127.0.0.1:{port}",
                          width=1400, height=900, min_size=(900, 600))
    webview.start()   # blocks until the window closes; the server thread is a daemon
    return 0


if __name__ == "__main__":
    sys.exit(main())
