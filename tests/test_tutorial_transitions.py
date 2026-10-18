from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QCoreApplication, QEvent
from PySide6.QtWidgets import QApplication

from mysql_editor.ui.tutorial import ProductTourDialog


_APP = QApplication.instance() or QApplication([])


def _dispose_tour(tour):
    tour.close()
    tour.deleteLater()
    QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
    _APP.processEvents()


class SettingsStub:
    def __init__(self, reduce_motion: bool):
        self.reduce_motion = reduce_motion

    def value(self, key, default=False, type=bool):
        assert key == "ui/reduceMotion"
        return self.reduce_motion


def test_guided_tour_reduce_motion_skips_page_animation():
    dialog = ProductTourDialog(settings=SettingsStub(True))
    try:
        dialog._go(1)
        assert dialog.pages.currentIndex() == 1
        assert dialog._fade is None
        assert dialog._fade_effect is None
        assert dialog.pages.graphicsEffect() is None
    finally:
        _dispose_tour(dialog)


def test_guided_tour_interruption_and_close_restore_page_stack():
    dialog = ProductTourDialog(settings=SettingsStub(False))
    try:
        dialog.show()
        _APP.processEvents()
        dialog._go(1)
        assert dialog._fade is not None
        first_animation_id = id(dialog._fade)
        assert dialog.pages.graphicsEffect() is not None

        # Rapid navigation must detach the previous animation/effect before
        # starting the next transition.
        dialog._go(2)
        assert dialog.pages.currentIndex() == 2
        assert dialog._fade is not None
        assert id(dialog._fade) != first_animation_id
        assert dialog.pages.graphicsEffect() is not None

        # Closing while the second transition is active must restore the stack.
        dialog.reject()
        assert dialog._fade is None
        assert dialog._fade_effect is None
        assert dialog.pages.graphicsEffect() is None
    finally:
        _dispose_tour(dialog)
