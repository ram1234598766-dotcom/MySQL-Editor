"""Regression checks for safe, interruptible UI color transitions."""
from PySide6.QtCore import QAbstractAnimation
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QLabel

from mysql_editor.ui.animations import (
    MICRO_DURATION_MS, STANDARD_DURATION_MS, animate_label_color,
    reduce_motion_enabled,
)


class SettingsStub:
    def __init__(self, value):
        self._value = value

    def value(self, key, default=False, type=bool):
        assert key == "ui/reduceMotion"
        return self._value


_APP = QApplication.instance() or QApplication([])


def test_reduce_motion_defaults_to_disabled():
    assert reduce_motion_enabled(SettingsStub(False)) is False


def test_reduce_motion_setting_is_respected():
    assert reduce_motion_enabled(SettingsStub(True)) is True


def test_animation_durations_are_short_and_bounded():
    assert 0 < MICRO_DURATION_MS <= STANDARD_DURATION_MS <= 220


def test_color_transition_restores_final_color_after_completion():
    label = QLabel("step")
    label.show()
    _APP.processEvents()

    animation = animate_label_color(
        label, settings=SettingsStub(False), duration_ms=1,
        start_color="#4a607c", end_color="#50d9ee",
    )
    assert animation is not None
    assert animation.state() == QAbstractAnimation.State.Running
    assert getattr(label, "_mysql_editor_color_animation", None) is animation

    QTest.qWait(35)
    _APP.processEvents()

    assert getattr(label, "_mysql_editor_color_animation", None) is None
    assert "#50d9ee" in label.styleSheet()
    label.close()


def test_reduce_motion_interrupts_active_transition_and_sets_final_state():
    label = QLabel("step")
    label.show()
    _APP.processEvents()

    animation = animate_label_color(label, settings=SettingsStub(False), duration_ms=180)
    assert animation is not None
    animate_label_color(label, settings=SettingsStub(True))

    assert animation.state() == QAbstractAnimation.State.Stopped
    assert getattr(label, "_mysql_editor_color_animation", None) is None
    assert "#50d9ee" in label.styleSheet()
    label.close()


def test_hidden_widget_gets_immediate_state_without_animation():
    label = QLabel("step")

    animation = animate_label_color(label, settings=SettingsStub(False))

    assert animation is None
    assert getattr(label, "_mysql_editor_color_animation", None) is None
    assert "#50d9ee" in label.styleSheet()
