"""Small, interruptible UI transitions with a persistent reduced-motion path."""
from __future__ import annotations

import weakref

from PySide6.QtCore import QEasingCurve, QSettings, QVariantAnimation
from PySide6.QtGui import QColor
from PySide6.QtWidgets import QWidget

MICRO_DURATION_MS = 120
STANDARD_DURATION_MS = 180
TOUR_DURATION_MS = 260
MAX_DURATION_MS = 280
_COLOR_ANIMATION_ATTR = "_mysql_editor_color_animation"
_COLOR_ANIMATION_GENERATION_ATTR = "_mysql_editor_color_animation_generation"
_COLOR_ANIMATION_OBJECT_NAME = "mysqlEditorColorTransition"


def reduce_motion_enabled(settings: QSettings | None = None) -> bool:
    """Return whether optional motion should be replaced with immediate feedback."""
    settings = settings or QSettings()
    return settings.value("ui/reduceMotion", False, type=bool)


def _set_label_color(widget: QWidget, color: QColor) -> None:
    """Apply a non-layout-changing color update to a small status/progress label."""
    widget.setStyleSheet(f"color: {color.name()}; font-size: 14px;")


def _find_animation(widget: QWidget) -> QVariantAnimation | None:
    animation = getattr(widget, "_mysql_editor_color_transition", None)
    if animation is not None:
        return animation
    return widget.findChild(QVariantAnimation, _COLOR_ANIMATION_OBJECT_NAME)


def stop_color_animation(widget: QWidget) -> None:
    """Stop active color feedback; retain its Qt-owned animator for safe reuse."""
    animation = _find_animation(widget)
    setattr(widget, _COLOR_ANIMATION_ATTR, None)
    setattr(widget, _COLOR_ANIMATION_GENERATION_ATTR, None)
    if animation is not None:
        animation.stop()


def _ensure_animation(widget: QWidget) -> QVariantAnimation:
    """Create at most one Qt-parented animation per label and connect it once."""
    existing = _find_animation(widget)
    if existing is not None:
        return existing

    target_ref = weakref.ref(widget)
    animation = QVariantAnimation(widget)
    animation.setObjectName(_COLOR_ANIMATION_OBJECT_NAME)

    def update_color(value, ref=target_ref) -> None:
        target = ref()
        if target is not None and getattr(target, _COLOR_ANIMATION_GENERATION_ATTR, None) is not None:
            _set_label_color(target, value)

    def finish(ref=target_ref) -> None:
        target = ref()
        if target is None:
            return
        generation = getattr(target, _COLOR_ANIMATION_GENERATION_ATTR, None)
        if generation is None:
            return
        final_color = QColor(getattr(target, "_mysql_editor_color_animation_end", "#50d9ee"))
        _set_label_color(target, final_color)
        setattr(target, _COLOR_ANIMATION_ATTR, None)
        setattr(target, _COLOR_ANIMATION_GENERATION_ATTR, None)

    animation.valueChanged.connect(update_color)
    animation.finished.connect(finish)
    # Retain the wrapper for the full lifetime of the widget. Qt owns the
    # underlying QObject as a child; dropping its only Python wrapper while the
    # parent is still alive can crash PySide during interpreter shutdown.
    widget._mysql_editor_color_transition = animation
    return animation


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

    animation = _ensure_animation(widget)
    generation = object()
    setattr(widget, _COLOR_ANIMATION_GENERATION_ATTR, generation)
    widget._mysql_editor_color_animation_end = end.name()
    animation.setDuration(max(0, min(int(duration_ms), MAX_DURATION_MS)))
    animation.setStartValue(QColor(start_color))
    animation.setEndValue(end)
    animation.setEasingCurve(QEasingCurve.Type.OutCubic)
    setattr(widget, _COLOR_ANIMATION_ATTR, animation)
    animation.start()
    return animation
