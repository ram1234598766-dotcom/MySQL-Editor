"""Generate crisp, transparent Windows branding assets from the supplied master logo."""
from __future__ import annotations

import sys
from collections import deque
from pathlib import Path
from statistics import median

from PIL import Image, ImageChops, ImageDraw, ImageFilter, ImageOps, UnidentifiedImageError

ROOT = Path(__file__).resolve().parents[1]
ASSETS = ROOT / "assets"
SOURCE = ASSETS / "mysql-editor-logo.webp"
TRANSPARENT_LOGO_NAME = "mysql-editor-logo-transparent.png"
ICON_OUTPUT = ASSETS / "mysql-editor.ico"
WIZARD_IMAGE_OUTPUT = ASSETS / "wizard-image.bmp"
WIZARD_SMALL_OUTPUT = ASSETS / "wizard-small.bmp"
ICON_SIZES = (16, 24, 32, 48, 64, 128, 256)
ICON_MASTER_SIZE = 512
WIZARD_IMAGE_SIZE = (164, 314)
WIZARD_SMALL_SIZE = (55, 55)
BACKGROUND = (11, 24, 42)
LIGHT_BACKGROUND_MIN_CHANNEL = 125
LIGHT_BACKGROUND_MIN_BRIGHTNESS = 170
LIGHT_BACKGROUND_MAX_CHROMA = 85
BADGE_ANCHOR_BRIGHTNESS = 160
BADGE_ANCHOR_CHROMA = 85
BADGE_PADDING_RATIO = 0.035
BADGE_CORNER_RADIUS_RATIO = 0.155
ICON_SHARPEN_RADIUS = 0.65
ICON_SHARPEN_PERCENT = 115
ICON_SHARPEN_THRESHOLD = 2


def _rgb_brightness(rgb: tuple[int, int, int]) -> float:
    return sum(rgb) / 3


def _rgb_chroma(rgb: tuple[int, int, int]) -> int:
    return max(rgb) - min(rgb)


def _light_background_candidate(r: int, g: int, b: int, alpha: int = 255) -> bool:
    """Recognize the supplied light neutral matte and its soft, low-chroma shadow."""
    rgb = (r, g, b)
    return (
        alpha > 0
        and min(rgb) >= LIGHT_BACKGROUND_MIN_CHANNEL
        and _rgb_brightness(rgb) >= LIGHT_BACKGROUND_MIN_BRIGHTNESS
        and _rgb_chroma(rgb) <= LIGHT_BACKGROUND_MAX_CHROMA
    )


def _estimate_border_matte(image: Image.Image) -> tuple[int, int, int]:
    rgba = image.convert("RGBA")
    width, height = rgba.size
    pixels = rgba.load()
    channels: list[list[int]] = [[], [], []]
    for x in range(width):
        for y in (0, height - 1):
            r, g, b, alpha = pixels[x, y]
            if _light_background_candidate(r, g, b, alpha):
                for i, value in enumerate((r, g, b)):
                    channels[i].append(value)
    for y in range(height):
        for x in (0, width - 1):
            r, g, b, alpha = pixels[x, y]
            if _light_background_candidate(r, g, b, alpha):
                for i, value in enumerate((r, g, b)):
                    channels[i].append(value)
    if not all(channels):
        return (250, 252, 252)
    return tuple(round(median(values)) for values in channels)  # type: ignore[return-value]


