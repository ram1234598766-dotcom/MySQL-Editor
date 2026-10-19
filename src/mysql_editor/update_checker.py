"""Opt-in GitHub Releases update checks; no telemetry or automatic downloads."""
from __future__ import annotations

import json
import re
from dataclasses import dataclass
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import urlsplit
from urllib.request import Request, urlopen

from PySide6.QtCore import QThread, Signal

from mysql_editor import __version__

REPOSITORY = "ram1234598766-dotcom/MySQL-Editor"
LATEST_RELEASE_API_URL = f"https://api.github.com/repos/{REPOSITORY}/releases/latest"
RELEASE_PAGE_PREFIX = f"https://github.com/{REPOSITORY}/releases/tag/"
NETWORK_TIMEOUT_SECONDS = 4.5
MAX_RESPONSE_BYTES = 512 * 1024

_VERSION_RE = re.compile(r"^[vV]?(\d+)\.(\d+)\.(\d+)(?:\+[0-9A-Za-z.-]+)?$")


@dataclass(frozen=True, slots=True)
class UpdateCheckResult:
    """Bounded result returned by a single public stable-release metadata request."""

    status: str
    current_version: str
    latest_version: str | None = None
    release_url: str | None = None
    detail: str = ""


def parse_stable_version(value: str) -> tuple[int, int, int] | None:
    """Parse the project's deliberately small stable X.Y.Z version format."""
    if not isinstance(value, str):
        return None
    match = _VERSION_RE.fullmatch(value.strip())
    if match is None:
        return None
    try:
        return tuple(int(part) for part in match.groups())
    except (ValueError, OverflowError):
        return None


def is_safe_release_url(value: str) -> bool:
    """Accept only a direct HTTPS release page for this repository."""
    if not isinstance(value, str):
        return False
    try:
        parsed = urlsplit(value)
        return (
            parsed.scheme == "https"
            and parsed.hostname == "github.com"
            and parsed.username is None
            and parsed.password is None
            and parsed.port in (None, 443)
            and parsed.path.startswith(f"/{REPOSITORY}/releases/tag/")
            and parsed.path != f"/{REPOSITORY}/releases/tag/"
            and not parsed.query
            and not parsed.fragment
        )
    except ValueError:
        return False


def check_latest_stable_release(
    current_version: str = __version__,
    *,
    opener: Any | None = None,
) -> UpdateCheckResult:
    """Compare the installed version with GitHub's latest published stable release.

    This makes one unauthenticated GET to the fixed public GitHub API endpoint. It
    sends no SQL, database details, credentials, device identifier, or usage data.
    Network, response-size, JSON, version, and release-link failures are returned as
    a safe error state instead of raising into the UI.
    """
    current = parse_stable_version(current_version)
    if current is None:
        return UpdateCheckResult(
            "error",
            str(current_version),
            detail="This application version is not a supported stable X.Y.Z version.",
        )

    request = Request(
        LATEST_RELEASE_API_URL,
        headers={
            "Accept": "application/vnd.github+json",
            "User-Agent": f"MySQLEditor/{current_version}",
        },
        method="GET",
    )
    open_request = opener or urlopen
    try:
        with open_request(request, timeout=NETWORK_TIMEOUT_SECONDS) as response:
            raw = response.read(MAX_RESPONSE_BYTES + 1)
    except HTTPError as exc:
        if exc.code == 404:
            return UpdateCheckResult(
                "no_release",
                current_version,
                detail="No published stable GitHub Release is available yet.",
            )
        return UpdateCheckResult(
            "error",
            current_version,
            detail="GitHub Releases returned an HTTP error. Try again later.",
        )
    except (URLError, TimeoutError, OSError, ValueError):
        return UpdateCheckResult(
            "error",
            current_version,
            detail="Could not reach GitHub Releases. Check your connection and try again.",
        )

    if len(raw) > MAX_RESPONSE_BYTES:
        return UpdateCheckResult(
            "error",
            current_version,
            detail="The GitHub Releases response was larger than the allowed limit.",
        )
    try:
        payload = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError):
        return UpdateCheckResult(
            "error",
            current_version,
            detail="GitHub Releases returned an unreadable response. Try again later.",
        )

    if not isinstance(payload, dict) or payload.get("draft") or payload.get("prerelease"):
        return UpdateCheckResult(
            "error",
            current_version,
            detail="GitHub did not return a published stable release.",
        )

    tag_name = payload.get("tag_name")
    release_url = payload.get("html_url")
    latest = parse_stable_version(tag_name) if isinstance(tag_name, str) else None
    if latest is None or not is_safe_release_url(release_url):
        return UpdateCheckResult(
            "error",
            current_version,
            detail="The latest release has an unsupported version tag or release URL.",
        )

    if latest > current:
        return UpdateCheckResult(
            "update_available",
            current_version,
            latest_version=tag_name.lstrip("vV"),
            release_url=release_url,
        )
    return UpdateCheckResult(
        "up_to_date",
        current_version,
        latest_version=tag_name.lstrip("vV"),
        release_url=release_url,
    )


class UpdateCheckThread(QThread):
    """Run the bounded network request away from Qt's UI thread."""

    result_ready = Signal(object)

    def __init__(self, current_version: str = __version__, parent=None) -> None:
        super().__init__(parent)
        self._current_version = current_version

    def run(self) -> None:
        try:
            result = check_latest_stable_release(self._current_version)
        except Exception:
            # Keep any unexpected error inside the background-task boundary; no
            # traceback or connection metadata is written to the UI or a log.
            result = UpdateCheckResult(
                "error",
                self._current_version,
                detail="The update check failed unexpectedly. Try again later.",
            )
        self.result_ready.emit(result)
