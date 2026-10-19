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
    assert 'package-ecosystem: "github-actions"' in dependabot
    assert 'directory: "/"' in dependabot
    assert 'interval: "weekly"' in dependabot


def test_release_publication_is_gated_by_full_test_matrix_and_mysql_integration():
    workflow = _read_workflow(".github/workflows/windows-release.yml")

    assert "pull_request:" in workflow
    assert 'python-version: ["3.12", "3.13", "3.14"]' in workflow
    assert "python -m pytest --ignore=tests/test_mysql_integration.py" in workflow
    assert "run: python -m pytest tests/test_mysql_integration.py -v" in workflow
    assert "needs: [release-tests, mysql-integration]" in workflow
    assert '"tools/create_release_manifest.py", "--dist", "dist", "--commit", $env:GITHUB_SHA' in workflow
    assert '"--signing-status", "signed"' in workflow
    assert '"--signing-certificate-type", "${{ steps.signing-config.outputs.certificate_type }}"' in workflow
    assert "Validate Windows signing configuration" in workflow
    assert "if: (github.event_name == 'push' || github.event_name == 'workflow_dispatch') && (github.ref == 'refs/heads/main' || startsWith(github.ref, 'refs/tags/v'))" in workflow
    assert "Sign and verify application executables" in workflow
    assert "Sign and verify Windows installer" in workflow
    app_build_at = workflow.index("Build portable executable")
    self_signed_test_at = workflow.index("Test self-signed signing flow with a temporary certificate")
    sign_app_at = workflow.index("Sign and verify application executables")
    installer_build_at = workflow.index("Build setup installer")
    sign_installer_at = workflow.index("Sign and verify Windows installer")
    smoke_test_at = workflow.index("Smoke test installer install and uninstall")
    assert app_build_at < self_signed_test_at < sign_app_at < installer_build_at < sign_installer_at < smoke_test_at

    signing_script = _read_workflow("tools/sign_windows_artifacts.ps1")
    assert "WINDOWS_SIGNING_CERTIFICATE_BASE64" in signing_script
    assert "WINDOWS_SIGNING_CERTIFICATE_PASSWORD" in signing_script
    assert '"sign", "/fd", "SHA256"' in signing_script
    assert "verify /pa /all /v" in signing_script
    assert "Remove-Item -LiteralPath $certificatePath" in signing_script
    assert "Stable version tags require an Authenticode PFX certificate and password" in workflow
    assert "remain unsigned by policy" in workflow
    assert "WINDOWS_SIGNING_CERTIFICATE_TYPE: ${{ vars.WINDOWS_SIGNING_CERTIFICATE_TYPE || 'self-signed' }}" in workflow
    assert "Test self-signed signing flow with a temporary certificate" in workflow
    assert '"tools/create_signing_smoke_executable.ps1"' in workflow
    assert "where.exe" not in workflow
    assert "Verify configured self-signed certificate without publishing a release" in workflow
    assert '"configured_certificate=$($hasCertificate.ToString().ToLowerInvariant())"' in workflow
    assert "github.event_name == 'workflow_dispatch' && github.ref == 'refs/heads/phase-b/self-signed-windows-signing'" in workflow
    assert "github.event_name == 'push' && github.ref == 'refs/heads/main' && steps.signing-config.outputs.configured_certificate == 'true'" in workflow
    assert "WINDOWS_SIGNING_EXPECTED_THUMBPRINT: A716417B2EEF09FBD91C6E7E044C569438762D91C45C2AAF8F3A7AD2B317E3A8" in workflow
    assert '"tools/test_self_signed_signing.ps1"' in workflow
    assert "Validate signing helper scripts parse" in workflow
    assert "WINDOWS_SIGNING_CERTIFICATE_TYPE" in signing_script
    smoke_builder = _read_workflow("tools/create_signing_smoke_executable.ps1")
    assert 'Get-AuthenticodeSignature -FilePath $OutputPath' in smoke_builder
    assert 'ne "NotSigned"' in smoke_builder
    assert "where.exe" not in smoke_builder
    assert 'Get-AuthenticodeSignature -FilePath $target' in signing_script
    assert '$signatureStatus -in @("UnknownError", "NotTrusted")' in signing_script
    assert '$signatureStatusMessage -match' in signing_script
    assert 'if ($signatureStatus -ne "Valid" -and -not $expectedUntrustedRoot)' in signing_script
    assert 'signature.SignerCertificate.Thumbprint -ne $certificate.Thumbprint' in signing_script
    assert "Import-Certificate" not in signing_script
    assert "certutil.exe" not in signing_script
    assert "X509Store" not in signing_script
    assert "without modifying any certificate store" in signing_script
    assert "A certificate chain processed, but" in signing_script
    assert "& $signTool verify /pa /all /v $target" in signing_script
    assert "Recipient PCs will not trust this self-signed certificate by default." in signing_script
    assert "Remove-Item -LiteralPath $certificatePath" in signing_script
    assert "http://timestamp.digicert.com" in workflow
    assert "dist/RELEASE-MANIFEST.json" in workflow
    assert "dist/MySQLEditor/MySQLEditor.exe" in workflow
