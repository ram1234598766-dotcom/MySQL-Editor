"""Theme-aware SQL syntax highlighting and custom editor surfaces."""
import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtGui import QFont
from PySide6.QtWidgets import QApplication

from mysql_editor.ui.editor import SqlEditor
from mysql_editor.ui.theme import EDITOR_PALETTES, stylesheet_for_theme

_APP = QApplication.instance() or QApplication([])


def _color_at(editor, token):
    block = editor.document().firstBlock()
    start = block.text().index(token)
    for item in block.layout().formats():
        if item.start <= start < item.start + item.length:
            return item.format.foreground().color().name().lower()
    raise AssertionError(f"No syntax format found for {token!r}")


def test_light_theme_updates_syntax_formats_and_custom_surface_palette():
    editor = SqlEditor()
    try:
        editor.setPlainText("SELECT 'value', 42, COUNT(1) -- note")
        editor.set_editor_theme("light")
        _APP.processEvents()

        palette = EDITOR_PALETTES["light"]
        assert editor.theme_name == "light"
        assert editor.highlighter.theme_name == "light"
        assert _color_at(editor, "SELECT") == palette["keyword"].lower()
        assert _color_at(editor, "'value'") == palette["string"].lower()
        assert _color_at(editor, "42") == palette["number"].lower()
        assert _color_at(editor, "COUNT") == palette["function"].lower()
        assert editor.theme_palette["gutter_background"] == "#F1F5F9"
        assert editor.theme_palette["current_line_background"] == "#EFF6FC"
        assert editor.theme_palette["bracket_background"] == "#D6E6F9"
    finally:
        editor.deleteLater()
        _APP.processEvents()


def test_dark_light_theme_changes_preserve_sql_selection_and_cursor_state():
    editor = SqlEditor()
    try:
        source = "SELECT customer_id FROM customers;"
        editor.setPlainText(source)
        cursor = editor.textCursor()
        start = source.index("customer_id")
        cursor.setPosition(start)
        cursor.setPosition(start + len("customer_id"), cursor.MoveMode.KeepAnchor)
        editor.setTextCursor(cursor)
        before_start = editor.textCursor().selectionStart()
        before_end = editor.textCursor().selectionEnd()
        before_selection = editor.textCursor().selectedText()

        editor.set_editor_theme("light")
        assert editor.toPlainText() == source
        assert editor.textCursor().selectionStart() == before_start
        assert editor.textCursor().selectionEnd() == before_end
        assert editor.textCursor().selectedText() == before_selection
        assert editor.theme_name == "light"

        editor.set_editor_theme("dark")
        assert editor.theme_name == "dark"
        assert editor.theme_palette == EDITOR_PALETTES["dark"]
        assert editor.highlighter.theme_name == "dark"
    finally:
        editor.deleteLater()
        _APP.processEvents()


def test_unknown_editor_theme_falls_back_to_dark_palette():
    editor = SqlEditor()
    try:
        editor.set_editor_theme("not-a-theme")
        assert editor.theme_name == "dark"
        assert editor.theme_palette == EDITOR_PALETTES["dark"]
    finally:
        editor.deleteLater()
        _APP.processEvents()


def test_shared_theme_stylesheet_respects_editor_font_preferences():
    """The application chrome stylesheet must not override the SQL editor font."""
    original_stylesheet = _APP.styleSheet()
    editor = None
    try:
        _APP.setStyleSheet(stylesheet_for_theme("dark"))
        editor = SqlEditor()
        editor.setFont(QFont("Cascadia Code", 15))
        _APP.processEvents()

        assert editor.font().pointSize() == 15
        assert editor.font().family().casefold() == "cascadia code"
    finally:
        if editor is not None:
            editor.deleteLater()
        _APP.setStyleSheet(original_stylesheet)
        _APP.processEvents()
