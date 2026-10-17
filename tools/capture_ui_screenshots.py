"""Generate synthetic-only screenshots for simulated Windows Qt display scales.

The images validate rendered Qt layout/scaling in the Windows CI runner. They are not
physical-monitor captures and must not be treated as proof of every Windows DPI setup.
"""
from __future__ import annotations

import json
import os
import struct
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SMOKE_TEST = ROOT / "tools" / "smoke_test_ui.py"
OUTPUT_DIR = ROOT / "dist" / "ui-visual-qa"
THEMES = ("dark", "light")
SCALES = (
    ("100-percent", "1.0"),
    ("125-percent", "1.25"),
    ("150-percent", "1.5"),
    ("200-percent", "2.0"),
)


def read_png_dimensions(path: Path) -> tuple[int, int]:
    """Read PNG dimensions from the IHDR header without an image library."""
    header = path.read_bytes()[:24]
    if (
        len(header) < 24
        or header[:8] != b"\x89PNG\r\n\x1a\n"
        or header[12:16] != b"IHDR"
    ):
        raise RuntimeError(f"Screenshot is not a valid PNG: {path}")
    width, height = struct.unpack(">II", header[16:24])
    if width <= 0 or height <= 0:
        raise RuntimeError(f"Screenshot has invalid dimensions: {path}")
    return width, height


def main() -> None:
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    manifest = {
        "capture_mode": "Windows GitHub Actions runner using the native Qt Windows platform",
        "scale_method": "QT_SCALE_FACTOR on native Qt Windows platform",
        "themes": list(THEMES),
        "note": (
            "Simulated Qt scale factors only. These screenshots are not physical-monitor "
            "captures and do not replace hands-on Windows DPI review. All grid rows are "
            "synthetic; no MySQL connection is opened."
        ),
        "screenshots": [],
    }
    for theme_name in THEMES:
        for label, factor in SCALES:
            output = OUTPUT_DIR / f"mysql-editor-{theme_name}-{label}.png"
            env = os.environ.copy()
            env["QT_QPA_PLATFORM"] = "windows"
            env["QT_SCALE_FACTOR"] = factor
            env["QT_ENABLE_HIGHDPI_SCALING"] = "1"
            env["MYSQL_EDITOR_CAPTURE_PATH"] = str(output)
            env["MYSQL_EDITOR_EXPECTED_SCALE"] = factor
            env["MYSQL_EDITOR_EXPECTED_THEME"] = theme_name
            # Fixed interpreter and repo-owned script; no shell or external command input.
            subprocess.run(  # noqa: S603
                [sys.executable, str(SMOKE_TEST)],
                cwd=ROOT,
                env=env,
                check=True,
                timeout=180,
            )
            if not output.is_file() or output.stat().st_size < 10_000:
                raise RuntimeError(f"Screenshot output is missing or too small: {output}")
            width, height = read_png_dimensions(output)
            record = {
                "file": output.name,
                "theme": theme_name,
                "requested_scale": float(factor),
                "png_width_px": width,
                "png_height_px": height,
                "file_size_bytes": output.stat().st_size,
            }
            manifest["screenshots"].append(record)
            print(
                f"{output.name}: theme={theme_name}, requested={factor}x, "
                f"image={width}x{height}, bytes={output.stat().st_size}"
            )

    manifest_path = OUTPUT_DIR / "manifest.json"
    manifest_path.write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    print(f"Visual QA manifest written: {manifest_path}")


if __name__ == "__main__":
    main()
