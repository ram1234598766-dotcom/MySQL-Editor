"""Small, interruptible UI transitions with a persistent reduced-motion path."""
from __future__ import annotations

from PySide6.QtCore import QEasingCurve, QPropertyAnimation, QSettings
from PySide6.QtWidgets import QGraphicsOpacityEffect, QWidget

MICRO_DURATION_MS = 120
STANDARD_DURATION_MS = 180


def reduce_motion_enabled(settings: QSettings | None = None) -> bool:
    settings = settings or QSettings()
    return settings.value("ui/reduceMotion", False, type=bool)


def fade_in(widget: QWidget, settings: QSettings | None = None, duration_ms: int = MICRO_DURATION_MS) -> None:
    """Fade a small panel into place; restore its graphics state on completion."""
    previous = getattr(widget, "_mysql_editor_fade_animation", None)
    if previous is not None:
        previous.stop()
        previous.deleteLater()
        widget._mysql_editor_fade_animation = None

    if reduce_motion_enabled(settings) or not widget.isVisible():
        return

    effect = QGraphicsOpacityEffect(widget)
    effect.setOpacity(0.72)
    widget.setGraphicsEffect(effect)
    animation = QPropertyAnimation(effect, b"opacity", widget)
    animation.setDuration(max(0, min(int(duration_ms), STANDARD_DURATION_MS)))
    animation.setStartValue(0.72)
    animation.setEndValue(1.0)
    animation.setEasingCurve(QEasingCurve.Type.OutCubic)

    def cleanup() -> None:
        if getattr(widget, "_mysql_editor_fade_animation", None) is animation:
            widget.setGraphicsEffect(None)
            widget._mysql_editor_fade_animation = None
        animation.deleteLater()

    animation.finished.connect(cleanup)
    widget._mysql_editor_fade_animation = animation
    animation.start()
