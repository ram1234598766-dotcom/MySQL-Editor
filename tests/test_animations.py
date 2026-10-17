from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QWidget

from mysql_editor.ui.animations import (
    MICRO_DURATION_MS, STANDARD_DURATION_MS, reduce_motion_enabled, fade_in,
)


class SettingsStub:
    def __init__(self, value):
        self._value = value

    def value(self, key, default=False, type=bool):
        assert key == "ui/reduceMotion"
        return self._value


def test_reduce_motion_defaults_to_disabled():
    assert reduce_motion_enabled(SettingsStub(False)) is False


def test_reduce_motion_setting_is_respected():
    assert reduce_motion_enabled(SettingsStub(True)) is True


def test_animation_durations_are_short_and_bounded():
    assert 0 < MICRO_DURATION_MS <= STANDARD_DURATION_MS <= 220



_APP = QApplication.instance() or QApplication([])


def test_fade_in_restores_widget_graphics_state_after_completion():
    widget = QWidget()
    widget.show()
    _APP.processEvents()

    fade_in(widget, SettingsStub(False), duration_ms=1)
    animation = getattr(widget, "_mysql_editor_fade_animation", None)
    assert animation is not None
    assert widget.graphicsEffect() is not None

    QTest.qWait(35)
    _APP.processEvents()

    assert widget.graphicsEffect() is None
    assert getattr(widget, "_mysql_editor_fade_animation", None) is None
    widget.close()


def test_reduce_motion_interrupts_and_cleans_an_active_fade():
    widget = QWidget()
    widget.show()
    _APP.processEvents()

    fade_in(widget, SettingsStub(False), duration_ms=180)
    animation = getattr(widget, "_mysql_editor_fade_animation", None)
    assert animation is not None

    fade_in(widget, SettingsStub(True))

    assert animation.state() == animation.State.Stopped
    assert widget.graphicsEffect() is None
    assert getattr(widget, "_mysql_editor_fade_animation", None) is None
    widget.close()


def test_hidden_widget_does_not_receive_a_graphics_effect():
    widget = QWidget()

    fade_in(widget, SettingsStub(False))

    assert widget.graphicsEffect() is None
    assert getattr(widget, "_mysql_editor_fade_animation", None) is None
