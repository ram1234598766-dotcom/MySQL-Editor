#!/usr/bin/env python3
"""Build Windows icon and installer artwork from the supplied product logo."""
from __future__ import annotations

from pathlib import Path
from PIL import Image

ROOT = Path(__file__).resolve().parents[1]
ASSETS = ROOT / "assets"
LOGO_SOURCE = ASSETS / "mysqlidle-logo.png"

NAVY = (11, 24, 42)
DEEP_NAVY = (5, 14, 27)
BLUE = (37, 99, 235)
CYAN = (34, 211, 238)
WHITE = (248, 250, 252)
MUTED = (148, 163, 184)


def _contained_logo(max_width: int, max_height: int) -> Image.Image:
    """Load the exact README logo and scale it proportionally without cropping or stretching."""
    with Image.open(LOGO_SOURCE) as source:
        source.load()
        logo = source.convert("RGBA")
    scale = min(max_width / logo.width, max_height / logo.height)
    size = (max(1, round(logo.width * scale)), max(1, round(logo.height * scale)))
    return logo.resize(size, Image.Resampling.NEAREST)


def _render_mark(size: int) -> Image.Image:
    """Put the exact logo on a transparent square icon canvas without distortion."""
    logo = _contained_logo(size, size)
    canvas = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    canvas.alpha_composite(
        logo,
        ((size - logo.width) // 2, (size - logo.height) // 2),
    )
    return canvas


def _wizard_image() -> Image.Image:
    """Place the untouched 96x96 logo in the installer panel without scaling it."""
    width, height = 164, 314
    image = Image.new("RGB", (width, height), NAVY)
    with Image.open(LOGO_SOURCE) as source:
        source.load()
        logo = source.convert("RGBA")
    image.paste(
        logo,
        ((width - logo.width) // 2, (height - logo.height) // 2),
        logo,
    )
    return image


def _wizard_small() -> Image.Image:
    """Fit the original logo to the installer-required 55x55 slot using nearest-neighbor."""
    image = Image.new("RGB", (55, 55), NAVY)
    logo = _contained_logo(55, 55)
    image.paste(logo, (0, 0), logo)
    return image


def main() -> None:
    if not LOGO_SOURCE.is_file():
        raise FileNotFoundError(f"Required app logo is missing: {LOGO_SOURCE}")
    ASSETS.mkdir(parents=True, exist_ok=True)
    icon_sizes = [
        (16, 16), (24, 24), (32, 32), (48, 48),
        (64, 64), (96, 96), (128, 128), (256, 256),
    ]
    # Pre-render each icon size from the original PNG with nearest-neighbor scaling.
    # Passing those exact frames prevents Pillow from applying an extra blurred resize.
    icon_frames = [_render_mark(size[0]) for size in icon_sizes]
    icon = next(frame for frame in icon_frames if frame.size == (256, 256))
    icon.save(
        ASSETS / "mysqlidle.ico",
        format="ICO",
        sizes=icon_sizes,
        append_images=[frame for frame in icon_frames if frame is not icon],
    )
    _wizard_image().save(ASSETS / "wizard-image.bmp", format="BMP")
    _wizard_small().save(ASSETS / "wizard-small.bmp", format="BMP")
    print("Generated Windows EXE, setup, wizard and shortcut icons from the exact README logo source.")


if __name__ == "__main__":
    main()
