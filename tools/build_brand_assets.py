"""Create a Windows multi-resolution ICO from the original tracked logo asset."""
from __future__ import annotations
import sys
from pathlib import Path
from PIL import Image, ImageOps, UnidentifiedImageError

ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "assets" / "mysql-editor-logo.webp"
OUTPUT = ROOT / "assets" / "mysql-editor.ico"
SIZES = (16, 24, 32, 48, 64, 128, 256)

def main() -> int:
    if not SOURCE.is_file():
        print(f"Missing logo source: {SOURCE}", file=sys.stderr)
        return 2
    try:
        with Image.open(SOURCE) as original:
            original.load()
            if original.width < 128 or original.height < 128:
                print(
                    f"Logo source is only {original.width}x{original.height}; "
                    "audit the original upload before claiming a high-resolution master.",
                    file=sys.stderr,
                )
                return 3
            image = ImageOps.exif_transpose(original).convert("RGBA")
    except (OSError, UnidentifiedImageError) as exc:
        print(f"Could not load logo artwork: {exc}", file=sys.stderr)
        return 2
    if image.width != image.height:
        side = min(image.size)
        left = (image.width - side) // 2
        top = (image.height - side) // 2
        image = image.crop((left, top, left + side, top + side))
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    image.save(OUTPUT, format="ICO", sizes=[(size, size) for size in SIZES])
    with Image.open(OUTPUT) as icon:
        print(f"Created {OUTPUT}; embedded frames: {sorted(icon.ico.sizes())}")
    return 0

if __name__ == "__main__":
    raise SystemExit(main())
