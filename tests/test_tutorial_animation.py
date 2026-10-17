"""Regression tests for guided-tour transitions and teardown."""
from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QAbstractAnimation
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication

from mysql_editor.ui.animations import TOUR_DURATION_MS
from mysql_editor.ui.tutorial import ProductTourDialog


_APP = QApplication.instance() or QApplication([])


class SettingsStub:
    def __init__(self, reduce_motion: bool):
        self._reduce_motion = reduce_motion

    def value(self, key, default=False, type=bool):
        assert key == "ui/reduceMotion"
        return self._reduce_motion


def test_tour_page_fade_completes_and_detaches_graphics_effect():
    dialog = ProductTourDialog(settings=SettingsStub(False))
    try:
        dialog.show()
        _APP.processEvents()
        dialog._go(1)

        assert dialog._index == 1
        assert dialog._fade is not None
        assert dialog._fade_effect is not None
        assert dialog.pages.graphicsEffect() is dialog._fade_effect

        QTest.qWait(TOUR_DURATION_MS + 80)
        _APP.processEvents()
        assert dialog._fade is None
        assert dialog._fade_effect is None
        assert dialog.pages.graphicsEffect() is None
    finally:
        dialog.close()
        dialog.deleteLater()
        _APP.processEvents()


def test_tour_reduce_motion_changes_page_without_animation():
    dialog = ProductTourDialog(settings=SettingsStub(True))
    try:
        dialog.show()
        _APP.processEvents()
        dialog._go(1)

        assert dialog._index == 1
        assert dialog.step_label.text() == "STEP 2 OF 5"
        assert dialog._fade is None
        assert dialog._fade_effect is None
        assert dialog.pages.graphicsEffect() is None
    finally:
        dialog.close()
        dialog.deleteLater()
        _APP.processEvents()


def test_repeated_tour_navigation_and_close_interrupt_cleanly():
    dialog = ProductTourDialog(settings=SettingsStub(False))
    try:
        dialog.show()
        _APP.processEvents()
        dialog._go(1)
        first = dialog._fade
        assert first is not None

        dialog._go(2)
        second = dialog._fade
        assert second is not None and second is not first
        assert first.state() == QAbstractAnimation.State.Stopped
        assert dialog.pages.graphicsEffect() is dialog._fade_effect

        dialog.close()
        _APP.processEvents()
        assert dialog._fade is None
        assert dialog._fade_effect is None
        assert dialog.pages.graphicsEffect() is None
        assert second.state() == QAbstractAnimation.State.Stopped
    finally:
        dialog.close()
        dialog.deleteLater()
        _APP.processEvents()
