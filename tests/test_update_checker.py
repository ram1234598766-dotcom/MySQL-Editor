"""Tests for the opt-in stable GitHub Releases checker."""
from __future__ import annotations

import json
from io import BytesIO
from urllib.error import HTTPError

import pytest

from mysql_editor.update_checker import (
    LATEST_RELEASE_API_URL,
    MAX_RESPONSE_BYTES,
    RELEASE_PAGE_PREFIX,
    check_latest_stable_release,
    is_safe_release_url,
    parse_stable_version,
)


def _release(tag="v0.2.0", *, url=None, prerelease=False, draft=False):
    return {
        "tag_name": tag,
        "html_url": url or RELEASE_PAGE_PREFIX + tag,
        "prerelease": prerelease,
        "draft": draft,
    }


def _opener_for(payload, *, seen=None):
    def opener(request, timeout):
        if seen is not None:
            seen["request"] = request
            seen["timeout"] = timeout
        return BytesIO(json.dumps(payload).encode("utf-8"))
    return opener


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        ("0.1.0", (0, 1, 0)),
        ("v1.20.3", (1, 20, 3)),
        ("V2.0.0", (2, 0, 0)),
        ("3.4.5+build.7", (3, 4, 5)),
        ("windows-preview-173", None),
        ("1.2", None),
        ("1.2.3-rc.1", None),
        ("", None),
        (None, None),
    ],
)
def test_parse_stable_version_accepts_only_supported_stable_tags(value, expected):
    assert parse_stable_version(value) == expected


@pytest.mark.parametrize(
    "url",
    [
        RELEASE_PAGE_PREFIX + "v1.0.0",
        "https://github.com/ram1234598766-dotcom/MySQL-Editor/releases/tag/v1.0.0",
    ],
)
def test_release_url_only_allows_this_repositories_https_release_page(url):
    assert is_safe_release_url(url)


@pytest.mark.parametrize(
    "url",
    [
        "http://github.com/ram1234598766-dotcom/MySQL-Editor/releases/tag/v1.0.0",
        "https://evil.example/ram1234598766-dotcom/MySQL-Editor/releases/tag/v1.0.0",
        "https://github.com.evil.example/ram1234598766-dotcom/MySQL-Editor/releases/tag/v1.0.0",
        "https://user@github.com/ram1234598766-dotcom/MySQL-Editor/releases/tag/v1.0.0",
        RELEASE_PAGE_PREFIX + "v1.0.0?redirect=https://evil.example",
        "https://github.com/another-owner/MySQL-Editor/releases/tag/v1.0.0",
        RELEASE_PAGE_PREFIX,
    ],
)
def test_release_url_rejects_noncanonical_or_untrusted_destinations(url):
    assert not is_safe_release_url(url)


def test_update_available_uses_only_the_public_github_release_endpoint():
    seen = {}
    result = check_latest_stable_release(
        "0.1.0", opener=_opener_for(_release("v0.2.0"), seen=seen)
    )

    assert result.status == "update_available"
    assert result.current_version == "0.1.0"
    assert result.latest_version == "0.2.0"
    assert result.release_url == RELEASE_PAGE_PREFIX + "v0.2.0"
    assert seen["request"].full_url == LATEST_RELEASE_API_URL
    assert seen["request"].get_method() == "GET"
    assert seen["request"].get_header("Accept") == "application/vnd.github+json"
    assert seen["request"].get_header("User-agent") == "MySQLEditor/0.1.0"
    assert seen["timeout"] <= 5


def test_latest_equal_or_older_version_is_up_to_date():
    equal = check_latest_stable_release(
        "0.2.0", opener=_opener_for(_release("v0.2.0"))
    )
    older = check_latest_stable_release(
        "0.3.0", opener=_opener_for(_release("v0.2.0"))
    )

    assert equal.status == "up_to_date"
    assert older.status == "up_to_date"


def test_invalid_installed_version_does_not_make_a_network_request():
    def forbidden_opener(*_args, **_kwargs):
        raise AssertionError("invalid local version must not initiate network access")

    result = check_latest_stable_release("preview-build-5", opener=forbidden_opener)

    assert result.status == "error"
    assert "stable X.Y.Z" in result.detail


def test_404_means_no_published_stable_release():
    def not_found(_request, timeout):
        raise HTTPError(LATEST_RELEASE_API_URL, 404, "Not Found", None, None)

    result = check_latest_stable_release("0.1.0", opener=not_found)

    assert result.status == "no_release"
    assert "No published stable GitHub Release" in result.detail


@pytest.mark.parametrize(
    "payload",
    [
        _release("windows-preview-173"),
        _release("v0.2.0", prerelease=True),
        _release("v0.2.0", draft=True),
        _release("v0.2.0", url="https://evil.example/download"),
    ],
)
def test_preview_tags_and_untrusted_release_metadata_never_offer_an_update(payload):
    result = check_latest_stable_release("0.1.0", opener=_opener_for(payload))

    assert result.status == "error"
    assert result.release_url is None


def test_unreadable_json_and_oversized_response_fail_safely():
    malformed = check_latest_stable_release(
        "0.1.0", opener=lambda *_args, **_kwargs: BytesIO(b"{not-json")
    )
    oversized = check_latest_stable_release(
        "0.1.0",
        opener=lambda *_args, **_kwargs: BytesIO(b"x" * (MAX_RESPONSE_BYTES + 1)),
    )

    assert malformed.status == "error"
    assert "unreadable response" in malformed.detail
    assert oversized.status == "error"
    assert "larger than the allowed limit" in oversized.detail


def test_http_failure_does_not_expose_raw_response_or_secrets():
    def failed(_request, timeout):
        raise HTTPError(LATEST_RELEASE_API_URL, 503, "Service Unavailable", None, None)

    result = check_latest_stable_release("0.1.0", opener=failed)

    assert result.status == "error"
    assert "HTTP error" in result.detail
    assert "503" not in result.detail
