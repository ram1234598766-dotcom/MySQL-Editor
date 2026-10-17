"""Main SQL workspace: query tabs, schema navigation, results and local query tools."""

from __future__ import annotations

import os
import tempfile
import uuid
from decimal import Decimal, InvalidOperation
from pathlib import Path

from PySide6.QtCore import QAbstractTableModel, QItemSelectionModel, QModelIndex, QSettings, QSortFilterProxyModel, Qt, QTimer
from PySide6.QtGui import QAction, QActionGroup, QColor, QFont, QKeySequence, QIcon, QPixmap, QShortcut, QTextCursor, QTextDocument
from PySide6.QtWidgets import (
    QApplication, QButtonGroup, QComboBox, QDialog, QFileDialog, QFontDialog, QHBoxLayout, QHeaderView, QInputDialog,
    QLabel, QListWidget, QListWidgetItem, QLineEdit, QMainWindow, QMenu, QMessageBox,
    QPlainTextEdit, QPushButton, QSplitter, QTabWidget, QTableView, QToolButton,
    QTreeWidget, QTreeWidgetItem, QVBoxLayout, QWidget,
)

from mysql_editor.core import (
    classify_statement, current_statement, format_sql, redact_secrets, redact_sql_secrets,
    split_sql_statements, unsupported_delimiter_message,
)
from mysql_editor.database import DatabaseWorker
from mysql_editor.storage import ConnectionProfile, CredentialStore, LocalRepository, app_data_dir
from mysql_editor.ui.animations import fade_in
from mysql_editor.ui.connection_context import (
    build_connection_context, connection_context_label, connection_context_matches,
)
from mysql_editor.ui.connection_dialog import ConnectionDialog
from mysql_editor.ui.editor import SqlEditor
from mysql_editor.ui.find_replace_bar import FindReplaceBar, count_matches
from mysql_editor.ui.tutorial import ProductTourDialog
from mysql_editor.ui.theme import normalize_theme, resolve_theme, stylesheet_for_theme
from mysql_editor.ui.result_tools import (
    cell_copy_text, cell_detail_text, column_headers_tsv, column_width_samples,
    result_filter_message, result_picker_label, result_summary_message, rows_tsv,
    selected_cells_tsv,
)
from mysql_editor.ui.preferences import (
    normalize_editor_font_family, normalize_result_row_height, normalize_tab_width,
)
from mysql_editor.ui.query_lifecycle import classify_query_outcome
from mysql_editor.ui.schema_tools import qualified_identifier, schema_status_message, select_preview_sql
from mysql_editor.recent_files import (
    MAX_RECENT_SQL_FILES, normalize_recent_sql_paths, record_recent_sql_path,
)


CSV_EXPORT_NULL_SEMANTICS = (
    "SQL NULL is encoded as " + r"\N" + "; empty text stays blank. "
    "Text values beginning with a backslash are escaped by adding one leading backslash."
)
CSV_EXPORT_SEMANTICS = (
    "CSV export preserves MySQL fetch order and includes every fetched row; "
    "it ignores grid sorting and the visible-row filter. " + CSV_EXPORT_NULL_SEMANTICS
)


