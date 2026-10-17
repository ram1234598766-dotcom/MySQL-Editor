from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QWidget

from mysql_editor.ui.animations import (
    MICRO_DURATION_MS,
    STANDARD_DURATION_MS,
    fade_in,
    reduce_motion_enabled,
)


_APP = QApplication.instance() or QApplication([])


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


def test_fade_in_skips_effect_when_reduce_motion_is_enabled():
    widget = QWidget()
    widget.show()
    _APP.processEvents()
    try:
        fade_in(widget, SettingsStub(True), duration_ms=35)
        assert widget.graphicsEffect() is None
        assert getattr(widget, "_mysql_editor_fade_animation", None) is None
    finally:
        widget.close()
        widget.deleteLater()
        _APP.processEvents()


def test_fade_in_skips_invisible_widgets():
    widget = QWidget()
    try:
        fade_in(widget, SettingsStub(False), duration_ms=35)
        assert widget.graphicsEffect() is None
        assert getattr(widget, "_mysql_editor_fade_animation", None) is None
    finally:
        widget.deleteLater()
        _APP.processEvents()


def test_fade_in_cleans_up_effect_after_animation_completes():
    widget = QWidget()
    widget.show()
    _APP.processEvents()
    try:
        fade_in(widget, SettingsStub(False), duration_ms=35)
        animation = getattr(widget, "_mysql_editor_fade_animation", None)
        assert animation is not None
        assert widget.graphicsEffect() is not None

        QTest.qWait(100)
        assert widget.graphicsEffect() is None
        assert getattr(widget, "_mysql_editor_fade_animation", None) is None
    finally:
        widget.close()
        widget.deleteLater()
        _APP.processEvents()


def test_restarting_fade_in_cleans_up_interrupted_animation():
    widget = QWidget()
    widget.show()
    _APP.processEvents()
    try:
        fade_in(widget, SettingsStub(False), duration_ms=180)
        first_animation = getattr(widget, "_mysql_editor_fade_animation", None)
        assert first_animation is not None
        assert widget.graphicsEffect() is not None

        fade_in(widget, SettingsStub(False), duration_ms=35)
        second_animation = getattr(widget, "_mysql_editor_fade_animation", None)
        assert second_animation is not None
        assert second_animation is not first_animation
        assert widget.graphicsEffect() is not None

        QTest.qWait(100)
        assert widget.graphicsEffect() is None
        assert getattr(widget, "_mysql_editor_fade_animation", None) is None
    finally:
        widget.close()
        widget.deleteLater()
        _APP.processEvents()
