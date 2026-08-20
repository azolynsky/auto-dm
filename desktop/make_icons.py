"""Build autodm.icns and autodm.ico from icon-1024.png.

macOS (Big Sur+) expects the artwork on a rounded-rect tile occupying
~824/1024 of the canvas with transparent margin; Windows uses the full
square. Rerunnable: python3 desktop/make_icons.py
"""
import shutil
import subprocess
import tempfile
from pathlib import Path

from PIL import Image, ImageDraw

HERE = Path(__file__).parent
SRC = HERE / "icon-1024.png"

# Apple's app-icon grid: 824x824 tile centered on 1024, corner radius ~185.
TILE, CANVAS, RADIUS = 824, 1024, 185


def macos_master() -> Image.Image:
    art = Image.open(SRC).convert("RGBA").resize((TILE, TILE), Image.LANCZOS)
    mask = Image.new("L", (TILE, TILE), 0)
    ImageDraw.Draw(mask).rounded_rectangle(
        (0, 0, TILE - 1, TILE - 1), radius=round(RADIUS * TILE / CANVAS), fill=255
    )
    out = Image.new("RGBA", (CANVAS, CANVAS), (0, 0, 0, 0))
    off = (CANVAS - TILE) // 2
    out.paste(art, (off, off), mask)
    return out


def build_icns(master: Image.Image) -> None:
    with tempfile.TemporaryDirectory() as td:
        iconset = Path(td) / "icon.iconset"
        iconset.mkdir()
        for s in (16, 32, 64, 128, 256, 512):
            master.resize((s, s), Image.LANCZOS).save(iconset / f"icon_{s}x{s}.png")
            master.resize((s * 2, s * 2), Image.LANCZOS).save(
                iconset / f"icon_{s}x{s}@2x.png"
            )
        subprocess.run(
            ["iconutil", "-c", "icns", iconset, "-o", HERE / "autodm.icns"],
            check=True,
        )


def build_ico() -> None:
    art = Image.open(SRC).convert("RGBA").resize((1024, 1024), Image.LANCZOS)
    art.save(
        HERE / "autodm.ico",
        sizes=[(16, 16), (32, 32), (48, 48), (64, 64), (128, 128), (256, 256)],
    )


if __name__ == "__main__":
    if shutil.which("iconutil"):
        build_icns(macos_master())
        print("wrote autodm.icns")
    else:
        print("iconutil not found (not macOS) — skipped autodm.icns")
    build_ico()
    print("wrote autodm.ico")
