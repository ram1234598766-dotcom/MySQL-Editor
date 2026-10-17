"""Regression checks for transition settings and deterministic headless feedback."""
import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

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


def test_reduce_motion_setting_is_respected():
    assert reduce_motion_enabled(SettingsStub(True)) is True
    assert reduce_motion_enabled(SettingsStub(False)) is False


def test_animation_durations_are_short_and_bounded():
    assert 0 < MICRO_DURATION_MS <= STANDARD_DURATION_MS <= 220


def test_headless_platform_uses_immediate_feedback_without_animation():
    label = QLabel("step")
    label.show()
    _APP.processEvents()

    animation = animate_label_color(
        label, settings=SettingsStub(False), duration_ms=1,
        start_color="#4a607c", end_color="#50d9ee",
    )

    assert animation is None
    assert getattr(label, "_mysql_editor_color_animation", None) is None
    assert "#50d9ee" in label.styleSheet()
    label.close()


def test_reduce_motion_uses_immediate_feedback():
    label = QLabel("step")
    label.show()
    _APP.processEvents()

    animation = animate_label_color(label, settings=SettingsStub(True))

    assert animation is None
    assert getattr(label, "_mysql_editor_color_animation", None) is None
    assert "#50d9ee" in label.styleSheet()
    label.close()


def test_hidden_widget_gets_immediate_state_without_animation():
    label = QLabel("step")

    animation = animate_label_color(label, settings=SettingsStub(False))

    assert animation is None
    assert getattr(label, "_mysql_editor_color_animation", None) is None
    assert "#50d9ee" in label.styleSheet()
