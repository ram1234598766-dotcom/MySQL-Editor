"""Regression checks for the inline SQL Find/Replace bar."""
import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication

from mysql_editor.ui.find_replace_bar import FindReplaceBar, count_matches


_APP = QApplication.instance() or QApplication([])


def test_match_count_is_literal_case_aware_and_handles_empty_search():
    assert count_matches("SELECT alpha, ALPHA, xalpha", "alpha") == 3
    assert count_matches("SELECT alpha, ALPHA, xalpha", "alpha", case_sensitive=True) == 2
    assert count_matches("a.*b and a.*b", "a.*b") == 2
    assert count_matches("some text", "") == 0


def test_find_bar_shows_replace_controls_on_request():
    bar = FindReplaceBar()
    assert bar.isHidden()
    assert bar.replace_row.isHidden()

    bar.show_bar(replace=False, seed_text="SELECT")
    assert not bar.isHidden()
    assert bar.search_text() == "SELECT"
    assert bar.replace_row.isHidden()

    bar.show_bar(replace=True)
    assert not bar.replace_row.isHidden()
    bar.close_bar()
    assert bar.isHidden()


def test_find_bar_exposes_accessible_actions_and_emits_search_changes():
    bar = FindReplaceBar()
    changes = []
    next_requests = []
    replace_all_requests = []
    bar.search_changed.connect(lambda text, case_sensitive: changes.append((text, case_sensitive)))
    bar.find_next_requested.connect(lambda: next_requests.append(True))
    bar.replace_all_requested.connect(lambda: replace_all_requests.append(True))

    bar.search_input.setText("table")
    bar.match_case.setChecked(True)
    bar.next_button.click()
    bar.replace_all_button.click()

    assert changes[-1] == ("table", True)
    assert next_requests == [True]
    assert replace_all_requests == [True]
    assert bar.search_input.accessibleName() == "Find text in SQL query"
    assert bar.replace_all_button.accessibleName() == "Replace all matches"