class ResultsModel(QAbstractTableModel):
    def __init__(self, headers=None, rows=None, parent=None):
        super().__init__(parent)
        self.headers = list(headers or [])
        self.rows = list(rows or [])

    def update(self, headers, rows):
        self.beginResetModel()
        self.headers = list(headers)
        self.rows = list(rows)
        self.endResetModel()

    def rowCount(self, parent=QModelIndex()):
        return 0 if parent.isValid() else len(self.rows)

    def columnCount(self, parent=QModelIndex()):
        return 0 if parent.isValid() else len(self.headers)

    def data(self, index, role=Qt.ItemDataRole.DisplayRole):
        if not index.isValid():
            return None
        value = self.rows[index.row()][index.column()]
        if role == Qt.ItemDataRole.UserRole:
            return value
        if role == Qt.ItemDataRole.DisplayRole:
            return "(NULL)" if value is None else str(value)
        if role == Qt.ItemDataRole.ForegroundRole and value is None:
            return QColor("#71839b")
        if role == Qt.ItemDataRole.TextAlignmentRole and isinstance(value, (int, float, Decimal)):
            return int(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        return None

    def headerData(self, section, orientation, role=Qt.ItemDataRole.DisplayRole):
        if role != Qt.ItemDataRole.DisplayRole:
            return None
        if orientation == Qt.Orientation.Horizontal and section < len(self.headers):
            return self.headers[section]
        if orientation == Qt.Orientation.Vertical:
            return str(section + 1)
        return None

    def sort(self, column, order=Qt.SortOrder.AscendingOrder):
        if not 0 <= column < len(self.headers):
            return
        self.layoutAboutToBeChanged.emit()

        def sort_key(row):
            value = row[column]
            try:
                return (0, 0, Decimal(str(value)))
            except (InvalidOperation, ValueError):
                return (0, 1, str(value).casefold())

        # NULL is always appended after non-NULL values, regardless of direction.
        non_null_rows = [row for row in self.rows if row[column] is not None]
        null_rows = [row for row in self.rows if row[column] is None]
        non_null_rows.sort(
            key=sort_key,
            reverse=order == Qt.SortOrder.DescendingOrder,
        )
        self.rows[:] = non_null_rows + null_rows
        self.layoutChanged.emit()


class ResultsFilterProxyModel(QSortFilterProxyModel):
    """Searchable result model with numeric-aware sorting for heterogeneous SQL values."""

    @staticmethod
    def _sort_key(index):
        value = index.data(Qt.ItemDataRole.UserRole)
        if value is None:
            return (1, 0, "")
        try:
            return (0, 0, Decimal(str(value)))
        except (InvalidOperation, ValueError):
            return (0, 1, str(value).casefold())

    def lessThan(self, left, right):
        left_value = left.data(Qt.ItemDataRole.UserRole)
        right_value = right.data(Qt.ItemDataRole.UserRole)
        if left_value is None or right_value is None:
            if left_value is None and right_value is None:
                return False
            # QSortFilterProxyModel applies the requested sort direction to lessThan.
            # Invert the NULL comparison for descending order so NULL stays at bottom.
            nulls_descending = self.sortOrder() == Qt.SortOrder.DescendingOrder
            if nulls_descending:
                return left_value is None
            return right_value is None
        return self._sort_key(left) < self._sort_key(right)


class MainWindow(QMainWindow):
    def __init__(self, worker: DatabaseWorker, repository: LocalRepository,
                 credentials: CredentialStore, profile: dict, config: dict, connect_result: dict):
        super().__init__()
        self.worker = worker
        self.repository = repository
        self.credentials = credentials
        self.profile = profile
        self.config = config
        self.connect_result = connect_result
        self._transaction_open = bool(connect_result.get("transaction_open", False))
        self._jobs: dict[str, tuple[str, dict]] = {}
        self._deferred_export_notifications: list[dict] = []
        self._schema_request_id: str | None = None
        self._schema_expansion_requests: dict[str, str] = {}
        self._schema_expand_items: dict[str, QTreeWidgetItem] = {}
        self._schema_completion_words: set[str] = set()
        self._schema_databases: set[str] = set()
        self._schema_tables: set[str] = set()
        self._schema_columns_by_table: dict[str, list[str]] = {}
        self._active_schema_name = str(config.get("default_schema", "") or connect_result.get("database", ""))
        self._result_completion_words: set[str] = set()
        self._query_running = False
        self._cancellation_requested = False
        self._current_result_id: str | None = None
        self._result_fetched_row_count = 0
        self._result_base_message = "Ready. Run a query to view results."
        self._query_results: list[dict] = []
        self._last_duration = 0
        self._last_sql = ""
        self._last_saved_paths: dict[int, str] = {}
        self._settings = QSettings()
        self._editor_tab_width = normalize_tab_width(self._settings.value("ui/tabWidth", 4))
        self._editor_font_family = normalize_editor_font_family(
            self._settings.value("ui/editorFontFamily", "Cascadia Code")
        )
        self._result_row_height = normalize_result_row_height(self._settings.value("ui/resultRowHeight", 28))
        self._find_count_timer = QTimer(self)
        self._find_count_timer.setSingleShot(True)
        self._find_count_timer.setInterval(80)
        self._find_count_timer.timeout.connect(self._refresh_find_count)
        try:
            font_size = int(self._settings.value("ui/editorFontSize", 10))
        except (TypeError, ValueError):
            font_size = 10
        self._editor_font_size = max(8, min(font_size, 24))
        self.setWindowTitle("MySQL Editor")
        self.setMinimumSize(1120, 720)
        self.resize(1500, 940)
        self._set_icon()
        self.worker.completed.connect(self._on_worker_completed)
        self.worker.activity.connect(self._on_activity)
        task_activity = getattr(self.worker, "task_activity", None)
        if task_activity is not None:
            task_activity.connect(self._on_task_activity)
        self._build_ui()
        self._restore_ui_preferences()
        self._build_menus()
        self.new_query_tab()
        self._update_connection_status()
        QTimer.singleShot(150, self.refresh_schema)

    def _set_icon(self):
        import sys
        candidates = [
            Path(__file__).resolve().parents[3] / "assets" / "mysql-editor.ico",
            Path(getattr(sys, "_MEIPASS", ".")) / "assets" / "mysql-editor.ico",
        ]
        for item in candidates:
            if item.is_file():
                self.setWindowIcon(QIcon(str(item)))
                return
        for item in [
            Path(__file__).resolve().parents[3] / "assets" / "mysql-editor-logo.webp",
            Path(getattr(sys, "_MEIPASS", ".")) / "assets" / "mysql-editor-logo.webp",
        ]:
            if item.is_file():
                self.setWindowIcon(QIcon(str(item)))
                return

    def _build_ui(self):
        root = QWidget()
        outer = QVBoxLayout(root)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)

        top = QWidget()
        top.setObjectName("topBar")
        top_layout = QHBoxLayout(top)
        top_layout.setContentsMargins(18, 9, 18, 9)
        logo = QLabel()
        logo.setFixedSize(36, 36)
        self._set_brand_logo(logo)
        brand = QVBoxLayout()
        name = QLabel("MySQL Editor")
        name.setObjectName("brandTitle")
        subtitle = QLabel("DESKTOP SQL WORKSPACE")
        subtitle.setObjectName("brandSubtitle")
        brand.addWidget(name)
        brand.addWidget(subtitle)
        top_layout.addWidget(logo)
        top_layout.addLayout(brand)
        top_layout.addStretch(1)
        self.connection_badge = QLabel()
        self.connection_badge.setObjectName("connectionBadge")
        self.connection_badge.setAccessibleName("Active MySQL connection status")
        top_layout.addWidget(self.connection_badge)
        self.connection_details = QLabel()
        self.connection_details.setObjectName("connectionDetails")
        self.connection_details.setMaximumWidth(275)
        top_layout.addWidget(self.connection_details)
        self.tour_button = QPushButton("✧  Guided tour")
        self.tour_button.clicked.connect(self._show_product_tour)
        top_layout.addWidget(self.tour_button)
        switch = QPushButton("Connect")
        switch.setObjectName("primaryButton")
        switch.clicked.connect(self.open_connection_dialog)
        top_layout.addWidget(switch)
        outer.addWidget(top)

        navigation = QWidget()
        navigation.setObjectName("workspaceNavigation")
        navigation_layout = QHBoxLayout(navigation)
        navigation_layout.setContentsMargins(16, 6, 16, 6)
        navigation_layout.setSpacing(6)
        self.workspace_nav_group = QButtonGroup(self)
        self.workspace_nav_group.setExclusive(True)
        self.workspace_nav_buttons: dict[str, QToolButton] = {}
        for label, icon in [
            ("SQL Editor", "▤"), ("Connections", "◇"), ("Schema explorer", "▦"),
            ("Query history", "◷"), ("Saved queries", "☆"),
        ]:
            button = QToolButton()
            button.setText(f"{icon}  {label}")
            button.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextOnly)
            button.setObjectName("navButton")
            button.setMinimumHeight(38)
            button.setCheckable(label != "Connections")
            button.setAccessibleName(label)
            button.setToolTip({
                "SQL Editor": "Return to the SQL editor",
                "Connections": "Manage and switch MySQL connections",
                "Schema explorer": "Browse databases, tables and views",
                "Query history": "Review opt-in local query history",
                "Saved queries": "Open saved SQL snippets",
            }[label])
            if label != "Connections":
                self.workspace_nav_group.addButton(button)
            button.clicked.connect(lambda checked=False, value=label: self._navigate(value))
            navigation_layout.addWidget(button)
            self.workspace_nav_buttons[label] = button
        navigation_layout.addStretch(1)
        privacy_hint = QLabel("LOCAL WORKSPACE  ·  DIRECT MYSQL CONNECTION")
        privacy_hint.setObjectName("navHint")
        navigation_layout.addWidget(privacy_hint)
        outer.addWidget(navigation)

        self.main_split = QSplitter(Qt.Orientation.Horizontal)
        body = self.main_split
        body.setObjectName("mainSplit")
        self.center = QWidget()
        center_layout = QVBoxLayout(self.center)
        center_layout.setContentsMargins(18, 17, 18, 10)
        center_layout.setSpacing(9)
        heading_row = QHBoxLayout()
        heading_box = QVBoxLayout()
        title = QLabel("Query workspace")
        title.setObjectName("pageTitle")
        caption = QLabel("Write SQL, inspect results, and manage your MySQL schema.")
        caption.setObjectName("mutedText")
        heading_box.addWidget(title)
        heading_box.addWidget(caption)
        heading_row.addLayout(heading_box, 1)
        self.format_button = QPushButton("✦  Format SQL")
        self.format_button.clicked.connect(self.format_current_sql)
        self.explain_button = QPushButton("Explain")
        self.explain_button.clicked.connect(self.explain_query)
        self.run_selection_button = QPushButton("Run selection")
        self.run_selection_button.clicked.connect(lambda: self.execute_current(selection_only=True))
        self.run_button = QPushButton("▶  Run SQL   Ctrl+Enter")
        self.run_button.setObjectName("primaryButton")
        self.run_button.clicked.connect(self.execute_current)
        heading_row.addWidget(self.format_button)
        heading_row.addWidget(self.explain_button)
        heading_row.addWidget(self.run_selection_button)
        heading_row.addWidget(self.run_button)
        center_layout.addLayout(heading_row)

        self.find_bar = FindReplaceBar(self.center)
        self.find_bar.search_changed.connect(self._queue_find_count_refresh)
        self.find_bar.find_next_requested.connect(lambda: self._navigate_find_match())
        self.find_bar.find_previous_requested.connect(
            lambda: self._navigate_find_match(backward=True)
        )
        self.find_bar.replace_requested.connect(self._replace_one)
        self.find_bar.replace_all_requested.connect(self._replace_all)
        self.find_bar.closed.connect(self._close_find_bar)
        center_layout.addWidget(self.find_bar)

        self.editors = QTabWidget()
        self.editors.setObjectName("editorTabs")
        self.editors.setAccessibleName("SQL query tabs")
        self.editors.setAccessibleDescription(
            "Switch between open SQL query documents. Modified tabs have unsaved changes."
        )
        self.editors.setTabsClosable(True)
        self.editors.setTabPosition(QTabWidget.TabPosition.North)
        self.editors.tabCloseRequested.connect(self.close_query_tab)
        self.editors.currentChanged.connect(self._update_editor_actions)
        self.editors.tabBar().setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.editors.tabBar().customContextMenuRequested.connect(self._show_editor_tab_context)

        result_panel = QWidget()
        result_layout = QVBoxLayout(result_panel)
        result_layout.setContentsMargins(0, 2, 0, 0)
        result_layout.setSpacing(6)
        toolbar = QHBoxLayout()
        self.results_title = QLabel("Results")
        self.results_title.setObjectName("panelTitle")
        self.result_picker = QComboBox()
        self.result_picker.setAccessibleName("Select query result set")
        self.result_picker.setAccessibleDescription(
            "Switch between result sets returned by the most recent script execution."
        )
        self.result_picker.setMinimumWidth(165)
        self.result_picker.setMaximumWidth(245)
        self.result_picker.currentIndexChanged.connect(self._select_result)
        self.result_filter = QLineEdit()
        self.result_filter.setObjectName("resultQuickFilter")
        self.result_filter.setPlaceholderText("Filter visible rows…")
        self.result_filter.setAccessibleName("Filter result rows")
        self.result_filter.setClearButtonEnabled(True)
        self.result_filter.setMinimumWidth(150)
        self.result_filter.setMaximumWidth(250)
        self.result_filter.setToolTip(
            "Filters the visible preview only. " + CSV_EXPORT_SEMANTICS
        )
        self.result_filter.textChanged.connect(self._filter_results)
        self.query_meta = QLabel("Ready")
        self.query_meta.setObjectName("mutedText")
        self.query_meta.setAccessibleName("Query execution status and row count")
        self.stop_button = QPushButton("Stop")
        self.stop_button.setAccessibleName("Request query cancellation")
        self.stop_button.setToolTip(
            "Request cancellation of the current query. MySQL may take time to interrupt it."
        )
        self.stop_button.setEnabled(False)
        self.stop_button.clicked.connect(self.stop_query)
        self.commit_button = QPushButton("Commit")
        self.commit_button.setAccessibleName("Commit active transaction")
        self.commit_button.setToolTip("Commit the current transaction on the active MySQL connection.")
        self.commit_button.clicked.connect(lambda: self._dispatch("commit", {}))
        self.rollback_button = QPushButton("Rollback")
        self.rollback_button.setAccessibleName("Roll back active transaction")
        self.rollback_button.setToolTip("Roll back the current transaction when MySQL permits it.")
        self.rollback_button.clicked.connect(lambda: self._dispatch("rollback", {}))
        self.export_button = QPushButton("↓  Export CSV")
        self.export_button.setAccessibleName("Export fetched result rows to CSV")
        self.export_button.setAccessibleDescription(CSV_EXPORT_SEMANTICS)
        self.export_button.clicked.connect(self.export_results)
        toolbar.addWidget(self.results_title)
        toolbar.addWidget(self.result_picker)
        toolbar.addWidget(self.result_filter)
        toolbar.addWidget(self.query_meta, 1)
        toolbar.addWidget(self.stop_button)
        toolbar.addWidget(self.commit_button)
        toolbar.addWidget(self.rollback_button)
        toolbar.addWidget(self.export_button)
        result_layout.addLayout(toolbar)
        self.result_model = ResultsModel()
        self.result_grid = QTableView()
        self.result_grid.setObjectName("resultsGrid")
        self.result_grid.setAccessibleName("SQL query results table")
        self.result_grid.setAccessibleDescription(
            "Use the arrow keys to navigate cells. Double-click for full cell details. "
            + CSV_EXPORT_SEMANTICS
        )
        self.result_proxy = ResultsFilterProxyModel(self)
        self.result_proxy.setSourceModel(self.result_model)
        self.result_proxy.setFilterCaseSensitivity(Qt.CaseSensitivity.CaseInsensitive)
        self.result_proxy.setFilterKeyColumn(-1)
        self.result_grid.setModel(self.result_proxy)
        self.result_grid.setSortingEnabled(True)
        self.result_grid.setAlternatingRowColors(True)
        self.result_grid.setSelectionBehavior(QTableView.SelectionBehavior.SelectItems)
        self.result_grid.setSelectionMode(QTableView.SelectionMode.ExtendedSelection)
        self.result_grid.setToolTip(
            "Select cells to copy. Double-click a cell for full-value details; right-click for result actions."
        )
        self.result_grid.doubleClicked.connect(self.show_cell_details)
        self.copy_cells_shortcut = QShortcut(QKeySequence.StandardKey.Copy, self.result_grid)
        self.copy_cells_shortcut.setContext(Qt.ShortcutContext.WidgetWithChildrenShortcut)
        self.copy_cells_shortcut.activated.connect(self.copy_selected_cells)
        self.result_grid.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Interactive)
        self.result_grid.horizontalHeader().setStretchLastSection(True)
        self.result_grid.verticalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Fixed)
        self.result_grid.verticalHeader().setDefaultSectionSize(self._result_row_height)
        self.result_grid.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.result_grid.customContextMenuRequested.connect(self._show_result_context)
        result_layout.addWidget(self.result_grid, 1)
        self.result_message = QLabel("Ready. Run a query to view results.")
        self.result_message.setObjectName("mutedText")
        self.result_message.setAccessibleName("Query result summary and details")
        self.result_message.setWordWrap(True)
        result_layout.addWidget(self.result_message)
        self.editor_results_split = QSplitter(Qt.Orientation.Vertical)
        self.editor_results_split.setObjectName("editorResultsSplit")
        self.editor_results_split.addWidget(self.editors)
        self.editor_results_split.addWidget(result_panel)
        self.editor_results_split.setStretchFactor(0, 4)
        self.editor_results_split.setStretchFactor(1, 3)
        self.editor_results_split.setSizes([470, 300])
        center_layout.addWidget(self.editor_results_split, 1)
        body.addWidget(self.center)

        self.inspector_tabs = QTabWidget()
        self.inspector_tabs.setAccessibleName("Workspace inspector")
        self.inspector_tabs.setAccessibleDescription(
            "Browse schema metadata, opt-in query history, and saved SQL snippets."
        )
        self.inspector_tabs.setTabPosition(QTabWidget.TabPosition.North)
        self.inspector_tabs.setObjectName("inspectorTabs")
        self.inspector_tabs.setMinimumWidth(245)
        self.inspector_tabs.setMaximumWidth(360)
        schema_page = QWidget()
        schema_layout = QVBoxLayout(schema_page)
        schema_layout.setContentsMargins(6, 6, 6, 6)
        schema_layout.setSpacing(6)
        schema_toolbar = QHBoxLayout()
        self.schema_state_label = QLabel("Schema metadata has not been loaded yet.")
        self.schema_state_label.setObjectName("mutedText")
        self.schema_state_label.setWordWrap(True)
        self.schema_state_label.setAccessibleName("Schema explorer status")
        schema_toolbar.addWidget(self.schema_state_label, 1)
        self.schema_refresh_button = QPushButton("Refresh")
        self.schema_refresh_button.setAccessibleName("Refresh schema metadata")
        self.schema_refresh_button.setToolTip("Reload visible databases, tables, views and columns.")
        self.schema_refresh_button.clicked.connect(self.refresh_schema)
        schema_toolbar.addWidget(self.schema_refresh_button)
        schema_layout.addLayout(schema_toolbar)
        self.schema_tree = QTreeWidget()
        self.schema_tree.setHeaderHidden(True)
        self.schema_tree.setAccessibleName("MySQL databases, tables and views")
        self.schema_tree.itemActivated.connect(self._schema_item_activated)
        self.schema_tree.itemExpanded.connect(self._schema_item_expanded)
        self.schema_tree.itemCollapsed.connect(self._schema_item_collapsed)
        self.schema_tree.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.schema_tree.customContextMenuRequested.connect(self._show_schema_context)
        schema_layout.addWidget(self.schema_tree, 1)
        self.inspector_tabs.addTab(schema_page, "Schema")
        self.history_list = QListWidget()
        self.history_list.setAccessibleName("Local query history")
        self.history_list.setAccessibleDescription(
            "Locally stored query history, available only when history is enabled in Settings."
        )
        self.history_list.itemDoubleClicked.connect(self._history_selected)
        self.inspector_tabs.addTab(self.history_list, "History")
        self.saved_list = QListWidget()
        self.saved_list.setAccessibleName("Saved SQL snippets")
        self.saved_list.setAccessibleDescription("Locally saved SQL snippets. Double-click to open one in a query tab.")
        self.saved_list.itemDoubleClicked.connect(self._saved_selected)
        self.inspector_tabs.addTab(self.saved_list, "Saved")
        body.addWidget(self.inspector_tabs)
        body.setStretchFactor(0, 1)
        body.setStretchFactor(1, 0)
        body.setSizes([1180, 310])
        outer.addWidget(body, 1)

        status_strip = QWidget()
        status_strip.setObjectName("statusStrip")
        status_layout = QHBoxLayout(status_strip)
        status_layout.setContentsMargins(0, 0, 0, 0)
        status_layout.setSpacing(0)
        self.status = QLabel("Ready")
        self.status.setObjectName("statusBar")
        self.status.setAccessibleName("Application status messages")
        self.editor_position = QLabel("Ln 1, Col 1")
        self.editor_position.setObjectName("editorPosition")
        self.editor_position.setAccessibleName("SQL editor cursor position and selection length")
        self.editor_position.setMinimumWidth(165)
        self.editor_position.setAlignment(
            Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter
        )
        status_layout.addWidget(self.status, 1)
        status_layout.addWidget(self.editor_position)
        outer.addWidget(status_strip)
        self.setCentralWidget(root)
        self._set_result_controls()
        self.refresh_history()
        self._refresh_saved_queries()
        self._set_workspace_nav("SQL Editor")

    def _set_brand_logo(self, label: QLabel):
        import sys
        for root in [
            Path(__file__).resolve().parents[3],
            Path(getattr(sys, "_MEIPASS", ".")),
        ]:
            for filename in ("mysql-editor-logo-transparent.png", "mysql-editor-logo.webp"):
                image = root / "assets" / filename
                if image.is_file():
                    pixmap = QPixmap(str(image))
                    if not pixmap.isNull():
                        label.setPixmap(pixmap.scaled(
                            34, 34, Qt.AspectRatioMode.KeepAspectRatio,
                            Qt.TransformationMode.SmoothTransformation,
                        ))
                        return
        label.setText("◈")
        label.setObjectName("logoMark")

    def _build_menus(self):
        file_menu = self.menuBar().addMenu("&File")
        self._action(file_menu, "New query", "Ctrl+N", self.new_query_tab)
        self._action(file_menu, "Open SQL file…", "Ctrl+O", self.open_sql_file)
        self.recent_sql_menu = file_menu.addMenu("Recent SQL files")
        self.recent_sql_menu.setAccessibleName("Recent SQL files")
        self.recent_sql_menu.setToolTip("Reopen one of the most recently opened or saved SQL files.")
        self.recent_sql_menu.aboutToShow.connect(self._refresh_recent_sql_menu)
        self._refresh_recent_sql_menu()
        self._action(file_menu, "Save SQL file", "Ctrl+S", self.save_sql_file)
        self._action(file_menu, "Save All", "", self.save_all_sql_files)
        self._action(file_menu, "Save SQL snippet", "Ctrl+Shift+S", self.save_query_snippet)
        file_menu.addSeparator()
        self._action(file_menu, "Switch connection…", "", self.open_connection_dialog)
        file_menu.addSeparator()
        self._action(file_menu, "Exit", "Alt+F4", self.close)

        edit_menu = self.menuBar().addMenu("&Edit")
        self._action(edit_menu, "Find…", "Ctrl+F", self.find_text)
        self._action(edit_menu, "Replace…", "Ctrl+H", self.replace_text)
        query_menu = self.menuBar().addMenu("&Query")
        self._action(query_menu, "Run current statement", "Ctrl+Return", self.execute_current)
        self._action(query_menu, "Run selection", "Ctrl+Shift+Return",
                     lambda: self.execute_current(selection_only=True))
        self._action(query_menu, "Run entire script", "Ctrl+Alt+Return", self.execute_script)
        self._action(query_menu, "Format SQL", "Ctrl+Shift+F", self.format_current_sql)
        self._action(query_menu, "Explain SELECT", "", self.explain_query)
        self._action(query_menu, "Refresh schema", "F5", self.refresh_schema)
        view_menu = self.menuBar().addMenu("&View")
        self._action(view_menu, "Increase SQL editor font", "Ctrl+Plus", self.increase_editor_font)
        self._action(view_menu, "Decrease SQL editor font", "Ctrl+Minus", self.decrease_editor_font)
        self._action(view_menu, "Reset SQL editor font", "Ctrl+0", self.reset_editor_font)

        settings_menu = self.menuBar().addMenu("&Settings")

        appearance_menu = settings_menu.addMenu("Appearance")
        theme_menu = appearance_menu.addMenu("Theme")
        theme_group = QActionGroup(self)
        theme_group.setExclusive(True)
        current_theme = normalize_theme(self._settings.value("ui/theme", "dark", type=str))
        for label, value in (("System", "system"), ("Light", "light"), ("Dark", "dark")):
            action = QAction(label, self)
            action.setCheckable(True)
            action.setChecked(value == current_theme)
            action.triggered.connect(
                lambda checked, selected=value: self._set_theme(selected) if checked else None
            )
            theme_group.addAction(action)
            theme_menu.addAction(action)
        appearance_menu.addSeparator()

        reduce_motion = QAction("Reduce motion", self)
        reduce_motion.setCheckable(True)
        reduce_motion.setChecked(self._settings.value("ui/reduceMotion", False, type=bool))
        reduce_motion.setToolTip("Disable non-essential UI animation and transitions.")
        reduce_motion.toggled.connect(
            lambda enabled: self._settings.setValue("ui/reduceMotion", enabled)
        )
        appearance_menu.addAction(reduce_motion)

        editor_preferences = settings_menu.addMenu("Editor")
        font_family_action = self._action(
            editor_preferences, "SQL font family…", "", self.choose_editor_font_family
        )
        font_family_action.setToolTip(
            "Choose an installed monospace font. Change the editor size under View."
        )
        editor_preferences.addSeparator()
        tab_width_menu = editor_preferences.addMenu("Tab width")
        tab_width_group = QActionGroup(self)
        tab_width_group.setExclusive(True)
        for width in (2, 4, 8):
            action = QAction(f"{width} spaces", self)
            action.setCheckable(True)
            action.setChecked(width == self._editor_tab_width)
            action.triggered.connect(
                lambda checked, value=width:
                self._set_editor_tab_width(value) if checked else None
            )
            tab_width_group.addAction(action)
            tab_width_menu.addAction(action)

        results_preferences = settings_menu.addMenu("Results")
        density_menu = results_preferences.addMenu("Row height")
        density_group = QActionGroup(self)
        density_group.setExclusive(True)
        for label, height in (
            ("Compact · 24 px", 24),
            ("Comfortable · 28 px", 28),
            ("Spacious · 36 px", 36),
        ):
            action = QAction(label, self)
            action.setCheckable(True)
            action.setChecked(height == self._result_row_height)
            action.triggered.connect(
                lambda checked, value=height:
                self._set_result_row_height(value) if checked else None
            )
            density_group.addAction(action)
            density_menu.addAction(action)

        history_menu = settings_menu.addMenu("Query History")
        history_action = QAction("Enable local query history", self)
        history_action.setCheckable(True)
        history_action.setChecked(self.repository.history_enabled())
        history_action.toggled.connect(self._set_history_enabled)
        history_menu.addAction(history_action)
        self._action(history_menu, "Clear query history", "", self.clear_history)
        help_menu = self.menuBar().addMenu("&Help")
        self._action(help_menu, "Guided tour", "F1", self._show_product_tour)
        self._action(help_menu, "SQL safety information", "", self.show_safety_info)
        self._action(help_menu, "About MySQL Editor", "", self.show_about)

    def _set_theme(self, value: str):
        """Apply an appearance preference without rebuilding or losing the workspace."""
        theme = normalize_theme(value)
        resolved_theme = resolve_theme(theme)
        self._settings.setValue("ui/theme", theme)
        app = QApplication.instance()
        if app is not None:
            app.setStyleSheet(stylesheet_for_theme(resolved_theme))
        for index in range(self.editors.count()):
            editor = self.editors.widget(index)
            if isinstance(editor, SqlEditor):
                # QApplication stylesheet changes can repolish fonts; restore the explicit
                # SQL editor preferences so appearance switches never reset readability.
                font = editor.font()
                font.setFamily(self._editor_font_family)
                font.setStyleHint(QFont.StyleHint.Monospace)
                font.setPointSize(self._editor_font_size)
                editor.setFont(font)
                editor.setTabStopDistance(
                    editor.fontMetrics().horizontalAdvance(" ") * self._editor_tab_width
                )
                editor.set_editor_theme(resolved_theme)
        label = {"system": "System", "light": "Light", "dark": "Dark"}[theme]
        self.status.setText(
            f"Appearance changed to {label}. Editor contents and workspace state were preserved."
        )

    def _action(self, menu: QMenu, text: str, shortcut: str, callback):
        action = QAction(text, self)
        if shortcut:
            action.setShortcut(QKeySequence(shortcut))
        action.triggered.connect(lambda _checked=False: callback())
        menu.addAction(action)
        return action

    def _restore_ui_preferences(self):
        geometry = self._settings.value("ui/windowGeometry")
        if geometry:
            self.restoreGeometry(geometry)

        sizes = self._settings.value("ui/mainSplitterSizes", [])
        if isinstance(sizes, (list, tuple)) and len(sizes) == self.main_split.count():
            try:
                self.main_split.setSizes([max(1, int(value)) for value in sizes])
            except (TypeError, ValueError):
                pass

        result_sizes = self._settings.value("ui/editorResultsSplitterSizes", [])
        if isinstance(result_sizes, (list, tuple)) and len(result_sizes) == self.editor_results_split.count():
            try:
                self.editor_results_split.setSizes([max(1, int(value)) for value in result_sizes])
            except (TypeError, ValueError):
                pass

        try:
            inspector_tab = int(self._settings.value("ui/inspectorTab", 0))
        except (TypeError, ValueError):
            inspector_tab = 0
        if 0 <= inspector_tab < self.inspector_tabs.count():
            self.inspector_tabs.setCurrentIndex(inspector_tab)

    def _set_editor_font_size(self, size: int):
        size = max(8, min(int(size), 24))
        self._editor_font_size = size
        for index in range(self.editors.count()):
            editor = self.editors.widget(index)
            if isinstance(editor, SqlEditor):
                font = editor.font()
                font.setFamily(self._editor_font_family)
                font.setStyleHint(QFont.StyleHint.Monospace)
                font.setPointSize(size)
                editor.setFont(font)
                editor.setTabStopDistance(
                    editor.fontMetrics().horizontalAdvance(" ") * self._editor_tab_width
                )
        self._settings.setValue("ui/editorFontSize", size)
        self.status.setText(f"SQL editor font size: {size} pt")

    def choose_editor_font_family(self):
        """Choose an installed monospace face without changing the configured point size."""
        initial_font = QFont(self._editor_font_family)
        initial_font.setStyleHint(QFont.StyleHint.Monospace)
        initial_font.setPointSize(self._editor_font_size)
        dialog = QFontDialog(initial_font, self)
        dialog.setWindowTitle("Choose SQL editor font family")
        dialog.setOption(QFontDialog.FontDialogOption.MonospacedFonts, True)
        dialog.setOption(QFontDialog.FontDialogOption.ScalableFonts, True)
        dialog.setToolTip(
            "Choose a monospace font family. The SQL editor point size is controlled separately."
        )
        if dialog.exec() == QDialog.DialogCode.Accepted:
            self._set_editor_font_family(dialog.currentFont().family())

    def _set_editor_font_family(self, family: object):
        """Apply and persist an editor font face across open and future query tabs."""
        family = normalize_editor_font_family(family)
        self._editor_font_family = family
        for index in range(self.editors.count()):
            editor = self.editors.widget(index)
            if isinstance(editor, SqlEditor):
                font = editor.font()
                font.setFamily(family)
                font.setStyleHint(QFont.StyleHint.Monospace)
                font.setPointSize(self._editor_font_size)
                editor.setFont(font)
                editor.setTabStopDistance(
                    editor.fontMetrics().horizontalAdvance(" ") * self._editor_tab_width
                )
        self._settings.setValue("ui/editorFontFamily", family)
        self.status.setText(f"SQL editor font family: {family}")

    def _set_editor_tab_width(self, width: int):
        width = normalize_tab_width(width)
        self._editor_tab_width = width
        for index in range(self.editors.count()):
            editor = self.editors.widget(index)
            if isinstance(editor, SqlEditor):
                editor.setTabStopDistance(
                    editor.fontMetrics().horizontalAdvance(" ") * width
                )
        self._settings.setValue("ui/tabWidth", width)
        self.status.setText(f"SQL editor tab width: {width} spaces")

    def _set_result_row_height(self, height: int):
        height = normalize_result_row_height(height)
        self._result_row_height = height
        self.result_grid.verticalHeader().setDefaultSectionSize(height)
        self._settings.setValue("ui/resultRowHeight", height)
        density = {24: "Compact", 28: "Comfortable", 36: "Spacious"}[height]
        self.status.setText(f"Result grid density: {density}")

    def increase_editor_font(self):
        self._set_editor_font_size(self._editor_font_size + 1)

    def decrease_editor_font(self):
        self._set_editor_font_size(self._editor_font_size - 1)

    def reset_editor_font(self):
        self._set_editor_font_size(10)

    def _dispatch(self, action: str, payload: dict, context: dict | None = None):
        # Keep a single SQL task active even if another entry point bypasses editor buttons.
        if action == "query" and self._query_running:
            self._report_query_busy("submit")
            return None
        job_id = uuid.uuid4().hex
        self._jobs[job_id] = (action, context or {})
        self.worker.submit(action, payload, job_id)
        if action == "query":
            self._cancellation_requested = False
            self._query_running = True
            self.run_button.setEnabled(False)
            self.stop_button.setEnabled(True)
            self.commit_button.setEnabled(False)
            self.rollback_button.setEnabled(False)
            self.query_meta.setText("Queued…")
            self.status.setText("Query queued…")
        elif action == "export_csv":
            self.status.setText("CSV export queued…")
        return job_id

    def _report_query_busy(self, operation: str) -> None:
        """Explain why a conflicting operation was not started."""
        if operation == "connection":
            self.status.setText(
                "Connection change blocked · a query is still active. Stop it or wait for completion."
            )
        else:
            self.status.setText(
                "SQL not submitted · a query is already active. Wait for completion or request cancellation."
            )

    def _set_workspace_nav(self, destination: str):
        button = self.workspace_nav_buttons.get(destination)
        if button is not None and button.isCheckable():
            button.setChecked(True)

    def _navigate(self, destination: str):
        if destination == "SQL Editor":
            self._set_workspace_nav(destination)
            if self._current_editor():
                self._current_editor().setFocus()
        elif destination == "Connections":
            self.open_connection_dialog()
            self._set_workspace_nav("SQL Editor")
        elif destination == "Schema explorer":
            self._set_workspace_nav(destination)
            self.inspector_tabs.setCurrentIndex(0)
            self.refresh_schema()
        elif destination == "Query history":
            self._set_workspace_nav(destination)
            self.inspector_tabs.setCurrentIndex(1)
            self.refresh_history()
        elif destination == "Saved queries":
            self._set_workspace_nav(destination)
            self.inspector_tabs.setCurrentIndex(2)
            self._refresh_saved_queries()

        if destination in {"Schema explorer", "Query history", "Saved queries"}:
            fade_in(self.inspector_tabs, self._settings)

    def _insert_tour_example(self):
        editor = self._current_editor()
        if editor is None:
            self.new_query_tab()
            editor = self._current_editor()
        if editor is not None:
            editor.setPlainText(
                "SELECT TABLE_SCHEMA, TABLE_NAME\n"
                "FROM information_schema.tables\n"
                "WHERE TABLE_SCHEMA = DATABASE()\n"
                "ORDER BY TABLE_NAME\n"
                "LIMIT 50;"
            )
            editor.document().setModified(True)
            editor.setFocus()
            self.status.setText("A sample SELECT was inserted. Review it, then run with Ctrl+Enter.")
            self._set_workspace_nav("SQL Editor")
            self.inspector_tabs.setCurrentIndex(0)

    def _show_product_tour(self):
        ProductTourDialog(self, self.repository, self._insert_tour_example).exec()

    def _current_editor(self) -> SqlEditor | None:
        editor = self.editors.currentWidget()
        return editor if isinstance(editor, SqlEditor) else None

    def _current_connection_context(self) -> dict[str, str | int]:
        return build_connection_context(self.profile, self.config, self.connect_result)

    def _bind_editor_connection_context(self, editor: SqlEditor, context: dict[str, str | int]) -> None:
        editor._mysql_editor_connection_context = dict(context)
        base = getattr(editor, "_mysql_editor_base_accessible_description", None)
        if base is None:
            base = editor.accessibleDescription()
            editor._mysql_editor_base_accessible_description = base
        target = connection_context_label(context)
        detail = (
            f"Query target: {target}. If the active connection profile changes, "
            "SQL execution requires explicit confirmation."
        )
        editor.setAccessibleDescription(f"{base}\n{detail}".strip())
        editor.setToolTip(detail)
        index = self.editors.indexOf(editor) if hasattr(self, "editors") else -1
        if index >= 0:
            self.editors.setTabToolTip(index, detail)

    def _confirm_query_target(self, editor: SqlEditor) -> bool:
        active = self._current_connection_context()
        bound = getattr(editor, "_mysql_editor_connection_context", None)
        if not bound:
            self._bind_editor_connection_context(editor, active)
            return True
        if connection_context_matches(bound, active):
            if bound != active:
                self._bind_editor_connection_context(editor, active)
            return True

        previous_label = connection_context_label(bound)
        active_label = connection_context_label(active)
        answer = QMessageBox.warning(
            self,
            "Confirm query target",
            "This query tab was opened under a different connection profile.\n\n"
            f"Tab target:\n{previous_label}\n\n"
            f"Active target:\n{active_label}\n\n"
            "Executing now will send this SQL to the active target. Continue and associate "
            "this query tab with that target?",
            QMessageBox.StandardButton.Cancel | QMessageBox.StandardButton.Yes,
            QMessageBox.StandardButton.Cancel,
        )
        if answer != QMessageBox.StandardButton.Yes:
            self.status.setText(
                "SQL not submitted · query target differs from the active connection. "
                "Confirm the target before retrying."
            )
            return False
        self._bind_editor_connection_context(editor, active)
        self.status.setText(f"Query target confirmed · {active_label}")
        return True

    def new_query_tab(self, text: str = "", path: str | None = None):
        editor = SqlEditor()
        editor.set_editor_theme(resolve_theme(self._settings.value("ui/theme", "dark", type=str)))
        self._bind_editor_connection_context(editor, self._current_connection_context())
        editor.set_completion_context(
            databases=self._schema_databases,
            tables=self._schema_tables,
            columns_by_table=self._schema_columns_by_table,
            extra_words=self._result_completion_words,
            active_schema=self._active_schema_name,
        )
        font = editor.font()
        font.setFamily(self._editor_font_family)
        font.setStyleHint(QFont.StyleHint.Monospace)
        font.setPointSize(self._editor_font_size)
        editor.setFont(font)
        editor.setTabStopDistance(
            editor.fontMetrics().horizontalAdvance(" ") * self._editor_tab_width
        )
        if text:
            editor.setPlainText(text)
        index = self.editors.addTab(editor, Path(path).name if path else "untitled.sql")
        editor._mysql_editor_connection_context = dict(editor._mysql_editor_connection_context)
        self.editors.setTabToolTip(index, editor.toolTip())
        self._last_saved_paths[id(editor)] = path or ""
        self.editors.setCurrentIndex(index)
        editor.document().setModified(False)
        editor.textChanged.connect(lambda ed=editor: self._update_tab_title(ed))
        editor.textChanged.connect(self._queue_find_count_refresh)
        editor.cursorPositionChanged.connect(lambda ed=editor: self._update_editor_position(ed))
        editor.selectionChanged.connect(lambda ed=editor: self._update_editor_position(ed))
        self._update_editor_position(editor)
        editor.setFocus()

    def _update_editor_position(self, editor: SqlEditor | None = None):
        """Show the active editor cursor position and selected character count."""
        if not hasattr(self, "editor_position"):
            return
        editor = editor or self._current_editor()
        if editor is None:
            self.editor_position.setText("No SQL editor")
            self.editor_position.setToolTip("No SQL query tab is active.")
            return
        if editor is not self._current_editor():
            return

        cursor = editor.textCursor()
        line = cursor.blockNumber() + 1
        column = cursor.positionInBlock() + 1
        selected_text = cursor.selectedText().replace("\\u2029", "\\n")
        selected_length = len(selected_text)
        label = f"Ln {line:,}, Col {column:,}"
        if cursor.hasSelection():
            label += f" · {selected_length:,} selected"
        self.editor_position.setText(label)
        self.editor_position.setToolTip(
            f"Line {line}, column {column}; {selected_length:,} selected character(s)."
        )

    def _update_tab_title(self, editor):
        index = self.editors.indexOf(editor)
        if index < 0:
            return
        label = self.editors.tabText(index).removesuffix(" *")
        self.editors.setTabText(index, label + (" *" if editor.document().isModified() else ""))

    def close_query_tab(self, index: int):
        editor = self.editors.widget(index)
        if editor and editor.document().isModified():
            answer = QMessageBox.question(
                self, "Unsaved query", "This query has unsaved changes. Close it?",
                QMessageBox.StandardButton.Discard | QMessageBox.StandardButton.Cancel,
                QMessageBox.StandardButton.Cancel,
            )
            if answer != QMessageBox.StandardButton.Discard:
                return
        if editor:
            self._last_saved_paths.pop(id(editor), None)
        self.editors.removeTab(index)
        if editor:
            editor.deleteLater()
        if self.editors.count() == 0:
            self.new_query_tab()

    def _show_editor_tab_context(self, point):
        tab_bar = self.editors.tabBar()
        index = tab_bar.tabAt(point)
        if index < 0:
            return

        self.editors.setCurrentIndex(index)
        selected_editor = self.editors.widget(index)
        menu = QMenu(self)
        new_action = menu.addAction("New query")
        close_action = menu.addAction("Close tab")
        close_others_action = menu.addAction("Close other tabs")
        close_others_action.setEnabled(self.editors.count() > 1)
        menu.addSeparator()
        save_action = menu.addAction("Save SQL file")
        chosen = menu.exec(tab_bar.mapToGlobal(point))

        if chosen == new_action:
            self.new_query_tab()
        elif chosen == close_action:
            self.close_query_tab(self.editors.indexOf(selected_editor))
        elif chosen == close_others_action:
            self.close_other_query_tabs(self.editors.indexOf(selected_editor))
        elif chosen == save_action:
            self.save_sql_file()

    def close_other_query_tabs(self, keep_index: int):
        """Close every query tab except one, confirming all dirty tabs in a single prompt."""
        count = self.editors.count()
        if not 0 <= keep_index < count:
            return

        keep_editor = self.editors.widget(keep_index)
        to_close = [
            (index, self.editors.widget(index), self.editors.tabText(index))
            for index in range(count)
            if index != keep_index
        ]
        dirty_names = [
            label for _, editor, label in to_close
            if editor is not None and editor.document().isModified()
        ]
        if dirty_names:
            details = "\n".join(f"• {name}" for name in dirty_names[:8])
            if len(dirty_names) > 8:
                details += f"\n…and {len(dirty_names) - 8} more"
            answer = QMessageBox.question(
                self,
                "Close other queries",
                f"{len(dirty_names)} other query tab(s) have unsaved changes. "
                "Discard them and close the other tabs?\n\n" + details,
                QMessageBox.StandardButton.Discard | QMessageBox.StandardButton.Cancel,
                QMessageBox.StandardButton.Cancel,
            )
            if answer != QMessageBox.StandardButton.Discard:
                return

        for index in range(count - 1, -1, -1):
            editor = self.editors.widget(index)
            if editor is keep_editor:
                continue
            self._last_saved_paths.pop(id(editor), None)
            self.editors.removeTab(index)
            if editor is not None:
                editor.deleteLater()

        self.editors.setCurrentWidget(keep_editor)
        if hasattr(self, "status"):
            self.status.setText(f"Closed {len(to_close)} other query tab(s).")

    def _update_editor_actions(self, *_):
        self._set_result_controls()
        self._refresh_find_count()
        self._update_editor_position()

    def _set_result_controls(self):
        self.export_button.setEnabled(bool(self._current_result_id))

    def _query_for_run(self, selection_only=False, whole_script=False):
        editor = self._current_editor()
        if not editor:
            return ""
        cursor = editor.textCursor()
        if selection_only and cursor.hasSelection():
            return cursor.selectedText().replace("\u2029", "\n")
        if whole_script:
            return editor.toPlainText()
        return current_statement(editor.toPlainText(), cursor.position())

    def execute_current(self, selection_only: bool = False):
        self._execute_sql(self._query_for_run(selection_only=selection_only))

    def execute_script(self):
        self._execute_sql(self._query_for_run(whole_script=True))

    def _execute_sql(self, sql: str):
        if self._query_running:
            self._report_query_busy("submit")
            return
        unsupported = unsupported_delimiter_message(sql)
        if unsupported:
            self.status.setText(
                "SQL not submitted · unsupported MySQL client DELIMITER directive."
            )
            QMessageBox.warning(self, "Unsupported MySQL client directive", unsupported)
            return
        statements = split_sql_statements(sql)
        if not statements:
            QMessageBox.information(
                self, "No SQL selected", "Place the cursor inside a statement or select SQL to run."
            )
            return
        editor = self._current_editor()
        if editor is None or not self._confirm_query_target(editor):
            return
        if len(statements) == 1:
            risk, explanation = classify_statement(statements[0])
            if risk == "high":
                answer = QMessageBox.warning(
                    self, "High-impact SQL",
                    explanation + "\n\nConfirm you have reviewed this statement and its scope.",
                    QMessageBox.StandardButton.Cancel | QMessageBox.StandardButton.Yes,
                    QMessageBox.StandardButton.Cancel,
                )
                if answer != QMessageBox.StandardButton.Yes:
                    return
        else:
            high: list[tuple[int, str]] = []
            for statement_number, statement in enumerate(statements, start=1):
                risk, explanation = classify_statement(statement)
                if risk == "high":
                    high.append((statement_number, explanation))
            if high:
                reasons = "\n".join(
                    f"Statement {number}: {explanation}"
                    for number, explanation in high
                )
                answer = QMessageBox.warning(
                    self,
                    "High-impact SQL script",
                    f"The script contains {len(high)} high-impact statement(s).\n\n"
                    f"{reasons}\n\n"
                    "Review the full script and its scope before continuing. "
                    "This advisory is a safeguard, not a substitute for MySQL privileges.",
                    QMessageBox.StandardButton.Cancel | QMessageBox.StandardButton.Yes,
                    QMessageBox.StandardButton.Cancel,
                )
                if answer != QMessageBox.StandardButton.Yes:
                    return
        self._last_sql = sql
        self._last_duration = 0
        self._current_result_id = None
        self._query_results = []
        self.result_picker.blockSignals(True)
        self.result_picker.clear()
        self.result_picker.blockSignals(False)
        self.result_model.update([], [])
        self._set_result_controls()
        self._dispatch("query", {"sql": sql}, {
            "sql": sql, "profile_name": self.profile.get("name", "Connection"),
        })
        self._set_result_message(
            "SQL is queued for the database worker. The editor remains responsive."
        )
        self.status.setText("Query queued…")

    def explain_query(self):
        editor = self._current_editor()
        if not editor:
            return
        sql = current_statement(editor.toPlainText(), editor.textCursor().position()).strip()
        if not sql:
            QMessageBox.information(self, "Explain SELECT", "Place the cursor inside a SELECT statement.")
            return
        if not sql.lstrip().upper().startswith("SELECT"):
            QMessageBox.warning(self, "Explain SELECT", "EXPLAIN is offered for SELECT statements.")
            return
        self._execute_sql("EXPLAIN " + sql)

    def stop_query(self):
        if self._query_running and not self._cancellation_requested:
            self._cancellation_requested = True
            self.status.setText("Cancellation requested · waiting for MySQL to respond…")
            self.query_meta.setText("Cancellation requested…")
            self._set_result_message(
                "A cancellation request was sent. The query remains active until MySQL interrupts it."
            )
            self.worker.cancel_current_query()
        elif self._query_running:
            self.status.setText("Cancellation is already requested; waiting for MySQL…")

    def format_current_sql(self):
        editor = self._current_editor()
        if not editor:
            return
        cursor = editor.textCursor()
        selected = cursor.selectedText().replace("\u2029", "\n")
        source = selected or editor.toPlainText()
        try:
            formatted = format_sql(source)
        except Exception as exc:
            QMessageBox.warning(self, "SQL formatting", redact_secrets(str(exc)))
            return
        if selected:
            cursor.insertText(formatted)
        else:
            position = cursor.position()
            editor.setPlainText(formatted)
            editor.document().setModified(True)
            cursor = editor.textCursor()
            cursor.setPosition(min(position, len(formatted)))
            editor.setTextCursor(cursor)

    def refresh_schema(self):
        schema = str(self.config.get("default_schema", "") or self.connect_result.get("database", ""))
        self._schema_request_id = None
        self._schema_expansion_requests.clear()
        self._schema_expand_items.clear()
        self.schema_tree.clear()
        self._schema_databases.clear()
        self._schema_tables.clear()
        self._schema_columns_by_table.clear()
        self._schema_completion_words.clear()
        self._active_schema_name = ""
        self._update_all_editor_completions()
        self.schema_state_label.setText("Loading database, table and column metadata…")
        self.schema_refresh_button.setEnabled(False)
        self.status.setText("Refreshing schema metadata…")
        self._schema_request_id = self._dispatch("schema", {"schema": schema})

    def _fill_schema_tree(self, result: dict):
        self.schema_tree.clear()
        active_schema = result.get("schema", "")
        for database in result.get("databases", []):
            is_active = database == active_schema
            item = QTreeWidgetItem([("▾  " if is_active else "▸  ") + database])
            item.setData(0, Qt.ItemDataRole.UserRole, {
                "kind": "schema", "schema": database,
                "metadata_loaded": is_active,
            })
            item.setToolTip(0, f"Database schema: {database}")
            if is_active:
                for record in result.get("objects", []):
                    name = record["name"]
                    kind = record.get("type", "BASE TABLE")
                    child = QTreeWidgetItem([("▤  " if kind == "BASE TABLE" else "◇  ") + name])
                    child.setData(0, Qt.ItemDataRole.UserRole, {
                        "kind": "table", "schema": database, "table": name, "object_type": kind,
                    })
                    child.setToolTip(0, f"{kind}: {database}.{name}")
                    item.addChild(child)
                item.setExpanded(True)
            else:
                placeholder = QTreeWidgetItem(["Expand to load tables and columns…"])
                placeholder.setData(0, Qt.ItemDataRole.UserRole, {"kind": "schema_placeholder"})
                placeholder.setToolTip(0, "Metadata for this schema is fetched only when expanded.")
                item.addChild(placeholder)
            self.schema_tree.addTopLevelItem(item)
        self._active_schema_name = str(active_schema or "")
        self._schema_databases = {str(database) for database in result.get("databases", [])}
        self._schema_tables = {
            str(record.get("name", ""))
            for record in result.get("objects", [])
            if record.get("name")
        }
        self._schema_completion_words = self._schema_databases | self._schema_tables
        self._schema_columns_by_table = {
            str(table): [str(column) for column in columns]
            for table, columns in (result.get("columns_by_table") or {}).items()
        }
        self._update_all_editor_completions()
        self.schema_state_label.setText(schema_status_message(result))
        status = f"Schema explorer refreshed · {len(result.get('databases', []))} database(s)"
        if result.get("column_metadata_truncated"):
            status += " · column completion limited to 10,000 columns"
            self.schema_state_label.setText(
                self.schema_state_label.text() + " Column completion is limited to 10,000 columns."
            )
        self.status.setText(status)

    def _schema_item_collapsed(self, item) -> None:
        data = item.data(0, Qt.ItemDataRole.UserRole) or {}
        if data.get("kind") == "schema":
            item.setText(0, f"▸  {data.get('schema', '')}")

    def _schema_item_expanded(self, item) -> None:
        data = item.data(0, Qt.ItemDataRole.UserRole) or {}
        if data.get("kind") != "schema":
            return
        schema = str(data.get("schema", "") or "")
        item.setText(0, f"▾  {schema}")
        if data.get("metadata_loaded") or data.get("metadata_loading") or not schema:
            return
        if schema in self._schema_expansion_requests:
            return

        while item.childCount():
            item.takeChild(0)
        placeholder = QTreeWidgetItem(["Loading tables and columns…"])
        placeholder.setData(0, Qt.ItemDataRole.UserRole, {"kind": "schema_placeholder_loading"})
        item.addChild(placeholder)
        data["metadata_loading"] = True
        item.setData(0, Qt.ItemDataRole.UserRole, data)

        job_id = self._dispatch("schema_objects", {"schema": schema}, {"schema": schema})
        if not job_id:
            data["metadata_loading"] = False
            item.setData(0, Qt.ItemDataRole.UserRole, data)
            while item.childCount():
                item.takeChild(0)
            retry = QTreeWidgetItem(["Could not load metadata · collapse and expand to retry"])
            retry.setData(0, Qt.ItemDataRole.UserRole, {"kind": "schema_placeholder"})
            item.addChild(retry)
            return
        self._schema_expansion_requests[schema] = job_id
        self._schema_expand_items[job_id] = item
        self.status.setText(f"Loading schema metadata · {schema}…")

    def _finish_schema_expansion(self, job_id: str, schema: str, item, result: dict) -> None:
        if self._schema_expansion_requests.get(schema) == job_id:
            self._schema_expansion_requests.pop(schema, None)
        self._schema_expand_items.pop(job_id, None)
        if item is None or item.treeWidget() is not self.schema_tree:
            return

        data = item.data(0, Qt.ItemDataRole.UserRole) or {}
        data.pop("metadata_loading", None)
        while item.childCount():
            item.takeChild(0)

        if not result.get("ok"):
            data["metadata_loaded"] = False
            item.setData(0, Qt.ItemDataRole.UserRole, data)
            retry = QTreeWidgetItem(["Could not load metadata · collapse and expand to retry"])
            retry.setData(0, Qt.ItemDataRole.UserRole, {"kind": "schema_placeholder"})
            retry.setToolTip(0, redact_secrets(str(result.get("error", "") or "")))
            item.addChild(retry)
            detail = redact_secrets(str(result.get("error", "") or "")).strip()
            self.status.setText(f"Could not load schema {schema}." + (f" {detail}" if detail else ""))
            return

        for record in result.get("objects", []):
            name = str(record.get("name", "") or "")
            if not name:
                continue
            kind = str(record.get("type", "BASE TABLE"))
            child = QTreeWidgetItem([("▤  " if kind == "BASE TABLE" else "◇  ") + name])
            child.setData(0, Qt.ItemDataRole.UserRole, {
                "kind": "table", "schema": schema, "table": name, "object_type": kind,
            })
            child.setToolTip(0, f"{kind}: {schema}.{name}")
            item.addChild(child)
        data["metadata_loaded"] = True
        data["metadata_loading"] = False
        item.setData(0, Qt.ItemDataRole.UserRole, data)
        table_count = len(result.get("objects", []))
        self.status.setText(f"Loaded {table_count:,} table/view object(s) from schema {schema}.")

    def _update_all_editor_completions(self) -> None:
        for index in range(self.editors.count()):
            editor = self.editors.widget(index)
            if isinstance(editor, SqlEditor):
                editor.set_completion_context(
                    databases=self._schema_databases,
                    tables=self._schema_tables,
                    columns_by_table=self._schema_columns_by_table,
                    extra_words=self._result_completion_words,
                    active_schema=self._active_schema_name,
                )

    def _set_result_completion_words(self, headers) -> None:
        self._result_completion_words = {str(header) for header in headers}
        self._update_all_editor_completions()

    def _filter_results(self, value: str) -> None:
        query = value.strip()
        self.result_proxy.setFilterFixedString(query)
        if not query:
            self.result_message.setText(self._result_base_message)
            return

        preview_rows = len(self.result_model.rows)
        visible_rows = self.result_proxy.rowCount()
        message = result_filter_message(
            query, visible_rows, preview_rows, self._result_fetched_row_count
        )
        self.result_message.setText(message)

    def _set_result_message(self, message: str) -> None:
        """Store the unfiltered result state so clearing a filter restores it."""
        self._result_base_message = str(message)
        self.result_message.setText(self._result_base_message)

    def _schema_item_activated(self, item, _column):
        data = item.data(0, Qt.ItemDataRole.UserRole) or {}
        if data.get("kind") == "schema":
            self._use_schema(data.get("schema", ""))
        elif data.get("kind") == "table":
            self._preview_schema_table(data.get("schema", ""), data.get("table", ""))

    def _use_schema(self, schema: str):
        if not schema:
            return
        self.config["default_schema"] = schema
        self.status.setText(f"Refreshing schema {schema}…")
        self.refresh_schema()

    def _preview_schema_table(self, schema: str, table: str):
        if not schema or not table:
            return
        self._dispatch("table_preview", {"schema": schema, "table": table}, {
            "profile_name": self.profile.get("name", "Connection"),
            "sql": f"Preview {qualified_identifier(schema, table)}",
        })

    def _generate_select_for_table(self, schema: str, table: str):
        if not schema or not table:
            return
        sql = select_preview_sql(schema, table)
        self.new_query_tab(sql)
        editor = self._current_editor()
        if editor is not None:
            editor.document().setModified(True)
            self._update_tab_title(editor)
            editor.setFocus()
        self._set_workspace_nav("SQL Editor")
        self.status.setText(
            f"Generated a limited SELECT for {qualified_identifier(schema, table)}. "
            "Review it before execution."
        )

    def _show_schema_context(self, point):
        item = self.schema_tree.itemAt(point)
        if item is None:
            return
        self.schema_tree.setCurrentItem(item)
        data = item.data(0, Qt.ItemDataRole.UserRole) or {}
        kind = data.get("kind")
        menu = QMenu(self)
        if kind == "schema":
            schema = str(data.get("schema", ""))
            schema_action = menu.addAction(
                "Refresh this schema" if schema == self._active_schema_name
                else "Use as default schema and refresh"
            )
            copy_action = menu.addAction("Copy schema name")
            chosen = menu.exec(self.schema_tree.viewport().mapToGlobal(point))
            if chosen == schema_action:
                self._use_schema(schema)
            elif chosen == copy_action:
                from PySide6.QtWidgets import QApplication
                QApplication.clipboard().setText(schema)
                self.status.setText(f"Copied schema name: {schema}")
            return

        if kind != "table":
            return
        schema = str(data.get("schema", ""))
        table = str(data.get("table", ""))
        object_type = str(data.get("object_type", "MySQL object"))
        qualified = qualified_identifier(schema, table)
        type_action = menu.addAction(f"{object_type} · {qualified}")
        type_action.setEnabled(False)
        menu.addSeparator()
        copy_action = menu.addAction("Copy qualified identifier")
        select_action = menu.addAction("Create SELECT preview in new tab")
        preview_action = menu.addAction("Preview table now")
        refresh_action = menu.addAction("Refresh schema")
        chosen = menu.exec(self.schema_tree.viewport().mapToGlobal(point))
        if chosen == copy_action:
            from PySide6.QtWidgets import QApplication
            QApplication.clipboard().setText(qualified)
            self.status.setText(f"Copied {qualified}")
        elif chosen == select_action:
            self._generate_select_for_table(schema, table)
        elif chosen == preview_action:
            self._preview_schema_table(schema, table)
        elif chosen == refresh_action:
            self._use_schema(schema)

    def _size_result_columns(self, headers: list[str], rows: list[list]) -> None:
        """Size columns from a bounded sample; long values remain available in cell details."""
        samples = column_width_samples(headers, rows, max_sample_rows=32, max_chars=160)
        metrics = self.result_grid.fontMetrics()
        for column, values in enumerate(samples):
            measured = max((metrics.horizontalAdvance(value) for value in values), default=0)
            self.result_grid.setColumnWidth(column, min(480, max(88, measured + 28)))

    def _select_result(self, index: int, total_duration: int | None = None):
        if index < 0 or index >= len(self._query_results):
            self._current_result_id = None
            self._result_fetched_row_count = 0
            self._set_result_controls()
            return
        item = self._query_results[index]
        self.result_filter.clear()
        self._set_result_completion_words(item.get("headers", []))
        headers = item.get("headers", [])
        rows = item.get("rows", [])
        self.result_model.update(headers, rows)
        self._size_result_columns(headers, rows)
        self._current_result_id = item.get("result_id")
        try:
            total = max(len(rows), int(item.get("row_count", len(rows)) or 0))
        except (TypeError, ValueError):
            total = len(rows)
        self._result_fetched_row_count = total
        duration = item.get("duration_ms", 0)
        self._last_duration = duration
        if total_duration is not None:
            self.query_meta.setText(f"{total:,} row(s) · {total_duration} ms total")
        else:
            self.query_meta.setText(f"{total:,} row(s) · {duration} ms")
        self._set_result_message(result_summary_message(item, len(rows), total))
        self._set_result_controls()

    def _on_worker_completed(self, job_id: str, action: str, result: dict):
        pending = self._jobs.pop(job_id, None)
        if pending is None:
            return
        expected_action, context = pending
        if expected_action != action:
            return
        if result.get("connection_lost"):
            self._mark_connection_lost(str(result.get("error", "") or ""))
        outcome = None
        if action == "query":
            if "transaction_open" in result:
                self._transaction_open = bool(result["transaction_open"])
            outcome = classify_query_outcome(result, self._cancellation_requested)
            self._query_running = False
            self._cancellation_requested = False
            self.run_button.setEnabled(True)
            self.stop_button.setEnabled(False)
            self.commit_button.setEnabled(True)
            self.rollback_button.setEnabled(True)
        if action in {"query", "table_preview"}:
            if not result.get("ok"):
                self.query_meta.setText("Query failed")
                self._set_result_message(result.get("error", "Query failed."))
            if result.get("results"):
                self._query_results = list(result["results"])
                self.result_picker.blockSignals(True)
                self.result_picker.clear()
                for index, item in enumerate(self._query_results, start=1):
                    label = result_picker_label(item, index)
                    self.result_picker.addItem(label, index - 1)
                self.result_picker.setCurrentIndex(len(self._query_results) - 1)
                self.result_picker.blockSignals(False)
                self._select_result(self.result_picker.currentIndex(), result.get("duration_ms", 0))
            else:
                # A query with no result set must not leave an older grid/export target
                # visible as though it belonged to this statement.
                self._query_results = []
                self.result_picker.blockSignals(True)
                self.result_picker.clear()
                self.result_picker.blockSignals(False)
                self.result_model.update([], [])
                self._current_result_id = None
                self._result_fetched_row_count = 0
                self.result_filter.clear()
                self._set_result_completion_words([])
                self._set_result_controls()
                if result.get("ok"):
                    self.query_meta.setText("No result set")
                    self._set_result_message("Statement completed. No result set was returned.")
                else:
                    self._set_result_message(result.get("error", "Query failed."))
            if action == "query":
                self._apply_query_outcome(outcome, result)
            else:
                self.status.setText(result.get("error") or "Table preview complete.")
            if context.get("sql"):
                self.repository.add_history(
                    context.get("profile_name", "Connection"), redact_sql_secrets(context["sql"]),
                    self._last_duration,
                    "success" if outcome == "complete" else "error" if outcome else ("success" if result.get("ok") else "error"),
                )
                self.refresh_history()
            if action == "query":
                self._flush_deferred_export_notifications()
            return
        if action == "schema_objects":
            item = self._schema_expand_items.get(job_id)
            schema = str(context.get("schema", "") or "")
            self._finish_schema_expansion(job_id, schema, item, result)
            return
        if action == "schema":
            if job_id != self._schema_request_id:
                return
            self._schema_request_id = None
            self.schema_refresh_button.setEnabled(True)
            if result.get("ok"):
                self._fill_schema_tree(result)
            else:
                detail = redact_secrets(str(result.get("error", "") or "")).strip()
                self.schema_state_label.setText(
                    "Schema metadata could not be loaded."
                    + (f"\n{detail}" if detail else " Check the connection and try again.")
                )
                self.status.setText(detail or "Could not load schema metadata. Use Refresh to retry.")
            return
        if action in {"commit", "rollback"}:
            if result.get("ok"):
                self._transaction_open = bool(result.get("transaction_open", False))
            self.status.setText(result.get("message", result.get("error", action.title())))
            if not result.get("ok"):
                QMessageBox.warning(self, action.title(), result.get("error", "Transaction operation failed."))
            return
        if action == "export_csv":
            if self._query_running:
                # A newer query owns the status area. Defer modal feedback until it completes.
                self._deferred_export_notifications.append({
                    "ok": bool(result.get("ok")),
                    "row_count": result.get("row_count", 0),
                    "path": str(result.get("path") or ""),
                    "error": str(result.get("error") or "Export failed."),
                })
                return
            self._show_export_notification(result)

    def _apply_query_outcome(self, outcome: str | None, result: dict):
        error = str(result.get("error") or "Query failed.")
        results = list(result.get("results") or [])
        completed_results = sum(item.get("kind") != "error" for item in results)
        duration = int(result.get("duration_ms", 0) or 0)

        if outcome == "complete":
            if results:
                self.status.setText(f"Query complete · {completed_results:,} result set(s) · {duration:,} ms.")
            else:
                self.query_meta.setText("Completed")
                self._set_result_message("Statement completed successfully. No result set was returned.")
                self.status.setText(f"Statement complete · {duration:,} ms.")
        elif outcome == "cancelled":
            self.query_meta.setText("Cancelled")
            self._set_result_message(
                "MySQL interrupted this query after a cancellation request. Any earlier statement results "
                "from a script remain available."
            )
            self.status.setText("Query cancelled by request.")
        elif outcome == "interrupted":
            self.query_meta.setText("Interrupted")
            self._set_result_message(
                "MySQL interrupted this query. This can occur when the server or another client interrupts it."
            )
            self.status.setText("Query interrupted by MySQL.")
        elif outcome == "partial_failure":
            self.query_meta.setText(f"{completed_results:,} completed result(s) · partial failure")
            self._set_result_message(
                "The script stopped when a later statement failed. Earlier results remain available; "
                "select the final Error result for details."
            )
            self.status.setText("Partial failure · a later SQL statement failed.")
        else:
            self.query_meta.setText("Query failed")
            self._set_result_message(error)
            self.status.setText(error)

    def _show_export_notification(self, result: dict, *, update_status: bool = True) -> None:
        if result.get("ok"):
            row_count = int(result.get("row_count", 0) or 0)
            path = str(result.get("path") or "the chosen destination")
            if update_status:
                self.status.setText(
                    f"CSV exported · {row_count:,} row(s) in MySQL fetch order"
                )
            QMessageBox.information(
                self, "CSV export complete",
                f"Exported {row_count:,} row(s) in MySQL fetch order to:\n{path}\n\n"
                "Grid sorting and the visible-row filter do not change the exported rows.\n\n"
                + CSV_EXPORT_NULL_SEMANTICS,
            )
        else:
            QMessageBox.warning(self, "CSV export", result.get("error", "Export failed."))

    def _flush_deferred_export_notifications(self) -> None:
        """Show export feedback only after the newer query has completed."""
        if self._query_running:
            return
        pending, self._deferred_export_notifications = self._deferred_export_notifications, []
        for notification in pending:
            # The query's final status is more recent; a modal can report the export
            # outcome without replacing that final status line.
            self._show_export_notification(notification, update_status=False)

    def _on_task_activity(self, job_id: str, message: str) -> None:
        """Ignore progress emitted after its job has completed or been superseded."""
        pending = self._jobs.get(job_id)
        if pending is None:
            return
        action, _context = pending
        if action not in {"query", "export_csv"}:
            return
        self._on_activity(message)

    def _on_activity(self, message: str):
        if self._query_running and message.startswith(("Exporting CSV", "Exported ")):
            # Progress from an earlier export must not overwrite the queued/running query.
            return
        self.status.setText(message)
        if message.startswith("Running "):
            self.query_meta.setText("Running…")
        elif message.startswith("Fetching result rows"):
            self.query_meta.setText("Fetching rows…")
        elif message.startswith("Fetched "):
            self.query_meta.setText(message)
        elif message.startswith("Cancellation request sent"):
            self.query_meta.setText("Cancellation request sent…")
        elif message.startswith("Cancellation could not be confirmed"):
            self.query_meta.setText("Cancellation not confirmed")
        elif message.startswith("Exporting CSV"):
            self.status.setText(message)
        elif message.startswith("Exported "):
            self.status.setText(message)

    def export_results(self):
        if not self._current_result_id:
            return
        path, _ = QFileDialog.getSaveFileName(
            self, "Export result grid", "mysql-query-results.csv", "CSV files (*.csv)"
        )
        if path:
            self._dispatch("export_csv", {"result_id": self._current_result_id, "path": path})

    def _show_result_context(self, point):
        clicked = self.result_grid.indexAt(point)
        selection = self.result_grid.selectionModel()
        if clicked.isValid() and clicked not in self.result_grid.selectedIndexes():
            selection.select(clicked, QItemSelectionModel.SelectionFlag.ClearAndSelect)

        menu = QMenu(self)
        details_action = menu.addAction("View cell details")
        details_action.setEnabled(clicked.isValid())
        menu.addSeparator()
        copy_cells_action = menu.addAction("Copy selected cells")
        copy_rows_action = menu.addAction("Copy selected rows")
        copy_headers_action = menu.addAction("Copy column headers")
        menu.addSeparator()
        export_action = menu.addAction("Export fetched result to CSV (MySQL fetch order)")
        chosen = menu.exec(self.result_grid.viewport().mapToGlobal(point))
        if chosen == details_action:
            self.show_cell_details(clicked)
        elif chosen == copy_cells_action:
            self.copy_selected_cells()
        elif chosen == copy_rows_action:
            self.copy_selected_rows()
        elif chosen == copy_headers_action:
            self.copy_column_headers()
        elif chosen == export_action:
            self.export_results()

    def _selected_view_rows(self) -> list[int]:
        return sorted({index.row() for index in self.result_grid.selectedIndexes()})

    def copy_selected_cells(self):
        indexes = self.result_grid.selectedIndexes()
        if not indexes:
            self.status.setText("Select one or more result cells to copy.")
            return
        cells = {}
        for index in indexes:
            source_index = self.result_proxy.mapToSource(index)
            value = self.result_model.rows[source_index.row()][source_index.column()]
            cells[(index.row(), index.column())] = value
        from PySide6.QtWidgets import QApplication
        QApplication.clipboard().setText(selected_cells_tsv(cells))
        self.status.setText(
            f"Copied {len(indexes):,} selected cell(s). SQL NULL is copied as NULL; empty text stays blank."
        )

    def copy_selected_rows(self):
        view_rows = self._selected_view_rows()
        if not view_rows:
            self.status.setText("Select one or more result rows to copy.")
            return
        rows = []
        for view_row in view_rows:
            values = []
            for column in range(self.result_proxy.columnCount()):
                view_index = self.result_proxy.index(view_row, column)
                source_index = self.result_proxy.mapToSource(view_index)
                values.append(self.result_model.rows[source_index.row()][source_index.column()])
            rows.append(values)
        from PySide6.QtWidgets import QApplication
        QApplication.clipboard().setText(rows_tsv(rows))
        self.status.setText(
            f"Copied {len(rows):,} selected row(s). SQL NULL is copied as NULL; empty text stays blank."
        )

    def copy_column_headers(self):
        selected_columns = sorted({index.column() for index in self.result_grid.selectedIndexes()})
        columns = selected_columns or list(range(len(self.result_model.headers)))
        headers = [
            self.result_model.headers[column] for column in columns
            if 0 <= column < len(self.result_model.headers)
        ]
        if not headers:
            self.status.setText("There are no result column headers to copy.")
            return
        from PySide6.QtWidgets import QApplication
        QApplication.clipboard().setText(column_headers_tsv(headers))
        self.status.setText(f"Copied {len(headers):,} column header(s).")

    def show_cell_details(self, index=None):
        if index is None or not index.isValid():
            index = self.result_grid.currentIndex()
        if not index.isValid():
            return
        source_index = self.result_proxy.mapToSource(index)
        value = self.result_model.rows[source_index.row()][source_index.column()]
        column_name = (
            self.result_model.headers[source_index.column()]
            if source_index.column() < len(self.result_model.headers) else "Value"
        )
        dialog = QDialog(self)
        dialog.setWindowTitle(f"Cell details · {column_name}")
        dialog.setMinimumSize(560, 340)
        layout = QVBoxLayout(dialog)
        state = QLabel(
            f"Row {source_index.row() + 1:,} · Column {column_name} · "
            + ("SQL NULL (no value)" if value is None else ("Empty text value" if value == "" else "Value"))
        )
        state.setWordWrap(True)
        layout.addWidget(state)
        detail = QPlainTextEdit(dialog)
        detail.setObjectName("cellDetailValue")
        detail.setReadOnly(True)
        detail.setPlainText(cell_detail_text(value))
        detail.setLineWrapMode(QPlainTextEdit.LineWrapMode.WidgetWidth)
        detail.setAccessibleName(f"Full value for column {column_name}")
        layout.addWidget(detail, 1)
        action_row = QHBoxLayout()
        copy_button = QPushButton("Copy full value", dialog)
        copy_button.setObjectName("copyCellValueButton")
        copy_button.setAccessibleName(f"Copy full cell value from column {column_name}")
        copy_button.setAccessibleDescription(
            "Copies the underlying cell value. SQL NULL is copied as NULL; empty text stays blank."
        )
        copy_button.clicked.connect(
            lambda _checked=False, selected_value=value, selected_column=column_name:
                self._copy_cell_detail_value(selected_value, selected_column)
        )
        action_row.addWidget(copy_button)
        action_row.addStretch(1)
        close_button = QPushButton("Close", dialog)
        close_button.clicked.connect(dialog.accept)
        action_row.addWidget(close_button)
        layout.addLayout(action_row)
        dialog.exec()

    def _copy_cell_detail_value(self, value, column_name: str) -> None:
        """Copy a full detail value without conflating SQL NULL and empty text."""
        from PySide6.QtWidgets import QApplication

        QApplication.clipboard().setText(cell_copy_text(value))
        self.status.setText(
            f"Copied full cell value from {column_name}. "
            "SQL NULL is copied as NULL; empty text stays blank."
        )

    def _set_history_enabled(self, enabled: bool):
        self.repository.set_history_enabled(enabled)
        self.refresh_history()
        self.status.setText(
            "Query history enabled (local, opt-in)." if enabled
            else "Query history disabled and cleared."
        )

    def refresh_history(self):
        self.history_list.clear()
        if not self.repository.history_enabled():
            self.history_list.addItem("Query history is off. Enable it in Settings to opt in.")
            return
        for entry in self.repository.history():
            item = QListWidgetItem(
                f"{entry['created_at']} · {entry['status']} · {entry['duration_ms']} ms"
            )
            item.setData(Qt.ItemDataRole.UserRole, entry["sql_text"])
            item.setToolTip(entry["sql_text"])
            self.history_list.addItem(item)

    def _history_selected(self, item):
        sql = item.data(Qt.ItemDataRole.UserRole)
        if sql:
            self.new_query_tab(sql)

    def _saved_root(self) -> Path:
        path = app_data_dir() / "saved_queries"
        path.mkdir(parents=True, exist_ok=True)
        return path

    def _refresh_saved_queries(self):
        self.saved_list.clear()
        try:
            paths = sorted(self._saved_root().glob("*.sql"), key=lambda p: p.name.casefold())
        except OSError as exc:
            self.saved_list.addItem("Saved queries are unavailable.")
            self.saved_list.setToolTip(redact_secrets(str(exc)))
            return
        for path in paths:
            item = QListWidgetItem(path.name)
            item.setData(Qt.ItemDataRole.UserRole, str(path))
            self.saved_list.addItem(item)
        if self.saved_list.count() == 0:
            self.saved_list.addItem("Save a query snippet to see it here.")

    def _open_sql_path(self, path: str | Path) -> bool:
        source_path = Path(path)
        try:
            sql_text = source_path.read_text(encoding="utf-8-sig")
        except (OSError, UnicodeError) as exc:
            QMessageBox.warning(
                self, "Open SQL file",
                f"Could not open {source_path.name}. The file may be missing, locked, or not valid text.\n\n"
                + redact_secrets(str(exc)),
            )
            self.status.setText("Could not open SQL file.")
            return False
        self.new_query_tab(sql_text, str(source_path))
        self._record_recent_sql_path(source_path)
        self.status.setText(f"Opened {source_path.name}")
        return True

    def _saved_selected(self, item):
        path = item.data(Qt.ItemDataRole.UserRole)
        if path:
            self._open_sql_path(path)

    def _recent_sql_paths(self) -> list[str]:
        """Read the bounded, local list of recent SQL file paths (never SQL content)."""
        stored = self._settings.value("ui/recentSqlFiles", [])
        return normalize_recent_sql_paths(stored, limit=MAX_RECENT_SQL_FILES)

    def _record_recent_sql_path(self, path: str | Path) -> None:
        paths = record_recent_sql_path(self._recent_sql_paths(), path)
        self._settings.setValue("ui/recentSqlFiles", paths)
        self._settings.sync()
        self._refresh_recent_sql_menu()

    def _refresh_recent_sql_menu(self) -> None:
        """Rebuild the menu from path-only settings and annotate missing files."""
        menu = getattr(self, "recent_sql_menu", None)
        if menu is None:
            return
        menu.clear()
        paths = self._recent_sql_paths()
        if not paths:
            empty = menu.addAction("No recent SQL files")
            empty.setEnabled(False)
        else:
            for raw_path in paths:
                file_path = Path(raw_path)
                exists = file_path.is_file()
                parent_label = file_path.parent.name or str(file_path.parent)
                label = f"{file_path.name} — {parent_label}"
                if not exists:
                    label += " · missing"
                action = menu.addAction(label)
                action.setToolTip(raw_path)
                action.setStatusTip(raw_path)
                action.triggered.connect(
                    lambda _checked=False, selected_path=raw_path: self._open_sql_path(selected_path)
                )
        menu.addSeparator()
        clear_action = menu.addAction("Clear recent list")
        clear_action.setToolTip("Remove recent file paths from this menu. Does not delete files.")
        clear_action.triggered.connect(lambda _checked=False: self._clear_recent_sql_files())

    def _clear_recent_sql_files(self) -> None:
        """Clear only the saved path list; source SQL files are not modified or deleted."""
        self._settings.setValue("ui/recentSqlFiles", [])
        self._settings.sync()
        self._refresh_recent_sql_menu()
        self.status.setText("Cleared Recent SQL files list. No SQL files were deleted.")

    def open_sql_file(self):
        path, _ = QFileDialog.getOpenFileName(
            self, "Open SQL file", "", "SQL files (*.sql);;Text files (*.txt);;All files (*)"
        )
        if path:
            self._open_sql_path(path)

    def _write_editor_to_path(self, editor, path: str) -> bool:
        """Atomically save one editor buffer and update only that tab's save state."""
        if editor is None:
            return False

        destination = Path(path)
        temporary_path: Path | None = None
        try:
            destination.parent.mkdir(parents=True, exist_ok=True)
            with tempfile.NamedTemporaryFile(
                mode="w",
                encoding="utf-8",
                newline="",
                prefix=f".{destination.name}.",
                suffix=".tmp",
                dir=str(destination.parent),
                delete=False,
            ) as temporary:
                temporary_path = Path(temporary.name)
                temporary.write(editor.toPlainText())
                temporary.flush()
                os.fsync(temporary.fileno())
            os.replace(temporary_path, destination)
            temporary_path = None
        except (OSError, UnicodeError) as exc:
            if temporary_path is not None:
                try:
                    temporary_path.unlink(missing_ok=True)
                except OSError:
                    pass
            QMessageBox.warning(
                self, "Save SQL file",
                f"Could not save {destination.name}. Your query remains open and unchanged.\n\n"
                + redact_secrets(str(exc)),
            )
            self.status.setText("Save failed; your query remains open.")
            return False

        editor.document().setModified(False)
        self._last_saved_paths[id(editor)] = str(destination)
        index = self.editors.indexOf(editor)
        if index >= 0:
            self.editors.setTabText(index, destination.name)
        self._refresh_saved_queries()
        self._record_recent_sql_path(destination)
        self.status.setText(f"Saved {destination.name}")
        return True

    def _write_current_editor(self, path: str) -> bool:
        return self._write_editor_to_path(self._current_editor(), path)

    def save_all_sql_files(self) -> bool:
        """Save modified tabs in order; cancellation/failure leaves later tabs untouched."""
        pending = [
            (self.editors.widget(index), self.editors.tabText(index))
            for index in range(self.editors.count())
            if self.editors.widget(index) is not None
            and self.editors.widget(index).document().isModified()
        ]
        if not pending:
            self.status.setText("All SQL tabs are already saved.")
            return True

        saved_count = 0
        for editor, raw_label in pending:
            path = self._last_saved_paths.get(id(editor), "") or ""
            if not path:
                tab_label = raw_label.removesuffix(" *")
                suggested = Path(tab_label).name or "query.sql"
                if not suggested.lower().endswith(".sql"):
                    suggested += ".sql"
                path, _ = QFileDialog.getSaveFileName(
                    self,
                    f"Save {tab_label}",
                    suggested,
                    "SQL files (*.sql)",
                )
                if not path:
                    if saved_count:
                        self.status.setText(
                            f"Save All cancelled after saving {saved_count} tab(s); "
                            "remaining tabs were left unchanged."
                        )
                    else:
                        self.status.setText("Save All cancelled; no tabs were saved.")
                    return False

            if not self._write_editor_to_path(editor, path):
                self.status.setText(
                    f"Save All stopped after saving {saved_count} tab(s); "
                    "remaining tabs were left unchanged."
                )
                return False
            saved_count += 1

        self.status.setText(f"Saved {saved_count} modified SQL tab(s).")
        return True

    def save_sql_file(self, force_dialog: bool = False):
        editor = self._current_editor()
        if not editor:
            return
        path = "" if force_dialog else self._last_saved_paths.get(id(editor), "")
        if not path:
            path, _ = QFileDialog.getSaveFileName(
                self, "Save SQL file", "query.sql", "SQL files (*.sql)"
            )
        if path:
            self._write_current_editor(path)

    def save_query_snippet(self):
        editor = self._current_editor()
        if not editor or not editor.toPlainText().strip():
            QMessageBox.information(self, "Save SQL snippet", "Write a query before saving a snippet.")
            return
        name, ok = QInputDialog.getText(self, "Save SQL snippet", "Snippet name:")
        if not ok or not name.strip():
            return
        safe_name = "".join(ch for ch in name.strip() if ch.isalnum() or ch in " _-.").strip()
        if not safe_name:
            QMessageBox.warning(self, "Save SQL snippet", "Enter a valid snippet name.")
            return
        try:
            root = self._saved_root()
        except OSError as exc:
            QMessageBox.warning(
                self, "Save SQL snippet",
                "The saved-queries folder could not be created.\n\n" + redact_secrets(str(exc)),
            )
            return
        path = root / (safe_name if safe_name.lower().endswith(".sql") else safe_name + ".sql")
        if path.exists():
            answer = QMessageBox.question(
                self, "Replace snippet", f"{path.name} already exists. Replace it?",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                QMessageBox.StandardButton.No,
            )
            if answer != QMessageBox.StandardButton.Yes:
                return
        self._write_current_editor(str(path))

    def find_text(self):
        self._show_find_replace(replace=False)

    def replace_text(self):
        self._show_find_replace(replace=True)

    def _show_find_replace(self, replace: bool):
        editor = self._current_editor()
        selected_text = ""
        if editor is not None and editor.textCursor().hasSelection():
            selected_text = editor.textCursor().selectedText().replace("\u2029", "\n")
        self.find_bar.show_bar(replace=replace, seed_text=selected_text or None)
        self._refresh_find_count()

    def _close_find_bar(self):
        editor = self._current_editor()
        if editor is not None:
            editor.setFocus()

    def show_find_replace(self, replace: bool = False):
        """Open Find/Replace from a menu, shortcut, or host-level UI action."""
        self._show_find_replace(replace=replace)

    def _queue_find_count_refresh(self, *_):
        if hasattr(self, "_find_count_timer"):
            self._find_count_timer.start()

    def _refresh_find_count(self):
        if not hasattr(self, "find_bar"):
            return
        editor = self._current_editor()
        if editor is None:
            self.find_bar.set_match_count(0)
            return
        total = count_matches(
            editor.toPlainText(),
            self.find_bar.search_text(),
            self.find_bar.match_case(),
        )
        self.find_bar.set_match_count(total)

    def _navigate_find_match(self, backward: bool = False) -> bool:
        editor = self._current_editor()
        if editor is None:
            return False
        needle = self.find_bar.search_text()
        if not needle:
            self.status.setText("Enter text to find in the current SQL query.")
            self._refresh_find_count()
            return False

        flags = QTextDocument.FindFlag(0)
        if self.find_bar.match_case():
            flags |= QTextDocument.FindFlag.FindCaseSensitively
        if backward:
            flags |= QTextDocument.FindFlag.FindBackward

        found = editor.find(needle, flags)
        if not found:
            cursor = editor.textCursor()
            cursor.movePosition(
                QTextCursor.MoveOperation.End if backward else QTextCursor.MoveOperation.Start
            )
            editor.setTextCursor(cursor)
            found = editor.find(needle, flags)

        if found:
            editor.setFocus()
            self.status.setText("Match selected.")
        else:
            self.status.setText(f"No matches for {needle!r}.")
        self._refresh_find_count()
        return bool(found)

    def _replace_one(self):
        editor = self._current_editor()
        needle = self.find_bar.search_text()
        if editor is None or not needle:
            return

        cursor = editor.textCursor()
        selected = cursor.selectedText().replace("\u2029", "\n")
        case_sensitive = self.find_bar.match_case()
        matched = selected == needle if case_sensitive else selected.casefold() == needle.casefold()
        if not matched:
            if not self._navigate_find_match():
                return
            cursor = editor.textCursor()
            selected = cursor.selectedText().replace("\u2029", "\n")
            matched = selected == needle if case_sensitive else selected.casefold() == needle.casefold()
            if not matched:
                return

        cursor.insertText(self.find_bar.replacement_text())
        editor.setTextCursor(cursor)
        self.status.setText("Replaced one occurrence.")
        self._refresh_find_count()
        self._navigate_find_match()

    def _replace_all(self):
        editor = self._current_editor()
        needle = self.find_bar.search_text()
        if editor is None or not needle:
            return

        flags = QTextDocument.FindFlag(0)
        if self.find_bar.match_case():
            flags |= QTextDocument.FindFlag.FindCaseSensitively
        replacement = self.find_bar.replacement_text()
        original_cursor = editor.textCursor()
        cursor = QTextCursor(editor.document())
        cursor.movePosition(QTextCursor.MoveOperation.Start)
        cursor.beginEditBlock()
        replaced = 0
        try:
            while True:
                match = editor.document().find(needle, cursor, flags)
                if match.isNull():
                    break
                match.insertText(replacement)
                cursor = match
                replaced += 1
        finally:
            cursor.endEditBlock()

        editor.setTextCursor(original_cursor)
        self._refresh_find_count()
        self.status.setText(
            f"Replaced {replaced:,} occurrence(s)." if replaced
            else f"No matches for {needle!r}."
        )

    def clear_history(self):
        self.repository.set_history_enabled(False)
        self.refresh_history()
        self.status.setText("Local query history cleared and disabled.")

    def _confirm_connection_switch(self, config: dict) -> bool:
        """Ask before a successful Connect replaces a session with uncommitted work."""
        if not self._transaction_open:
            return True

        active_context = self._current_connection_context()
        candidate_profile = {
            "id": config.get("profile_id", ""),
            "name": config.get("profile_name", "Connection"),
            "host": config.get("host", "MySQL"),
            "port": config.get("port", 3306),
            "username": config.get("username", ""),
        }
        candidate_context = build_connection_context(candidate_profile, config, {})
        active_label = connection_context_label(active_context)
        candidate_label = connection_context_label(candidate_context)
        answer = QMessageBox.warning(
            self,
            "Uncommitted transaction",
            "The active MySQL session has an open transaction. If the replacement connection "
            "succeeds, the current session will close and MySQL can roll back uncommitted work.\n\n"
            f"Current session:\n{active_label}\n\n"
            f"Requested session:\n{candidate_label}\n\n"
            "Continue connecting? Cancel returns to the connection dialog without replacing "
            "the active session. If the new connection fails, the current session is retained.",
            QMessageBox.StandardButton.Cancel | QMessageBox.StandardButton.Yes,
            QMessageBox.StandardButton.Cancel,
        )
        if answer != QMessageBox.StandardButton.Yes:
            self.status.setText(
                "Connection change cancelled · the current session and its open transaction remain active."
            )
            return False
        return True

    def open_connection_dialog(self):
        if self._query_running:
            self._report_query_busy("connection")
            return
        dialog = ConnectionDialog(
            self.worker, self.repository, self.credentials, self,
            master_unlocked=True, before_connect=self._confirm_connection_switch,
        )
        dialog.connected.connect(self._switch_connection)
        dialog.exec()

    def _switch_connection(self, profile: dict, config: dict, connect_result: dict):
        if self._query_running:
            self._report_query_busy("connection")
            return
        self._persist_profile(profile, config)
        self.profile = profile
        self.config = config
        self.connect_result = connect_result
        self._transaction_open = bool(connect_result.get("transaction_open", False))
        self._update_connection_status()
        self.refresh_schema()
        editor = self._current_editor()
        if editor is not None:
            bound = getattr(editor, "_mysql_editor_connection_context", None)
            active = self._current_connection_context()
            if bound and not connection_context_matches(bound, active):
                self.status.setText(
                    "Active MySQL connection changed. This query tab keeps its prior target; "
                    "confirm before executing SQL on the new connection."
                )

    def _persist_profile(self, profile: dict, config: dict):
        if not config.get("save_profile"):
            self.repository.set_setting("last_profile_id", "")
            return
        try:
            self.repository.save_profile(ConnectionProfile(**profile))
            self.credentials.save(profile["id"], config.get("password", ""))
            self.repository.set_setting("last_profile_id", profile["id"])
            self.status.setText("Connection profile and password saved in Windows Credential Manager.")
        except Exception as exc:
            self.repository.set_setting("last_profile_id", "")
            QMessageBox.warning(
                self, "Profile not saved",
                "Connected successfully, but the profile/password was not saved securely. "
                "The password was not written to a file.\n\n" + redact_secrets(str(exc)),
            )

    def _set_connection_badge_state(self, state: str) -> None:
        self.connection_badge.setProperty("connectionState", state)
        style = self.connection_badge.style()
        style.unpolish(self.connection_badge)
        style.polish(self.connection_badge)
        self.connection_badge.update()

    def _mark_connection_lost(self, error_message: str = "") -> None:
        """Show a lost database session without discarding query buffers or target details."""
        host = str(self.config.get("host", "MySQL") or "MySQL")
        profile_name = str(self.profile.get("name", "Connection") or "Connection")
        schema = self.connect_result.get("database") or self.config.get("default_schema") or "(no default schema)"
        hint = "MySQL session lost. Reconnect before running more SQL."
        detail = redact_secrets(str(error_message or "")).strip()
        details = f"{hint}" + (f" Details: {detail}" if detail else "")
        self.connection_badge.setText(f"●  {profile_name} · {host} · Connection lost")
        self.connection_badge.setToolTip(details)
        self.connection_badge.setAccessibleName("MySQL connection lost")
        self.connection_badge.setAccessibleDescription(details)
        self._set_connection_badge_state("lost")
        self.connection_details.setText(
            f"{self.config.get('username', '')}@{host}:{self.config.get('port', 3306)} · {schema} · Lost"
        )
        self.connection_details.setToolTip(details)
        self.connection_details.setAccessibleName("Lost MySQL connection details")
        self.connection_details.setAccessibleDescription(details)
        self._transaction_open = False
        if hasattr(self, "commit_button"):
            self.commit_button.setEnabled(False)
        if hasattr(self, "rollback_button"):
            self.rollback_button.setEnabled(False)
        self.status.setText(hint)

    def _update_connection_status(self):
        host = self.config.get("host", "MySQL")
        schema = self.connect_result.get("database") or self.config.get("default_schema") or "(no default schema)"
        profile_name = str(self.profile.get("name", "Connection") or "Connection")
        self.connection_badge.setText(f"●  {profile_name} · {host} · Connected")
        self.connection_badge.setAccessibleName("Active MySQL connection status")
        self._set_connection_badge_state("connected")
        details = (
            f"{host}:{self.config.get('port', 3306)} · {self.config.get('username', '')} · "
            f"Database: {schema} · Server: {self.connect_result.get('server_version', 'MySQL')} · "
            f"TLS: {self.config.get('tls_mode', 'Automatic TLS')}"
        )
        self.connection_details.setText(
            f"{self.config.get('username', '')}@{host}:{self.config.get('port', 3306)} · {schema}"
        )
        self.connection_details.setToolTip(details)
        self.connection_details.setAccessibleName("Active MySQL connection details")
        self.connection_details.setAccessibleDescription(details)

    def show_safety_info(self):
        QMessageBox.information(
            self, "SQL execution and safety",
            "High-impact SQL receives a confirmation prompt, but the prompt is advisory only. "
            "Use least-privilege MySQL accounts and server-side grants for access control. "
            "Transactions are manual: use Commit or Rollback. Some MySQL DDL statements commit implicitly.",
        )

    def show_about(self):
        QMessageBox.about(
            self, "About MySQL Editor",
            "MySQL Editor 0.1.0\nA clean-room Windows SQL IDE for MySQL.\n"
            "SQL execution runs in a dedicated worker thread. Database passwords do not live in SQLite.",
        )

    def closeEvent(self, event):
        if self._query_running:
            answer = QMessageBox.question(
                self, "Query running",
                "A query is still running. Ask MySQL to cancel it and close?",
                QMessageBox.StandardButton.Cancel | QMessageBox.StandardButton.Yes,
                QMessageBox.StandardButton.Cancel,
            )
            if answer != QMessageBox.StandardButton.Yes:
                event.ignore()
                return
            self.worker.cancel_current_query()
        for index in range(self.editors.count()):
            editor = self.editors.widget(index)
            if editor and editor.document().isModified():
                answer = QMessageBox.question(
                    self, "Unsaved query",
                    "One or more query tabs have unsaved edits. Close MySQL Editor anyway?",
                    QMessageBox.StandardButton.Discard | QMessageBox.StandardButton.Cancel,
                    QMessageBox.StandardButton.Cancel,
                )
                if answer != QMessageBox.StandardButton.Discard:
                    event.ignore()
                    return
                break
        self._settings.setValue("ui/windowGeometry", self.saveGeometry())
        self._settings.setValue("ui/mainSplitterSizes", self.main_split.sizes())
        self._settings.setValue("ui/editorResultsSplitterSizes", self.editor_results_split.sizes())
        self._settings.setValue("ui/inspectorTab", self.inspector_tabs.currentIndex())
        self._settings.sync()
        self.worker.submit("disconnect", {})
        self.worker.shutdown()
        self.worker.wait(5000)
        event.accept()
