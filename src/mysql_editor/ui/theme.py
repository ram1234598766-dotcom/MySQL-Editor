"""Semantic design tokens and the shared dark Qt stylesheet."""
from __future__ import annotations

TOKENS = {
    "window_bg": "#0B111B",
    "surface_base": "#101927",
    "surface_raised": "#162235",
    "surface_hover": "#1B2B42",
    "surface_selected": "#203650",
    "border_subtle": "#26364B",
    "text_primary": "#E7EEF8",
    "text_secondary": "#A6B6CB",
    "text_muted": "#8093AC",
    "accent_primary": "#37C7D8",
    "accent_secondary": "#8D91FF",
    "status_success": "#4CC7A3",
    "status_warning": "#F2BE6B",
    "status_danger": "#F07886",
}


# UI geometry and type are named here so component styles can evolve together.
# Values are CSS pixels unless a key explicitly uses point units.
SPACING = {
    "scale": (4, 8, 12, 16, 20, 24, 32),
    "menu_vertical": 4,
    "menu_horizontal": 10,
    "button_vertical": 8,
    "button_horizontal": 11,
    "tab_vertical": 9,
    "tab_horizontal": 12,
    "tree_item_padding": 4,
    "input_padding": 7,
}

TYPOGRAPHY = {
    "app_family": "Segoe UI",
    "app_size_pt": 9,
    "caption_px": 10,
    "body_px": 12,
    "panel_title_px": 13,
    "brand_title_px": 17,
    "dialog_title_px": 20,
    "page_title_px": 23,
}

RADII = {
    "compact": 4,
    "control": 6,
    "button": 7,
    "panel": 9,
    "feature": 10,
}

COMPONENT_SIZES = {
    "button_min_height": 19,
    "tree_item_min_height": 25,
    "checkbox_indicator": 16,
    "splitter_handle": 5,
    "scrollbar": 12,
}


# Palette for the SQL editor's own painting/highlighting. Qt stylesheets do not
# style QSyntaxHighlighter formats or the custom line-number gutter.
EDITOR_PALETTES = {
    "dark": {
        "keyword": "#37D6E7",
        "string": "#F6C56F",
        "number": "#BD9CFF",
        "function": "#69B7FF",
        "comment": "#7F93AD",
        "gutter_background": "#0A111B",
        "gutter_text": "#71839D",
        "gutter_active_text": "#D2DEED",
        "current_line_background": "#122136",
        "bracket_background": "#2B526D",
        "bracket_foreground": "#F5FAFF",
    },
    "light": {
        "keyword": "#087E8B",
        "string": "#946200",
        "number": "#6D28D9",
        "function": "#1F6FEB",
        "comment": "#526174",
        "gutter_background": "#F1F5F9",
        "gutter_text": "#526174",
        "gutter_active_text": "#243246",
        "current_line_background": "#EFF6FC",
        "bracket_background": "#D6E6F9",
        "bracket_foreground": "#243246",
    },
}

