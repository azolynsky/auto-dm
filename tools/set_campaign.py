#!/usr/bin/env python3
"""
Point the active-adventure file (campaigns/active.json) at a save.

The DM runs this once during session-start step 0, after the table picks an
adventure in conversation. From then on every tool and the webapp resolve the
campaign from the pointer — no CAMPAIGN_ROOT env var needed.

Usage:
    python tools/set_campaign.py dungeon-of-the-mad-mage
    python tools/set_campaign.py emberwick --system dnd5e   # if slug is ambiguous
    python tools/set_campaign.py campaigns/dnd5e/emberwick  # a path works too
    python tools/set_campaign.py                            # show current pointer
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import campaign_lib


def main() -> int:
    p = argparse.ArgumentParser(description="Choose the active adventure save.")
    p.add_argument("which", nargs="?", help="save slug (from list_campaigns.py) or path")
    p.add_argument("--system", help="disambiguate when the same slug exists in two systems")
    args = p.parse_args()

    if not args.which:
        active = campaign_lib.get_active()
        if active is None:
            print(json.dumps({"active": None, "note": "no adventure selected"}))
        else:
            print(json.dumps(campaign_lib.set_active(active), indent=2, ensure_ascii=False))
        return 0

    as_path = Path(args.which)
    if not as_path.is_absolute():
        as_path = campaign_lib.REPO / args.which
    if (as_path / "state" / "current.json").exists():
        target = as_path
    else:
        matches = [s for s in campaign_lib.list_campaigns(system=args.system)
                   if s["slug"] == args.which]
        if not matches:
            sys.exit(f"no save named {args.which!r} — run: python tools/list_campaigns.py")
        if len(matches) > 1:
            systems = ", ".join(s["system"] for s in matches)
            sys.exit(f"slug {args.which!r} exists in several systems ({systems}) — add --system")
        target = campaign_lib.REPO / matches[0]["path"]

    record = campaign_lib.set_active(target)
    print(json.dumps(record, indent=2, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())
