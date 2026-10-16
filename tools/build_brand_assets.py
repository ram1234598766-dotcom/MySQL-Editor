"""Generate Windows app icon and Inno Setup wizard artwork from the supplied logo."""
from __future__ import annotations

import sys
from pathlib import Path

from PIL import Image, ImageOps, UnidentifiedImageError

ROOT = Path(__file__).resolve().parents[1]
ASSETS = ROOT / "assets"
SOURCE = ASSETS / "mysql-editor-logo.webp"
ICON_OUTPUT = ASSETS / "mysql-editor.ico"
WIZARD_IMAGE_OUTPUT = ASSETS / "wizard-image.bmp"
WIZARD_SMALL_OUTPUT = ASSETS / "wizard-small.bmp"
ICON_SIZES = (16, 24, 32, 48, 64, 128, 256)
WIZARD_IMAGE_SIZE = (164, 314)
WIZARD_SMALL_SIZE = (55, 55)
BACKGROUND = (11, 24, 42)


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

    square = _center_crop_square(source_image)
    icon_output = output_dir / ICON_OUTPUT.name
    square.save(icon_output, format="ICO", sizes=[(size, size) for size in ICON_SIZES])
    with Image.open(icon_output) as icon:
        actual = set(icon.ico.sizes())
    if actual != {(size, size) for size in ICON_SIZES}:
        raise RuntimeError(f"Unexpected ICO frames: {sorted(actual)}")

    wizard_output = output_dir / WIZARD_IMAGE_OUTPUT.name
    _composite_centered(source_image, WIZARD_IMAGE_SIZE, (128, 128)).save(
        wizard_output, format="BMP"
    )
    small_output = output_dir / WIZARD_SMALL_OUTPUT.name
    _composite_centered(source_image, WIZARD_SMALL_SIZE, WIZARD_SMALL_SIZE).save(
        small_output, format="BMP"
    )

    with Image.open(wizard_output) as panel:
        if panel.size != WIZARD_IMAGE_SIZE:
            raise RuntimeError(f"Wrong wizard panel size: {panel.size}")
    with Image.open(small_output) as small:
        if small.size != WIZARD_SMALL_SIZE:
            raise RuntimeError(f"Wrong wizard badge size: {small.size}")

    return {
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