# Component rules remain one stylesheet so semantic palette changes are applied
# consistently. Values are resolved here because Qt stylesheets do not support CSS vars.
# App-level typography is set through QApplication. Avoid universal font rules here so
# each SQL editor can keep its configured monospace family and point size.
_STYLESHEET_TEMPLATE = r'''
QMainWindow, QDialog, QWidget { background: @COLOR_WINDOW_BG@; color: @COLOR_TEXT_PRIMARY@; }
QMenuBar { background: #121a27; color: @COLOR_TEXT_PRIMARY@; padding: @SPACE_MENU_VERTICAL@px @SPACE_MENU_HORIZONTAL@px; border-bottom: 1px solid #2c3a50; }
QMenuBar::item { padding: 6px 9px; border-radius: 5px; }
QMenuBar::item:selected, QMenu { background: @COLOR_SURFACE_RAISED@; }
QMenu { border: 1px solid #344761; padding: 5px; }
QMenu::item { padding: 7px 25px 7px 12px; border-radius: @RADIUS_COMPACT@px; }
QMenu::item:selected { background: #2569cb; color: white; }
QLabel { color: @COLOR_TEXT_PRIMARY@; }
QLabel#mutedText { color: @COLOR_TEXT_SECONDARY@; }
QLabel#noticeText { color: #d3e1f5; background: #111e2f; border: 1px solid #405675; border-radius: 7px; padding: 9px; }
QLabel#dialogTitle { font-size: @TYPE_DIALOG_TITLE@px; font-weight: 650; }
QLabel#brandTitle { font-size: @TYPE_BRAND_TITLE@px; font-weight: 700; }
QLabel#brandSubtitle { color: #9cb0cc; font-size: 9px; font-weight: 650; letter-spacing: 1px; }
QLabel#logoMark { color: #47c8e1; font-size: 28px; font-weight: 700; }
QLabel#pageTitle { font-size: @TYPE_PAGE_TITLE@px; font-weight: 700; }
QLabel#panelTitle { font-size: @TYPE_PANEL_TITLE@px; font-weight: 650; }
QLabel#sectionLabel { color: #aabbd2; font-size: @TYPE_CAPTION@px; font-weight: 700; padding: 4px 8px; }
QLabel#connectionBadge { color: #3bd49b; background: #142d2b; border: 1px solid #426d62; border-radius: 8px; padding: 7px 10px; }
QLabel#connectionBadge[connectionState="lost"] { color: @COLOR_STATUS_DANGER@; background: #3a1f26; border: 1px solid #8f3541; border-radius: 8px; padding: 7px 10px; }
QLabel#connectionBadge[connectionState="disconnected"] { color: @COLOR_TEXT_SECONDARY@; background: @COLOR_SURFACE_RAISED@; border: 1px solid @COLOR_BORDER_SUBTLE@; border-radius: 8px; padding: 7px 10px; }
QWidget#statusStrip { background: #121a27; border-top: 1px solid #354760; }
QLabel#statusBar { background: transparent; color: #c0ccdc; border: none; padding: 7px 13px; }
QLabel#editorPosition { background: transparent; color: #A6B6CB; border: none; padding: 7px 13px; font-family: "Cascadia Code"; font-size: @TYPE_CAPTION@px; }
QLabel#securityNotice, QFrame#securityCard { background: #151f2e; border: 1px solid #405675; border-radius: @RADIUS_PANEL@px; padding: 10px; color: #c0ccdc; }
QFrame#separator { color: #40516a; max-height: 1px; }
QLineEdit, QSpinBox, QComboBox, QPlainTextEdit, QTreeWidget, QListWidget {
  background: #080e17; color: @COLOR_TEXT_PRIMARY@; border: 1px solid #405675;
  border-radius: @RADIUS_CONTROL@px; padding: @SPACE_INPUT_PADDING@px; selection-background-color: #286cc7;
  selection-color: white; min-height: 20px;
}
QLineEdit:focus, QSpinBox:focus, QComboBox:focus, QPlainTextEdit:focus, QTreeWidget:focus, QListWidget:focus,
QPushButton:focus, QToolButton:focus, QTableView:focus, QTabBar::tab:focus { border: 1px solid #4a9bff; }
QComboBox::drop-down { border: none; width: 24px; }
QComboBox QAbstractItemView { background: #101a29; color: @COLOR_TEXT_PRIMARY@; selection-background-color: #2569cb; }
QPushButton { background: @COLOR_SURFACE_RAISED@; color: @COLOR_TEXT_PRIMARY@; border: 1px solid #405675; border-radius: @RADIUS_BUTTON@px; padding: @SPACE_BUTTON_VERTICAL@px @SPACE_BUTTON_HORIZONTAL@px; min-height: @SIZE_BUTTON_MIN_HEIGHT@px; }
QPushButton:hover { background: @COLOR_SURFACE_HOVER@; border-color: #87a4ca; }
QPushButton:pressed { background: #0b1422; }
QPushButton:disabled { color: #8293a9; background: #121a26; border-color: #35465c; }
QPushButton#primaryButton { background: @COLOR_ACCENT_PRIMARY@; color: @COLOR_WINDOW_BG@; border: 1px solid @COLOR_ACCENT_PRIMARY@; font-weight: 650; }
QPushButton#primaryButton:hover { background: #55D5E2; border-color: #55D5E2; }
QPushButton#primaryButton:disabled { background: #121a26; color: #8293a9; border-color: #35465c; }
QPushButton#primaryButton:disabled:hover { background: #121a26; border-color: #35465c; }
QWidget#workspaceNavigation { background: #0d1522; border-bottom: 1px solid #263951; }
QToolButton#navButton { text-align: center; background: transparent; color: #aebed2; border: 1px solid transparent; border-radius: 8px; padding: 9px 13px; }
QToolButton#navButton:hover { background: #18273b; color: #eef6ff; border-color: #354b65; }
QToolButton#navButton:checked { background: @COLOR_SURFACE_SELECTED@; color: #62dff0; border: 1px solid #285c77; }
QToolButton#navButton:focus { border: 1px solid #5bbdff; }
QLabel#navHint { color: #7187a3; font-size: 9px; font-weight: 650; letter-spacing: 1px; padding-right: 5px; }
QLabel#connectionDetails { color: #a7bad1; font-size: @TYPE_CAPTION@px; }
QWidget#findReplaceBar { background: @COLOR_SURFACE_BASE@; border: 1px solid @COLOR_BORDER_SUBTLE@; border-radius: @RADIUS_BUTTON@px; }
QWidget#findReplaceBar QLabel#findMatchCount { color: #A6B6CB; font-size: @TYPE_CAPTION@px; padding: 4px; }
QWidget#findReplaceBar QPushButton { padding: 5px 9px; min-height: 16px; }
QWidget#findReplaceBar QCheckBox { color: #A6B6CB; spacing: 6px; }
QSplitter::handle { background: #263e58; width: @SIZE_SPLITTER_HANDLE@px; height: @SIZE_SPLITTER_HANDLE@px; }
QSplitter::handle:hover { background: #4a9bff; }
QLabel#tourEyebrow { color: #58dcec; font-weight: 700; font-size: @TYPE_CAPTION@px; letter-spacing: 1.2px; }
QLabel#tourStep { color: #91a9c4; font-weight: 700; font-size: @TYPE_CAPTION@px; }
QLabel#tourTitle { color: #f0f6ff; font-size: 23px; font-weight: 700; }
QFrame#tourCard { background: #111d2d; border: 1px solid #2d425b; border-radius: @RADIUS_FEATURE@px; }
QLabel#tourNumber { color: #5ddbec; font-size: @TYPE_CAPTION@px; font-weight: 750; }
QLabel#tourCardTitle { color: #edf5ff; font-weight: 650; font-size: @TYPE_BODY@px; }
QLabel#tourCardBody { color: #adc0d5; font-size: 11px; }
QWidget#tourPage { background: transparent; }
QLabel#tourProgress { padding: 0 2px; }
QLabel#tourProgress[current="true"] { color: #58dcec; font-size: 14px; }
QLabel#tourProgress[current="false"] { color: #7187a3; font-size: @TYPE_BODY@px; }
QTabWidget::pane { background: #090f19; border: 1px solid #405675; border-radius: 7px; top: -1px; }
QTabBar::tab { background: @COLOR_SURFACE_RAISED@; color: #b6c5d9; padding: @SPACE_TAB_VERTICAL@px @SPACE_TAB_HORIZONTAL@px; border: 1px solid #354760; border-top-left-radius: @RADIUS_CONTROL@px; border-top-right-radius: @RADIUS_CONTROL@px; margin-right: 3px; }
QTabBar::tab:selected { background: #090f19; color: @COLOR_TEXT_PRIMARY@; border-bottom-color: #090f19; }
QTableView { background: #0b121d; alternate-background-color: #101b2a; color: @COLOR_TEXT_PRIMARY@; gridline-color: #354760; border: 1px solid #405675; selection-background-color: #1d4f88; selection-color: white; }
QHeaderView::section { background: @COLOR_SURFACE_RAISED@; color: #cad7e7; border: none; border-bottom: 1px solid #405675; padding: 8px; font-weight: 650; }
QTreeWidget, QListWidget { border: none; }
QTreeWidget::item, QListWidget::item { min-height: @SIZE_TREE_ITEM_MIN_HEIGHT@px; padding: @SPACE_TREE_ITEM_PADDING@px; }
QTreeWidget::item:selected, QListWidget::item:selected { background: #205ca4; border-radius: 4px; }
QScrollBar:vertical { background: @COLOR_SURFACE_BASE@; width: @SIZE_SCROLLBAR@px; margin: 1px; }
QScrollBar::handle:vertical { background: #486181; border-radius: 5px; min-height: 24px; }
QScrollBar:horizontal { background: @COLOR_SURFACE_BASE@; height: @SIZE_SCROLLBAR@px; margin: 1px; }
QScrollBar::handle:horizontal { background: #486181; border-radius: 5px; min-width: 24px; }
QCheckBox { spacing: 8px; }
QCheckBox::indicator { width: @SIZE_CHECKBOX_INDICATOR@px; height: @SIZE_CHECKBOX_INDICATOR@px; }
QCheckBox::indicator:unchecked { background: #080e17; border: 1px solid #6b829e; border-radius: 3px; }
QCheckBox::indicator:checked { background: #2879e8; border: 1px solid #438fff; border-radius: 3px; }
QLabel#statusSuccess { color: @COLOR_STATUS_SUCCESS@; }
QLabel#statusWarning { color: @COLOR_STATUS_WARNING@; }
QLabel#statusDanger { color: @COLOR_STATUS_DANGER@; }
QPushButton#accentSecondary { border-color: @COLOR_ACCENT_SECONDARY@; }
'''
 
 
_STYLE_METRIC_VALUES = {
    "@COLOR_WINDOW_BG@": TOKENS["window_bg"],
    "@COLOR_SURFACE_BASE@": TOKENS["surface_base"],
    "@COLOR_SURFACE_RAISED@": TOKENS["surface_raised"],
    "@COLOR_SURFACE_HOVER@": TOKENS["surface_hover"],
    "@COLOR_SURFACE_SELECTED@": TOKENS["surface_selected"],
    "@COLOR_BORDER_SUBTLE@": TOKENS["border_subtle"],
    "@COLOR_TEXT_PRIMARY@": TOKENS["text_primary"],
    "@COLOR_TEXT_SECONDARY@": TOKENS["text_secondary"],
    "@COLOR_ACCENT_PRIMARY@": TOKENS["accent_primary"],
    "@COLOR_ACCENT_SECONDARY@": TOKENS["accent_secondary"],
    "@COLOR_STATUS_SUCCESS@": TOKENS["status_success"],
    "@COLOR_STATUS_WARNING@": TOKENS["status_warning"],
    "@COLOR_STATUS_DANGER@": TOKENS["status_danger"],
    "@SPACE_MENU_VERTICAL@": SPACING["menu_vertical"],
    "@SPACE_MENU_HORIZONTAL@": SPACING["menu_horizontal"],
    "@SPACE_BUTTON_VERTICAL@": SPACING["button_vertical"],
    "@SPACE_BUTTON_HORIZONTAL@": SPACING["button_horizontal"],
    "@SPACE_TAB_VERTICAL@": SPACING["tab_vertical"],
    "@SPACE_TAB_HORIZONTAL@": SPACING["tab_horizontal"],
    "@SPACE_TREE_ITEM_PADDING@": SPACING["tree_item_padding"],
    "@SPACE_INPUT_PADDING@": SPACING["input_padding"],
    "@TYPE_DIALOG_TITLE@": TYPOGRAPHY["dialog_title_px"],
    "@TYPE_BRAND_TITLE@": TYPOGRAPHY["brand_title_px"],
    "@TYPE_PAGE_TITLE@": TYPOGRAPHY["page_title_px"],
    "@TYPE_PANEL_TITLE@": TYPOGRAPHY["panel_title_px"],
    "@TYPE_CAPTION@": TYPOGRAPHY["caption_px"],
    "@TYPE_BODY@": TYPOGRAPHY["body_px"],
    "@RADIUS_COMPACT@": RADII["compact"],
    "@RADIUS_CONTROL@": RADII["control"],
    "@RADIUS_BUTTON@": RADII["button"],
    "@RADIUS_PANEL@": RADII["panel"],
    "@RADIUS_FEATURE@": RADII["feature"],
    "@SIZE_BUTTON_MIN_HEIGHT@": COMPONENT_SIZES["button_min_height"],
    "@SIZE_TREE_ITEM_MIN_HEIGHT@": COMPONENT_SIZES["tree_item_min_height"],
    "@SIZE_CHECKBOX_INDICATOR@": COMPONENT_SIZES["checkbox_indicator"],
    "@SIZE_SPLITTER_HANDLE@": COMPONENT_SIZES["splitter_handle"],
    "@SIZE_SCROLLBAR@": COMPONENT_SIZES["scrollbar"],
}


