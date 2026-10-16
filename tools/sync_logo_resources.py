#!/usr/bin/env python3
"""Copy the untouched application logo into the Android drawable resource."""
from __future__ import annotations

from pathlib import Path
import shutil

ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "assets" / "mysqlidle-logo.png"
ANDROID_RESOURCE = (
    ROOT / "android-app" / "app" / "src" / "main" / "res"
    / "drawable-nodpi" / "ic_mysqlidle_logo.png"
)


def main() -> None:
    if not SOURCE.is_file():
        raise FileNotFoundError(f"Required original app logo is missing: {SOURCE}")
    ANDROID_RESOURCE.parent.mkdir(parents=True, exist_ok=True)
    source_bytes = SOURCE.read_bytes()
    target_bytes = ANDROID_RESOURCE.read_bytes() if ANDROID_RESOURCE.exists() else None
    if target_bytes != source_bytes:
        shutil.copyfile(SOURCE, ANDROID_RESOURCE)
    if ANDROID_RESOURCE.read_bytes() != source_bytes:
        raise RuntimeError("Android logo resource does not exactly match assets/mysqlidle-logo.png")
    print("Android logo is byte-for-byte identical to assets/mysqlidle-logo.png (no resizing or editing).")


if __name__ == "__main__":
    main()
