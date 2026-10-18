import re

from mysql_editor.ui.theme import (
    STYLE_COLORS,
    STYLESHEET,
    _STYLESHEET_TEMPLATE,
    stylesheet_for_theme,
)


def test_shared_style_colors_are_resolved():
    assert STYLE_COLORS["control_border"] == "#405675"
    assert STYLE_COLORS["focus_border"] == "#4a9bff"
    assert STYLE_COLORS["disabled_background"] == "#121a26"
    assert STYLE_COLORS["table_selection"] == "#1d4f88"
    for value in STYLE_COLORS.values():
        assert value in STYLESHEET
    assert "@STYLE_" not in STYLESHEET
    assert "@COLOR_" not in STYLESHEET
    assert "@SPACE_" not in STYLESHEET
    assert "@TYPE_" not in STYLESHEET
    assert "@RADIUS_" not in STYLESHEET
    assert "@SIZE_" not in STYLESHEET
    assert not re.search(r"#[0-9A-Fa-f]{3,8}\b", _STYLESHEET_TEMPLATE)


def test_shared_style_colors_translate_to_light_theme():
    light = stylesheet_for_theme("light")
    assert STYLE_COLORS["focus_border"] not in light
    assert "#1F6FEB" in light
    assert "#D6E6F9" in light
