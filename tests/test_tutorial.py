"""Regression checks for the guided tour's reduced-motion and interruption behavior."""
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
    monkeypatch.setattr("mysql_editor.ui.tutorial.reduce_motion_enabled", lambda: True)
    repository = RepositoryStub()
    tour = ProductTourDialog(repository=repository)

    assert tour._fade is None
    assert tour._opacity is None
    assert tour.pages.graphicsEffect() is None

    tour._go(1)

    assert tour.pages.currentIndex() == 1
    assert tour.heading.text() == "Connect with confidence"
    assert tour.pages.graphicsEffect() is None

    tour._skip()
    assert repository.settings["guided_tour_completed"] == "true"


def test_guided_tour_animation_uses_shared_duration_and_restarts_cleanly(monkeypatch):
    monkeypatch.setattr("mysql_editor.ui.tutorial.reduce_motion_enabled", lambda: False)
    tour = ProductTourDialog(repository=RepositoryStub())

    assert tour._fade is not None
    assert tour._fade.duration() == TOUR_DURATION_MS
    assert tour._opacity is not None
    assert tour.pages.graphicsEffect() is tour._opacity

    tour._go(1)
    assert tour.pages.currentIndex() == 1
    assert tour._fade.state() == QAbstractAnimation.State.Running

    # A rapid second navigation should stop/restart the same animation safely.
    tour._go(2)
    assert tour.pages.currentIndex() == 2
    assert tour._fade.state() == QAbstractAnimation.State.Running

    # Closing while a fade is active must stop motion and restore full opacity.
    tour._opacity.setOpacity(0.4)
    tour._skip()
    assert tour._fade.state() == QAbstractAnimation.State.Stopped
    assert tour._opacity.opacity() == 1.0


def test_guided_tour_finish_also_cleans_up_active_animation(monkeypatch):
    monkeypatch.setattr("mysql_editor.ui.tutorial.reduce_motion_enabled", lambda: False)
    repository = RepositoryStub()
    tour = ProductTourDialog(repository=repository)
    tour._go(1)

    tour._finish()

    assert tour._fade.state() == QAbstractAnimation.State.Stopped
    assert tour._opacity.opacity() == 1.0
    assert repository.settings["guided_tour_completed"] == "true"
