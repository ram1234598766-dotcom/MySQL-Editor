#!/usr/bin/env python3
"""Copy the supplied MySQL Editor logo into the Android drawable resource."""
from __future__ import annotations

from pathlib import Path
from PIL import Image, ImageFilter


ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "assets" / "mysql-editor-logo.jpg"
ANDROID_RESOURCE = (
    ROOT / "android-app" / "app" / "src" / "main" / "res"
    / "drawable-nodpi" / "ic_mysqlidle_logo.jpg"
)


def main() -> None:
    if not SOURCE.is_file():
        raise FileNotFoundError(f"Required app logo is missing: {SOURCE}")
    ANDROID_RESOURCE.parent.mkdir(parents=True, exist_ok=True)

    # Android launchers may scale icons to 192 px or more. Build a crisp,
    # square 256 px drawable from the shared source with a single Lanczos resize
    # and a restrained unsharp mask; retain the same composition and proportions.
    with Image.open(SOURCE) as source_image:
        logo = source_image.convert("RGB")
    logo = logo.resize((256, 256), Image.Resampling.LANCZOS)
    logo = logo.filter(ImageFilter.UnsharpMask(radius=0.55, percent=125, threshold=3))
    logo.save(ANDROID_RESOURCE, format="JPEG", quality=95, subsampling=0, optimize=True)

    with Image.open(ANDROID_RESOURCE) as generated:
        if generated.size != (256, 256) or generated.format != "JPEG":
            raise RuntimeError("Android logo must be a 256x256 high-quality JPEG drawable.")
    print("Generated crisp 256x256 Android launcher artwork from assets/mysql-editor-logo.jpg.")


if __name__ == "__main__":
    main()
