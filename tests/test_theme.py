from mysql_editor.ui.theme import (
    STYLESHEET, TOKENS, normalize_theme, resolve_theme, stylesheet_for_theme,
)


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



def test_theme_preference_validation_and_system_resolution():
    assert normalize_theme("LIGHT") == "light"
    assert normalize_theme("system") == "system"
    assert normalize_theme(None) == "dark"
    assert normalize_theme("unrecognised-theme") == "dark"
    assert resolve_theme("system", system_is_dark=True) == "dark"
    assert resolve_theme("system", system_is_dark=False) == "light"
    assert resolve_theme("light", system_is_dark=True) == "light"
    assert resolve_theme("dark", system_is_dark=False) == "dark"


def test_light_theme_translates_shared_component_styles_and_preserves_contrast():
    dark = stylesheet_for_theme("dark", system_is_dark=False)
    light = stylesheet_for_theme("light")
    assert dark == STYLESHEET
    assert light != STYLESHEET
    assert "QMainWindow, QDialog, QWidget { background: #F8FAFC; color: #243246; }" in light
    assert "QPushButton#primaryButton { background: #087E8B; color: #F8FAFC;" in light
    assert "QMenu::item:selected { background: #225EA8; color: white; }" in light
    assert "QTreeWidget::item:selected, QListWidget::item:selected { background: #D6E6F9;" in light
    assert "#0B111B" not in light
    assert "#080e17" not in light


def test_system_stylesheet_resolves_to_a_concrete_palette():
    assert stylesheet_for_theme("system", system_is_dark=True) == STYLESHEET
    assert stylesheet_for_theme("system", system_is_dark=False) == stylesheet_for_theme("light")