def remove_edge_connected_light_background(image: Image.Image) -> Image.Image:
    """Remove edge-connected light matte/shadow while preserving enclosed white art.

    Eight-way connectivity prevents diagonal antialias pixels leaving white flecks.
    Edge pixels are unmatted against the sampled border color to avoid pale fringes
    when the transparent image is placed on the application's dark surfaces.
    """
    rgba = image.convert("RGBA")
    width, height = rgba.size
    pixels = rgba.load()
    visited = bytearray(width * height)
    queue: deque[tuple[int, int]] = deque()

    def add_if_background(x: int, y: int) -> None:
        index = y * width + x
        if visited[index]:
            return
        r, g, b, alpha = pixels[x, y]
        if _light_background_candidate(r, g, b, alpha):
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
        for dy in (-1, 0, 1):
            for dx in (-1, 0, 1):
                if not (dx or dy):
                    continue
                nx, ny = x + dx, y + dy
                if 0 <= nx < width and 0 <= ny < height:
                    add_if_background(nx, ny)

    matte = _estimate_border_matte(rgba)
    # Use a stable snapshot for matting math; output edits must not affect later pixels.
    source_pixels = rgba.copy().load()
    for y in range(height):
        for x in range(width):
            index = y * width + x
            r, g, b, alpha = source_pixels[x, y]
            if visited[index]:
                pixels[x, y] = (0, 0, 0, 0)
                continue
            if alpha == 0 or _rgb_brightness((r, g, b)) < 145:
                continue

            foreground_neighbors: list[tuple[int, int, int]] = []
            touches_clear = False
            for dy in (-1, 0, 1):
                for dx in (-1, 0, 1):
                    if not (dx or dy):
                        continue
                    nx, ny = x + dx, y + dy
                    if not (0 <= nx < width and 0 <= ny < height):
                        continue
                    nindex = ny * width + nx
                    nr, ng, nb, na = source_pixels[nx, ny]
                    if visited[nindex] or na == 0:
                        touches_clear = True
                    elif (
                        _rgb_brightness((nr, ng, nb)) < 175
                        or _rgb_chroma((nr, ng, nb)) > 75
                    ):
                        foreground_neighbors.append((nr, ng, nb))

            if not touches_clear or not foreground_neighbors or _rgb_chroma((r, g, b)) > 100:
                continue
            observed = (r, g, b)
            foreground = max(
                foreground_neighbors,
                key=lambda rgb: sum((matte[i] - rgb[i]) ** 2 for i in range(3)),
            )
            bg_to_pixel = tuple(matte[i] - observed[i] for i in range(3))
            bg_to_foreground = tuple(matte[i] - foreground[i] for i in range(3))
            denominator = sum(value * value for value in bg_to_foreground)
            alpha_fraction = (
                sum(bg_to_pixel[i] * bg_to_foreground[i] for i in range(3)) / denominator
                if denominator else 1.0
            )
            alpha_fraction = max(0.0, min(1.0, alpha_fraction))
            if alpha_fraction < 0.10:
                pixels[x, y] = (0, 0, 0, 0)
            elif alpha_fraction < 0.97:
                unmatte = tuple(
                    max(
                        0,
                        min(
                            255,
                            round(
                                (observed[i] - (1 - alpha_fraction) * matte[i])
                                / alpha_fraction
                            ),
                        ),
                    )
                    for i in range(3)
                )
                pixels[x, y] = (*unmatte, round(alpha_fraction * 255))

    return rgba


def _detect_badge_bounds(image: Image.Image) -> tuple[int, int, int, int]:
    """Find the dark/saturated app badge, ignoring pale padding and drop shadow."""
    rgb = image.convert("RGB")
    pixels = rgb.load()
    left, top, right, bottom = rgb.width, rgb.height, -1, -1
    for y in range(rgb.height):
        for x in range(rgb.width):
            r, g, b = pixels[x, y]
            value = (r, g, b)
            brightness = _rgb_brightness(value)
            chroma = _rgb_chroma(value)
            if brightness < BADGE_ANCHOR_BRIGHTNESS or (
                chroma > BADGE_ANCHOR_CHROMA and brightness < 225
            ):
                left = min(left, x)
                top = min(top, y)
                right = max(right, x + 1)
                bottom = max(bottom, y + 1)
    if right <= left or bottom <= top:
        raise ValueError("Could not find the dark/saturated MySQL Editor badge in the source logo.")
    width, height = right - left, bottom - top
    if min(width, height) < 64 or not 0.72 <= width / height <= 1.38:
        raise ValueError(
            f"Detected badge bounds {width}x{height} are implausible; refusing to build a bad app icon."
        )
    return left, top, right, bottom


