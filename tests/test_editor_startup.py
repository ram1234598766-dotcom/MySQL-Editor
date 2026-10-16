"""Regression checks for the Qt module imports used by the SQL editor."""

import ast
from pathlib import Path


def test_qtextedit_is_imported_from_qtwidgets():
    """Prevent the startup ImportError caused by importing QTextEdit from QtGui."""
    editor_path = (
        Path(__file__).resolve().parents[1]
        / "src"
        / "mysql_editor"
        / "ui"
        / "editor.py"
    )
    syntax_tree = ast.parse(editor_path.read_text(encoding="utf-8"))
    qtgui_imports = set()
    qtwidgets_imports = set()

    for node in ast.walk(syntax_tree):
        if not isinstance(node, ast.ImportFrom):
            continue
        imported_names = {alias.name for alias in node.names}
        if node.module == "PySide6.QtGui":
            qtgui_imports.update(imported_names)
        elif node.module == "PySide6.QtWidgets":
            qtwidgets_imports.update(imported_names)

    assert "QTextEdit" not in qtgui_imports
    assert "QTextEdit" in qtwidgets_imports
