#!/usr/bin/env python3
"""Keep Android's launcher drawable byte-for-byte identical to the shared logo master."""
from __future__ import annotations
from pathlib import Path
import shutil
from PIL import Image

ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "assets" / "mysql-editor-logo.webp"
ANDROID_RESOURCE = (
    ROOT / "android-app" / "app" / "src" / "main" / "res"
    / "drawable-nodpi" / "ic_mysqlidle_logo.webp"
)

def main() -> None:
    if not SOURCE.is_file():
        raise FileNotFoundError(f"Required high-resolution app logo is missing: {SOURCE}")
    with Image.open(SOURCE) as image:
        if image.format != "WEBP" or image.size != (256, 256):
            raise RuntimeError(f"Shared logo must be a 256x256 WebP; got {image.format} {image.size}.")
    ANDROID_RESOURCE.parent.mkdir(parents=True, exist_ok=True)
    source_bytes = SOURCE.read_bytes()
    if not ANDROID_RESOURCE.is_file() or ANDROID_RESOURCE.read_bytes() != source_bytes:
        shutil.copyfile(SOURCE, ANDROID_RESOURCE)
    if ANDROID_RESOURCE.read_bytes() != source_bytes:
        raise RuntimeError("Android drawable does not exactly match assets/mysql-editor-logo.webp")
    with Image.open(ANDROID_RESOURCE) as generated:
        if generated.format != "WEBP" or generated.size != (256, 256):
            raise RuntimeError("Android drawable is not the required 256x256 WebP.")
    print("Android uses the exact 256x256 shared WebP logo; no JPEG re-encoding or upscaling.")

if __name__ == "__main__":
    main()
