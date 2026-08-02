#!/usr/bin/env python3
"""
The character roster: reusable heroes and villains, usable in ANY campaign.

Heroes live at   roster/<system>/characters/<id>.json (+ images/<id>.jpg)
Villains live at roster/<system>/villains/<id>/ (summary.md + stats.json)

Importing copies into the ACTIVE save — each campaign gets its own copy that
evolves independently; the roster stays pristine. Exporting copies a hero
built in a campaign back to the roster for reuse.

Usage:
    python tools/roster.py list [--system strike]
    python tools/roster.py import --char cyclops
    python tools/roster.py import --villain u-men
    python tools/roster.py export --char my-new-hero
    (--force overwrites an existing copy on either side)

Every command prints one JSON object.
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
ROSTER_DIR = REPO / "roster"
IMAGE_EXTS = (".jpg", ".jpeg", ".png", ".webp")


def active_system(root: Path) -> str | None:
    try:
        current = json.loads((root / "state" / "current.json").read_text(encoding="utf-8"))
        return current.get("system")
    except Exception:
        return None


def resolve_system(args) -> str:
    if args.system:
        return args.system
    system = active_system(campaign_lib.resolve_root())
    if system:
        return system
    systems = sorted(p.name for p in ROSTER_DIR.iterdir() if p.is_dir()) \
        if ROSTER_DIR.exists() else []
    if len(systems) == 1:
        return systems[0]
    sys.exit("can't tell which system's roster you mean — pass --system "
             + (f"(available: {', '.join(systems)})" if systems else "(roster/ is empty)"))


def find_portrait(images_dir: Path, char_id: str) -> Path | None:
    for ext in IMAGE_EXTS:
        p = images_dir / f"{char_id}{ext}"
        if p.exists():
            return p
    return None


def read_char(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def cmd_list(args) -> None:
    system = resolve_system(args)
    base = ROSTER_DIR / system
    chars_dir = base / "characters"
    villains_dir = base / "villains"

    characters = []
    if chars_dir.exists():
        for f in sorted(chars_dir.glob("*.json")):
            c = read_char(f)
            characters.append({
                "id": c.get("id", f.stem),
                "name": c.get("name", f.stem),
                "class": c.get("class"),
                "role": c.get("role"),
                "level": c.get("level"),
                "portrait": find_portrait(chars_dir / "images", f.stem) is not None,
            })

    villains = []
    if villains_dir.exists():
        for d in sorted(p for p in villains_dir.iterdir() if p.is_dir()):
            units = []
            stats = d / "stats.json"
            if stats.exists():
                try:
                    units = [u.get("name") for u in json.loads(stats.read_text(encoding="utf-8"))]
                except Exception:
                    units = ["(unreadable stats.json)"]
            villains.append({"id": d.name, "units": units})

    print(json.dumps({"system": system, "characters": characters, "villains": villains},
                     indent=2, ensure_ascii=False))


def cmd_import(args) -> None:
    system = resolve_system(args)
    root = campaign_lib.resolve_root()
    base = ROSTER_DIR / system

    if args.char:
        src = base / "characters" / f"{args.char}.json"
        if not src.exists():
            sys.exit(f"no such hero in the {system} roster: {args.char} "
                     "(python tools/roster.py list)")
        dest = root / "characters" / f"{args.char}.json"
        if dest.exists() and not args.force:
            sys.exit(f"{dest} already exists — re-run with --force to replace it")
        dest.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(src, dest)
        portrait = find_portrait(base / "characters" / "images", args.char)
        copied_portrait = None
        if portrait:
            img_dest = root / "characters" / "images" / portrait.name
            img_dest.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(portrait, img_dest)
            copied_portrait = str(img_dest.relative_to(root))
        name = read_char(dest).get("name", args.char)
        print(json.dumps({"action": "import", "kind": "character", "id": args.char,
                          "name": name, "to": str(dest), "portrait": copied_portrait},
                         ensure_ascii=False))
    else:
        src = base / "villains" / args.villain
        if not src.is_dir():
            sys.exit(f"no such villain in the {system} roster: {args.villain} "
                     "(python tools/roster.py list)")
        dest = root / "npcs" / "recurring" / args.villain
        if dest.exists() and not args.force:
            sys.exit(f"{dest} already exists — re-run with --force to replace it")
        if dest.exists():
            shutil.rmtree(dest)
        shutil.copytree(src, dest)
        print(json.dumps({"action": "import", "kind": "villain", "id": args.villain,
                          "to": str(dest),
                          "note": "add a line to campaign npcs/INDEX.md"},
                         ensure_ascii=False))


def cmd_export(args) -> None:
    system = resolve_system(args)
    root = campaign_lib.resolve_root()
    src = root / "characters" / f"{args.char}.json"
    if not src.exists():
        sys.exit(f"no such character in the active save: {args.char}")
    dest_dir = ROSTER_DIR / system / "characters"
    dest = dest_dir / f"{args.char}.json"
    if dest.exists() and not args.force:
        sys.exit(f"{dest} already exists in the roster — re-run with --force to replace it")
    dest_dir.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(src, dest)
    portrait = find_portrait(root / "characters" / "images", args.char)
    copied_portrait = None
    if portrait:
        img_dest = dest_dir / "images" / portrait.name
        img_dest.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(portrait, img_dest)
        copied_portrait = str(img_dest.relative_to(REPO))
    print(json.dumps({"action": "export", "kind": "character", "id": args.char,
                      "to": str(dest), "portrait": copied_portrait}, ensure_ascii=False))


def main() -> int:
    p = argparse.ArgumentParser(description="Reusable hero/villain roster.")
    p.add_argument("--system", default=None,
                   help="system slug (default: the active save's system)")
    sub = p.add_subparsers(dest="cmd", required=True)

    s = sub.add_parser("list", help="enumerate roster heroes and villains")
    s.set_defaults(func=cmd_list)

    s = sub.add_parser("import", help="copy a hero or villain into the active save")
    g = s.add_mutually_exclusive_group(required=True)
    g.add_argument("--char", help="hero id, e.g. cyclops")
    g.add_argument("--villain", help="villain id, e.g. u-men")
    s.add_argument("--force", action="store_true", help="replace an existing copy")
    s.set_defaults(func=cmd_import)

    s = sub.add_parser("export", help="copy a hero from the active save into the roster")
    s.add_argument("--char", required=True, help="character id in the active save")
    s.add_argument("--force", action="store_true", help="replace an existing roster entry")
    s.set_defaults(func=cmd_export)

    args = p.parse_args()
    args.func(args)
    return 0


if __name__ == "__main__":
    sys.exit(main())
