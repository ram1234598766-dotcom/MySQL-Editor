"""Motion and reduced-motion regression coverage for the guided tour."""
import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QAbstractAnimation, QCoreApplication, QEvent
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication

from mysql_editor.ui.animations import TOUR_DURATION_MS
from mysql_editor.ui.tutorial import ProductTourDialog


_APP = QApplication.instance() or QApplication([])


def _dispose_tour(tour):
    """Destroy offscreen dialogs deterministically before QApplication teardown."""
    tour.close()
    tour.deleteLater()
    QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
    _APP.processEvents()


class SettingsStub:
    def __init__(self, reduced):
        self.reduced = reduced

    def value(self, key, default=False, type=bool):
        assert key == "ui/reduceMotion"
        return self.reduced


def test_guided_tour_skips_fade_when_reduce_motion_is_enabled():
    tour = ProductTourDialog(settings=SettingsStub(True))
    try:
        tour._go(1)
        assert tour.pages.currentIndex() == 1
        assert tour._fade is None
        assert tour._fade_effect is None
        assert tour.pages.graphicsEffect() is None
        assert tour.windowOpacity() == 1.0
    finally:
        _dispose_tour(tour)


def test_guided_tour_transition_uses_shared_motion_token_and_cleans_up():
    tour = ProductTourDialog(settings=SettingsStub(False))
    try:
        tour.show()
        _APP.processEvents()

        tour._go(1)
        assert tour.pages.currentIndex() == 1
        assert tour._fade is not None
        assert tour._fade.state() == QAbstractAnimation.State.Running
        assert tour._fade.duration() == TOUR_DURATION_MS
        assert tour._fade_effect is not None
        assert tour.pages.graphicsEffect() is tour._fade_effect

        QTest.qWait(TOUR_DURATION_MS + 80)
        _APP.processEvents()
        assert tour._fade is None
        assert tour._fade_effect is None
        assert tour.pages.graphicsEffect() is None
        assert tour.windowOpacity() == 1.0
    finally:
        _dispose_tour(tour)



def test_tour_progress_state_uses_shared_stylesheet_not_widget_local_colors():
    tour = ProductTourDialog(settings=SettingsStub(True))
    try:
        assert all(label.styleSheet() == "" for label in tour.progress_labels)
        assert [label.property("current") for label in tour.progress_labels] == [
            True, False, False, False, False
        ]

        tour._go(1)

        assert [label.property("current") for label in tour.progress_labels] == [
            False, True, False, False, False
        ]
        assert all(label.styleSheet() == "" for label in tour.progress_labels)
    finally:
        _dispose_tour(tour)



def test_guided_tour_actions_have_screen_reader_names_and_finish_label():
    tour = ProductTourDialog(settings=SettingsStub(True))
    try:
        assert tour.skip_button.accessibleName() == "Skip guided tour"
        assert tour.back_button.accessibleName() == "Previous guided tour step"
        assert tour.next_button.accessibleName() == "Next guided tour step"
        tour._go(len(tour._pages) - 1)
        assert tour.next_button.accessibleName() == "Finish guided tour"
        assert "Close" in tour.next_button.toolTip()
    finally:
        _dispose_tour(tour)
