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

    assert manifest["schema_version"] == 2
    assert manifest["product"] == {"name": "MySQL Editor", "version": "1.2.3"}
    assert manifest["source"]["commit_sha"] == "a" * 40
    assert manifest["signing"]["status"] == "unsigned"
    assert manifest["signing"]["certificate_type"] is None
    assert manifest["signing"]["authenticode_verified"] is False
    assert manifest["signing"]["trust_scope"] == "none"
    assert manifest["signing"]["recipient_trust"] == "not-applicable"
    assert len(manifest["artifacts"]) == len(REQUIRED_ARTIFACTS)
    for record in manifest["artifacts"]:
        artifact_path = dist / record["path"]
        assert record["size_bytes"] == artifact_path.stat().st_size
        assert record["sha256"] == hashlib.sha256(artifact_path.read_bytes()).hexdigest()


def test_manifest_records_signed_status_only_after_verified_signature(tmp_path: Path):
    project_root, dist = _release_fixture(tmp_path)

    manifest = build_release_manifest(
        dist,
        "e" * 40,
        project_root=project_root,
        signing_status="signed",
        authenticode_verified=True,
        signing_certificate_type="self-signed",
    )

    assert manifest["signing"]["status"] == "signed"
    assert manifest["signing"]["certificate_type"] == "self-signed"
    assert manifest["signing"]["authenticode_verified"] is True
    assert manifest["signing"]["trust_scope"] == "build-runner-only"
    assert manifest["signing"]["recipient_trust"] == "not-trusted-by-default"
    assert "Recipient PCs do not trust this certificate by default" in manifest["signing"]["details"]
    assert manifest["signing"]["timestamp_authority"] == "http://timestamp.digicert.com"
    assert manifest["signing"]["verification_method"].startswith("Get-AuthenticodeSignature plus SignTool /verify /pa /all /v")
    assert "added to the build runner's current-user Root store and removed afterward" in manifest["signing"]["details"]


def test_manifest_rejects_signed_status_without_authenticode_verification(tmp_path: Path):
    project_root, dist = _release_fixture(tmp_path)

    with pytest.raises(ValueError, match="requires successful Authenticode verification"):
        build_release_manifest(
            dist,
            "f" * 40,
            project_root=project_root,
            signing_status="signed",
            authenticode_verified=False,
            signing_certificate_type="self-signed",
        )


def test_manifest_rejects_authenticode_claim_for_unsigned_assets(tmp_path: Path):
    project_root, dist = _release_fixture(tmp_path)

    with pytest.raises(ValueError, match="cannot claim Authenticode verification"):
        build_release_manifest(
            dist,
            "0" * 40,
            project_root=project_root,
            signing_status="unsigned",
            authenticode_verified=True,
        )


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

def test_manifest_records_trusted_certificate_mode_without_promising_smart_screen_behavior(tmp_path: Path):
    project_root, dist = _release_fixture(tmp_path)

    manifest = build_release_manifest(
        dist,
        "1" * 40,
        project_root=project_root,
        signing_status="signed",
        authenticode_verified=True,
        signing_certificate_type="trusted",
    )

    assert manifest["signing"]["certificate_type"] == "trusted"
    assert manifest["signing"]["trust_scope"] == "build-runner-windows-trust-policy"
    assert manifest["signing"]["recipient_trust"] == "depends-on-recipient-trust-store-and-reputation"
    assert "SmartScreen warnings are not ruled out" in manifest["signing"]["details"]


def test_manifest_rejects_signed_assets_without_certificate_type(tmp_path: Path):
    project_root, dist = _release_fixture(tmp_path)

    with pytest.raises(ValueError, match="requires a signing certificate type"):
        build_release_manifest(
            dist,
            "2" * 40,
            project_root=project_root,
            signing_status="signed",
            authenticode_verified=True,
        )


def test_manifest_rejects_certificate_type_for_unsigned_assets(tmp_path: Path):
    project_root, dist = _release_fixture(tmp_path)

    with pytest.raises(ValueError, match="cannot claim a signing certificate type"):
        build_release_manifest(
            dist,
            "3" * 40,
            project_root=project_root,
            signing_status="unsigned",
            authenticode_verified=False,
            signing_certificate_type="self-signed",
        )
