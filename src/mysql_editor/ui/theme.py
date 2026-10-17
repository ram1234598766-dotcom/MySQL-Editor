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

# Component rules remain one stylesheet so semantic palette changes are applied
# consistently. Values are resolved here because Qt stylesheets do not support CSS vars.
STYLESHEET = r'''
* { font-family: "Segoe UI"; font-size: 12px; }
QMainWindow, QDialog, QWidget { background: #0B111B; color: #e8f1ff; }
QMenuBar { background: #121a27; color: #e8f1ff; padding: 4px 10px; border-bottom: 1px solid #2c3a50; }
QMenuBar::item { padding: 6px 9px; border-radius: 5px; }
QMenuBar::item:selected, QMenu { background: #172235; }
QMenu { border: 1px solid #344761; padding: 5px; }
QMenu::item { padding: 7px 25px 7px 12px; border-radius: 4px; }
QMenu::item:selected { background: #2569cb; color: white; }
QLabel { color: #e8f1ff; }
QLabel#mutedText { color: #a9bad0; }
QLabel#noticeText { color: #d3e1f5; background: #111e2f; border: 1px solid #405675; border-radius: 7px; padding: 9px; }
QLabel#dialogTitle { font-size: 20px; font-weight: 650; }
QLabel#brandTitle { font-size: 17px; font-weight: 700; }
QLabel#brandSubtitle { color: #9cb0cc; font-size: 9px; font-weight: 650; letter-spacing: 1px; }
QLabel#logoMark { color: #47c8e1; font-size: 28px; font-weight: 700; }
QLabel#pageTitle { font-size: 23px; font-weight: 700; }
QLabel#panelTitle { font-size: 13px; font-weight: 650; }
QLabel#sectionLabel { color: #aabbd2; font-size: 10px; font-weight: 700; padding: 4px 8px; }
QLabel#connectionBadge { color: #3bd49b; background: #142d2b; border: 1px solid #426d62; border-radius: 8px; padding: 7px 10px; }
QLabel#statusBar { background: #121a27; color: #c0ccdc; border-top: 1px solid #354760; padding: 7px 13px; }
QLabel#securityNotice, QFrame#securityCard { background: #151f2e; border: 1px solid #405675; border-radius: 9px; padding: 10px; color: #c0ccdc; }
QFrame#separator { color: #40516a; max-height: 1px; }
QLineEdit, QSpinBox, QComboBox, QPlainTextEdit, QTreeWidget, QListWidget {
  background: #080e17; color: #e8f1ff; border: 1px solid #405675;
  border-radius: 6px; padding: 7px; selection-background-color: #286cc7;
  selection-color: white; min-height: 20px;
}
QLineEdit:focus, QSpinBox:focus, QComboBox:focus, QPlainTextEdit:focus, QTreeWidget:focus, QListWidget:focus { border: 1px solid #4a9bff; }
QComboBox::drop-down { border: none; width: 24px; }
QComboBox QAbstractItemView { background: #101a29; color: #e8f1ff; selection-background-color: #2569cb; }
QPushButton { background: #172235; color: #e8f1ff; border: 1px solid #405675; border-radius: 7px; padding: 8px 11px; min-height: 19px; }
QPushButton:hover { background: #22334b; border-color: #87a4ca; }
QPushButton:pressed { background: #0b1422; }
QPushButton:disabled { color: #8293a9; background: #121a26; border-color: #35465c; }
QPushButton#primaryButton { background: #2879e8; color: white; border: 1px solid #438fff; font-weight: 650; }
QPushButton#primaryButton:hover { background: #3987f0; }
QWidget#workspaceNavigation { background: #0d1522; border-bottom: 1px solid #263951; }
QToolButton#navButton { text-align: center; background: transparent; color: #aebed2; border: 1px solid transparent; border-radius: 8px; padding: 9px 13px; }
QToolButton#navButton:hover { background: #18273b; color: #eef6ff; border-color: #354b65; }
QToolButton#navButton:checked { background: #132b42; color: #62dff0; border: 1px solid #285c77; }
QToolButton#navButton:focus { border: 1px solid #5bbdff; }
QLabel#navHint { color: #7187a3; font-size: 9px; font-weight: 650; letter-spacing: 1px; padding-right: 5px; }
QLabel#connectionDetails { color: #a7bad1; font-size: 10px; }
QSplitter::handle { background: #263e58; width: 5px; height: 5px; }
QSplitter::handle:hover { background: #4a9bff; }
QLabel#tourEyebrow { color: #58dcec; font-weight: 700; font-size: 10px; letter-spacing: 1.2px; }
QLabel#tourStep { color: #91a9c4; font-weight: 700; font-size: 10px; }
QLabel#tourTitle { color: #f0f6ff; font-size: 23px; font-weight: 700; }
QFrame#tourCard { background: #111d2d; border: 1px solid #2d425b; border-radius: 10px; }
QLabel#tourNumber { color: #5ddbec; font-size: 10px; font-weight: 750; }
QLabel#tourCardTitle { color: #edf5ff; font-weight: 650; font-size: 12px; }
QLabel#tourCardBody { color: #adc0d5; font-size: 11px; }
QWidget#tourPage { background: transparent; }
QLabel#tourProgress { padding: 0 2px; }
QTabWidget::pane { background: #090f19; border: 1px solid #405675; border-radius: 7px; top: -1px; }
QTabBar::tab { background: #172235; color: #b6c5d9; padding: 9px 12px; border: 1px solid #354760; border-top-left-radius: 6px; border-top-right-radius: 6px; margin-right: 3px; }
QTabBar::tab:selected { background: #090f19; color: #e8f1ff; border-bottom-color: #090f19; }
QTableView { background: #0b121d; alternate-background-color: #101b2a; color: #e8f1ff; gridline-color: #354760; border: 1px solid #405675; selection-background-color: #1d4f88; selection-color: white; }
QHeaderView::section { background: #172235; color: #cad7e7; border: none; border-bottom: 1px solid #405675; padding: 8px; font-weight: 650; }
QTreeWidget, QListWidget { border: none; }
QTreeWidget::item, QListWidget::item { min-height: 25px; padding: 4px; }
QTreeWidget::item:selected, QListWidget::item:selected { background: #205ca4; border-radius: 4px; }
QScrollBar:vertical { background: #101927; width: 12px; margin: 1px; }
QScrollBar::handle:vertical { background: #486181; border-radius: 5px; min-height: 24px; }
QScrollBar:horizontal { background: #101927; height: 12px; margin: 1px; }
QScrollBar::handle:horizontal { background: #486181; border-radius: 5px; min-width: 24px; }
QCheckBox { spacing: 8px; }
QCheckBox::indicator { width: 16px; height: 16px; }
QCheckBox::indicator:unchecked { background: #080e17; border: 1px solid #6b829e; border-radius: 3px; }
QCheckBox::indicator:checked { background: #2879e8; border: 1px solid #438fff; border-radius: 3px; }
QLabel#statusSuccess { color: #4CC7A3; }
QLabel#statusWarning { color: #F2BE6B; }
QLabel#statusDanger { color: #F07886; }
QPushButton#accentSecondary { border-color: #8D91FF; }
'''
