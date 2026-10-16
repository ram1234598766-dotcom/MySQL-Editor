"""Regression checks for imports used by the packaged desktop startup path."""


def test_application_startup_import_graph_is_valid():
    """Fail tests immediately if a UI import prevents the application from opening."""
    from mysql_editor.app import main
    from mysql_editor.ui.editor import SqlEditor

    assert callable(main)
    assert SqlEditor.__name__ == "SqlEditor"
