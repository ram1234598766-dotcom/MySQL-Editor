"""Regression checks for runtime and build-environment dependency audit coverage."""
from __future__ import annotations

import re
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def _read_workflow(relative_path: str) -> str:
    return (ROOT / relative_path).read_text(encoding="utf-8")


def test_security_workflow_audits_runtime_constraints_and_installed_tooling():
    workflow = _read_workflow(".github/workflows/security.yml")

    assert 'python -m pip install -e ".[dev]" pyinstaller pip-licenses' in workflow
    assert "python -m pip_audit -r requirements.txt" in workflow
    assert "run: python -m pip_audit\n" in workflow

    install_at = workflow.index("Install project, test, and packaging dependencies")
    runtime_audit_at = workflow.index("Audit declared runtime dependency constraints")
    environment_audit_at = workflow.index("Audit installed test and packaging environment")
    assert install_at < runtime_audit_at < environment_audit_at


def test_windows_release_audits_build_environment_before_packaging_and_keeps_runtime_sbom():
    workflow = _read_workflow(".github/workflows/windows-release.yml")

    install_at = workflow.index("Install runtime and build dependencies")
    environment_audit_at = workflow.index("Audit installed test and packaging environment")
    package_at = workflow.index("Build application folder")
    sbom_at = workflow.index("Generate CycloneDX dependency SBOM and stage release notes")

    assert "run: python -m pip_audit\n" in workflow
    assert install_at < environment_audit_at < package_at < sbom_at
    assert (
        "python -m pip_audit -r requirements.txt --format cyclonedx-json "
        "--output dist/sbom.cdx.json"
    ) in workflow
    assert "python -m pip_audit --format cyclonedx-json --output dist/sbom.cdx.json" not in workflow

def test_windows_build_uses_read_only_permissions_and_isolates_release_write_access():
    workflow = _read_workflow(".github/workflows/windows-release.yml")

    assert "permissions:\n  contents: read\n" in workflow
    assert "permissions:\n      contents: read" in workflow
    assert "permissions:\n      contents: write" in workflow

    build_job = workflow.split("  build:\n", 1)[1].split("  publish:\n", 1)[0]
    publish_job = workflow.split("  publish:\n", 1)[1]
    assert "Publish Windows packages to GitHub Releases" not in build_job
    assert re.search(r"uses: actions/download-artifact@[0-9a-f]{40} # v7", publish_job)
    assert "needs: build" in publish_job
    assert "GH_TOKEN: ${{ secrets.GITHUB_TOKEN }}" in publish_job
    assert "GH_REPO: ${{ github.repository }}" in publish_job
    assert "contents: write" not in build_job

    upload_at = build_job.index("Upload Windows packages")
    upload_end = build_job.index("if-no-files-found: error", upload_at)
    upload_config = build_job[upload_at:upload_end]
    for required_asset in (
        "dist/sbom.cdx.json",
        "dist/RELEASE-NOTES.md",
        "dist/WINDOWS_SIGNING.md",
        "dist/THIRD_PARTY_LICENSES.md",
    ):
        assert required_asset in upload_config

def test_ci_actions_are_pinned_to_immutable_shas_and_dependabot_updates_them():
    workflow_paths = (
        ".github/workflows/desktop-ci.yml",
        ".github/workflows/security.yml",
        ".github/workflows/windows-release.yml",
    )
    for relative_path in workflow_paths:
        workflow = _read_workflow(relative_path)
        action_lines = [
            line.strip()
            for line in workflow.splitlines()
            if re.match(r"^\s*(?:-\s*)?uses:", line)
        ]
        assert action_lines, f"No actions found in {relative_path}"
        for line in action_lines:
            assert re.search(r"@[0-9a-f]{40}\s+#\s*v\d+\s*$", line), (
                f"Action reference is not SHA-pinned in {relative_path}: {line}"
            )

    dependabot = _read_workflow(".github/dependabot.yml")
    assert '"package-ecosystem": "github-actions"' in dependabot
    assert 'directory: "/"' in dependabot
    assert 'interval: "weekly"' in dependabot
