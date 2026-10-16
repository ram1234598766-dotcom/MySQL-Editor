#!/usr/bin/env python3
"""Copy the supplied MySQL Editor logo into the Android drawable resource."""
from __future__ import annotations

from pathlib import Path
import shutil

ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "assets" / "mysql-editor-logo.jpg"
ANDROID_RESOURCE = (
    ROOT / "android-app" / "app" / "src" / "main" / "res"
    / "drawable-nodpi" / "ic_mysqlidle_logo.jpg"
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
        raise RuntimeError("Android logo resource does not exactly match assets/mysql-editor-logo.jpg")
    print("Android logo is byte-for-byte identical to assets/mysql-editor-logo.jpg (the new shared app logo).")


if __name__ == "__main__":
    main()
