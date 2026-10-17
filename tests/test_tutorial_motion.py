"""Motion and reduced-motion regression coverage for the guided tour."""
import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QAbstractAnimation
from PySide6.QtWidgets import QApplication

from mysql_editor.ui.tutorial import ProductTourDialog


_APP = QApplication.instance() or QApplication([])


class SettingsStub:
    def __init__(self, reduced):
        self.reduced = reduced

    def value(self, key, default=False, type=bool):
        assert key == "ui/reduceMotion"
        return self.reduced


def test_guided_tour_skips_fade_when_reduce_motion_is_enabled():
    tour = ProductTourDialog(settings=SettingsStub(True))

    tour._go(1)

    assert tour.pages.currentIndex() == 1
    assert tour._fade.state() == QAbstractAnimation.State.Stopped
    assert tour.windowOpacity() == 1.0
    tour.close()


def test_guided_tour_transition_uses_shared_motion_token_and_can_be_interrupted():
    tour = ProductTourDialog(settings=SettingsStub(False))
    tour.show()
    _APP.processEvents()

    tour._go(1)
    assert tour.pages.currentIndex() == 1
    assert tour._fade.state() == QAbstractAnimation.State.Running

    # Moving again interrupts the first transition and begins from a known opacity.
    tour._go(2)
    assert tour.pages.currentIndex() == 2
    assert tour._fade.state() == QAbstractAnimation.State.Running

    # Dismissal must cancel motion and leave the page fully visible.
    tour.close()
    assert tour._fade.state() == QAbstractAnimation.State.Stopped
    assert tour.windowOpacity() == 1.0
