from mysql_editor.ui.theme import (
    COMPONENT_SIZES, EDITOR_PALETTES, RADII, SPACING, STYLESHEET, TOKENS, TYPOGRAPHY,
    color_for_theme, normalize_theme, resolve_theme, stylesheet_for_theme,
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
    assert 'QLabel#connectionBadge[connectionState="disconnected"]' in STYLESHEET
    assert 'QLabel#connectionBadge[connectionState="disconnected"]' in stylesheet_for_theme("light")



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
    assert "QMainWindow, QDialog, QWidget { background: #F8FAFC; color: #263548; }" in light
    assert "QPushButton#primaryButton { background: #087E8B; color: #F8FAFC;" in light
    assert "QMenu::item:selected { background: #225EA8; color: white; }" in light
    assert "QTreeWidget::item:selected, QListWidget::item:selected { background: #D6E6F9;" in light
    assert "#0B111B" not in light
    assert "#080e17" not in light


def test_keyboard_focus_indicators_cover_primary_interactive_surfaces():
    for selector in (
        "QPushButton:focus", "QToolButton:focus", "QTableView:focus", "QTabBar::tab:focus"
    ):
        assert selector in STYLESHEET
        assert selector in stylesheet_for_theme("light")


def test_system_stylesheet_resolves_to_a_concrete_palette():
    assert stylesheet_for_theme("system", system_is_dark=True) == STYLESHEET
    assert stylesheet_for_theme("system", system_is_dark=False) == stylesheet_for_theme("light")


def _linear_channel(component: int) -> float:
    value = component / 255
    return value / 12.92 if value <= 0.04045 else ((value + 0.055) / 1.055) ** 2.4


def _luminance(hex_color: str) -> float:
    channels = [_linear_channel(int(hex_color[index:index + 2], 16)) for index in (1, 3, 5)]
    return 0.2126 * channels[0] + 0.7152 * channels[1] + 0.0722 * channels[2]


def _contrast_ratio(foreground: str, background: str) -> float:
    values = sorted((_luminance(foreground), _luminance(background)), reverse=True)
    return (values[0] + 0.05) / (values[1] + 0.05)


def test_light_theme_key_text_states_meet_wcag_aa_contrast():
    assert _contrast_ratio("#243246", "#F8FAFC") >= 4.5  # primary text
    assert _contrast_ratio("#526174", "#F8FAFC") >= 4.5  # secondary text
    assert _contrast_ratio("#F8FAFC", "#087E8B") >= 4.5  # primary button
    assert _contrast_ratio("#126B50", "#DFF5ED") >= 4.5  # success badge
    assert _contrast_ratio("#946200", "#F8FAFC") >= 4.5  # warning
    assert _contrast_ratio("#B42335", "#F8FAFC") >= 4.5  # danger
    assert _contrast_ratio("#1F6FEB", "#FFFFFF") >= 4.5  # focus ring


def test_muted_result_text_token_meets_contrast_in_both_grid_themes():
    dark = color_for_theme("text_muted", "dark")
    light = color_for_theme("text_muted", "light")

    assert dark == TOKENS["text_muted"]
    assert light == "#65748A"
    assert _contrast_ratio(dark, "#0B121D") >= 4.5
    assert _contrast_ratio(light, "#FFFFFF") >= 4.5



def test_dark_theme_key_text_states_meet_wcag_aa_contrast():
    # These pairs represent actual visible text states in the shared dark stylesheet.
    assert _contrast_ratio(TOKENS["text_primary"], TOKENS["window_bg"]) >= 4.5  # primary text
    assert _contrast_ratio(TOKENS["text_secondary"], TOKENS["window_bg"]) >= 4.5  # secondary/helper text
    assert _contrast_ratio("#8093AC", "#0B111B") >= 4.5  # muted text
    assert _contrast_ratio(TOKENS["window_bg"], TOKENS["accent_primary"]) >= 4.5  # primary-button text
    assert _contrast_ratio("#3bd49b", "#142d2b") >= 4.5  # connection success badge
    assert _contrast_ratio(TOKENS["status_warning"], TOKENS["window_bg"]) >= 4.5  # warning text
    assert _contrast_ratio(TOKENS["status_danger"], TOKENS["window_bg"]) >= 4.5  # danger text
    assert _contrast_ratio("#8293a9", "#121a26") >= 4.5  # disabled button text
    assert _contrast_ratio("#FFFFFF", "#1d4f88") >= 4.5  # selected table rows
    assert _contrast_ratio("#4a9bff", "#0B111B") >= 3.0  # focus boundary, non-text


def test_light_theme_focus_boundary_meets_non_text_contrast_target():
    assert _contrast_ratio("#1F6FEB", "#FFFFFF") >= 3.0


def test_sql_syntax_palette_text_meets_wcag_aa_on_editor_surface():
    backgrounds = {"dark": "#080e17", "light": "#FFFFFF"}
    for theme_name, palette in EDITOR_PALETTES.items():
        background = backgrounds[theme_name]
        for role in ("keyword", "string", "number", "function", "comment"):
            assert _contrast_ratio(palette[role], background) >= 4.5, (
                f"{theme_name} SQL {role} contrast failed: "
                f"{_contrast_ratio(palette[role], background):.2f}:1"
            )
        gutter_background = palette["gutter_background"]
        for role in ("gutter_text", "gutter_active_text"):
            assert _contrast_ratio(palette[role], gutter_background) >= 4.5, (
                f"{theme_name} editor {role} contrast failed: "
                f"{_contrast_ratio(palette[role], gutter_background):.2f}:1"
            )



def test_guided_tour_progress_states_are_styled_by_shared_theme_in_both_palettes():
    dark = stylesheet_for_theme("dark")
    light = stylesheet_for_theme("light")

    assert 'QLabel#tourProgress[current="true"]' in dark
    assert 'QLabel#tourProgress[current="false"]' in dark
    assert "color: #58dcec; font-size: 14px;" in dark
    assert "color: #7187a3; font-size: 12px;" in dark
    assert 'QLabel#tourProgress[current="true"]' in light
    assert 'QLabel#tourProgress[current="false"]' in light
    assert "color: #087E8B; font-size: 14px;" in light
    assert "color: #63748A; font-size: 12px;" in light



def test_design_metrics_are_named_and_resolved_into_shared_stylesheet():
    assert SPACING["scale"] == (4, 8, 12, 16, 20, 24, 32)
    assert TYPOGRAPHY["app_family"] == "Segoe UI"
    assert TYPOGRAPHY["app_size_pt"] == 9
    assert TYPOGRAPHY["dialog_title_px"] == 20
    assert TYPOGRAPHY["caption_px"] == 10
    assert TYPOGRAPHY["body_px"] == 12
    assert RADII["button"] == 7
    assert RADII["control"] == 6
    assert RADII["panel"] == 9
    assert COMPONENT_SIZES["button_min_height"] == 19
    assert COMPONENT_SIZES["tree_item_min_height"] == 25
    assert COMPONENT_SIZES["checkbox_indicator"] == 16
    assert not any(token in STYLESHEET for token in ("@SPACE_", "@TYPE_", "@RADIUS_", "@SIZE_"))
    assert "border-radius: 7px; padding: 8px 11px; min-height: 19px;" in STYLESHEET
    assert "QLabel#pageTitle { font-size: 23px; font-weight: 700; }" in STYLESHEET
    assert "#162235" in STYLESHEET
    assert "#1B2B42" in STYLESHEET
    assert "#203650" in STYLESHEET
    assert "#26364B" in STYLESHEET
    assert TOKENS["text_primary"] in STYLESHEET
    assert TOKENS["text_secondary"] in STYLESHEET
    assert not any(token in STYLESHEET for token in (
        "@COLOR_", "@SPACE_", "@TYPE_", "@RADIUS_", "@SIZE_"
    ))



def test_disabled_primary_button_uses_disabled_palette_in_dark_and_light_themes():
    dark = stylesheet_for_theme("dark")
    light = stylesheet_for_theme("light")

    assert "QPushButton#primaryButton:disabled {" in dark
    assert (
        "background: #121a26; color: #A6B6CB; border-color: #35465c;"
        in dark
    )
    assert "QPushButton#primaryButton:disabled:hover {" in dark

    assert "QPushButton#primaryButton:disabled {" in light
    assert (
        "background: #F2F5F9; color: #64748B; border-color: #D6DEE8;"
        in light
    )
    assert "QPushButton#primaryButton:disabled:hover {" in light

    assert _contrast_ratio("#A6B6CB", "#121A26") >= 4.5
    assert _contrast_ratio("#526174", "#F2F5F9") >= 4.5
