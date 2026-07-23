#!/usr/bin/env python3
"""
Start a fresh campaign from a template.

Copies campaigns/starter/ (or --template <dir>) to <repo>/campaign/, which is
where every tool and the webapp look for live state. Refuses to overwrite an
existing campaign unless --force.

Usage:
    python tools/new_campaign.py --name "Emberwick Nights"
    python tools/new_campaign.py --name "Test" --template campaigns/starter --force
"""
from __future__ import annotations

import argparse
import json
import shutil
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent


def main() -> int:
    p = argparse.ArgumentParser(description="Create the active campaign from a template.")
    p.add_argument("--name", required=True, help="campaign name (shown in the webapp header)")
    p.add_argument("--template", default="campaigns/starter", help="template directory to copy")
    p.add_argument("--dest", default="campaign", help="destination (the active campaign dir)")
    p.add_argument("--force", action="store_true", help="replace an existing campaign (DESTRUCTIVE)")
    args = p.parse_args()

    template = REPO / args.template
    dest = REPO / args.dest
    if not (template / "state" / "current.json").exists():
        sys.exit(f"not a campaign template: {template}")
    if dest.exists():
        if not args.force:
            sys.exit(
                f"{dest} already exists — this repo has an active campaign.\n"
                "Re-run with --force to REPLACE it (destroys all its state), "
                "or move it aside first."
            )
        shutil.rmtree(dest)

    shutil.copytree(template, dest)

    current_file = dest / "state" / "current.json"
    current = json.loads(current_file.read_text(encoding="utf-8"))
    current["campaign"] = args.name
    current_file.write_text(json.dumps(current, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")

    print(f"Campaign '{args.name}' created at {dest}.")
    print("Next: run a session 0 to make characters (docs/character-schema.md),")
    print("then start the web companion:  python webapp/server.py")
    return 0


if __name__ == "__main__":
    sys.exit(main())
