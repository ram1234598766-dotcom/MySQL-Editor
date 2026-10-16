from pathlib import Path

from PIL import Image

from tools.build_brand_assets import (
    ICON_SIZES,
    WIZARD_IMAGE_SIZE,
    WIZARD_SMALL_SIZE,
    build_brand_assets,
)


def test_brand_asset_generator_preserves_source_and_creates_all_windows_assets(tmp_path: Path):
    source = Path(__file__).resolve().parents[1] / "assets" / "mysql-editor-logo.webp"
    with Image.open(source) as original:
        original.load()
        original_bytes = original.tobytes()
        assert original.width >= 128 and original.height >= 128

    files = build_brand_assets(source=source, output_dir=tmp_path)

    assert set(files) == {"icon", "wizard_image", "wizard_small"}
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
