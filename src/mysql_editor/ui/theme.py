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


# Named colours for recurring widget states; all are resolved before Qt sees the stylesheet.
STYLE_COLORS = {
    "menu_background": "#121a27",
    "menu_border": "#2c3a50",
    "menu_selection": "#2569cb",
    "notice_background": "#111e2f",
    "notice_text": "#d3e1f5",
    "control_border": "#405675",
    "input_background": "#080e17",
    "selection_background": "#286cc7",
    "focus_border": "#4a9bff",
    "disabled_text": "#8293a9",
    "disabled_background": "#121a26",
    "disabled_border": "#35465c",
    "primary_hover": "#55D5E2",
    "navigation_background": "#0d1522",
    "navigation_hover": "#18273b",
    "navigation_text": "#aebed2",
    "navigation_selected_text": "#62dff0",
    "navigation_focus": "#5bbdff",
    "table_background": "#0b121d",
    "table_alternate": "#101b2a",
    "table_selection": "#1d4f88",
    "tree_selection": "#205ca4",
    "scrollbar_handle": "#486181",
    "checkbox_border": "#6b829e",
    "checkbox_checked": "#2879e8",
    "checkbox_checked_border": "#438fff",
    "menu_item_border": "#344761",
    "brand_subtitle": "#9cb0cc",
    "brand_accent": "#47c8e1",
    "section_label": "#aabbd2",
    "connection_success_text": "#3bd49b",
    "connection_success_background": "#142d2b",
    "connection_success_border": "#426d62",
    "connection_lost_background": "#3a1f26",
    "connection_lost_border": "#8f3541",
    "status_strip_border": "#354760",
    "status_text": "#c0ccdc",
    "editor_position_text": "#A6B6CB",
    "security_surface": "#151f2e",
    "separator": "#40516a",
    "combo_background": "#101a29",
    "combo_arrow": "#87a4ca",
    "pressed_surface": "#0b1422",
    "navigation_border": "#263951",
    "navigation_hover_text": "#eef6ff",
    "navigation_hover_border": "#354b65",
    "navigation_selected_border": "#285c77",
    "navigation_hint": "#7187a3",
    "connection_details": "#a7bad1",
    "splitter": "#263e58",
    "tour_accent": "#58dcec",
    "tour_step": "#91a9c4",
    "tour_title": "#f0f6ff",
    "tour_surface": "#111d2d",
    "tour_border": "#2d425b",
    "tour_number": "#5ddbec",
    "tour_card_title": "#edf5ff",
    "tour_card_body": "#adc0d5",
    "editor_surface": "#090f19",
    "tab_text": "#b6c5d9",
    "table_header_text": "#cad7e7",
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
QMenuBar { background: @STYLE_MENU_BACKGROUND@; color: @COLOR_TEXT_PRIMARY@; padding: @SPACE_MENU_VERTICAL@px @SPACE_MENU_HORIZONTAL@px; border-bottom: 1px solid @STYLE_MENU_BORDER@; }
QMenuBar::item { padding: 6px 9px; border-radius: 5px; }
QMenuBar::item:selected, QMenu { background: @COLOR_SURFACE_RAISED@; }
QMenu { border: 1px solid @STYLE_MENU_ITEM_BORDER@; padding: 5px; }
QMenu::item { padding: 7px 25px 7px 12px; border-radius: @RADIUS_COMPACT@px; }
QMenu::item:selected { background: @STYLE_MENU_SELECTION@; color: white; }
QLabel { color: @COLOR_TEXT_PRIMARY@; }
QLabel#mutedText { color: @COLOR_TEXT_SECONDARY@; }
QLabel#noticeText { color: @STYLE_NOTICE_TEXT@; background: @STYLE_NOTICE_BACKGROUND@; border: 1px solid @STYLE_CONTROL_BORDER@; border-radius: 7px; padding: 9px; }
QLabel#dialogTitle { font-size: @TYPE_DIALOG_TITLE@px; font-weight: 650; }
QLabel#brandTitle { font-size: @TYPE_BRAND_TITLE@px; font-weight: 700; }
QLabel#brandSubtitle { color: @STYLE_BRAND_SUBTITLE@; font-size: 9px; font-weight: 650; letter-spacing: 1px; }
QLabel#logoMark { color: @STYLE_BRAND_ACCENT@; font-size: 28px; font-weight: 700; }
QLabel#pageTitle { font-size: @TYPE_PAGE_TITLE@px; font-weight: 700; }
QLabel#panelTitle { font-size: @TYPE_PANEL_TITLE@px; font-weight: 650; }
QLabel#sectionLabel { color: @STYLE_SECTION_LABEL@; font-size: @TYPE_CAPTION@px; font-weight: 700; padding: 4px 8px; }
QLabel#connectionBadge { color: @STYLE_CONNECTION_SUCCESS_TEXT@; background: @STYLE_CONNECTION_SUCCESS_BACKGROUND@; border: 1px solid @STYLE_CONNECTION_SUCCESS_BORDER@; border-radius: 8px; padding: 7px 10px; }
QLabel#connectionBadge[connectionState="lost"] { color: @COLOR_STATUS_DANGER@; background: @STYLE_CONNECTION_LOST_BACKGROUND@; border: 1px solid @STYLE_CONNECTION_LOST_BORDER@; border-radius: 8px; padding: 7px 10px; }
QLabel#connectionBadge[connectionState="disconnected"] { color: @COLOR_TEXT_SECONDARY@; background: @COLOR_SURFACE_RAISED@; border: 1px solid @COLOR_BORDER_SUBTLE@; border-radius: 8px; padding: 7px 10px; }
QWidget#statusStrip { background: @STYLE_MENU_BACKGROUND@; border-top: 1px solid @STYLE_STATUS_STRIP_BORDER@; }
QLabel#statusBar { background: transparent; color: @STYLE_STATUS_TEXT@; border: none; padding: 7px 13px; }
QLabel#editorPosition { background: transparent; color: @STYLE_EDITOR_POSITION_TEXT@; border: none; padding: 7px 13px; font-family: "Cascadia Code"; font-size: @TYPE_CAPTION@px; }
QLabel#securityNotice, QFrame#securityCard { background: @STYLE_SECURITY_SURFACE@; border: 1px solid @STYLE_CONTROL_BORDER@; border-radius: @RADIUS_PANEL@px; padding: 10px; color: @STYLE_STATUS_TEXT@; }
QFrame#separator { color: @STYLE_SEPARATOR@; max-height: 1px; }
QLineEdit, QSpinBox, QComboBox, QPlainTextEdit, QTreeWidget, QListWidget {
  background: @STYLE_INPUT_BACKGROUND@; color: @COLOR_TEXT_PRIMARY@; border: 1px solid @STYLE_CONTROL_BORDER@;
  border-radius: @RADIUS_CONTROL@px; padding: @SPACE_INPUT_PADDING@px; selection-background-color: @STYLE_SELECTION_BACKGROUND@;
  selection-color: white; min-height: 20px;
}
QLineEdit:focus, QSpinBox:focus, QComboBox:focus, QPlainTextEdit:focus, QTreeWidget:focus, QListWidget:focus,
QPushButton:focus, QToolButton:focus, QTableView:focus, QTabBar::tab:focus { border: 1px solid @STYLE_FOCUS_BORDER@; }
QComboBox::drop-down { border: none; width: 24px; }
QComboBox QAbstractItemView { background: @STYLE_COMBO_BACKGROUND@; color: @COLOR_TEXT_PRIMARY@; selection-background-color: @STYLE_MENU_SELECTION@; }
QPushButton { background: @COLOR_SURFACE_RAISED@; color: @COLOR_TEXT_PRIMARY@; border: 1px solid @STYLE_CONTROL_BORDER@; border-radius: @RADIUS_BUTTON@px; padding: @SPACE_BUTTON_VERTICAL@px @SPACE_BUTTON_HORIZONTAL@px; min-height: @SIZE_BUTTON_MIN_HEIGHT@px; }
QPushButton:hover { background: @COLOR_SURFACE_HOVER@; border-color: @STYLE_COMBO_ARROW@; }
QPushButton:pressed { background: @STYLE_PRESSED_SURFACE@; }
QPushButton:disabled { color: @STYLE_DISABLED_TEXT@; background: @STYLE_DISABLED_BACKGROUND@; border-color: @STYLE_DISABLED_BORDER@; }
QPushButton#primaryButton { background: @COLOR_ACCENT_PRIMARY@; color: @COLOR_WINDOW_BG@; border: 1px solid @COLOR_ACCENT_PRIMARY@; font-weight: 650; }
QPushButton#primaryButton:hover { background: @STYLE_PRIMARY_HOVER@; border-color: @STYLE_PRIMARY_HOVER@; }
QPushButton#primaryButton:disabled { background: @STYLE_DISABLED_BACKGROUND@; color: @STYLE_EDITOR_POSITION_TEXT@; border-color: @STYLE_DISABLED_BORDER@; }
QPushButton#primaryButton:disabled:hover { background: @STYLE_DISABLED_BACKGROUND@; border-color: @STYLE_DISABLED_BORDER@; }
QWidget#workspaceNavigation { background: @STYLE_NAVIGATION_BACKGROUND@; border-bottom: 1px solid @STYLE_NAVIGATION_BORDER@; }
QToolButton#navButton { text-align: center; background: transparent; color: @STYLE_NAVIGATION_TEXT@; border: 1px solid transparent; border-radius: 8px; padding: 9px 13px; }
QToolButton#navButton:hover { background: @STYLE_NAVIGATION_HOVER@; color: @STYLE_NAVIGATION_HOVER_TEXT@; border-color: @STYLE_NAVIGATION_HOVER_BORDER@; }
QToolButton#navButton:checked { background: @COLOR_SURFACE_SELECTED@; color: @STYLE_NAVIGATION_SELECTED_TEXT@; border: 1px solid @STYLE_NAVIGATION_SELECTED_BORDER@; }
QToolButton#navButton:focus { border: 1px solid @STYLE_NAVIGATION_FOCUS@; }
QLabel#navHint { color: @STYLE_NAVIGATION_HINT@; font-size: 9px; font-weight: 650; letter-spacing: 1px; padding-right: 5px; }
QLabel#connectionDetails { color: @STYLE_CONNECTION_DETAILS@; font-size: @TYPE_CAPTION@px; }
QWidget#findReplaceBar { background: @COLOR_SURFACE_BASE@; border: 1px solid @COLOR_BORDER_SUBTLE@; border-radius: @RADIUS_BUTTON@px; }
QWidget#findReplaceBar QLabel#findMatchCount { color: @STYLE_EDITOR_POSITION_TEXT@; font-size: @TYPE_CAPTION@px; padding: 4px; }
QWidget#findReplaceBar QPushButton { padding: 5px 9px; min-height: 16px; }
QWidget#findReplaceBar QCheckBox { color: @STYLE_EDITOR_POSITION_TEXT@; spacing: 6px; }
QSplitter::handle { background: @STYLE_SPLITTER@; width: @SIZE_SPLITTER_HANDLE@px; height: @SIZE_SPLITTER_HANDLE@px; }
QSplitter::handle:hover { background: @STYLE_FOCUS_BORDER@; }
QLabel#tourEyebrow { color: @STYLE_TOUR_ACCENT@; font-weight: 700; font-size: @TYPE_CAPTION@px; letter-spacing: 1.2px; }
QLabel#tourStep { color: @STYLE_TOUR_STEP@; font-weight: 700; font-size: @TYPE_CAPTION@px; }
QLabel#tourTitle { color: @STYLE_TOUR_TITLE@; font-size: 23px; font-weight: 700; }
QFrame#tourCard { background: @STYLE_TOUR_SURFACE@; border: 1px solid @STYLE_TOUR_BORDER@; border-radius: @RADIUS_FEATURE@px; }
QLabel#tourNumber { color: @STYLE_TOUR_NUMBER@; font-size: @TYPE_CAPTION@px; font-weight: 750; }
QLabel#tourCardTitle { color: @STYLE_TOUR_CARD_TITLE@; font-weight: 650; font-size: @TYPE_BODY@px; }
QLabel#tourCardBody { color: @STYLE_TOUR_CARD_BODY@; font-size: 11px; }
QWidget#tourPage { background: transparent; }
QLabel#tourProgress { padding: 0 2px; }
QLabel#tourProgress[current="true"] { color: @STYLE_TOUR_ACCENT@; font-size: 14px; }
QLabel#tourProgress[current="false"] { color: @STYLE_NAVIGATION_HINT@; font-size: @TYPE_BODY@px; }
QTabWidget::pane { background: @STYLE_EDITOR_SURFACE@; border: 1px solid @STYLE_CONTROL_BORDER@; border-radius: 7px; top: -1px; }
QTabBar::tab { background: @COLOR_SURFACE_RAISED@; color: @STYLE_TAB_TEXT@; padding: @SPACE_TAB_VERTICAL@px @SPACE_TAB_HORIZONTAL@px; border: 1px solid @STYLE_STATUS_STRIP_BORDER@; border-top-left-radius: @RADIUS_CONTROL@px; border-top-right-radius: @RADIUS_CONTROL@px; margin-right: 3px; }
QTabBar::tab:selected { background: @STYLE_EDITOR_SURFACE@; color: @COLOR_TEXT_PRIMARY@; border-bottom-color: @STYLE_EDITOR_SURFACE@; }
QTableView { background: @STYLE_TABLE_BACKGROUND@; alternate-background-color: @STYLE_TABLE_ALTERNATE@; color: @COLOR_TEXT_PRIMARY@; gridline-color: @STYLE_STATUS_STRIP_BORDER@; border: 1px solid @STYLE_CONTROL_BORDER@; selection-background-color: @STYLE_TABLE_SELECTION@; selection-color: white; }
QHeaderView::section { background: @COLOR_SURFACE_RAISED@; color: @STYLE_TABLE_HEADER_TEXT@; border: none; border-bottom: 1px solid @STYLE_CONTROL_BORDER@; padding: 8px; font-weight: 650; }
QTreeWidget, QListWidget { border: none; }
QTreeWidget::item, QListWidget::item { min-height: @SIZE_TREE_ITEM_MIN_HEIGHT@px; padding: @SPACE_TREE_ITEM_PADDING@px; }
QTreeWidget::item:selected, QListWidget::item:selected { background: @STYLE_TREE_SELECTION@; border-radius: 4px; }
QScrollBar:vertical { background: @COLOR_SURFACE_BASE@; width: @SIZE_SCROLLBAR@px; margin: 1px; }
QScrollBar::handle:vertical { background: @STYLE_SCROLLBAR_HANDLE@; border-radius: 5px; min-height: 24px; }
QScrollBar:horizontal { background: @COLOR_SURFACE_BASE@; height: @SIZE_SCROLLBAR@px; margin: 1px; }
QScrollBar::handle:horizontal { background: @STYLE_SCROLLBAR_HANDLE@; border-radius: 5px; min-width: 24px; }
QCheckBox { spacing: 8px; }
QCheckBox::indicator { width: @SIZE_CHECKBOX_INDICATOR@px; height: @SIZE_CHECKBOX_INDICATOR@px; }
QCheckBox::indicator:unchecked { background: @STYLE_INPUT_BACKGROUND@; border: 1px solid @STYLE_CHECKBOX_BORDER@; border-radius: 3px; }
QCheckBox::indicator:checked { background: @STYLE_CHECKBOX_CHECKED@; border: 1px solid @STYLE_CHECKBOX_CHECKED_BORDER@; border-radius: 3px; }
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
    "@STYLE_MENU_BACKGROUND@": STYLE_COLORS["menu_background"],
    "@STYLE_MENU_BORDER@": STYLE_COLORS["menu_border"],
    "@STYLE_MENU_SELECTION@": STYLE_COLORS["menu_selection"],
    "@STYLE_NOTICE_BACKGROUND@": STYLE_COLORS["notice_background"],
    "@STYLE_NOTICE_TEXT@": STYLE_COLORS["notice_text"],
    "@STYLE_CONTROL_BORDER@": STYLE_COLORS["control_border"],
    "@STYLE_INPUT_BACKGROUND@": STYLE_COLORS["input_background"],
    "@STYLE_SELECTION_BACKGROUND@": STYLE_COLORS["selection_background"],
    "@STYLE_FOCUS_BORDER@": STYLE_COLORS["focus_border"],
    "@STYLE_DISABLED_TEXT@": STYLE_COLORS["disabled_text"],
    "@STYLE_DISABLED_BACKGROUND@": STYLE_COLORS["disabled_background"],
    "@STYLE_DISABLED_BORDER@": STYLE_COLORS["disabled_border"],
    "@STYLE_PRIMARY_HOVER@": STYLE_COLORS["primary_hover"],
    "@STYLE_NAVIGATION_BACKGROUND@": STYLE_COLORS["navigation_background"],
    "@STYLE_NAVIGATION_HOVER@": STYLE_COLORS["navigation_hover"],
    "@STYLE_NAVIGATION_TEXT@": STYLE_COLORS["navigation_text"],
    "@STYLE_NAVIGATION_SELECTED_TEXT@": STYLE_COLORS["navigation_selected_text"],
    "@STYLE_NAVIGATION_FOCUS@": STYLE_COLORS["navigation_focus"],
    "@STYLE_TABLE_BACKGROUND@": STYLE_COLORS["table_background"],
    "@STYLE_TABLE_ALTERNATE@": STYLE_COLORS["table_alternate"],
    "@STYLE_TABLE_SELECTION@": STYLE_COLORS["table_selection"],
    "@STYLE_TREE_SELECTION@": STYLE_COLORS["tree_selection"],
    "@STYLE_SCROLLBAR_HANDLE@": STYLE_COLORS["scrollbar_handle"],
    "@STYLE_CHECKBOX_BORDER@": STYLE_COLORS["checkbox_border"],
    "@STYLE_CHECKBOX_CHECKED@": STYLE_COLORS["checkbox_checked"],
    "@STYLE_CHECKBOX_CHECKED_BORDER@": STYLE_COLORS["checkbox_checked_border"],
    "@STYLE_MENU_ITEM_BORDER@": STYLE_COLORS["menu_item_border"],
    "@STYLE_BRAND_SUBTITLE@": STYLE_COLORS["brand_subtitle"],
    "@STYLE_BRAND_ACCENT@": STYLE_COLORS["brand_accent"],
    "@STYLE_SECTION_LABEL@": STYLE_COLORS["section_label"],
    "@STYLE_CONNECTION_SUCCESS_TEXT@": STYLE_COLORS["connection_success_text"],
    "@STYLE_CONNECTION_SUCCESS_BACKGROUND@": STYLE_COLORS["connection_success_background"],
    "@STYLE_CONNECTION_SUCCESS_BORDER@": STYLE_COLORS["connection_success_border"],
    "@STYLE_CONNECTION_LOST_BACKGROUND@": STYLE_COLORS["connection_lost_background"],
    "@STYLE_CONNECTION_LOST_BORDER@": STYLE_COLORS["connection_lost_border"],
    "@STYLE_STATUS_STRIP_BORDER@": STYLE_COLORS["status_strip_border"],
    "@STYLE_STATUS_TEXT@": STYLE_COLORS["status_text"],
    "@STYLE_EDITOR_POSITION_TEXT@": STYLE_COLORS["editor_position_text"],
    "@STYLE_SECURITY_SURFACE@": STYLE_COLORS["security_surface"],
    "@STYLE_SEPARATOR@": STYLE_COLORS["separator"],
    "@STYLE_COMBO_BACKGROUND@": STYLE_COLORS["combo_background"],
    "@STYLE_COMBO_ARROW@": STYLE_COLORS["combo_arrow"],
    "@STYLE_PRESSED_SURFACE@": STYLE_COLORS["pressed_surface"],
    "@STYLE_NAVIGATION_BORDER@": STYLE_COLORS["navigation_border"],
    "@STYLE_NAVIGATION_HOVER_TEXT@": STYLE_COLORS["navigation_hover_text"],
    "@STYLE_NAVIGATION_HOVER_BORDER@": STYLE_COLORS["navigation_hover_border"],
    "@STYLE_NAVIGATION_SELECTED_BORDER@": STYLE_COLORS["navigation_selected_border"],
    "@STYLE_NAVIGATION_HINT@": STYLE_COLORS["navigation_hint"],
    "@STYLE_CONNECTION_DETAILS@": STYLE_COLORS["connection_details"],
    "@STYLE_SPLITTER@": STYLE_COLORS["splitter"],
    "@STYLE_TOUR_ACCENT@": STYLE_COLORS["tour_accent"],
    "@STYLE_TOUR_STEP@": STYLE_COLORS["tour_step"],
    "@STYLE_TOUR_TITLE@": STYLE_COLORS["tour_title"],
    "@STYLE_TOUR_SURFACE@": STYLE_COLORS["tour_surface"],
    "@STYLE_TOUR_BORDER@": STYLE_COLORS["tour_border"],
    "@STYLE_TOUR_NUMBER@": STYLE_COLORS["tour_number"],
    "@STYLE_TOUR_CARD_TITLE@": STYLE_COLORS["tour_card_title"],
    "@STYLE_TOUR_CARD_BODY@": STYLE_COLORS["tour_card_body"],
    "@STYLE_EDITOR_SURFACE@": STYLE_COLORS["editor_surface"],
    "@STYLE_TAB_TEXT@": STYLE_COLORS["tab_text"],
    "@STYLE_TABLE_HEADER_TEXT@": STYLE_COLORS["table_header_text"],
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
