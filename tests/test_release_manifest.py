"""Regression coverage for Windows release provenance."""
from __future__ import annotations

import hashlib
import json
import zipfile
from pathlib import Path

import pytest

from tools.create_release_manifest import REQUIRED_ARTIFACTS, build_release_manifest


def _release_fixture(tmp_path: Path) -> tuple[Path, Path]:
    project_root = tmp_path / "project"
    project_root.mkdir()
    (project_root / "pyproject.toml").write_text(
        '[project]\nname = "mysql-editor"\nversion = "1.2.3"\n',
        encoding="utf-8",
    )
    dist = tmp_path / "dist"
    dist.mkdir()

    for relative_path, _role in REQUIRED_ARTIFACTS:
        path = dist / relative_path
        path.parent.mkdir(parents=True, exist_ok=True)
        if path.suffix.casefold() == ".exe":
            path.write_bytes(b"MZ" + b"E" * 100_000)
        elif relative_path == "MySQLEditor-Folder.zip":
            with zipfile.ZipFile(path, "w", compression=zipfile.ZIP_STORED) as archive:
                archive.writestr("MySQLEditor.exe", b"MZ" + b"E" * 100_000)
                archive.writestr("package-data.bin", b"D" * 1_050_000)
        elif relative_path == "sbom.cdx.json":
            path.write_text(
                json.dumps(
                    {
                        "bomFormat": "CycloneDX",
                        "specVersion": "1.6",
                        "version": 1,
                        "components": [],
                    }
                ),
                encoding="utf-8",
            )
        else:
            path.write_text(f"fixture for {relative_path}\n", encoding="utf-8")
    return project_root, dist


def test_manifest_records_exact_commit_version_and_artifact_hashes(tmp_path: Path):
    project_root, dist = _release_fixture(tmp_path)
    commit = "A" * 40

    manifest = build_release_manifest(dist, commit, project_root=project_root)

    assert manifest["schema_version"] == 1
    assert manifest["product"] == {"name": "MySQL Editor", "version": "1.2.3"}
    assert manifest["source"]["commit_sha"] == "a" * 40
    assert manifest["signing"]["status"] == "unsigned"
    assert manifest["signing"]["authenticode_verified"] is False
    assert len(manifest["artifacts"]) == len(REQUIRED_ARTIFACTS)
    for record in manifest["artifacts"]:
        artifact_path = dist / record["path"]
        assert record["size_bytes"] == artifact_path.stat().st_size
        assert record["sha256"] == hashlib.sha256(artifact_path.read_bytes()).hexdigest()


def test_manifest_rejects_a_missing_release_asset(tmp_path: Path):
    project_root, dist = _release_fixture(tmp_path)
    (dist / "installer" / "MySQLEditor-Setup.exe").unlink()

    with pytest.raises(ValueError, match="Required release artifact is missing"):
        build_release_manifest(dist, "b" * 40, project_root=project_root)


def test_manifest_rejects_an_invalid_source_sha(tmp_path: Path):
    project_root, dist = _release_fixture(tmp_path)

    with pytest.raises(ValueError, match="full 40-character Git SHA"):
        build_release_manifest(dist, "main", project_root=project_root)


def test_manifest_rejects_an_incomplete_executable(tmp_path: Path):
    project_root, dist = _release_fixture(tmp_path)
    (dist / "MySQLEditor-Portable.exe").write_bytes(b"MZ")

    with pytest.raises(ValueError, match="Executable looks incomplete"):
        build_release_manifest(dist, "c" * 40, project_root=project_root)


def test_manifest_rejects_a_non_cyclonedx_sbom(tmp_path: Path):
    project_root, dist = _release_fixture(tmp_path)
    (dist / "sbom.cdx.json").write_text('{"format": "json"}', encoding="utf-8")

    with pytest.raises(ValueError, match="not identified as CycloneDX"):
        build_release_manifest(dist, "d" * 40, project_root=project_root)
