"""Regression checks for guided-tour motion accessibility and page state."""
import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication

from mysql_editor.ui.tutorial import ProductTourDialog


_APP = QApplication.instance() or QApplication([])


class RepositoryStub:
    def __init__(self):
        self.settings = {}

    def set_setting(self, key, value):
        self.settings[key] = value


def test_guided_tour_respects_reduce_motion_and_changes_pages_immediately(monkeypatch):
    monkeypatch.setattr("mysql_editor.ui.animations.reduce_motion_enabled", lambda settings=None: True)
    tour = ProductTourDialog(repository=RepositoryStub())
    tour.show()
    _APP.processEvents()

    assert tour.pages.graphicsEffect() is None
    tour._go(1)

    assert tour.pages.currentIndex() == 1
    assert tour.heading.text() == "Connect with confidence"
    assert tour.pages.graphicsEffect() is None
    assert getattr(tour.progress_labels[1], "_mysql_editor_color_animation", None) is None
    assert "#50d9ee" in tour.progress_labels[1].styleSheet()

    tour._skip()
    assert tour.pages.graphicsEffect() is None
    tour.close()


def test_guided_tour_uses_immediate_feedback_in_headless_mode(monkeypatch):
    monkeypatch.setattr("mysql_editor.ui.animations.reduce_motion_enabled", lambda settings=None: False)
    tour = ProductTourDialog(repository=RepositoryStub())
    tour.show()
    _APP.processEvents()

    tour._go(1)
    assert tour.pages.currentIndex() == 1
    assert getattr(tour.progress_labels[1], "_mysql_editor_color_animation", None) is None
    assert "#50d9ee" in tour.progress_labels[1].styleSheet()

    tour._go(2)
    assert tour.pages.currentIndex() == 2
    assert getattr(tour.progress_labels[2], "_mysql_editor_color_animation", None) is None

    tour._skip()
    assert all(label.graphicsEffect() is None for label in tour.progress_labels)
    tour.close()


def test_guided_tour_finish_persists_completion_and_cleans_up():
    repository = RepositoryStub()
    tour = ProductTourDialog(repository=repository)
    tour.show()
    _APP.processEvents()

    tour._finish()

    assert repository.settings["guided_tour_completed"] == "true"
    assert all(label.graphicsEffect() is None for label in tour.progress_labels)
    tour.close()
