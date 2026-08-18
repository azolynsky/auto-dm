#!/usr/bin/env python3
"""
Model sandbox: run the same player message through several DM models and
compare what the players would have seen.

    python tools/sandbox.py "I search the cellar for secret doors"
    python tools/sandbox.py -m openai/gpt-5.2 -m qwen/qwen3.7-flash "..."

Each model gets a throwaway COPY of the campaign (state, chronicle, and the
DM's conversation thread), so every run is a real turn — real dice, real
tools, real narration — from the same starting point, and the live campaign
is never touched. Runs go in parallel; the report shows each model's new
chronicle entries and wall time, and prints each copy's path for inspection.

Requires the desktop dependencies and an OpenRouter key (app config or
OPENROUTER_API_KEY). Model override rides the AUTODM_MODEL env var.
"""
from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
import tempfile
import time
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "desktop"))
import config  # noqa: E402

DEFAULT_MODELS = [
    "~deepseek/deepseek-v4-flash-latest",
    "openai/gpt-5.6-luna-pro",
    "qwen/qwen3.7-flash",
    "nvidia/nemotron-3.5-lightning",
]

TURN_TIMEOUT = 600  # seconds per model


def feed_entries(root: Path) -> list[dict]:
    path = root / "state" / "player-feed.jsonl"
    if not path.exists():
        return []
    out = []
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line:
            try:
                out.append(json.loads(line))
            except json.JSONDecodeError:
                pass
    return out


def new_entries(root: Path, before: int) -> list[dict]:
    return feed_entries(root)[before:]


def start_run(model: str, prompt: str, src: Path) -> dict:
    copy = Path(tempfile.mkdtemp(prefix="autodm-sandbox-")) / "campaign"
    shutil.copytree(src, copy)
    # Effects queued by the live session but not yet narrated would drain onto
    # the first model that uses narrate.py properly, framing it for subtext it
    # never produced. Every contender starts with a clean queue.
    (copy / "state" / "pending-effects.jsonl").unlink(missing_ok=True)
    env = {**os.environ, "CAMPAIGN_ROOT": str(copy), "AUTODM_MODEL": model}
    proc = subprocess.Popen(
        [sys.executable, str(REPO / "desktop" / "agent.py"), prompt],
        env=env, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    return {"model": model, "copy": copy, "before": len(feed_entries(copy)),
            "proc": proc, "t0": time.monotonic(), "error": None}


def finish_runs(runs: list[dict]) -> list[dict]:
    """Wait on all runs at once, stamping each one's real finish time —
    communicate() in sequence would report reap time, not run time."""
    # ponytail: output rides the pipe until reaped; fine while agent.py prints
    # one small JSON line — switch to reader threads if output ever grows.
    pending = set(range(len(runs)))
    deadline = time.monotonic() + TURN_TIMEOUT
    while pending and time.monotonic() < deadline:
        for i in list(pending):
            if runs[i]["proc"].poll() is not None:
                runs[i]["seconds"] = time.monotonic() - runs[i]["t0"]
                pending.discard(i)
        time.sleep(0.25)
    for i in pending:
        runs[i]["proc"].kill()
        runs[i]["seconds"] = time.monotonic() - runs[i]["t0"]
        runs[i]["error"] = f"timed out after {TURN_TIMEOUT}s"
    for run in runs:
        _out, err = run["proc"].communicate()
        run["entries"] = new_entries(run["copy"], run["before"])
        if run["error"] is None and run["proc"].returncode != 0:
            run["error"] = ((err or "").strip().splitlines() or ["nonzero exit"])[-1][:300]
    return runs


def report(runs: list[dict]) -> None:
    for run in runs:
        print(f"\n{'═' * 74}\n  {run['model']}  —  {run['seconds']:.1f}s"
              f"\n{'═' * 74}")
        if run["error"]:
            print(f"  ERROR: {run['error']}")
        for entry in run["entries"]:
            if entry.get("type") == "player":
                continue  # the echoed input, same for everyone
            for line in entry.get("text", "").splitlines():
                print(f"  > {line}")
            for fx in entry.get("effects") or []:
                print(f"      · {fx}")
        if not run["entries"] and not run["error"]:
            print("  (no chronicle output)")
        print(f"  copy: {run['copy']}")

    print(f"\n{'─' * 74}")
    for run in runs:
        status = "ERROR" if run["error"] else f"{len(run['entries'])} entries"
        print(f"  {run['model']:44} {run['seconds']:6.1f}s  {status}")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.strip().splitlines()[0])
    parser.add_argument("prompt", help="the player message to send to every model")
    parser.add_argument("-m", "--model", action="append", dest="models",
                        metavar="ID", help="OpenRouter model id (repeatable); "
                        "default: " + ", ".join(DEFAULT_MODELS))
    parser.add_argument("--campaign", type=Path, default=config.CAMPAIGN,
                        help="campaign to copy from (default: the app's)")
    args = parser.parse_args()

    if not config.api_key():
        sys.exit("No OpenRouter key — set OPENROUTER_API_KEY or configure the app.")
    if not (args.campaign / "state" / "current.json").exists():
        sys.exit(f"No campaign at {args.campaign} — pass --campaign.")

    models = args.models or DEFAULT_MODELS
    print(f"Racing {len(models)} models on: {args.prompt!r}")
    runs = [start_run(m, args.prompt, args.campaign) for m in models]
    report(finish_runs(runs))
    return 0


if __name__ == "__main__":
    sys.exit(main())
