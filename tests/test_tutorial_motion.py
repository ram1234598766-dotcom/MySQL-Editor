"""Motion and reduced-motion regression coverage for the guided tour."""
import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QAbstractAnimation, QEventLoop, QTimer
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


def test_guided_tour_transition_uses_shared_motion_token_and_cleans_up():
    tour = ProductTourDialog(settings=SettingsStub(False))
    tour.show()
    _APP.processEvents()

    tour._go(1)
    assert tour.pages.currentIndex() == 1
    assert tour._fade.state() == QAbstractAnimation.State.Running

    # Let Qt complete the top-level window animation before deleting the dialog.
    # The reduced-motion case above verifies the immediate state path.
    loop = QEventLoop()
    tour._fade.finished.connect(loop.quit)
    QTimer.singleShot(500, loop.quit)
    loop.exec()

    assert tour._fade.state() == QAbstractAnimation.State.Stopped
    assert tour.windowOpacity() == 1.0

    tour.close()
    assert tour._fade.state() == QAbstractAnimation.State.Stopped
    assert tour.windowOpacity() == 1.0
