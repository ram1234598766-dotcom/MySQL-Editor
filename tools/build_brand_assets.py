"""Generate Windows app icon and Inno Setup wizard artwork from the supplied logo."""
from __future__ import annotations

import sys
from collections import deque
from pathlib import Path

from PIL import Image, ImageOps, UnidentifiedImageError

ROOT = Path(__file__).resolve().parents[1]
ASSETS = ROOT / "assets"
SOURCE = ASSETS / "mysql-editor-logo.webp"
TRANSPARENT_LOGO_NAME = "mysql-editor-logo-transparent.png"
ICON_OUTPUT = ASSETS / "mysql-editor.ico"
WIZARD_IMAGE_OUTPUT = ASSETS / "wizard-image.bmp"
WIZARD_SMALL_OUTPUT = ASSETS / "wizard-small.bmp"
ICON_SIZES = (16, 24, 32, 48, 64, 128, 256)
WIZARD_IMAGE_SIZE = (164, 314)
WIZARD_SMALL_SIZE = (55, 55)
BACKGROUND = (11, 24, 42)


def remove_edge_connected_light_background(image: Image.Image) -> Image.Image:
    """Remove only near-white/neutral pixels connected to the image boundary.

    White artwork enclosed by the logo's foreground is preserved. This produces an
    alpha-bearing PNG for UI surfaces while leaving the supplied original untouched.
    """
    rgba = image.convert("RGBA")
    width, height = rgba.size
    pixels = rgba.load()
    visited = bytearray(width * height)
    queue: deque[tuple[int, int]] = deque()

    def is_background_candidate(x: int, y: int) -> bool:
        red, green, blue, alpha = pixels[x, y]
        return (
            alpha > 0
            and min(red, green, blue) >= 232
            and max(red, green, blue) - min(red, green, blue) <= 24
        )

    def add_if_background(x: int, y: int) -> None:
        index = y * width + x
        if not visited[index] and is_background_candidate(x, y):
            visited[index] = 1
            queue.append((x, y))

    for x in range(width):
        add_if_background(x, 0)
        add_if_background(x, height - 1)
    for y in range(height):
        add_if_background(0, y)
        add_if_background(width - 1, y)

    while queue:
        x, y = queue.popleft()
        for nx, ny in ((x - 1, y), (x + 1, y), (x, y - 1), (x, y + 1)):
            if 0 <= nx < width and 0 <= ny < height:
                add_if_background(nx, ny)

    # Clear the connected matte and defringe almost-white antialias pixels touching it.
    for y in range(height):
        for x in range(width):
            index = y * width + x
            if visited[index]:
                pixels[x, y] = (0, 0, 0, 0)
                continue
            red, green, blue, alpha = pixels[x, y]
            if alpha == 0:
                continue
            if min(red, green, blue) >= 220 and max(red, green, blue) - min(red, green, blue) <= 24:
                touches_clear = any(
                    0 <= nx < width and 0 <= ny < height and visited[ny * width + nx]
                    for nx, ny in (
                        (x - 1, y), (x + 1, y), (x, y - 1), (x, y + 1),
                        (x - 1, y - 1), (x + 1, y - 1), (x - 1, y + 1), (x + 1, y + 1),
                    )
                )
                if touches_clear:
                    luminance = min(red, green, blue)
                    new_alpha = max(0, min(255, round((255 - luminance) * 255 / 35)))
                    if new_alpha < 255:
                        pixels[x, y] = (red, green, blue, new_alpha)

    return rgba


def _center_crop_square(image: Image.Image) -> Image.Image:
    if image.width == image.height:
        return image
    side = min(image.size)
    left = (image.width - side) // 2
    top = (image.height - side) // 2
    return image.crop((left, top, left + side, top + side))


def _composite_centered(master: Image.Image, canvas_size: tuple[int, int],
                        logo_bounds: tuple[int, int]) -> Image.Image:
    canvas = Image.new("RGB", canvas_size, BACKGROUND)
    mark = ImageOps.contain(master, logo_bounds, method=Image.Resampling.LANCZOS)
    x = (canvas_size[0] - mark.width) // 2
    y = (canvas_size[1] - mark.height) // 2
    canvas.paste(mark, (x, y), mark if mark.mode == "RGBA" else None)
    return canvas


def build_brand_assets(source: Path = SOURCE, output_dir: Path = ASSETS) -> dict[str, Path]:
    """Generate assets without altering the source logo artwork."""
    if not source.is_file():
        raise FileNotFoundError(f"Missing supplied logo source: {source}")
    try:
        with Image.open(source) as original:
            original.load()
            if original.width < 128 or original.height < 128:
                raise ValueError(
                    f"Logo master is only {original.width}x{original.height}; "
                    "a source at least 128x128 is required for Windows icon generation."
                )
            source_image = ImageOps.exif_transpose(original).convert("RGBA")
    except (OSError, UnidentifiedImageError) as exc:
        raise ValueError(f"Could not load logo artwork: {exc}") from exc

    output_dir.mkdir(parents=True, exist_ok=True)

    transparent_logo = remove_edge_connected_light_background(source_image)
    transparent_output = output_dir / TRANSPARENT_LOGO_NAME
    transparent_logo.save(transparent_output, format="PNG", optimize=True)

    square = _center_crop_square(transparent_logo)
    icon_output = output_dir / ICON_OUTPUT.name
    square.save(icon_output, format="ICO", sizes=[(size, size) for size in ICON_SIZES])
    with Image.open(icon_output) as icon:
        actual = set(icon.ico.sizes())
    if actual != {(size, size) for size in ICON_SIZES}:
        raise RuntimeError(f"Unexpected ICO frames: {sorted(actual)}")

    wizard_output = output_dir / WIZARD_IMAGE_OUTPUT.name
    _composite_centered(transparent_logo, WIZARD_IMAGE_SIZE, (128, 128)).save(
        wizard_output, format="BMP"
    )
    small_output = output_dir / WIZARD_SMALL_OUTPUT.name
    _composite_centered(transparent_logo, WIZARD_SMALL_SIZE, WIZARD_SMALL_SIZE).save(
        small_output, format="BMP"
    )

    with Image.open(wizard_output) as panel:
        if panel.size != WIZARD_IMAGE_SIZE:
            raise RuntimeError(f"Wrong wizard panel size: {panel.size}")
    with Image.open(small_output) as small:
        if small.size != WIZARD_SMALL_SIZE:
            raise RuntimeError(f"Wrong wizard badge size: {small.size}")

    return {
        "transparent_logo": transparent_output,
        "icon": icon_output,
        "wizard_image": wizard_output,
        "wizard_small": small_output,
    }


def main() -> int:
    try:
        outputs = build_brand_assets()
    except (FileNotFoundError, ValueError, RuntimeError) as exc:
        print(f"Brand asset generation failed: {exc}", file=sys.stderr)
        return 2
    for name, path in outputs.items():
        print(f"Created {name}: {path}")
    print(f"ICO frames: {list(ICON_SIZES)}")
    print(f"Wizard artwork: {WIZARD_IMAGE_SIZE} and {WIZARD_SMALL_SIZE}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
