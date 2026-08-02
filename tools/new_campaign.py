#!/usr/bin/env python3
"""
Start a fresh adventure save from a template.

Copies campaigns/starter/ (or --template <dir>) to campaigns/<system>/<slug>/
(or --dest <dir>), stamps the campaign name and rule system into
state/current.json, and refuses to overwrite an existing save unless --force.

Usage:
    python tools/new_campaign.py --name "Emberwick Nights"
    python tools/new_campaign.py --name "Test" --system dnd5e --force
"""
from __future__ import annotations

import argparse
import json
import shutil
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import campaign_lib

REPO = campaign_lib.REPO


def default_dest(system: str, name: str) -> str:
    """Where a save lands when --dest isn't given: campaigns/<system>/<slug>."""
    return f"campaigns/{system}/{campaign_lib.slugify(name)}"


def main() -> int:
    p = argparse.ArgumentParser(description="Create an adventure save from a template.")
    p.add_argument("--name", required=True, help="campaign name (shown in the webapp header)")
    p.add_argument("--system", default="dnd5e", help="rule system slug (see rules/systems.json)")
    p.add_argument("--template", default=None,
                   help="template directory to copy (default: the system's starter_template "
                        "from rules/systems.json, else campaigns/starter)")
    p.add_argument("--dest", default=None,
                   help="destination dir (default: campaigns/<system>/<slug from --name>)")
    p.add_argument("--force", action="store_true", help="replace an existing save (DESTRUCTIVE)")
    args = p.parse_args()

    system_entry = None
    systems_file = REPO / "rules" / "systems.json"
    if systems_file.exists():
        systems = json.loads(systems_file.read_text(encoding="utf-8"))["systems"]
        system_entry = next((s for s in systems if s["slug"] == args.system), None)
        if system_entry is None:
            known = ", ".join(sorted(s["slug"] for s in systems))
            sys.exit(f"unknown rule system {args.system!r} — registered: {known}")

    if args.template is None:
        args.template = (system_entry or {}).get("starter_template", "campaigns/starter")

    template = REPO / args.template
    dest = REPO / (args.dest or default_dest(args.system, args.name))
    if not (template / "state" / "current.json").exists():
        sys.exit(f"not a campaign template: {template}")
    if dest.exists():
        if not args.force:
            sys.exit(
                f"{dest} already exists — an adventure save is already there.\n"
                "Re-run with --force to REPLACE it (destroys all its state), "
                "pick a different --name, or move it aside first."
            )
        shutil.rmtree(dest)

    shutil.copytree(template, dest)

    current_file = dest / "state" / "current.json"
    current = json.loads(current_file.read_text(encoding="utf-8"))
    current["campaign"] = args.name
    current["system"] = args.system
    current_file.write_text(json.dumps(current, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")

    print(f"Campaign '{args.name}' ({args.system}) created at {dest}.")
    if campaign_lib.CAMPAIGNS_DIR in dest.parents:
        campaign_lib.set_active(dest)
        print("It is now the active adventure (campaigns/active.json).")
    else:
        print(f"Activate it with:  python tools/set_campaign.py \"{dest}\"")
    print("Next: run a session 0 to make characters, then start the web companion:")
    print("  python webapp/server.py")
    return 0


if __name__ == "__main__":
    sys.exit(main())
