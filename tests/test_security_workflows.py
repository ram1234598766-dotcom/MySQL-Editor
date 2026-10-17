"""Regression checks for runtime and build-environment dependency audit coverage."""
from __future__ import annotations

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
