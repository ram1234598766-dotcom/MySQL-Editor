"""Regression checks for guided-tour motion accessibility and interruption behavior."""
import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QAbstractAnimation
from PySide6.QtWidgets import QApplication

from mysql_editor.ui.animations import TOUR_DURATION_MS
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


def test_guided_tour_color_transition_uses_shared_duration_and_restarts_cleanly(monkeypatch):
    monkeypatch.setattr("mysql_editor.ui.animations.reduce_motion_enabled", lambda settings=None: False)
    tour = ProductTourDialog(repository=RepositoryStub())
    tour.show()
    _APP.processEvents()

    tour._go(1)
    first = getattr(tour.progress_labels[1], "_mysql_editor_color_animation", None)
    assert first is not None
    assert first.duration() == TOUR_DURATION_MS
    assert first.state() == QAbstractAnimation.State.Running

    tour._go(2)
    assert first.state() == QAbstractAnimation.State.Stopped
    current = getattr(tour.progress_labels[2], "_mysql_editor_color_animation", None)
    assert current is not None
    assert current.state() == QAbstractAnimation.State.Running

    tour._skip()
    assert current.state() == QAbstractAnimation.State.Stopped
    assert getattr(tour.progress_labels[2], "_mysql_editor_color_animation", None) is None
    assert all(label.graphicsEffect() is None for label in tour.progress_labels)


def test_guided_tour_finish_cleans_up_active_transition(monkeypatch):
    monkeypatch.setattr("mysql_editor.ui.animations.reduce_motion_enabled", lambda settings=None: False)
    repository = RepositoryStub()
    tour = ProductTourDialog(repository=repository)
    tour.show()
    _APP.processEvents()
    tour._go(1)

    current = getattr(tour.progress_labels[1], "_mysql_editor_color_animation", None)
    assert current is not None

    tour._finish()

    assert current.state() == QAbstractAnimation.State.Stopped
    assert getattr(tour.progress_labels[1], "_mysql_editor_color_animation", None) is None
    assert repository.settings["guided_tour_completed"] == "true"
