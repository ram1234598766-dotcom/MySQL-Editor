from pathlib import Path

from PIL import Image, ImageDraw

from tools.build_brand_assets import (
    ICON_SIZES,
    WIZARD_IMAGE_SIZE,
    WIZARD_SMALL_SIZE,
    _crop_badge_to_transparent_square,
    build_brand_assets,
    remove_edge_connected_light_background,
)


def test_brand_asset_generator_preserves_source_and_creates_all_windows_assets(tmp_path: Path):
    source = Path(__file__).resolve().parents[1] / "assets" / "mysql-editor-logo.webp"
    with Image.open(source) as original:
        original.load()
        original_bytes = original.tobytes()
        assert original.width >= 128 and original.height >= 128

    files = build_brand_assets(source=source, output_dir=tmp_path)

    assert set(files) == {"transparent_logo", "icon", "wizard_image", "wizard_small"}
    with Image.open(files["transparent_logo"]) as clean_logo:
        assert clean_logo.format == "PNG"
        assert clean_logo.mode == "RGBA"
        assert clean_logo.width == clean_logo.height
        assert clean_logo.getchannel("A").getextrema()[0] == 0
        assert clean_logo.getpixel((0, 0))[3] == 0
        alpha_bounds = clean_logo.getchannel("A").getbbox()
        assert alpha_bounds is not None
        assert alpha_bounds[2] - alpha_bounds[0] >= clean_logo.width * 0.85
        assert alpha_bounds[3] - alpha_bounds[1] >= clean_logo.height * 0.85
    with Image.open(source) as current:
        assert current.tobytes() == original_bytes

    with Image.open(files["icon"]) as icon:
        assert icon.format == "ICO"
        assert icon.ico.sizes() == {(size, size) for size in ICON_SIZES}

    with Image.open(files["wizard_image"]) as panel:
        assert panel.format == "BMP"
        assert panel.size == WIZARD_IMAGE_SIZE

    with Image.open(files["wizard_small"]) as small:
        assert small.format == "BMP"
        assert small.size == WIZARD_SMALL_SIZE


def test_background_removal_preserves_enclosed_white_artwork():
    source = Image.new("RGBA", (64, 64), (255, 255, 255, 255))
    draw = ImageDraw.Draw(source)
    draw.rectangle((12, 12, 52, 52), fill=(26, 126, 220, 255))
    draw.rectangle((26, 26, 38, 38), fill=(255, 255, 255, 255))

    result = remove_edge_connected_light_background(source)

    assert result.getpixel((0, 0))[3] == 0
    assert result.getpixel((15, 15)) == (26, 126, 220, 255)
    assert result.getpixel((32, 32)) == (255, 255, 255, 255)


def test_background_removal_clears_soft_shadow_but_preserves_white_artwork():
    source = Image.new("RGBA", (96, 88), (247, 250, 251, 255))
    draw = ImageDraw.Draw(source)
    draw.rounded_rectangle((8, 8, 87, 79), radius=18, fill=(213, 226, 234, 255))
    draw.rounded_rectangle((13, 12, 82, 75), radius=14, fill=(26, 58, 94, 255))
    draw.rectangle((37, 36, 52, 51), fill=(255, 255, 255, 255))

    cleaned = remove_edge_connected_light_background(source)

    assert cleaned.getpixel((0, 0))[3] == 0
    assert cleaned.getpixel((9, 40))[3] == 0
    assert cleaned.getpixel((15, 40))[3] == 255
    assert cleaned.getpixel((44, 44)) == (255, 255, 255, 255)

    icon = _crop_badge_to_transparent_square(source, cleaned)
    assert icon.width == icon.height
    assert icon.getpixel((0, 0))[3] == 0
    assert any(
        icon.getpixel((x, y)) == (255, 255, 255, 255)
        for y in range(icon.height)
        for x in range(icon.width)
    )
