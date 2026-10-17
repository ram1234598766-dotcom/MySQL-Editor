"""Small, interruptible UI transitions with a persistent reduced-motion path."""
from __future__ import annotations

from PySide6.QtCore import QEasingCurve, QSettings, QVariantAnimation
from PySide6.QtGui import QColor
from PySide6.QtWidgets import QWidget

MICRO_DURATION_MS = 120
STANDARD_DURATION_MS = 180
TOUR_DURATION_MS = 260
MAX_DURATION_MS = 280
_COLOR_ANIMATION_ATTR = "_mysql_editor_color_animation"


def reduce_motion_enabled(settings: QSettings | None = None) -> bool:
    """Return whether optional motion should be replaced with immediate feedback."""
    settings = settings or QSettings()
    return settings.value("ui/reduceMotion", False, type=bool)


def _set_label_color(widget: QWidget, color: QColor) -> None:
    """Apply a non-layout-changing color update to a small status/progress label."""
    widget.setStyleSheet(f"color: {color.name()}; font-size: 14px;")


def stop_color_animation(widget: QWidget) -> None:
    """Stop the widget's active color transition without leaving stale state behind."""
    animation = getattr(widget, _COLOR_ANIMATION_ATTR, None)
    if animation is None:
        return
    animation.stop()
    setattr(widget, _COLOR_ANIMATION_ATTR, None)
    animation.deleteLater()


def animate_label_color(
    widget: QWidget,
    *,
    settings: QSettings | None = None,
    duration_ms: int = MICRO_DURATION_MS,
    start_color: str = "#4a607c",
    end_color: str = "#50d9ee",
) -> QVariantAnimation | None:
    """Animate a small label's accent color without graphics effects or layout changes."""
    stop_color_animation(widget)
    end = QColor(end_color)
    if reduce_motion_enabled(settings) or not widget.isVisible():
        _set_label_color(widget, end)
        return None

    animation = QVariantAnimation(widget)
    animation.setDuration(max(0, min(int(duration_ms), MAX_DURATION_MS)))
    animation.setStartValue(QColor(start_color))
    animation.setEndValue(end)
    animation.setEasingCurve(QEasingCurve.Type.OutCubic)
    animation.valueChanged.connect(lambda value: _set_label_color(widget, value))

    def finish() -> None:
        _set_label_color(widget, end)
        if getattr(widget, _COLOR_ANIMATION_ATTR, None) is animation:
            setattr(widget, _COLOR_ANIMATION_ATTR, None)
        animation.deleteLater()

    animation.finished.connect(finish)
    setattr(widget, _COLOR_ANIMATION_ATTR, animation)
    animation.start()
    return animation
