"""Build a provenance manifest for the exact Windows release packages.

The manifest is generated after packaging and before SHA256SUMS. The checksum
file includes this manifest; the manifest lists package inputs except itself
and SHA256SUMS to avoid a circular hash dependency.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import platform
import re
import sys
import tomllib
import zipfile
from datetime import datetime, timezone
from pathlib import Path, PurePosixPath
from typing import Any

REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
MINIMUM_EXECUTABLE_BYTES = 100_000
MINIMUM_FOLDER_ARCHIVE_BYTES = 1_000_000
COMMIT_SHA_PATTERN = re.compile(r"^[0-9a-fA-F]{40}$")

# Paths are relative to dist and use POSIX separators in the JSON manifest.
REQUIRED_ARTIFACTS: tuple[tuple[str, str], ...] = (
    ("MySQLEditor/MySQLEditor.exe", "application-folder executable"),
    ("MySQLEditor-Portable.exe", "portable executable"),
    ("installer/MySQLEditor-Setup.exe", "Windows installer"),
    ("MySQLEditor-Folder.zip", "application-folder archive"),
    ("sbom.cdx.json", "CycloneDX software bill of materials"),
    ("RELEASE-NOTES.md", "release notes"),
    ("WINDOWS_SIGNING.md", "Windows signing disclosure"),
    ("THIRD_PARTY_LICENSES.md", "third-party license inventory"),
)


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _project_version(project_root: Path) -> str:
    pyproject = project_root / "pyproject.toml"
    with pyproject.open("rb") as handle:
        metadata = tomllib.load(handle)
    version = metadata.get("project", {}).get("version")
    if not isinstance(version, str) or not version.strip():
        raise ValueError(f"Missing [project].version in {pyproject}")
    return version.strip()


def _validate_folder_archive(path: Path) -> None:
    try:
        with zipfile.ZipFile(path) as archive:
            corrupt_member = archive.testzip()
            if corrupt_member is not None:
                raise ValueError(f"Folder ZIP contains a corrupt member: {corrupt_member}")
            if not any(
                PurePosixPath(member).name.casefold() == "mysqleditor.exe"
                for member in archive.namelist()
            ):
                raise ValueError("Folder ZIP does not contain MySQLEditor.exe")
    except zipfile.BadZipFile as exc:
        raise ValueError("Folder archive is not a valid ZIP file") from exc


def build_release_manifest(
    dist_dir: str | Path,
    commit_sha: str,
    *,
    project_root: str | Path | None = None,
) -> dict[str, Any]:
    """Validate required outputs and return JSON-compatible build provenance."""
    dist_path = Path(dist_dir)
    project_path = Path(project_root) if project_root is not None else REPOSITORY_ROOT
    normalized_sha = commit_sha.strip().lower()
    if not COMMIT_SHA_PATTERN.fullmatch(normalized_sha):
        raise ValueError("Source commit must be a full 40-character Git SHA")
    if not dist_path.is_dir():
        raise ValueError(f"Distribution directory does not exist: {dist_path}")

    files: list[dict[str, Any]] = []
    for relative_path, role in REQUIRED_ARTIFACTS:
        artifact_path = dist_path / Path(relative_path)
        if not artifact_path.is_file():
            raise ValueError(f"Required release artifact is missing: {relative_path}")
        size_bytes = artifact_path.stat().st_size
        if artifact_path.suffix.casefold() == ".exe" and size_bytes < MINIMUM_EXECUTABLE_BYTES:
            raise ValueError(f"Executable looks incomplete: {relative_path} ({size_bytes} bytes)")
        if relative_path == "MySQLEditor-Folder.zip":
            if size_bytes < MINIMUM_FOLDER_ARCHIVE_BYTES:
                raise ValueError(f"Folder archive looks incomplete ({size_bytes} bytes)")
            _validate_folder_archive(artifact_path)
        files.append(
            {
                "path": PurePosixPath(relative_path).as_posix(),
                "name": artifact_path.name,
                "role": role,
                "size_bytes": size_bytes,
                "sha256": _sha256(artifact_path),
            }
        )

    sbom_path = dist_path / "sbom.cdx.json"
    try:
        sbom = json.loads(sbom_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise ValueError("CycloneDX SBOM is not valid JSON") from exc
    if not isinstance(sbom, dict) or sbom.get("bomFormat") != "CycloneDX":
        raise ValueError("SBOM is not identified as CycloneDX")

    return {
        "schema_version": 1,
        "product": {
            "name": "MySQL Editor",
            "version": _project_version(project_path),
        },
        "source": {"commit_sha": normalized_sha},
        "build": {
            "target": "Windows 10/11 x64",
            "runner_os": os.environ.get("RUNNER_OS", platform.system()),
            "runner_architecture": os.environ.get("RUNNER_ARCH", platform.machine()),
            "python_version": platform.python_version(),
            "generated_at_utc": (
                datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")
            ),
        },
        "signing": {
            "status": "unsigned",
            "authenticode_verified": False,
            "details": "The configured Windows workflow does not sign these artifacts.",
        },
        "artifacts": files,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dist", type=Path, default=Path("dist"), help="package output directory")
    parser.add_argument(
        "--commit",
        default=os.environ.get("GITHUB_SHA", ""),
        help="full source commit SHA (defaults to GITHUB_SHA)",
    )
    parser.add_argument(
        "--project-root",
        type=Path,
        default=REPOSITORY_ROOT,
        help="directory containing pyproject.toml",
    )
    args = parser.parse_args(argv)
    if not args.commit:
        parser.error("--commit is required when GITHUB_SHA is not set")

    try:
        manifest = build_release_manifest(args.dist, args.commit, project_root=args.project_root)
        destination = args.dist / "RELEASE-MANIFEST.json"
        temporary = destination.with_suffix(destination.suffix + ".tmp")
        temporary.write_text(
            json.dumps(manifest, indent=2, ensure_ascii=False, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        temporary.replace(destination)
    except (OSError, ValueError, tomllib.TOMLDecodeError) as exc:
        print(f"Release manifest validation failed: {exc}", file=sys.stderr)
        return 2

    print(
        f"Created {destination} for commit {manifest['source']['commit_sha']} "
        f"({len(manifest['artifacts'])} validated artifacts; signing: unsigned)."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