def _resolve_style_tokens(template: str) -> str:
    """Resolve semantic palette, geometry and typography tokens for Qt."""
    result = template
    for placeholder, value in _STYLE_METRIC_VALUES.items():
        result = result.replace(placeholder, str(value))
    return result


STYLESHEET = _resolve_style_tokens(_STYLESHEET_TEMPLATE)


# A light palette is generated by translating the shared dark stylesheet rather than
# maintaining a second, drifting set of widget rules. Deep selection/focus accents remain
# dark enough for readable white text; state colours keep their semantic meaning.
_LIGHT_COLOR_MAP = {
    "#0B111B": "#F8FAFC", "#101927": "#FFFFFF", "#162235": "#EEF3F8",
    "#1B2B42": "#E6EDF5", "#203650": "#D6E3F2", "#26364B": "#CFD8E3",
    "#E7EEF8": "#263548", "#A6B6CB": "#526174", "#8093AC": "#65748A",
    "#37C7D8": "#087E8B", "#8D91FF": "#5B5FC7", "#4CC7A3": "#126B50",
    "#F2BE6B": "#946200", "#F07886": "#B42335", "#e8f1ff": "#243246",
    "#121a27": "#F2F5F9", "#2c3a50": "#CBD5E1", "#172235": "#E9EFF6",
    "#344761": "#CBD5E1", "#2569cb": "#225EA8", "#a9bad0": "#526174",
    "#d3e1f5": "#344256", "#111e2f": "#F6F8FB", "#405675": "#CBD5E1",
    "#9cb0cc": "#526174", "#47c8e1": "#087E8B", "#aabbd2": "#526174",
    "#3bd49b": "#126B50", "#142d2b": "#DFF5ED", "#426d62": "#ACD6C7",
    "#3a1f26": "#FCE7E9", "#8f3541": "#FDA4AF",
    "#354760": "#D6DEE8", "#c0ccdc": "#526174", "#151f2e": "#F2F5F9",
    "#40516a": "#CFD8E3", "#080e17": "#FFFFFF", "#286cc7": "#225EA8",
    "#4a9bff": "#1F6FEB", "#101a29": "#F8FAFC", "#22334b": "#E4EBF3",
    "#87a4ca": "#64748B", "#0b1422": "#E2E8F0", "#8293a9": "#64748B",
    "#121a26": "#F2F5F9", "#35465c": "#D6DEE8", "#55D5E2": "#056C78",
    "#0d1522": "#F8FAFC", "#263951": "#CFD8E3", "#aebed2": "#526174",
    "#18273b": "#E7EEF6", "#eef6ff": "#243246", "#354b65": "#D1DCE8",
    "#132b42": "#D4E6F4", "#62dff0": "#087E8B", "#285c77": "#AFC5D6",
    "#5bbdff": "#1F6FEB", "#7187a3": "#63748A", "#a7bad1": "#526174",
    "#263e58": "#CDD7E3", "#58dcec": "#087E8B", "#91a9c4": "#526174",
    "#f0f6ff": "#243246", "#111d2d": "#F6F8FB", "#2d425b": "#D1DCE8",
    "#5ddbec": "#087E8B", "#edf5ff": "#243246", "#adc0d5": "#526174",
    "#090f19": "#FFFFFF", "#b6c5d9": "#526174", "#0b121d": "#FFFFFF",
    "#101b2a": "#F8FAFC", "#1d4f88": "#184C82", "#cad7e7": "#344256",
    "#205ca4": "#D6E6F9", "#486181": "#C1CBD8", "#6b829e": "#687B91",
    "#2879e8": "#1F6FEB", "#438fff": "#1F6FEB",
}


