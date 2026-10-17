"""Regression tests for safe multi-tab close behavior."""
from mysql_editor.ui.main_window import MainWindow, QMessageBox


class FakeDocument:
    def __init__(self, modified=False):
        self.modified = modified

    def isModified(self):
        return self.modified


class FakeEditor:
    def __init__(self, modified=False):
        self.doc = FakeDocument(modified)
        self.deleted = False

    def document(self):
        return self.doc

    def deleteLater(self):
        self.deleted = True


class FakeTabs:
    def __init__(self, names, dirty=()):
        dirty = set(dirty)
        self.items = [
            (FakeEditor(name in dirty), name)
            for name in names
        ]
        self.current_index = 0

    def count(self):
        return len(self.items)

    def widget(self, index):
        return self.items[index][0]

    def tabText(self, index):
        return self.items[index][1]

    def removeTab(self, index):
        del self.items[index]
        if self.current_index > index:
            self.current_index -= 1
        elif self.current_index == index:
            self.current_index = min(index, len(self.items) - 1)

    def setCurrentWidget(self, editor):
        self.current_index = next(
            index for index, (candidate, _) in enumerate(self.items)
            if candidate is editor
        )


class FakeStatus:
    def __init__(self):
        self.message = ""

    def setText(self, message):
        self.message = message


class WindowHarness:
    def __init__(self, names, dirty=()):
        self.editors = FakeTabs(names, dirty)
        self._last_saved_paths = {
            id(editor): f"/queries/{name}.sql"
            for editor, name in self.editors.items
        }
        self.status = FakeStatus()


def test_close_other_tabs_keeps_selected_tab_and_removes_saved_path_entries(monkeypatch):
    window = WindowHarness(["first.sql", "keep.sql", "third.sql"])
    keep_editor = window.editors.widget(1)

    def unexpected_prompt(*_args, **_kwargs):
        raise AssertionError("Closing clean tabs must not prompt.")

    monkeypatch.setattr(QMessageBox, "question", unexpected_prompt)
    MainWindow.close_other_query_tabs(window, 1)

    assert window.editors.count() == 1
    assert window.editors.widget(0) is keep_editor
    assert window.editors.tabText(0) == "keep.sql"
    assert window.editors.current_index == 0
    assert set(window._last_saved_paths) == {id(keep_editor)}
    assert window.status.message == "Closed 2 other query tab(s)."


def test_cancelled_close_other_tabs_preserves_every_tab_and_dirty_buffer(monkeypatch):
    window = WindowHarness(["changed.sql", "keep.sql", "also-changed.sql"], dirty={"changed.sql", "also-changed.sql"})
    before = list(window.editors.items)
    calls = []

    def cancel(*_args, **_kwargs):
        calls.append(True)
        return QMessageBox.StandardButton.Cancel

    monkeypatch.setattr(QMessageBox, "question", cancel)
    MainWindow.close_other_query_tabs(window, 1)

    assert len(calls) == 1
    assert window.editors.items == before
    assert len(window._last_saved_paths) == 3
    assert window.status.message == ""


def test_confirmed_close_other_tabs_uses_one_discard_prompt(monkeypatch):
    window = WindowHarness(["changed.sql", "keep.sql", "also-changed.sql"], dirty={"changed.sql", "also-changed.sql"})
    keep_editor = window.editors.widget(1)
    calls = []

    def discard(*_args, **_kwargs):
        calls.append(True)
        return QMessageBox.StandardButton.Discard

    monkeypatch.setattr(QMessageBox, "question", discard)
    MainWindow.close_other_query_tabs(window, 1)

    assert len(calls) == 1
    assert window.editors.count() == 1
    assert window.editors.widget(0) is keep_editor
    assert set(window._last_saved_paths) == {id(keep_editor)}
    assert window.status.message == "Closed 2 other query tab(s)."
