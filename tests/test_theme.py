from mysql_editor.ui.theme import STYLESHEET, TOKENS


def test_dark_theme_tokens_are_defined_and_stylesheet_has_no_unresolved_tokens():
    expected = {
        "window_bg", "surface_base", "surface_raised", "surface_hover",
        "surface_selected", "border_subtle", "text_primary", "text_secondary",
        "text_muted", "accent_primary", "accent_secondary", "status_success",
        "status_warning", "status_danger",
    }
    assert set(TOKENS) == expected
    assert all(value.startswith("#") and len(value) == 7 for value in TOKENS.values())
    assert "{" in STYLESHEET and "QMainWindow" in STYLESHEET
    assert not any("{" + key + "}" in STYLESHEET for key in expected)


def test_dark_theme_uses_semantic_palette_values():
    assert TOKENS["window_bg"] in STYLESHEET
    assert TOKENS["accent_primary"] in STYLESHEET
    assert TOKENS["status_danger"] in STYLESHEET