def normalize_theme(value: object) -> str:
    """Validate a persisted theme preference, defaulting safely to dark."""
    name = str(value or "dark").strip().lower()
    return name if name in {"system", "light", "dark"} else "dark"


def resolve_theme(value: object, system_is_dark: bool | None = None) -> str:
    """Resolve System/Light/Dark to a concrete palette name."""
    name = normalize_theme(value)
    if name != "system":
        return name
    if system_is_dark is None:
        system_is_dark = _system_prefers_dark()
    return "dark" if system_is_dark else "light"


def _system_prefers_dark() -> bool:
    """Read the Windows app-colour preference, with a Qt-palette fallback elsewhere."""
    import sys

    if sys.platform == "win32":
        try:
            from PySide6.QtCore import QSettings

            registry = QSettings(
                r"HKEY_CURRENT_USER\Software\Microsoft\Windows\CurrentVersion\Themes\Personalize",
                QSettings.Format.NativeFormat,
            )
            return int(registry.value("AppsUseLightTheme", 1)) == 0
        except (ImportError, TypeError, ValueError, RuntimeError):
            pass

    try:
        from PySide6.QtGui import QPalette
        from PySide6.QtWidgets import QApplication

        app = QApplication.instance()
        if app is not None:
            return app.palette().color(QPalette.ColorRole.Window).lightness() < 128
    except (ImportError, RuntimeError):
        pass
    return False


def stylesheet_for_theme(value: object = "dark", system_is_dark: bool | None = None) -> str:
    """Return the shared stylesheet for the validated theme preference."""
    if resolve_theme(value, system_is_dark) == "dark":
        return STYLESHEET
    stylesheet = STYLESHEET
    for dark_value, light_value in _LIGHT_COLOR_MAP.items():
        stylesheet = stylesheet.replace(dark_value, light_value)
    return stylesheet


def color_for_theme(
    token_name: str, value: object = "dark", system_is_dark: bool | None = None,
) -> str:
    """Resolve a semantic colour token for the selected concrete palette."""
    if token_name not in TOKENS:
        raise KeyError(f"Unknown theme colour token: {token_name}")
    dark_color = TOKENS[token_name]
    if resolve_theme(value, system_is_dark) == "dark":
        return dark_color
    return _LIGHT_COLOR_MAP.get(dark_color, dark_color)
