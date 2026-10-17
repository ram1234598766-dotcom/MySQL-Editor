"""Regression tests for validation of persisted editor and result preferences."""
import pytest

from mysql_editor.ui.preferences import normalize_result_row_height, normalize_tab_width


@pytest.mark.parametrize(("value", "expected"), [
    (2, 2), ("2", 2), (4, 4), ("8", 8),
    (0, 4), (3, 4), (8.5, 4), (True, 4), (None, 4), ("invalid", 4),
])
def test_tab_width_accepts_only_supported_values(value, expected):
    assert normalize_tab_width(value) == expected


@pytest.mark.parametrize(("value", "expected"), [
    (24, 24), ("28", 28), (36, 36),
    (0, 28), (23, 28), (48, 28), (False, 28), (None, 28), ("invalid", 28),
])
def test_result_row_height_accepts_only_supported_values(value, expected):
    assert normalize_result_row_height(value) == expected
