from mysql_editor.ui.theme import STYLE_COLORS, STYLESHEET


def test_shared_style_colors_are_resolved():
    assert STYLE_COLORS["control_border"] in STYLESHEET
