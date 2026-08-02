#!/usr/bin/env python3
"""
List adventure saves under campaigns/<system>/<slug>/.

The DM runs this at session start (CLAUDE.md step 0) to offer the table a
choice: continue one of these, or start a new adventure (new_campaign.py).

Usage:
    python tools/list_campaigns.py
    python tools/list_campaigns.py --system dnd5e --sort name
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import campaign_lib


def main() -> int:
    p = argparse.ArgumentParser(description="List adventure saves.")
    p.add_argument("--system", help="only saves using this rule system slug")
    p.add_argument("--sort", default="last_played",
                   choices=("last_played", "name", "system"),
                   help="sort order (default: last_played, newest first)")
    args = p.parse_args()

    saves = campaign_lib.list_campaigns(system=args.system, sort=args.sort)
    print(json.dumps({"count": len(saves), "campaigns": saves},
                     indent=2, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())