def _crop_badge_to_transparent_square(source: Image.Image, cleaned: Image.Image) -> Image.Image:
    """Isolate the rounded-square artwork; discard banner padding and the outer shadow."""
    left, top, right, bottom = _detect_badge_bounds(source)
    badge = cleaned.crop((left, top, right, bottom))
    side = max(badge.size)
    if badge.size != (side, side):
        # Correct the slight aspect distortion from the promotional source so the app
        # icon is truly square instead of looking soft or squeezed in Windows.
        badge = badge.resize((side, side), Image.Resampling.LANCZOS)

    shape = Image.new("L", (side, side), 0)
    draw = ImageDraw.Draw(shape)
    radius = max(1, round(side * BADGE_CORNER_RADIUS_RATIO))
    draw.rounded_rectangle((0, 0, side - 1, side - 1), radius=radius, fill=255)
    badge.putalpha(ImageChops.multiply(badge.getchannel("A"), shape))

    badge_pixels = badge.load()
    for y in range(side):
        for x in range(side):
            r, g, b, alpha = badge_pixels[x, y]
            # These tiny pale-alpha JPEG interpolation samples vanish visually but can
            # turn into white flecks in small ICO frames, so make them fully transparent.
            if alpha <= 8:
                badge_pixels[x, y] = (0, 0, 0, 0)

    padding = max(4, round(side * BADGE_PADDING_RATIO))
    output = Image.new("RGBA", (side + padding * 2, side + padding * 2), (0, 0, 0, 0))
    output.alpha_composite(badge, (padding, padding))
    output_pixels = output.load()
    for y in range(output.height):
        for x in range(output.width):
            if output_pixels[x, y][3] == 0:
                output_pixels[x, y] = (0, 0, 0, 0)
    return output


def _sharpen_without_halo(image: Image.Image) -> Image.Image:
    """Sharpen RGB detail slightly while keeping the cleaned alpha channel unchanged."""
    rgba = image.convert("RGBA")
    alpha = rgba.getchannel("A")
    rgb = rgba.convert("RGB").filter(
        ImageFilter.UnsharpMask(
            radius=ICON_SHARPEN_RADIUS,
            percent=ICON_SHARPEN_PERCENT,
            threshold=ICON_SHARPEN_THRESHOLD,
        )
    )
    rgb.putalpha(alpha)
    return rgb


def _composite_centered(
    master: Image.Image,
    canvas_size: tuple[int, int],
    logo_bounds: tuple[int, int],
) -> Image.Image:
    canvas = Image.new("RGB", canvas_size, BACKGROUND)
    mark = ImageOps.contain(master, logo_bounds, method=Image.Resampling.LANCZOS)
    x = (canvas_size[0] - mark.width) // 2
    y = (canvas_size[1] - mark.height) // 2
    canvas.paste(mark, (x, y), mark if mark.mode == "RGBA" else None)
    return canvas


def build_brand_assets(source: Path = SOURCE, output_dir: Path = ASSETS) -> dict[str, Path]:
    """Generate app, installer and UI assets without altering the source artwork."""
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

    # Clean the matte first, then crop to the actual badge instead of center-cropping
    # the full promotional canvas. This keeps the mark large and removes white halos.
    cleaned = remove_edge_connected_light_background(source_image)
    transparent_logo = _crop_badge_to_transparent_square(source_image, cleaned)
    transparent_output = output_dir / TRANSPARENT_LOGO_NAME
    transparent_logo.save(transparent_output, format="PNG", optimize=True)

    icon_master = transparent_logo.resize(
        (ICON_MASTER_SIZE, ICON_MASTER_SIZE), Image.Resampling.LANCZOS
    )
    icon_master = _sharpen_without_halo(icon_master)
    icon_output = output_dir / ICON_OUTPUT.name
    icon_master.save(icon_output, format="ICO", sizes=[(size, size) for size in ICON_SIZES])
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
