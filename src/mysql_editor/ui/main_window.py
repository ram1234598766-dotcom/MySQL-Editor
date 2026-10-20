"""Main SQL workspace: query tabs, schema navigation, results and local query tools."""

from __future__ import annotations

import os
import tempfile
import uuid
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any

from PySide6.QtCore import QAbstractTableModel, QItemSelectionModel, QModelIndex, QSettings, QSortFilterProxyModel, Signal, Qt, QTimer, QUrl
from PySide6.QtGui import QAction, QActionGroup, QColor, QDesktopServices, QFont, QKeySequence, QIcon, QPixmap, QShortcut, QTextCursor, QTextDocument
from PySide6.QtWidgets import (
    QApplication, QComboBox, QDialog, QFileDialog, QFontDialog, QHBoxLayout, QHeaderView, QInputDialog,
    QLabel, QListWidget, QListWidgetItem, QLineEdit, QMainWindow, QMenu, QMessageBox,
    QPlainTextEdit, QPushButton, QSplitter, QTabWidget, QTableView, QToolButton,
    QTreeWidget, QTreeWidgetItem, QVBoxLayout, QWidget,
)

from mysql_editor.core import (
    ScriptParseError, classify_statement, current_statement, current_statement_source, format_sql,
    redact_sql_secrets, sanitize_error_message, split_sql_statements,
)
from mysql_editor.database import DatabaseWorker, RESULT_PAGE_ROWS
from mysql_editor.storage import ConnectionProfile, CredentialStore, LocalRepository, app_data_dir
from mysql_editor.ui.animations import fade_in
from mysql_editor.ui.connection_context import (
    build_connection_context, connection_context_label, connection_context_matches,
)
from mysql_editor.ui.connection_dialog import ConnectionDialog
from mysql_editor.ui.editor import SqlEditor
from mysql_editor.ui.find_replace_bar import FindReplaceBar, count_matches
from mysql_editor.ui.tutorial import ProductTourDialog
from mysql_editor.ui.theme import color_for_theme, normalize_theme, resolve_theme, stylesheet_for_theme
from mysql_editor.ui.result_tools import (
    cell_copy_text, cell_detail_text, column_headers_tsv, column_width_samples,
    result_export_target, result_filter_message, result_picker_label, result_summary_message,
    result_window_message,
    rows_tsv, selected_cells_tsv,
)
from mysql_editor.ui.preferences import (
    normalize_boolean_preference, normalize_editor_font_family,
    normalize_result_row_height, normalize_tab_width,
)
from mysql_editor.ui.query_lifecycle import classify_query_outcome
from mysql_editor.ui.schema_tools import qualified_identifier, schema_status_message, select_preview_sql
from mysql_editor.ui.schema_inspector import SchemaObjectInspectorDialog
from mysql_editor.ui.cell_editor import EditTableCellDialog
from mysql_editor.ui.explain_plan import ExplainPlanDialog, ExplainPlanError, extract_explain_json
from mysql_editor.update_checker import UpdateCheckResult, UpdateCheckThread, is_safe_release_url
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
RESULT_EXPORT_SEMANTICS = (
    "Exports include every fetched row in MySQL fetch order, independent of grid sorting "
    "and the visible-row filter."
)
EXPORT_ACTIONS = frozenset({"export_csv", "export_json", "export_ndjson"})
EXPORT_FORMAT_LABELS = {"csv": "CSV", "json": "JSON", "ndjson": "NDJSON"}


class ResultsModel(QAbstractTableModel):
    """Bounded, contiguous row window over the on-disk result spool."""

    more_rows_requested = Signal()
    previous_rows_requested = Signal()
    MAX_RETAINED_ROWS = RESULT_PAGE_ROWS * 5

    def __init__(self, headers=None, rows=None, parent=None, theme: object = "dark"):
        super().__init__(parent)
        self.headers = list(headers or [])
        self.rows = [list(row) for row in (rows or [])]
        self.base_offset = 0
        self._row_offsets = list(range(len(self.rows)))
        self.total_rows = len(self.rows)
        self._page_load_pending = False
        self._page_load_available = True
        self._null_foreground = QColor(color_for_theme("text_muted", theme))

    def set_theme(self, theme: object) -> None:
        """Update NULL-cell contrast without resetting or reordering result data."""
        foreground = QColor(color_for_theme("text_muted", theme))
        if foreground == self._null_foreground:
            return
        self._null_foreground = foreground
        if self.rowCount() and self.columnCount():
            self.dataChanged.emit(
                self.index(0, 0),
                self.index(self.rowCount() - 1, self.columnCount() - 1),
                [Qt.ItemDataRole.ForegroundRole],
            )

    def update(
        self,
        headers,
        rows,
        *,
        base_offset: int = 0,
        source_offsets=None,
        total_rows: int | None = None,
    ):
        """Replace the row window; base_offset is view position, offsets address source rows."""
        try:
            parsed_offset = max(0, int(base_offset))
        except (TypeError, ValueError, OverflowError):
            parsed_offset = 0
        new_rows = [list(row) for row in (rows or [])]
        new_offsets = list(source_offsets) if source_offsets is not None else []
        if len(new_rows) > self.MAX_RETAINED_ROWS:
            new_rows = new_rows[: self.MAX_RETAINED_ROWS]
            if new_offsets:
                new_offsets = new_offsets[: self.MAX_RETAINED_ROWS]
        if len(new_offsets) != len(new_rows):
            new_offsets = list(range(parsed_offset, parsed_offset + len(new_rows)))
        else:
            try:
                new_offsets = [max(0, int(offset)) for offset in new_offsets]
            except (TypeError, ValueError, OverflowError):
                new_offsets = list(range(parsed_offset, parsed_offset + len(new_rows)))
        try:
            parsed_total = max(0, int(total_rows)) if total_rows is not None else parsed_offset + len(new_rows)
        except (TypeError, ValueError, OverflowError):
            parsed_total = parsed_offset + len(new_rows)
        self.beginResetModel()
        self.headers = list(headers or [])
        self.rows = new_rows
        self.base_offset = parsed_offset
        self._row_offsets = new_offsets
        self.total_rows = max(parsed_offset + len(new_rows), parsed_total)
        self._page_load_pending = False
        self._page_load_available = True
        self.endResetModel()

    def set_paging_state(
        self,
        *,
        total_rows: int | None = None,
        pending: bool | None = None,
        available: bool | None = None,
    ) -> None:
        """Update asynchronous spool paging state without resetting visible rows."""
        if total_rows is not None:
            try:
                parsed_total = max(0, int(total_rows))
            except (TypeError, ValueError, OverflowError):
                parsed_total = self.base_offset + len(self.rows)
            self.total_rows = max(self.base_offset + len(self.rows), parsed_total)
        if pending is not None:
            self._page_load_pending = bool(pending)
        if available is not None:
            self._page_load_available = bool(available)

    def absolute_row_index(self, local_row: int) -> int | None:
        """Return the zero-based source-spool row index for a visible model row."""
        if not 0 <= local_row < len(self._row_offsets):
            return None
        return self._row_offsets[local_row]

    def canFetchMore(self, parent=QModelIndex()) -> bool:
        if parent.isValid():
            return False
        return (
            self._page_load_available
            and not self._page_load_pending
            and self.base_offset + len(self.rows) < self.total_rows
        )

    def fetchMore(self, parent=QModelIndex()) -> None:
        """Request the next spool page; the worker result arrives asynchronously."""
        if not self.canFetchMore(parent):
            return
        self._page_load_pending = True
        self.more_rows_requested.emit()

    def canFetchPrevious(self) -> bool:
        """Whether an earlier window can be loaded from the same local result spool."""
        return (
            self._page_load_available
            and not self._page_load_pending
            and self.base_offset > 0
        )

    def fetchPrevious(self) -> None:
        """Request the previous spool page without a synchronous database call."""
        if not self.canFetchPrevious():
            return
        self._page_load_pending = True
        self.previous_rows_requested.emit()

    def update_cell_row(self, row_index: int, values) -> bool:
        """Replace a single preview row after MySQL confirms a cell update."""
        if not 0 <= row_index < len(self.rows) or len(values) != len(self.headers):
            return False
        self.rows[row_index] = list(values)
        if self.columnCount():
            self.dataChanged.emit(
                self.index(row_index, 0),
                self.index(row_index, self.columnCount() - 1),
                [
                    Qt.ItemDataRole.DisplayRole,
                    Qt.ItemDataRole.UserRole,
                    Qt.ItemDataRole.ForegroundRole,
                    Qt.ItemDataRole.TextAlignmentRole,
                ],
            )
        return True

    def append_rows(self, rows, *, source_offsets=None) -> int:
        """Append rows and evict the oldest window prefix once the cache bound is reached."""
        additions = [list(row) for row in rows]
        if not additions:
            return 0
        next_offset = self.base_offset + len(self.rows)
        try:
            offsets = [max(0, int(offset)) for offset in source_offsets] if source_offsets is not None else []
        except (TypeError, ValueError, OverflowError):
            offsets = []
        if len(offsets) != len(additions):
            offsets = list(range(next_offset, next_offset + len(additions)))
        first = len(self.rows)
        last = first + len(additions) - 1
        self.beginInsertRows(QModelIndex(), first, last)
        self.rows.extend(additions)
        self._row_offsets.extend(offsets)
        self.total_rows = max(self.total_rows, self.base_offset + len(self.rows))
        self.endInsertRows()

        evicted = max(0, len(self.rows) - self.MAX_RETAINED_ROWS)
        if evicted:
            self.beginRemoveRows(QModelIndex(), 0, evicted - 1)
            del self.rows[:evicted]
            del self._row_offsets[:evicted]
            self.base_offset += evicted
            self.endRemoveRows()
        return evicted

    def prepend_rows(self, rows, *, start_offset: int, source_offsets=None) -> int:
        """Prepend a contiguous earlier page and evict the newest tail if necessary."""
        additions = [list(row) for row in rows]
        if not additions:
            return 0
        try:
            offset = max(0, int(start_offset))
        except (TypeError, ValueError, OverflowError):
            return 0
        if offset + len(additions) != self.base_offset:
            return 0
        try:
            offsets = [max(0, int(value)) for value in source_offsets] if source_offsets is not None else []
        except (TypeError, ValueError, OverflowError):
            offsets = []
        if len(offsets) != len(additions):
            offsets = list(range(offset, offset + len(additions)))
        last = len(additions) - 1
        self.beginInsertRows(QModelIndex(), 0, last)
        self.rows[0:0] = additions
        self._row_offsets[0:0] = offsets
        self.base_offset = offset
        self.total_rows = max(self.total_rows, self.base_offset + len(self.rows))
        self.endInsertRows()

        evicted = max(0, len(self.rows) - self.MAX_RETAINED_ROWS)
        if evicted:
            first_removed = len(self.rows) - evicted
            last_removed = len(self.rows) - 1
            self.beginRemoveRows(QModelIndex(), first_removed, last_removed)
            del self.rows[first_removed:]
            del self._row_offsets[first_removed:]
            self.endRemoveRows()
        return evicted

    def rowCount(self, parent=QModelIndex()):
        return 0 if parent.isValid() else len(self.rows)

    def columnCount(self, parent=QModelIndex()):
        return 0 if parent.isValid() else len(self.headers)

    def data(self, index, role=Qt.ItemDataRole.DisplayRole):
        if not index.isValid() or not (0 <= index.row() < len(self.rows)):
            return None
        if not 0 <= index.column() < len(self.headers):
            return None
        value = self.rows[index.row()][index.column()]
        if role == Qt.ItemDataRole.UserRole:
            return value
        if role == Qt.ItemDataRole.DisplayRole:
            return "(NULL)" if value is None else str(value)
        if role == Qt.ItemDataRole.ForegroundRole and value is None:
            return QColor(self._null_foreground)
        if role == Qt.ItemDataRole.TextAlignmentRole and isinstance(value, (int, float, Decimal)):
            return int(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        return None

    def headerData(self, section, orientation, role=Qt.ItemDataRole.DisplayRole):
        if role != Qt.ItemDataRole.DisplayRole:
            return None
        if orientation == Qt.Orientation.Horizontal and section < len(self.headers):
            return self.headers[section]
        if orientation == Qt.Orientation.Vertical and 0 <= section < len(self._row_offsets):
            return str(self._row_offsets[section] + 1)
        return None

    def sort(self, column, order=Qt.SortOrder.AscendingOrder):
        if not 0 <= column < len(self.headers):
            return
        # The live table view sorts through ResultsFilterProxyModel. Sorting the
        # source model itself would destroy spool order, making the next/previous
        # page boundary ambiguous for a bounded window.
        if self.base_offset > 0 or len(self.rows) < self.total_rows:
            return
        self.layoutAboutToBeChanged.emit()

        def sort_key(row):
            value = row[column]
            try:
                return (0, 0, Decimal(str(value)))
            except (InvalidOperation, ValueError):
                return (0, 1, str(value).casefold())

        indexed_rows = list(zip(self.rows, self._row_offsets, strict=True))
        non_null = [entry for entry in indexed_rows if entry[0][column] is not None]
        null_rows = [entry for entry in indexed_rows if entry[0][column] is None]
        non_null.sort(
            key=lambda entry: sort_key(entry[0]),
            reverse=order == Qt.SortOrder.DescendingOrder,
        )
        ordered = non_null + null_rows
        self.rows[:] = [row for row, _offset in ordered]
        self._row_offsets[:] = [offset for _row, offset in ordered]
        self.base_offset = min(self._row_offsets, default=self.base_offset)
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

    def headerData(self, section, orientation, role=Qt.ItemDataRole.DisplayRole):
        if role == Qt.ItemDataRole.DisplayRole and orientation == Qt.Orientation.Vertical:
            source = self.sourceModel()
            if source is not None and source.columnCount() > 0:
                proxy_index = self.index(section, 0)
                if proxy_index.isValid():
                    source_index = self.mapToSource(proxy_index)
                    absolute_row = getattr(source, "absolute_row_index", None)
                    if callable(absolute_row):
                        offset = absolute_row(source_index.row())
                        if offset is not None:
                            return str(offset + 1)
        return super().headerData(section, orientation, role)

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
        self._connection_available = True
        self._disconnect_pending = False
        self._jobs: dict[str, tuple[str, dict]] = {}
        self._task_sequence_counter = 0
        self._task_sequences: dict[str, int] = {}
        self._latest_query_sequence = 0
        self._deferred_export_notifications: list[dict] = []
        self._schema_request_id: str | None = None
        self._schema_expansion_requests: dict[str, str] = {}
        self._schema_expand_items: dict[str, QTreeWidgetItem] = {}
        self._schema_completion_words: set[str] = set()
        self._schema_databases: set[str] = set()
        self._schema_tables: set[str] = set()
        self._schema_columns_by_table: dict[str, list[str]] = {}
        self._schema_tables_by_schema: dict[str, set[str]] = {}
        self._schema_columns_by_schema_and_table: dict[str, dict[str, list[str]]] = {}
        self._active_schema_name = str(config.get("default_schema", "") or connect_result.get("database", ""))
        self._result_completion_words: set[str] = set()
        self._query_running = False
        self._cell_edit_pending = False
        # Original preview rows stay available until the owning MySQL transaction ends.
        self._pending_table_preview_undo: dict[tuple[str, int], dict[str, Any]] = {}
        self._cancellation_requested = False
        self._current_result_id: str | None = None
        self._result_fetched_row_count = 0
        self._result_page_load_pending = None
        self._filter_generation = 0
        self._pending_spool_filter: dict | None = None
        self._spool_filter_request: dict | None = None
        self._result_base_message = "Ready. Run a query to view results."
        self._query_results: list[dict] = []
        self._last_duration = 0
        self._last_sql = ""
        self._last_saved_paths: dict[int, str] = {}
        self._settings = QSettings()
        self._update_checks_enabled = normalize_boolean_preference(
            self._settings.value("updates/automaticCheck", False), False
        )
        self._update_check_thread: UpdateCheckThread | None = None
        self._close_after_update_check = False
        self._close_after_update_check_approved = False
        self._update_check_manual = False
        self._editor_tab_width = normalize_tab_width(self._settings.value("ui/tabWidth", 4))
        self._show_editor_line_numbers = normalize_boolean_preference(
            self._settings.value("ui/showLineNumbers", True), True
        )
        self._highlight_current_line = normalize_boolean_preference(
            self._settings.value("ui/currentLineHighlight", True), True
        )
        self._editor_font_family = normalize_editor_font_family(
            self._settings.value("ui/editorFontFamily", "Cascadia Code")
        )
        self._result_row_height = normalize_result_row_height(self._settings.value("ui/resultRowHeight", 28))
        self._find_count_timer = QTimer(self)
        self._find_count_timer.setSingleShot(True)
        self._find_count_timer.setInterval(80)
        self._find_count_timer.timeout.connect(self._refresh_find_count)
        self._filter_debounce_timer = QTimer(self)
        self._filter_debounce_timer.setSingleShot(True)
        self._filter_debounce_timer.setInterval(300)
        self._filter_debounce_timer.timeout.connect(self._dispatch_spool_filter)
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
        QTimer.singleShot(1400, self._maybe_check_for_updates_on_startup)

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
        self.tour_button.setAccessibleName("Open MySQL Editor guided tour")
        self.tour_button.setAccessibleDescription(
            "Opens a guided overview of the SQL workspace and common actions."
        )
        self.tour_button.setToolTip("Learn the main parts of the MySQL Editor workspace.")
        self.tour_button.clicked.connect(self._show_product_tour)
        top_layout.addWidget(self.tour_button)
        self.connect_button = QPushButton("Connect")
        self.connect_button.setObjectName("primaryButton")
        self.connect_button.setAccessibleName("Connect or switch MySQL connection")
        self.connect_button.setToolTip("Connect to another MySQL server or reconnect after disconnecting.")
        self.connect_button.clicked.connect(self.open_connection_dialog)
        top_layout.addWidget(self.connect_button)
        self.disconnect_button = QPushButton("Disconnect")
        self.disconnect_button.setAccessibleName("Disconnect from the active MySQL server")
        self.disconnect_button.setAccessibleDescription(
            "Closes the current database session. Query tabs and fetched results stay open."
        )
        self.disconnect_button.setToolTip(
            "Close the active MySQL session without closing SQL tabs or removing fetched results."
        )
        self.disconnect_button.clicked.connect(self.disconnect_from_mysql)
        top_layout.addWidget(self.disconnect_button)
        outer.addWidget(top)

        navigation = QWidget()
        navigation.setObjectName("workspaceNavigation")
        navigation_layout = QHBoxLayout(navigation)
        navigation_layout.setContentsMargins(16, 6, 16, 6)
        navigation_layout.setSpacing(6)
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
            button.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
            button.setAccessibleName(label)
            button.setToolTip({
                "SQL Editor": "Return to the SQL editor",
                "Connections": "Manage and switch MySQL connections",
                "Schema explorer": "Browse databases, tables and views",
                "Query history": "Review opt-in local query history",
                "Saved queries": "Open saved SQL snippets",
            }[label])
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
        self.format_button.setAccessibleName("Format SQL in the current query tab")
        self.format_button.setToolTip("Format the SQL text in the active query tab.")
        self.format_button.clicked.connect(self.format_current_sql)
        self.explain_button = QPushButton("Explain")
        self.explain_button.setAccessibleName("Explain the current SELECT query")
        self.explain_button.setToolTip("Ask MySQL to explain the SELECT query at the cursor.")
        self.explain_button.clicked.connect(self.explain_query)
        self.run_selection_button = QPushButton("Run selection")
        self.run_selection_button.setAccessibleName("Run selected SQL text")
        self.run_selection_button.setToolTip("Execute only the selected SQL text.")
        self.run_selection_button.clicked.connect(lambda: self.execute_current(selection_only=True))
        self.run_button = QPushButton("▶  Run SQL   Ctrl+Enter")
        self.run_button.setObjectName("primaryButton")
        self.run_button.setAccessibleName("Run current SQL statement or selection")
        self.run_button.setAccessibleDescription(
            "Executes selected SQL text, or the statement at the cursor when no text is selected. "
            "Keyboard shortcut: Ctrl+Enter."
        )
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
        self.result_filter.setPlaceholderText("Filter fetched rows…")
        self.result_filter.setAccessibleName("Filter result rows")
        self.result_filter.setAccessibleDescription(
            "Searches all fetched rows for large query results using the local SQLite result cache. "
            "The grid stays memory-bounded and exports keep the full original result."
        )
        self.result_filter.setMaxLength(256)
        self.result_filter.setClearButtonEnabled(True)
        self.result_filter.setMinimumWidth(150)
        self.result_filter.setMaximumWidth(250)
        self.result_filter.setToolTip(
            "Searches all fetched rows for large query results using a disk-backed index; "
            "smaller results are filtered locally. " + RESULT_EXPORT_SEMANTICS
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
        self.fetch_more_button = QPushButton("Fetch +1,000")
        self.fetch_more_button.setObjectName("fetchMoreRowsButton")
        self.fetch_more_button.setAccessibleName("Fetch more result rows from the local result cache")
        self.fetch_more_button.setToolTip(
            "Scroll to the end of the visible rows to load the next page automatically, "
            "or use this button to append up to 1,000 already-fetched rows. SQL is not rerun; "
            "CSV, JSON and NDJSON exports include every fetched row."
        )
        self.fetch_more_button.setEnabled(False)
        self.fetch_more_button.clicked.connect(self.fetch_result_page_manually)
        self.export_button = QPushButton("↓  Export…")
        self.export_button.setAccessibleName("Export fetched result rows")
        self.export_button.setAccessibleDescription(
            "Choose CSV, JSON array, or newline-delimited JSON. " + RESULT_EXPORT_SEMANTICS
        )
        self.export_button.setToolTip(
            "Export all fetched result rows as CSV, JSON, or NDJSON. The current grid sort and filter do not exclude rows."
        )
        self.export_button.clicked.connect(self.export_results)
        toolbar.addWidget(self.results_title)
        toolbar.addWidget(self.result_picker)
        toolbar.addWidget(self.result_filter)
        toolbar.addWidget(self.query_meta, 1)
        toolbar.addWidget(self.stop_button)
        toolbar.addWidget(self.commit_button)
        toolbar.addWidget(self.rollback_button)
        toolbar.addWidget(self.fetch_more_button)
        toolbar.addWidget(self.export_button)
        result_layout.addLayout(toolbar)
        self.result_model = ResultsModel(
            theme=resolve_theme(self._settings.value("ui/theme", "dark", type=str))
        )
        self.result_model.more_rows_requested.connect(self.fetch_more_result_rows)
        self.result_model.previous_rows_requested.connect(self.fetch_previous_result_rows)
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
        self.result_grid.verticalScrollBar().valueChanged.connect(
            self._maybe_fetch_result_page_on_scroll
        )
        self.result_grid.setSortingEnabled(True)
        self.result_grid.horizontalHeader().sortIndicatorChanged.connect(
            self._on_result_sort_indicator_changed
        )
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
        self.export_feedback = QLabel("")
        self.export_feedback.setObjectName("statusSuccess")
        self.export_feedback.setAccessibleName("Result export status")
        self.export_feedback.setAccessibleDescription(
            "Persistent feedback for the most recent result export; errors remain visible until replaced."
        )
        self.export_feedback.setWordWrap(True)
        self.export_feedback.setTextInteractionFlags(
            Qt.TextInteractionFlag.TextSelectableByMouse
            | Qt.TextInteractionFlag.TextSelectableByKeyboard
        )
        self.export_feedback.hide()
        result_layout.addWidget(self.export_feedback)
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

        editor_preferences.addSeparator()
        line_numbers_action = QAction("Show line numbers", self)
        line_numbers_action.setCheckable(True)
        line_numbers_action.setChecked(self._show_editor_line_numbers)
        line_numbers_action.setToolTip("Show or hide the SQL editor line-number gutter.")
        line_numbers_action.toggled.connect(self._set_editor_line_numbers_visible)
        editor_preferences.addAction(line_numbers_action)

        current_line_action = QAction("Highlight current line", self)
        current_line_action.setCheckable(True)
        current_line_action.setChecked(self._highlight_current_line)
        current_line_action.setToolTip(
            "Highlight the active SQL line without hiding bracket matches."
        )
        current_line_action.toggled.connect(self._set_current_line_highlight_enabled)
        editor_preferences.addAction(current_line_action)

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

        updates_menu = settings_menu.addMenu("Updates")
        self.update_checks_action = QAction("Automatically check for updates at startup", self)
        self.update_checks_action.setCheckable(True)
        self.update_checks_action.setChecked(self._update_checks_enabled)
        self.update_checks_action.setToolTip(
            "When enabled, check the latest stable GitHub Release at startup. "
            "Only public release metadata is requested; updates are never downloaded or installed automatically."
        )
        self.update_checks_action.toggled.connect(self._set_update_checks_enabled)
        updates_menu.addAction(self.update_checks_action)

        history_menu = settings_menu.addMenu("Query History")
        history_action = QAction("Enable local query history", self)
        history_action.setCheckable(True)
        history_action.setChecked(self.repository.history_enabled())
        history_action.toggled.connect(self._set_history_enabled)
        history_menu.addAction(history_action)
        self._action(history_menu, "Clear query history", "", self.clear_history)
        help_menu = self.menuBar().addMenu("&Help")
        self._action(help_menu, "Guided tour", "F1", self._show_product_tour)
        self._action(help_menu, "Check for updates…", "", self.check_for_updates)
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
        result_model = getattr(self, "result_model", None)
        if result_model is not None:
            result_model.set_theme(resolved_theme)
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
                editor.set_tab_width(self._editor_tab_width)
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

    def _set_update_checks_enabled(self, enabled: bool) -> None:
        """Persist the explicit opt-in controlling startup update requests."""
        self._update_checks_enabled = bool(enabled)
        self._settings.setValue("updates/automaticCheck", self._update_checks_enabled)
        self._settings.sync()
        if self._update_checks_enabled:
            self.status.setText(
                "Automatic update checks enabled for future startups. "
                "Use Help → Check for updates to check now."
            )
        else:
            self.status.setText("Update checks disabled. No update metadata will be requested on startup.")

    def check_for_updates(self) -> None:
        """Run an on-demand update check only after the user opted in."""
        self._run_update_check(manual=True)

    def _maybe_check_for_updates_on_startup(self) -> None:
        if self._update_checks_enabled:
            self._run_update_check(manual=False)

    def _run_update_check(self, *, manual: bool) -> None:
        # Startup checks are disabled by default. An explicit Help → Check for updates
        # action is a one-time user request and does not change the startup preference.
        if not manual and not self._update_checks_enabled:
            return

        current = self._update_check_thread
        if current is not None and current.isRunning():
            if manual:
                QMessageBox.information(
                    self,
                    "Update check in progress",
                    "A GitHub Releases check is already running. Please wait for it to finish.",
                )
            return

        thread = UpdateCheckThread(parent=self)
        self._update_check_thread = thread
        self._update_check_manual = manual
        thread.result_ready.connect(
            self._on_update_check_result, Qt.ConnectionType.QueuedConnection
        )
        thread.finished.connect(
            self._on_update_check_finished, Qt.ConnectionType.QueuedConnection
        )
        self.status.setText("Checking the latest stable GitHub Release…")
        thread.start()

    def _on_update_check_finished(self) -> None:
        """Release the completed background thread and resume a requested close."""
        thread = self._update_check_thread
        if thread is not None and not thread.isRunning():
            self._update_check_thread = None
            thread.deleteLater()

        if self._close_after_update_check:
            self._close_after_update_check = False
            self._close_after_update_check_approved = True
            self.setEnabled(True)
            QTimer.singleShot(0, self.close)

    def _on_update_check_result(self, result: UpdateCheckResult) -> None:
        """Render update results on the UI thread only."""
        if self._close_after_update_check or self._close_after_update_check_approved:
            return
        manual = self._update_check_manual
        if not manual and not self._update_checks_enabled:
            return

        if result.status == "update_available" and result.release_url:
            self.status.setText(f"MySQL Editor {result.latest_version} is available.")
            message = QMessageBox(self)
            message.setIcon(QMessageBox.Icon.Information)
            message.setWindowTitle("MySQL Editor update available")
            message.setText(f"MySQL Editor {result.latest_version} is available.")
            message.setInformativeText(
                f"Installed version: {result.current_version}\n"
                f"Latest stable release: {result.latest_version}\n\n"
                "Open the official release page to review its notes and download manually. "
                "MySQL Editor will not download or install the update for you."
            )
            open_button = message.addButton(
                "Open release page", QMessageBox.ButtonRole.AcceptRole
            )
            message.addButton("Later", QMessageBox.ButtonRole.RejectRole)
            message.exec()
            if (
                message.clickedButton() is open_button
                and is_safe_release_url(result.release_url)
            ):
                QDesktopServices.openUrl(QUrl(result.release_url))
            return

        if result.status == "up_to_date":
            self.status.setText(
                f"Update check complete · installed {result.current_version}, "
                f"latest stable {result.latest_version}."
            )
            if manual:
                QMessageBox.information(
                    self,
                    "MySQL Editor is up to date",
                    f"Installed version: {result.current_version}\n"
                    f"Latest stable release: {result.latest_version}\n\n"
                    "No newer stable release is available.",
                )
            return

        if result.status == "no_release":
            self.status.setText("No published stable GitHub Release is available yet.")
            if manual:
                QMessageBox.information(
                    self,
                    "No stable release available",
                    "No published stable GitHub Release is available yet. "
                    "You can continue using this build.",
                )
            return

        detail = result.detail or "The update check failed. Try again later."
        self.status.setText("Update check failed. Use Help → Check for updates to retry.")
        if manual:
            QMessageBox.warning(self, "Update check failed", detail)

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
                editor.set_tab_width(self._editor_tab_width)
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
                editor.set_tab_width(self._editor_tab_width)
        self._settings.setValue("ui/editorFontFamily", family)
        self.status.setText(f"SQL editor font family: {family}")

    def _set_editor_tab_width(self, width: int):
        width = normalize_tab_width(width)
        self._editor_tab_width = width
        for index in range(self.editors.count()):
            editor = self.editors.widget(index)
            if isinstance(editor, SqlEditor):
                editor.set_tab_width(width)
        self._settings.setValue("ui/tabWidth", width)
        self.status.setText(f"SQL editor tab width: {width} spaces")

    def _set_editor_line_numbers_visible(self, visible: bool) -> None:
        """Persist and apply the line-number gutter preference to every open query tab."""
        enabled = bool(visible)
        self._show_editor_line_numbers = enabled
        for index in range(self.editors.count()):
            editor = self.editors.widget(index)
            if isinstance(editor, SqlEditor):
                editor.set_line_numbers_visible(enabled)
        self._settings.setValue("ui/showLineNumbers", enabled)
        state = "shown" if enabled else "hidden"
        self.status.setText(f"SQL editor line numbers {state}.")

    def _set_current_line_highlight_enabled(self, enabled: bool) -> None:
        """Persist and apply current-line highlighting to every open query tab."""
        self._highlight_current_line = bool(enabled)
        for index in range(self.editors.count()):
            editor = self.editors.widget(index)
            if isinstance(editor, SqlEditor):
                editor.set_current_line_highlight_enabled(self._highlight_current_line)
        self._settings.setValue("ui/currentLineHighlight", self._highlight_current_line)
        state = "enabled" if self._highlight_current_line else "disabled"
        self.status.setText(f"Current-line highlighting {state}.")

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

    def _mysql_task_pending(self) -> bool:
        """Return whether a connection-bound task is queued or being processed."""
        connection_actions = {
            "query", "schema", "schema_objects", "table_preview", "inspect_schema_object",
            "update_table_cell", "use_schema", "commit", "rollback", "disconnect",
        }
        return any(
            action in connection_actions
            for action, _context in self._jobs.values()
        )

    def _dispatch(self, action: str, payload: dict, context: dict | None = None):
        database_actions = {
            "query", "schema", "schema_objects", "table_preview", "inspect_schema_object",
            "update_table_cell", "use_schema", "commit", "rollback",
        }
        if action in database_actions and (
            not self._connection_available or self._disconnect_pending
        ):
            self.status.setText(
                "SQL not submitted · no active MySQL connection. Use Connect to reconnect."
                if action == "query"
                else "MySQL action not started · connect to a server first."
            )
            if action == "query":
                self.query_meta.setText("Not connected")
            return None
        if action == "disconnect" and self._query_running:
            self._report_query_busy("connection")
            return None
        # Keep a single SQL task active even if another entry point bypasses editor buttons.
        if self._cell_edit_pending and action in database_actions:
            self.status.setText(
                "MySQL action paused · wait for the single-cell update to finish."
            )
            return None
        if action == "query" and self._query_running:
            self._report_query_busy("submit")
            return None
        if action == "update_table_cell" and self._mysql_task_pending():
            self.status.setText(
                "Cell edit paused · another MySQL operation is still queued. Wait for it to finish and retry."
            )
            return None
        job_id = uuid.uuid4().hex
        self._task_sequence_counter += 1
        task_sequence = self._task_sequence_counter
        self._task_sequences[job_id] = task_sequence
        if action == "query":
            self._latest_query_sequence = task_sequence
        self._jobs[job_id] = (action, context or {})
        self.worker.submit(action, payload, job_id)
        if action == "query":
            self._cancellation_requested = False
            self._query_running = True
            self._set_result_controls()
            self.run_button.setEnabled(False)
            self.stop_button.setEnabled(True)
            self.commit_button.setEnabled(False)
            self.rollback_button.setEnabled(False)
            self.query_meta.setText("Queued…")
            self.status.setText("Query queued…")
        elif action in EXPORT_ACTIONS:
            format_name = EXPORT_FORMAT_LABELS[action.removeprefix("export_")]
            self.status.setText(f"{format_name} export queued…")
        elif action == "fetch_result_page":
            self.status.setText("Loading additional rows from the local result cache…")
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
        # Navigation buttons are separate Tab stops, not a radio group. Manage the
        # selected visual state directly so Qt cannot remove Tab focus from siblings.
        for label, button in self.workspace_nav_buttons.items():
            if button.isCheckable():
                button.setChecked(label == destination)

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
            tables_by_schema=self._schema_tables_by_schema,
            columns_by_schema_and_table=self._schema_columns_by_schema_and_table,
        )
        font = editor.font()
        font.setFamily(self._editor_font_family)
        font.setStyleHint(QFont.StyleHint.Monospace)
        font.setPointSize(self._editor_font_size)
        editor.setFont(font)
        editor.set_tab_width(self._editor_tab_width)
        editor.set_line_numbers_visible(self._show_editor_line_numbers)
        editor.set_current_line_highlight_enabled(self._highlight_current_line)
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

    def _result_item_by_id(self, result_id: str | None):
        if not result_id:
            return None
        return next(
            (item for item in self._query_results if item.get("result_id") == result_id),
            None,
        )

    def _result_window_bounds(self, item: dict | None) -> tuple[int, int, int]:
        """Return (window start, window end, result total) for one cached result."""
        if not item:
            return 0, 0, 0
        rows = item.get("rows", [])
        try:
            start = max(0, int(item.get("window_start_offset", 0) or 0))
        except (TypeError, ValueError, OverflowError):
            start = 0
        end = start + len(rows)
        total_key = "view_row_count" if item.get("view_id") else "row_count"
        try:
            total = max(end, int(item.get(total_key, end) or 0))
        except (TypeError, ValueError, OverflowError):
            total = end
        # One sentinel slot lets the bounded model request another source page without
        # claiming that rows not yet fetched already exist in the local SQLite cache.
        if item.get("table_preview") and item.get("preview_has_more") and not item.get("view_id"):
            total = max(total, end) + 1
        return start, end, total

    def _release_result_filter_views(self, items) -> None:
        """Drop materialized full-result filter indexes before result sets are discarded."""
        for item in list(items or []):
            if isinstance(item, dict) and item.get("view_id"):
                self._restore_initial_result_window(item)

    def _restore_initial_result_window(self, item: dict | None) -> None:
        """Restore a result's original preview and release its temporary filtered view."""
        if not isinstance(item, dict):
            return
        view_id = item.pop("view_id", None)
        item.pop("view_query", None)
        item.pop("view_row_count", None)
        item.pop("source_offsets", None)
        item.pop("sort_column", None)
        item.pop("sort_descending", None)
        if view_id:
            self._dispatch(
                "drop_result_filter",
                {"view_id": str(view_id)},
                {"result_id": item.get("result_id"), "view_id": str(view_id)},
            )
        if "initial_rows" not in item:
            return
        initial = item.pop("initial_rows")
        item["rows"] = [list(row) for row in initial]
        item["window_start_offset"] = 0
        try:
            total = max(len(item["rows"]), int(item.get("row_count", len(item["rows"])) or 0))
        except (TypeError, ValueError, OverflowError):
            total = len(item["rows"])
        item["preview_truncated"] = len(item["rows"]) < total

    def _set_result_controls(self):
        item = self._result_item_by_id(self._current_result_id)
        self.export_button.setEnabled(
            bool(self._current_result_id) and not bool(item and item.get("export_unavailable"))
        )
        start, end, total = self._result_window_bounds(item)
        is_row_result = bool(item and str(item.get("kind", "")).casefold() == "rows")
        has_more = bool(
            is_row_result
            and end < total
            and not item.get("page_load_unavailable")
        )
        has_previous = bool(
            is_row_result
            and start > 0
            and not item.get("page_load_unavailable")
        )
        current_view_pending = (
            self._pending_spool_filter is not None
            and self._pending_spool_filter.get("result_id") == self._current_result_id
            and self._pending_spool_filter.get("generation") == self._filter_generation
        )
        current_view_running = (
            self._spool_filter_request is not None
            and self._spool_filter_request.get("result_id") == self._current_result_id
            and self._spool_filter_request.get("generation") == self._filter_generation
        )
        view_pending = current_view_pending or current_view_running
        pending = self._result_page_load_pending is not None or view_pending
        if view_pending:
            request = self._pending_spool_filter or self._spool_filter_request or {}
            if request.get("operation") == "sort" or request.get("action") == "sort_result_spool":
                self.fetch_more_button.setText("Sorting…")
                self.fetch_more_button.setToolTip(
                    "Sorting every row in the local SQLite result view. The active grid remains bounded."
                )
            elif request.get("sort_column") is not None:
                self.fetch_more_button.setText("Filtering + sorting…")
                self.fetch_more_button.setToolTip(
                    "Filtering all fetched rows and sorting matching rows in the local SQLite cache. "
                    "The active grid remains bounded."
                )
            else:
                self.fetch_more_button.setText("Filtering…")
                self.fetch_more_button.setToolTip(
                    "Searching the full result in the local SQLite cache. The active grid remains bounded."
                )
            self.fetch_more_button.setEnabled(False)
        elif pending:
            self.fetch_more_button.setText("Loading…")
            pending_action = (self._result_page_load_pending or {}).get("action")
            self.fetch_more_button.setToolTip(
                "Loading another bounded page from the MySQL table preview."
                if pending_action == "table_preview_page"
                else "Loading a page from the local result cache. SQL is not rerun."
            )
            self.fetch_more_button.setEnabled(False)
        elif self._query_running and (has_more or has_previous):
            self.fetch_more_button.setText("Query Running…")
            self.fetch_more_button.setToolTip(
                "Cached result paging is paused until the active SQL operation completes."
            )
            self.fetch_more_button.setEnabled(False)
        elif has_previous and (
            not has_more or self.result_grid.verticalScrollBar().maximum() <= 0
        ):
            earlier_count = min(RESULT_PAGE_ROWS, start)
            self.fetch_more_button.setText(f"Fetch Earlier {earlier_count:,}")
            self.fetch_more_button.setToolTip(
                f"Load rows {max(1, start - earlier_count + 1):,}–{start:,} "
                "from the local SQLite result cache. This is useful when a filter leaves "
                "too few rows to scroll the grid. The full result remains in the spool."
            )
            self.fetch_more_button.setEnabled(True)
        elif (
            item
            and item.get("table_preview")
            and not item.get("view_id")
            and item.get("preview_has_more")
            and end >= int(item.get("preview_loaded_count", item.get("row_count", 0)) or 0)
        ):
            self.fetch_more_button.setText("Fetch Next Preview Page")
            self.fetch_more_button.setToolTip(
                "Read up to 1,000 additional rows from MySQL in primary-key order. "
                "The preview remains bounded in memory and keeps cell-edit metadata aligned with visible rows."
            )
            self.fetch_more_button.setEnabled(not self._query_running)
        elif has_more:
            next_count = min(RESULT_PAGE_ROWS, total - end)
            self.fetch_more_button.setText(f"Fetch +{next_count:,}")
            self.fetch_more_button.setToolTip(
                f"Load rows {end + 1:,}–{min(total, end + next_count):,} from the local SQLite result cache. "
                "Scroll to the grid's bottom for the next page or to the top for earlier rows. "
                "The active grid window is capped at 5,000 rows; one initial-page recovery snapshot may be retained while paging. Exports use the full result spool."
            )
            self.fetch_more_button.setEnabled(True)
        elif has_previous:
            earlier_count = min(RESULT_PAGE_ROWS, start)
            self.fetch_more_button.setText(f"Fetch Earlier {earlier_count:,}")
            self.fetch_more_button.setToolTip(
                "Load earlier rows from the local SQLite result cache without rerunning SQL."
            )
            self.fetch_more_button.setEnabled(True)
        elif is_row_result and not item.get("page_load_unavailable"):
            self.fetch_more_button.setText("All Rows Loaded")
            self.fetch_more_button.setToolTip(
                "The full result is already available in the local SQLite spool. "
                "Only the current row window is retained in grid memory; exports include every row."
            )
            self.fetch_more_button.setEnabled(False)
        elif item and item.get("page_load_unavailable"):
            self.fetch_more_button.setText("Fetch Unavailable")
            self.fetch_more_button.setToolTip(
                "The local result cache could not supply more rows. Run the query again to rebuild it."
            )
            self.fetch_more_button.setEnabled(False)
        else:
            self.fetch_more_button.setText("Fetch +1,000")
            self.fetch_more_button.setToolTip(
                "Load another page from the local result cache when a result contains more than the displayed rows."
            )
            self.fetch_more_button.setEnabled(False)

    def fetch_result_page_manually(self) -> None:
        """Choose a direction for a manual page request when scrolling cannot expose it."""
        item = self._result_item_by_id(self._current_result_id)
        start, end, total = self._result_window_bounds(item)
        scrollbar = self.result_grid.verticalScrollBar()
        if start > 0 and (end >= total or scrollbar.maximum() <= 0):
            self.fetch_previous_result_rows()
            return
        self.fetch_more_result_rows()

    def fetch_more_result_rows(self) -> None:
        """Append a local result page or safely fetch another Schema Explorer source page."""
        if self._query_running:
            self.result_model.set_paging_state(pending=False)
            return
        if self._result_page_load_pending is not None:
            if self._result_page_load_pending.get("result_id") != self._current_result_id:
                self.result_model.set_paging_state(pending=False, available=False)
            return
        result_id = self._current_result_id
        item = self._result_item_by_id(result_id)
        if not item or str(item.get("kind", "")).casefold() != "rows":
            self.result_model.set_paging_state(pending=False, available=False)
            self._set_result_controls()
            return
        _start, offset, total = self._result_window_bounds(item)
        if offset >= total:
            self.result_model.set_paging_state(pending=False)
            self._set_result_controls()
            return
        if item.get("page_load_unavailable"):
            self.result_model.set_paging_state(pending=False, available=False)
            self._set_result_controls()
            return

        item.setdefault("initial_rows", [list(row) for row in item.get("rows", [])])
        loaded_count = max(0, int(item.get("preview_loaded_count", item.get("row_count", 0)) or 0))
        has_connected_preview = (
            item.get("table_preview")
            and item.get("preview_stable_order")
            and not item.get("view_id")
            and self._connection_available
            and not self._disconnect_pending
        )
        if has_connected_preview:
            direction = "next" if offset >= loaded_count else "cached"
            action = "table_preview_page"
            payload = {
                "result_id": result_id,
                "offset": offset,
                "limit": RESULT_PAGE_ROWS,
                "direction": direction,
            }
            context = {
                "result_id": result_id,
                "offset": offset,
                # Model direction describes the active window; cached source re-reads
                # still append rows when the user scrolls down within the loaded range.
                "direction": "next",
                "page_action": action,
            }
        else:
            action = "fetch_result_page"
            payload = {"result_id": result_id, "offset": offset, "limit": RESULT_PAGE_ROWS}
            context = {"result_id": result_id, "offset": offset, "direction": "next"}
            if item.get("view_id"):
                payload["view_id"] = str(item["view_id"])
                context["view_id"] = str(item["view_id"])

        job_id = self._dispatch(action, payload, context)
        if job_id:
            self._result_page_load_pending = {
                "job_id": job_id,
                "result_id": result_id,
                "offset": offset,
                "direction": "next",
                "action": action,
            }
            self.result_model.set_paging_state(pending=True)
            self._set_result_controls()
        else:
            item["page_load_unavailable"] = True
            self.result_model.set_paging_state(pending=False, available=False)
            self._set_result_controls()

    def fetch_previous_result_rows(self) -> None:
        """Load an earlier page from MySQL or the local spool without rerunning SQL."""
        if self._query_running or self._result_page_load_pending is not None:
            return
        result_id = self._current_result_id
        item = self._result_item_by_id(result_id)
        if (
            not item
            or str(item.get("kind", "")).casefold() != "rows"
            or item.get("page_load_unavailable")
            or not self.result_model.canFetchPrevious()
        ):
            return
        start, _end, _total = self._result_window_bounds(item)
        offset = max(0, start - RESULT_PAGE_ROWS)
        limit = start - offset
        if limit <= 0:
            return
        item.setdefault("initial_rows", [list(row) for row in item.get("rows", [])])
        has_connected_preview = (
            item.get("table_preview")
            and item.get("preview_stable_order")
            and not item.get("view_id")
            and self._connection_available
            and not self._disconnect_pending
        )
        if has_connected_preview:
            action = "table_preview_page"
            payload = {
                "result_id": result_id,
                "offset": offset,
                "limit": limit,
                "direction": "previous",
            }
            context = {
                "result_id": result_id,
                "offset": offset,
                "direction": "previous",
                "expected_end": start,
                "page_action": action,
            }
        else:
            action = "fetch_result_page"
            payload = {"result_id": result_id, "offset": offset, "limit": limit}
            context = {
                "result_id": result_id,
                "offset": offset,
                "direction": "previous",
                "expected_end": start,
            }
            if item.get("view_id"):
                payload["view_id"] = str(item["view_id"])
                context["view_id"] = str(item["view_id"])
            if item.get("table_preview") and isinstance(item.get("table_edit"), dict):
                item["table_edit"]["enabled"] = False
                item["table_edit"]["reason"] = (
                    "This cached preview page was reloaded while MySQL was disconnected; "
                    "refresh the preview before editing."
                )
        job_id = self._dispatch(action, payload, context)
        if job_id:
            self._result_page_load_pending = {
                "job_id": job_id,
                "result_id": result_id,
                "offset": offset,
                "direction": "previous",
                "expected_end": start,
                "action": action,
            }
            self.result_model.set_paging_state(pending=True)
            self._set_result_controls()
        else:
            item["page_load_unavailable"] = True
            self.result_model.set_paging_state(pending=False, available=False)
            self._set_result_controls()

    def _maybe_fetch_result_page_on_scroll(self, value: int) -> None:
        """Load cached pages in either direction when the visible window reaches an edge."""
        if self._query_running or self._result_page_load_pending is not None:
            return
        scrollbar = self.result_grid.verticalScrollBar()
        maximum = scrollbar.maximum()
        if value <= 0 and self.result_model.canFetchPrevious():
            self.result_model.fetchPrevious()
            return
        if maximum > 0 and value >= maximum and self.result_proxy.canFetchMore(QModelIndex()):
            self.result_proxy.fetchMore(QModelIndex())

    def _query_for_run(self, selection_only=False, whole_script=False):
        editor = self._current_editor()
        if not editor:
            return ""
        cursor = editor.textCursor()
        if selection_only and cursor.hasSelection():
            return cursor.selectedText().replace("\u2029", "\n")
        if whole_script:
            return editor.toPlainText()
        return current_statement_source(editor.toPlainText(), cursor.position())

    def execute_current(self, selection_only: bool = False):
        try:
            sql = self._query_for_run(selection_only=selection_only)
        except ScriptParseError as exc:
            self._report_script_parse_error(exc)
            return
        self._execute_sql(sql)

    def execute_script(self):
        self._execute_sql(self._query_for_run(whole_script=True))

    def _report_script_parse_error(self, error: ScriptParseError) -> None:
        self.status.setText("SQL not submitted · script parsing failed.")
        QMessageBox.warning(self, "SQL script parsing failed", str(error))

    def _execute_sql(self, sql: str, additional_context: dict | None = None):
        if self._query_running:
            self._report_query_busy("submit")
            return
        try:
            statements = split_sql_statements(sql)
        except ScriptParseError as exc:
            self._report_script_parse_error(exc)
            return
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
        query_context = {
            "sql": sql,
            "profile_name": self.profile.get("name", "Connection"),
        }
        query_context.update(additional_context or {})
        # The history entry records the exact EXPLAIN request submitted to MySQL.
        query_context["sql"] = sql
        self._dispatch("query", {"sql": sql}, query_context)
        self._set_result_message(
            "SQL is queued for the database worker. The editor remains responsive."
        )
        self.status.setText("Query queued…")

    def explain_query(self):
        editor = self._current_editor()
        if not editor:
            return
        try:
            sql = current_statement(editor.toPlainText(), editor.textCursor().position()).strip()
        except ScriptParseError as exc:
            self._report_script_parse_error(exc)
            return
        if not sql:
            QMessageBox.information(self, "Explain SELECT", "Place the cursor inside a SELECT statement.")
            return
        if not sql.lstrip().upper().startswith("SELECT"):
            QMessageBox.warning(self, "Explain SELECT", "EXPLAIN is offered for SELECT statements.")
            return
        self._execute_sql(
            "EXPLAIN FORMAT=JSON " + sql,
            additional_context={"explain_plan": True, "explained_sql": sql},
        )

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
            QMessageBox.warning(self, "SQL formatting", sanitize_error_message(exc))
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
        if not self._connection_available or self._disconnect_pending:
            self.schema_state_label.setText(
                "No active MySQL connection. Connect to a server to browse schema metadata."
            )
            self.status.setText("Schema refresh unavailable · connect to MySQL first.")
            self.schema_refresh_button.setEnabled(False)
            return
        schema = str(self.config.get("default_schema", "") or self.connect_result.get("database", ""))
        self._schema_request_id = None
        self._schema_expansion_requests.clear()
        self._schema_expand_items.clear()
        self.schema_tree.clear()
        self._schema_databases.clear()
        self._schema_tables.clear()
        self._schema_columns_by_table.clear()
        self._schema_tables_by_schema.clear()
        self._schema_columns_by_schema_and_table.clear()
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
        if self._active_schema_name:
            self._schema_tables_by_schema[self._active_schema_name] = set(self._schema_tables)
            self._schema_columns_by_schema_and_table[self._active_schema_name] = {
                table: list(columns)
                for table, columns in self._schema_columns_by_table.items()
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
            retry.setToolTip(0, sanitize_error_message(result.get("error"), fallback=""))
            item.addChild(retry)
            detail = sanitize_error_message(result.get("error"), fallback="")
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
        self._schema_tables_by_schema[schema] = {
            str(record.get("name", "") or "")
            for record in result.get("objects", [])
            if str(record.get("name", "") or "")
        }
        self._schema_columns_by_schema_and_table[schema] = {
            str(table): [str(column) for column in columns]
            for table, columns in (result.get("columns_by_table") or {}).items()
        }
        self._update_all_editor_completions()
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
                    tables_by_schema=self._schema_tables_by_schema,
                    columns_by_schema_and_table=self._schema_columns_by_schema_and_table,
                )

    def _set_result_completion_words(self, headers) -> None:
        self._result_completion_words = {str(header) for header in headers}
        self._update_all_editor_completions()

    def _schedule_spool_view_request(self, request: dict) -> None:
        """Queue one generation-checked filter/sort request behind active spool work."""
        pending = dict(request)
        self._pending_spool_filter = pending
        self.result_proxy.setFilterFixedString("")
        self.result_model.set_paging_state(pending=True)
        item = self._result_item_by_id(pending.get("result_id"))
        source_total = max(
            0, int((item or {}).get("row_count", len((item or {}).get("rows", []))) or 0)
        )
        query = str(pending.get("query") or "")
        if pending.get("operation") == "sort":
            column = max(0, int(pending.get("sort_column", 0) or 0))
            direction = "descending" if pending.get("sort_descending") else "ascending"
            self.query_meta.setText(f"Sorting {source_total:,} fetched row(s)…")
            self._set_result_message(
                f"Sorting the full local result by column {column + 1} ({direction}). "
                f"Exports retain all {source_total:,} original fetched row(s) in MySQL fetch order."
            )
            self.status.setText("Sorting the full result · preparing the disk-backed row order…")
        else:
            self.query_meta.setText(f"Searching {source_total:,} fetched row(s)…")
            if pending.get("sort_column") is not None:
                self._set_result_message(
                    f"Filtering the full local result for {query!r} and preserving the selected full-result sort. "
                    f"All {source_total:,} fetched row(s) remain in the export set."
                )
                self.status.setText(
                    f"Filtering and sorting the full result · scanning {source_total:,} cached row(s)…"
                )
            else:
                self._set_result_message(
                    f"Searching the full local result for {query!r}. "
                    f"All {source_total:,} fetched row(s) remain in the export set."
                )
                self.status.setText(
                    f"Filtering the full result · scanning {source_total:,} cached row(s)…"
                )
        self._set_result_controls()
        self._filter_debounce_timer.start(0)

    def _filter_results(self, value: str) -> None:
        query = str(value or "").strip()
        item = self._result_item_by_id(self._current_result_id)
        queued_view_request = self._pending_spool_filter
        if (
            queued_view_request is not None
            and queued_view_request.get("generation") == self._filter_generation
            and queued_view_request.get("result_id") == self._current_result_id
            and queued_view_request.get("query") == query
        ):
            # Paging completion calls _filter_results again for the current text.
            # Do not invalidate a queued global filter/sort as a side effect.
            self.result_proxy.setFilterFixedString("")
            if item is not None and item.get("view_id") and str(item.get("view_query") or "") == query:
                self._set_spool_filter_message(item)
            self.result_model.set_paging_state(pending=True)
            self._filter_debounce_timer.start(0)
            self._set_result_controls()
            return

        self._filter_generation += 1
        generation = self._filter_generation
        self._filter_debounce_timer.stop()

        if item is None:
            self._pending_spool_filter = None
            self.result_proxy.setFilterFixedString(query)
            return

        if not query:
            self._pending_spool_filter = None
            self.result_proxy.setFilterFixedString("")
            view_query = str(item.get("view_query") or "")
            sort_column = item.get("sort_column")
            if view_query and sort_column is not None:
                # Clearing a filter should restore the full result in its selected global
                # sort order, rather than discard the sort or expose a window-only order.
                self._schedule_spool_view_request({
                    "generation": generation,
                    "result_id": str(item.get("result_id") or ""),
                    "query": "",
                    "operation": "sort",
                    "sort_column": int(sort_column),
                    "sort_descending": bool(item.get("sort_descending", False)),
                    "base_view_id": None,
                    "previous_sort_column": int(sort_column),
                    "previous_sort_descending": bool(item.get("sort_descending", False)),
                })
                return
            if item.get("view_id") and view_query:
                self._restore_initial_result_window(item)
                headers = item.get("headers", [])
                rows = item.get("rows", [])
                try:
                    source_total = max(
                        len(rows),
                        int(item.get("row_count", len(rows)) or 0),
                    )
                except (TypeError, ValueError, OverflowError):
                    source_total = len(rows)
                self.result_model.update(
                    headers, rows, base_offset=0, total_rows=source_total
                )
                item["rows"] = self.result_model.rows
                item.pop("source_offsets", None)
                item["window_start_offset"] = 0
                item["preview_truncated"] = len(rows) < source_total
                self.result_model.set_paging_state(
                    total_rows=source_total,
                    pending=self._result_page_load_pending is not None,
                    available=not bool(item.get("page_load_unavailable")),
                )
                self._result_fetched_row_count = source_total
                self.query_meta.setText(f"{source_total:,} row(s) fetched")
                self._set_result_message(result_summary_message(item, len(rows), source_total))
                self._size_result_columns(headers, rows)
                self._set_result_controls()
            elif item.get("sort_column") is not None and not item.get("view_id"):
                # A sort may be queued while an earlier filter request is in flight.
                # Clearing that filter invalidates its result and keeps the chosen sort.
                self._schedule_spool_view_request({
                    "generation": generation,
                    "result_id": str(item.get("result_id") or ""),
                    "query": "",
                    "operation": "sort",
                    "sort_column": int(item["sort_column"]),
                    "sort_descending": bool(item.get("sort_descending", False)),
                    "base_view_id": None,
                })
                return
            elif item.get("view_id") and not view_query:
                # This is already a sorted whole-result view. Clearing an empty filter
                # must not discard its materialized sort index.
                self.result_model.set_paging_state(
                    pending=self._result_page_load_pending is not None
                )
                total = max(0, int(item.get("view_row_count", item.get("row_count", 0)) or 0))
                start = max(0, int(item.get("window_start_offset", 0) or 0))
                self.query_meta.setText(
                    f"{total:,} row(s) sorted by column {int(item.get('sort_column', 0)) + 1}"
                )
                self._set_result_message(
                    result_window_message(item, start, len(item.get("rows", [])), total)
                )
                self._set_result_controls()
            else:
                self.result_model.set_paging_state(
                    pending=self._result_page_load_pending is not None
                )
                self.result_message.setText(self._result_base_message)
                self._set_result_controls()
            return

        if item.get("view_id") and str(item.get("view_query") or "") == query:
            # The current window is already the complete result of this spool-backed
            # query; do not scan the full result again when paging updates the message.
            self.result_proxy.setFilterFixedString("")
            self._set_spool_filter_message(item)
            return

        if len(query) > 256:
            # Keep the displayed query and the debounced request identical.
            query = query[:256]
            if self.result_filter.text() != query:
                self.result_filter.setText(query)
                return

        original_rows = item.get("initial_rows", item.get("rows", []))
        try:
            source_total = max(
                len(original_rows),
                int(item.get("row_count", len(original_rows)) or 0),
            )
        except (TypeError, ValueError, OverflowError):
            source_total = len(original_rows)
        supports_spool_filter = (
            str(item.get("kind", "")).casefold() == "rows"
            and not bool(item.get("table_edit"))
            and (bool(item.get("view_id")) or source_total > len(original_rows))
        )

        if not supports_spool_filter:
            self._pending_spool_filter = None
            self.result_model.set_paging_state(pending=False)
            self.result_proxy.setFilterFixedString(query)
            visible_rows = self.result_proxy.rowCount()
            self.result_message.setText(
                result_filter_message(
                    query, visible_rows, len(self.result_model.rows), source_total
                )
            )
            return

        # Preserve one original preview for clearing the filter, and keep only a
        # bounded number of rows in the grid while the worker indexes all matches.
        item.setdefault("initial_rows", [list(row) for row in item.get("rows", [])])
        request = {
            "generation": generation,
            "result_id": str(item.get("result_id") or ""),
            "query": query,
            "operation": "filter",
        }
        if item.get("sort_column") is not None:
            request["sort_column"] = int(item["sort_column"])
            request["sort_descending"] = bool(item.get("sort_descending", False))
        self._schedule_spool_view_request(request)

    def _dispatch_spool_filter(self) -> None:
        """Dispatch one debounced filter/sort view operation at a time."""
        pending = self._pending_spool_filter
        if pending is None:
            return
        if (
            pending.get("generation") != self._filter_generation
            or pending.get("result_id") != self._current_result_id
            or pending.get("query") != self.result_filter.text().strip()
        ):
            self._pending_spool_filter = None
            self._set_result_controls()
            return
        if self._spool_filter_request is not None or self._result_page_load_pending is not None:
            self._filter_debounce_timer.start(120)
            return
        item = self._result_item_by_id(pending["result_id"])
        if item is None:
            self._pending_spool_filter = None
            self.result_model.set_paging_state(pending=False)
            self._set_result_controls()
            return

        self._pending_spool_filter = None
        operation = str(pending.get("operation") or "filter")
        if operation == "sort":
            action = "sort_result_spool"
            payload = {
                "result_id": pending["result_id"],
                "column": pending.get("sort_column", 0),
                "descending": bool(pending.get("sort_descending", False)),
                "base_view_id": pending.get("base_view_id"),
                "limit": RESULT_PAGE_ROWS,
            }
        else:
            action = "filter_result_spool"
            payload = {
                "result_id": pending["result_id"],
                "query": pending["query"],
                "limit": RESULT_PAGE_ROWS,
            }
            if pending.get("sort_column") is not None:
                payload["sort_column"] = int(pending["sort_column"])
                payload["sort_descending"] = bool(pending.get("sort_descending", False))
        job_id = self._dispatch(action, payload, dict(pending))
        if job_id:
            self._spool_filter_request = {**pending, "job_id": job_id, "action": action}
            self.result_model.set_paging_state(pending=True)
        else:
            self.result_model.set_paging_state(pending=False)
            if operation == "sort":
                self.status.setText("Full-result sort did not start. The current result view remains available.")
                self.result_message.setText(
                    "The full result could not be sorted. The loaded grid window is still available; "
                    "exports keep the original MySQL fetch order."
                )
            else:
                self.status.setText(
                    "Full-result filter did not start. Retry the search or clear the filter."
                )
                self.result_message.setText(
                    "The full result could not be searched. The current grid remains available; "
                    "exports still include all fetched rows."
                )
        self._set_result_controls()

    def _on_result_sort_indicator_changed(self, column: int, order: Qt.SortOrder) -> None:
        """Sort all fetched rows for spooled query results; keep small/preview sorts local."""
        item = self._result_item_by_id(self._current_result_id)
        if (
            item is None
            or str(item.get("kind", "")).casefold() != "rows"
            or bool(item.get("table_edit"))
            or not str(item.get("result_id") or "").strip()
        ):
            return
        original_rows = item.get("initial_rows", item.get("rows", []))
        try:
            source_total = max(
                len(original_rows), int(item.get("row_count", len(original_rows)) or 0)
            )
        except (TypeError, ValueError, OverflowError):
            source_total = len(original_rows)
        if not item.get("view_id") and source_total <= len(original_rows):
            return

        try:
            sort_column = int(column)
        except (TypeError, ValueError, OverflowError):
            return
        if not 0 <= sort_column < len(item.get("headers", [])):
            return
        descending = order == Qt.SortOrder.DescendingOrder
        previous_sort_column = item.get("sort_column")
        previous_sort_descending = bool(item.get("sort_descending", False))
        item["sort_column"] = sort_column
        item["sort_descending"] = descending
        self._filter_generation += 1
        generation = self._filter_generation
        query = self.result_filter.text().strip()
        view_id = str(item.get("view_id") or "")
        view_query = str(item.get("view_query") or "")
        if query and view_id and view_query == query:
            request = {
                "generation": generation,
                "result_id": str(item.get("result_id") or ""),
                "query": query,
                "operation": "sort",
                "sort_column": sort_column,
                "sort_descending": descending,
                "base_view_id": view_id,
            }
        elif query:
            # Compose a new full-result filter with this sort in the same worker request;
            # scanning the source spool prevents a prior filter from narrowing the query.
            request = {
                "generation": generation,
                "result_id": str(item.get("result_id") or ""),
                "query": query,
                "operation": "filter",
                "sort_column": sort_column,
                "sort_descending": descending,
            }
        else:
            request = {
                "generation": generation,
                "result_id": str(item.get("result_id") or ""),
                "query": "",
                "operation": "sort",
                "sort_column": sort_column,
                "sort_descending": descending,
                "base_view_id": None,
            }
        request["previous_sort_column"] = previous_sort_column
        request["previous_sort_descending"] = previous_sort_descending
        self._schedule_spool_view_request(request)


    def _set_spool_filter_message(self, item: dict) -> None:
        query = str(item.get("view_query") or "")
        try:
            source_total = max(0, int(item.get("row_count", 0) or 0))
            matched_total = max(0, int(item.get("view_row_count", 0) or 0))
        except (TypeError, ValueError, OverflowError):
            source_total = 0
            matched_total = 0
        if matched_total == 0:
            message = (
                f"No fetched rows match {query!r}. Searched all {source_total:,} result row(s). "
                f"Exports still include all {source_total:,} original row(s)."
            )
        else:
            message = (
                f"Full-result filter: {matched_total:,} of {source_total:,} fetched row(s) match "
                f"{query!r}. The grid is a bounded matching window; exports still include all "
                f"{source_total:,} original row(s)."
            )
        self._set_result_message(message)

    def _handle_spool_sort_completed(
        self, job_id: str, result: dict, context: dict
    ) -> None:
        """Install a completed globally sorted view only when its request is still current."""
        request = self._spool_filter_request
        view_id = str(result.get("view_id") or "")
        if request is None or request.get("job_id") != job_id:
            if view_id:
                self._dispatch("drop_result_filter", {"view_id": view_id}, {"view_id": view_id})
            return
        self._spool_filter_request = None
        generation = request.get("generation")
        result_id = str(request.get("result_id") or "")
        query = str(request.get("query") or "")
        is_current = (
            generation == self._filter_generation
            and result_id == self._current_result_id
            and query == self.result_filter.text().strip()
        )
        item = self._result_item_by_id(result_id)
        if not is_current or item is None:
            if view_id:
                self._dispatch("drop_result_filter", {"view_id": view_id}, {"view_id": view_id})
            if self._pending_spool_filter is not None:
                QTimer.singleShot(0, self._dispatch_spool_filter)
            self._set_result_controls()
            return

        if not result.get("ok") or not view_id:
            # Keep the prior view intact if a replacement could not be built. Restore
            # its committed sort metadata rather than claiming a global sort succeeded.
            previous_column = request.get("previous_sort_column")
            previous_descending = request.get("previous_sort_descending")
            if previous_column is None:
                item.pop("sort_column", None)
                item.pop("sort_descending", None)
            else:
                item["sort_column"] = previous_column
                item["sort_descending"] = bool(previous_descending)
            self.result_model.set_paging_state(
                pending=False, available=not bool(item.get("page_load_unavailable"))
            )
            header = self.result_grid.horizontalHeader()
            header.blockSignals(True)
            try:
                if previous_column is None:
                    header.setSortIndicator(-1, Qt.SortOrder.AscendingOrder)
                    self.result_proxy.sort(-1, Qt.SortOrder.AscendingOrder)
                else:
                    restored_column = int(previous_column)
                    restored_order = (
                        Qt.SortOrder.DescendingOrder
                        if bool(previous_descending)
                        else Qt.SortOrder.AscendingOrder
                    )
                    header.setSortIndicator(restored_column, restored_order)
                    self.result_proxy.sort(restored_column, restored_order)
            finally:
                header.blockSignals(False)
            detail = sanitize_error_message(
                result.get("error"),
                fallback="The full local result could not be sorted.",
            )
            self.status.setText("Full-result sort failed · the existing view remains available.")
            self._set_result_message(
                f"Full-result sort failed: {detail} The current grid view remains available; "
                "exports keep all original rows in MySQL fetch order."
            )
            self._set_result_controls()
            return

        old_view_id = str(item.get("view_id") or "")
        item.setdefault("initial_rows", [list(row) for row in item.get("rows", [])])
        headers = item.get("headers", [])
        rows = [list(row) for row in (result.get("rows") or [])]
        try:
            source_total = max(
                0, int(result.get("source_row_count", item.get("row_count", 0)) or 0)
            )
            view_total = max(0, int(result.get("row_count", source_total) or 0))
            source_offsets = [int(value) for value in (result.get("source_offsets") or [])]
            sort_column = int(request.get("sort_column", result.get("sort_column", 0)))
        except (TypeError, ValueError, OverflowError):
            self._dispatch("drop_result_filter", {"view_id": view_id}, {"view_id": view_id})
            self.result_model.set_paging_state(pending=False)
            self.status.setText("Full-result sort returned invalid row metadata.")
            self._set_result_controls()
            return
        if len(source_offsets) != len(rows) or len(rows) > ResultsModel.MAX_RETAINED_ROWS:
            self._dispatch("drop_result_filter", {"view_id": view_id}, {"view_id": view_id})
            self.result_model.set_paging_state(pending=False)
            self.status.setText("Full-result sort returned an invalid result page.")
            self._set_result_controls()
            return

        descending = bool(request.get("sort_descending", result.get("sort_descending", False)))
        item["view_id"] = view_id
        item["view_query"] = query
        item["view_row_count"] = view_total
        item["row_count"] = source_total
        item["window_start_offset"] = 0
        item["rows"] = rows
        item["source_offsets"] = source_offsets
        item["sort_column"] = sort_column
        item["sort_descending"] = descending
        item["preview_truncated"] = view_total > len(rows)
        item.pop("page_load_unavailable", None)
        self.result_proxy.setFilterFixedString("")
        self.result_model.update(
            headers,
            rows,
            base_offset=0,
            source_offsets=source_offsets,
            total_rows=view_total,
        )
        item["rows"] = self.result_model.rows
        item["source_offsets"] = list(self.result_model._row_offsets)
        self.result_model.set_paging_state(
            total_rows=view_total, pending=False, available=True
        )
        self._result_fetched_row_count = source_total
        column_name = (
            str(headers[sort_column])
            if 0 <= sort_column < len(headers) else f"column {sort_column + 1}"
        )
        if query:
            self.query_meta.setText(
                f"{view_total:,} match(es) · {source_total:,} fetched row(s)"
            )
            self._set_spool_filter_message(item)
        else:
            direction = "descending" if descending else "ascending"
            self.query_meta.setText(
                f"{view_total:,} row(s) sorted by {column_name} ({direction})"
            )
            self._set_result_message(
                result_window_message(item, 0, len(rows), view_total)
            )
        start, end, total = self._result_window_bounds(item)
        self.status.setText(
            f"Full-result sort ready · {start + 1:,}–{end:,} of {total:,} view row(s); "
            "source row numbers are preserved and exports remain in original MySQL fetch order."
        )
        self._set_result_controls()
        if old_view_id and old_view_id != view_id:
            self._dispatch(
                "drop_result_filter",
                {"view_id": old_view_id},
                {"view_id": old_view_id},
            )

    def _handle_spool_filter_completed(
        self, job_id: str, result: dict, context: dict
    ) -> None:
        request = self._spool_filter_request
        view_id = str(result.get("view_id") or "")
        if request is None or request.get("job_id") != job_id:
            if view_id:
                self._dispatch("drop_result_filter", {"view_id": view_id}, {"view_id": view_id})
            return
        self._spool_filter_request = None
        generation = request.get("generation")
        result_id = str(request.get("result_id") or "")
        query = str(request.get("query") or "")
        is_current = (
            generation == self._filter_generation
            and result_id == self._current_result_id
            and query == self.result_filter.text().strip()
        )
        item = self._result_item_by_id(result_id)
        if not is_current or item is None:
            if view_id:
                self._dispatch("drop_result_filter", {"view_id": view_id}, {"view_id": view_id})
            if self._pending_spool_filter is not None:
                QTimer.singleShot(0, self._dispatch_spool_filter)
            self._set_result_controls()
            return

        if not result.get("ok"):
            self._restore_initial_result_window(item)
            headers = item.get("headers", [])
            rows = item.get("rows", [])
            try:
                source_total = max(
                    len(rows), int(item.get("row_count", len(rows)) or 0)
                )
            except (TypeError, ValueError, OverflowError):
                source_total = len(rows)
            self.result_model.update(headers, rows, base_offset=0, total_rows=source_total)
            item["rows"] = self.result_model.rows
            self.result_model.set_paging_state(
                total_rows=source_total, pending=False,
                available=not bool(item.get("page_load_unavailable")),
            )
            self.result_proxy.setFilterFixedString(query)
            self._result_fetched_row_count = source_total
            self.query_meta.setText(f"{source_total:,} row(s) fetched · full filter unavailable")
            detail = sanitize_error_message(
                result.get("error"),
                fallback="The full local result could not be searched.",
            )
            visible = self.result_proxy.rowCount()
            self._set_result_message(
                f"Full-result filter failed: {detail} "
                f"Showing matches in the loaded window only ({visible:,} of {len(rows):,} row(s)); "
                f"exports still include all {source_total:,} fetched row(s)."
            )
            self.status.setText("Full-result filter failed · only the loaded window is filtered.")
            self._set_result_controls()
            return

        if not view_id:
            self.result_model.set_paging_state(pending=False)
            self.status.setText("Full-result filter returned no usable view. Clear and retry the filter.")
            self._set_result_controls()
            return

        old_view_id = str(item.get("view_id") or "")
        item.setdefault("initial_rows", [list(row) for row in item.get("rows", [])])
        headers = item.get("headers", [])
        rows = [list(row) for row in (result.get("rows") or [])]
        try:
            source_total = max(0, int(result.get("source_row_count", item.get("row_count", 0)) or 0))
            matched_total = max(0, int(result.get("row_count", 0) or 0))
            source_offsets = [int(value) for value in (result.get("source_offsets") or [])]
        except (TypeError, ValueError, OverflowError):
            self._dispatch("drop_result_filter", {"view_id": view_id}, {"view_id": view_id})
            self.result_model.set_paging_state(pending=False)
            self.status.setText("Full-result filter returned invalid row metadata.")
            self._set_result_controls()
            return
        if len(source_offsets) != len(rows) or len(rows) > ResultsModel.MAX_RETAINED_ROWS:
            self._dispatch("drop_result_filter", {"view_id": view_id}, {"view_id": view_id})
            self.result_model.set_paging_state(pending=False)
            self.status.setText("Full-result filter returned an invalid result page.")
            self._set_result_controls()
            return

        item["view_id"] = view_id
        item["view_query"] = query
        item["view_row_count"] = matched_total
        item["row_count"] = source_total
        if request.get("sort_column") is not None:
            item["sort_column"] = int(request["sort_column"])
            item["sort_descending"] = bool(request.get("sort_descending", False))
        else:
            item.pop("sort_column", None)
            item.pop("sort_descending", None)
        item["window_start_offset"] = 0
        item["rows"] = rows
        item["source_offsets"] = source_offsets
        item["preview_truncated"] = matched_total > len(rows)
        item.pop("page_load_unavailable", None)
        self.result_proxy.setFilterFixedString("")
        self.result_model.update(
            headers,
            rows,
            base_offset=0,
            source_offsets=source_offsets,
            total_rows=matched_total,
        )
        item["rows"] = self.result_model.rows
        item["source_offsets"] = list(self.result_model._row_offsets)
        self.result_model.set_paging_state(
            total_rows=matched_total, pending=False, available=True
        )
        self._result_fetched_row_count = source_total
        self.query_meta.setText(
            f"{matched_total:,} match(es) · {source_total:,} fetched row(s)"
        )
        self._size_result_columns(headers, rows)
        self._set_spool_filter_message(item)
        start, end, total = self._result_window_bounds(item)
        self.status.setText(
            f"Full-result filter ready · matching rows {start + 1:,}–{end:,} of {total:,}; "
            "source row numbers are preserved and SQL was not rerun."
        )
        self._set_result_controls()
        if old_view_id and old_view_id != view_id:
            self._dispatch(
                "drop_result_filter",
                {"view_id": old_view_id},
                {"view_id": old_view_id},
            )

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
        # Schema selection changes the live MySQL session. Do not update displayed
        # context until the worker confirms that MySQL accepted the switch.
        schema = str(schema or "")
        if not schema.strip():
            return
        if self._query_running:
            self._report_query_busy("schema switch")
            return
        if not self._connection_available or self._disconnect_pending:
            self.schema_state_label.setText(
                "No active MySQL connection. Connect to a server to switch schemas."
            )
            self.status.setText("Schema switch unavailable · connect to MySQL first.")
            return

        current_schema = str(
            self.connect_result.get("database")
            or self.config.get("default_schema", "")
            or ""
        )
        if schema == current_schema:
            self.refresh_schema()
            return

        self.schema_state_label.setText(f"Switching active schema to {schema!r}…")
        self.status.setText(f"Switching active MySQL schema to {schema!r}…")
        self._dispatch("use_schema", {"schema": schema}, {"schema": schema})

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

    def _inspect_schema_object(self, schema: str, table: str, object_type: str = "") -> None:
        if not schema or not table:
            return
        if self._query_running:
            self.status.setText(
                "Object inspection paused · wait for the active SQL statement to finish."
            )
            return
        task_id = self._dispatch(
            "inspect_schema_object",
            {"schema": schema, "table": table, "object_type": object_type},
            {"schema": schema, "table": table, "object_type": object_type},
        )
        if task_id:
            self.status.setText(f"Reading definition and metadata for {qualified_identifier(schema, table)}…")

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
                else "Switch active schema and refresh"
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
        inspect_action = menu.addAction("Inspect DDL and metadata…")
        select_action = menu.addAction("Create SELECT preview in new tab")
        preview_action = menu.addAction("Preview table now")
        refresh_action = menu.addAction("Refresh schema")
        chosen = menu.exec(self.schema_tree.viewport().mapToGlobal(point))
        if chosen == copy_action:
            from PySide6.QtWidgets import QApplication
            QApplication.clipboard().setText(qualified)
            self.status.setText(f"Copied {qualified}")
        elif chosen == inspect_action:
            self._inspect_schema_object(schema, table, object_type)
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
        previous_item = self._result_item_by_id(self._current_result_id)
        if index < 0 or index >= len(self._query_results):
            self._restore_initial_result_window(previous_item)
            self._current_result_id = None
            self._result_fetched_row_count = 0
            self.result_model.update([], [])
            self._set_result_controls()
            return

        item = self._query_results[index]
        new_result_id = item.get("result_id")
        if previous_item is not None and previous_item.get("result_id") != new_result_id:
            if (
                self._result_page_load_pending is not None
                and self._result_page_load_pending.get("result_id") == previous_item.get("result_id")
            ):
                # The in-flight spool page belongs to an old selection. Do not let its
                # completion repopulate a window that has already been reset.
                self._result_page_load_pending["discard_on_completion"] = True
            self._restore_initial_result_window(previous_item)

        self.result_filter.clear()
        self._set_result_completion_words(item.get("headers", []))
        headers = item.get("headers", [])
        rows = item.get("rows", [])
        try:
            window_start = max(0, int(item.get("window_start_offset", 0) or 0))
        except (TypeError, ValueError, OverflowError):
            window_start = 0
        item["window_start_offset"] = window_start
        try:
            source_total = max(
                window_start + len(rows),
                int(item.get("row_count", window_start + len(rows)) or 0),
            )
        except (TypeError, ValueError, OverflowError):
            source_total = window_start + len(rows)
        item["row_count"] = source_total
        is_filtered_view = bool(item.get("view_id"))
        try:
            window_total = max(
                window_start + len(rows),
                int(item.get("view_row_count", source_total) if is_filtered_view else source_total),
            )
        except (TypeError, ValueError, OverflowError):
            window_total = window_start + len(rows)
        self._current_result_id = new_result_id
        self.result_model.update(
            headers,
            rows,
            base_offset=window_start,
            source_offsets=item.get("source_offsets") if is_filtered_view else None,
            total_rows=window_total,
        )
        # The selected result and the Qt model share one bounded cache list. A
        # filtered model uses source offsets for absolute labels and view offsets for paging.
        item["rows"] = self.result_model.rows
        if is_filtered_view:
            item["source_offsets"] = list(self.result_model._row_offsets)
        self._size_result_columns(headers, rows)
        item["preview_truncated"] = window_start > 0 or window_start + len(rows) < window_total
        self.result_model.set_paging_state(
            total_rows=window_total,
            pending=False,
            available=not bool(item.get("page_load_unavailable")),
        )
        self._result_fetched_row_count = source_total
        duration = item.get("duration_ms", 0)
        self._last_duration = duration
        if is_filtered_view:
            self.query_meta.setText(f"{window_total:,} match(es) · {source_total:,} fetched row(s)")
        elif total_duration is not None:
            self.query_meta.setText(f"{source_total:,} row(s) · {total_duration} ms total")
        else:
            self.query_meta.setText(f"{source_total:,} row(s) · {duration} ms")
        if is_filtered_view:
            self._set_spool_filter_message(item)
        elif str(item.get("kind", "")).casefold() == "rows" and window_start > 0:
            self._set_result_message(
                result_window_message(item, window_start, len(rows), window_total)
            )
        else:
            self._set_result_message(result_summary_message(item, len(rows), source_total))
        self._set_result_controls()

    def _on_worker_completed(self, job_id: str, action: str, result: dict):
        # Retain the submission order after the worker finishes. Qt signals can be
        # queued while a newer query is submitted; completion order alone must not
        # let an older job reclaim the global status line.
        task_sequence = self._task_sequences.pop(job_id, None)
        pending = self._jobs.pop(job_id, None)
        if pending is None:
            return
        expected_action, context = pending
        if expected_action != action:
            return
        if action == "drop_result_filter":
            return
        if result.get("connection_lost"):
            self._mark_connection_lost(str(result.get("error", "") or ""))
        preview_rollback_rows = result.get("preview_rollback_rows") or []
        preview_restore_errors = result.get("preview_restore_errors") or []
        preview_invalidated_result_ids = result.get("preview_invalidated_result_ids") or []
        for invalidated_result_id in preview_invalidated_result_ids:
            cached_preview = self._result_item_by_id(str(invalidated_result_id))
            if cached_preview is None:
                continue
            cached_preview["export_unavailable"] = True
            cached_preview["page_load_unavailable"] = True
            edit_context = cached_preview.get("table_edit")
            if isinstance(edit_context, dict):
                edit_context["enabled"] = False
                edit_context["reason"] = (
                    "This preview may be stale after ROLLBACK TO SAVEPOINT; "
                    "refresh the table before editing or exporting."
                )
        if preview_rollback_rows:
            self._restore_table_preview_rows(
                preview_rollback_rows,
                disable_editing=bool(preview_restore_errors),
            )
        if result.get("preview_transaction_finalized"):
            # A successful COMMIT or equivalent implicit-commit statement makes the
            # current preview values final. Rollback snapshots must not linger.
            self._pending_table_preview_undo.clear()
        if preview_restore_errors:
            detail = "\n".join(
                sanitize_error_message(error, fallback="")
                for error in preview_restore_errors
                if str(error).strip()
            )
            if detail:
                QTimer.singleShot(
                    0,
                    lambda message=detail: QMessageBox.warning(
                        self,
                        "Table preview needs refresh",
                        "MySQL transaction handling completed, but some local table-preview "
                        "snapshots could not be restored. Refresh affected previews before editing "
                        "or exporting them.\n\n" + message,
                    ),
                )
        outcome = None
        if action == "filter_result_spool":
            self._handle_spool_filter_completed(job_id, result, context)
            return
        if action == "sort_result_spool":
            self._handle_spool_sort_completed(job_id, result, context)
            return
        if action == "query":
            if "transaction_open" in result:
                self._transaction_open = bool(result["transaction_open"])
            outcome = classify_query_outcome(result, self._cancellation_requested)
            self._query_running = False
            self._cancellation_requested = False
            self._sync_connection_controls()
        if action == "query" and context.get("explain_plan"):
            self._handle_explain_plan_completed(result, context)
            if context.get("sql"):
                self.repository.add_history(
                    context.get("profile_name", "Connection"),
                    redact_sql_secrets(context["sql"]),
                    int(result.get("duration_ms", 0) or 0),
                    "success" if result.get("ok") else "error",
                )
                self.refresh_history()
            self._flush_deferred_export_notifications()
            return
        if action in {"query", "table_preview"}:
            # A fresh result set replaces the previous result list. Release any
            # disk-backed filter indexes first instead of retaining orphaned view
            # rows in the session spool until application shutdown.
            self._release_result_filter_views(self._query_results)
            if not result.get("ok"):
                self.query_meta.setText("Query failed")
                self._set_result_message(sanitize_error_message(result.get("error"), fallback="Query failed."))
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
                    self._set_result_message(sanitize_error_message(result.get("error"), fallback="Query failed."))
            if action == "query":
                self._apply_query_outcome(outcome, result)
            else:
                self.status.setText(sanitize_error_message(result.get("error"), fallback="Table preview complete."))
            if context.get("sql"):
                self.repository.add_history(
                    context.get("profile_name", "Connection"), redact_sql_secrets(context["sql"]),
                    self._last_duration,
                    "success" if outcome == "complete" else "error" if outcome else ("success" if result.get("ok") else "error"),
                )
                self.refresh_history()
            if action == "table_preview":
                preview_item = self._result_item_by_id(self._current_result_id)
                edit_context = preview_item.get("table_edit", {}) if preview_item else {}
                preview_count = len(preview_item.get("rows", [])) if preview_item else 0
                if edit_context.get("enabled"):
                    suffix = (
                        " More rows are available through Fetch Next Preview Page."
                        if preview_item and preview_item.get("preview_has_more")
                        else ""
                    )
                    self.status.setText(
                        f"Table preview loaded · {preview_count:,} row(s) shown.{suffix} "
                        "Right-click a non-key cell to edit it. Any UPDATE remains under "
                        "MySQL's Commit/Rollback transaction controls."
                    )
                else:
                    reason = str(edit_context.get("reason") or "this preview is read-only.")
                    self.status.setText(f"Table preview loaded · {reason}")
            if action == "query" and preview_invalidated_result_ids:
                current_status = self.status.text().strip()
                notice = (
                    "ROLLBACK TO SAVEPOINT completed · cached table previews are invalidated. "
                    "Re-preview affected tables before editing or exporting."
                )
                self.status.setText(f"{current_status} · {notice}" if current_status else notice)
            if action == "query":
                self._flush_deferred_export_notifications()
            return
        if action == "fetch_result_page":
            pending_page = self._result_page_load_pending
            if not pending_page or pending_page.get("job_id") != job_id:
                return
            self._result_page_load_pending = None
            result_id = str(context.get("result_id") or "")
            item = self._result_item_by_id(result_id)
            current_item = self._result_item_by_id(self._current_result_id)

            if pending_page.get("discard_on_completion") or result_id != self._current_result_id:
                if current_item is not None:
                    self.result_model.set_paging_state(
                        pending=False,
                        available=not bool(current_item.get("page_load_unavailable")),
                    )
                self._set_result_controls()
                return

            if item is None:
                self.result_model.set_paging_state(pending=False, available=False)
                self._set_result_controls()
                return

            if not result.get("ok"):
                item["page_load_unavailable"] = True
                self.result_model.set_paging_state(pending=False, available=False)
                if not self._query_running:
                    detail = sanitize_error_message(
                        result.get("error"),
                        fallback="The local result cache could not supply more rows.",
                    )
                    self.status.setText("Could not fetch result rows · " + detail)
                self._set_result_controls()
                return

            page_rows = [list(row) for row in (result.get("rows") or [])]
            try:
                expected_offset = max(0, int(context.get("offset", 0) or 0))
                source_offsets = [
                    int(value) for value in (result.get("source_offsets") or [])
                ]
            except (TypeError, ValueError, OverflowError):
                expected_offset = -1
                source_offsets = []

            direction = str(pending_page.get("direction", context.get("direction", "next")))
            window_start, window_end, old_total = self._result_window_bounds(item)
            expected_view_id = str(context.get("view_id") or "")
            filtered_view_valid = (
                expected_view_id == str(item.get("view_id") or "")
                and (
                    not expected_view_id
                    or (
                        str(result.get("view_id") or "") == expected_view_id
                        and len(source_offsets) == len(page_rows)
                    )
                )
            )
            try:
                total = max(
                    window_end,
                    int(result.get("row_count", item.get("row_count", old_total)) or 0),
                )
            except (TypeError, ValueError, OverflowError):
                total = old_total

            if direction == "previous":
                try:
                    expected_end = max(0, int(pending_page.get("expected_end", window_start)))
                except (TypeError, ValueError, OverflowError):
                    expected_end = -1
                page_range_valid = (
                    expected_end == window_start
                    and expected_offset + len(page_rows) == expected_end
                    and self.result_model.base_offset == window_start
                )
            else:
                page_range_valid = (
                    expected_offset == window_end
                    and self.result_model.base_offset == window_start
                )

            page_required = (
                (direction == "next" and expected_offset < total)
                or (direction == "previous" and expected_offset < window_start)
            )
            if (
                not filtered_view_valid
                or not page_range_valid
                or (not page_rows and page_required)
            ):
                item["page_load_unavailable"] = True
                self.result_model.set_paging_state(pending=False, available=False)
                if not self._query_running:
                    self.status.setText(
                        "Rows were not added because this result window changed while paging. "
                        "Run the query again if the result cache is inconsistent."
                    )
                self._set_result_controls()
                return

            item.setdefault("initial_rows", [list(row) for row in item.get("rows", [])])
            scrollbar = self.result_grid.verticalScrollBar()
            scroll_before = scrollbar.value()
            page_count = len(page_rows)

            if direction == "previous":
                evicted = self.result_model.prepend_rows(
                    page_rows,
                    start_offset=expected_offset,
                    source_offsets=source_offsets if item.get("view_id") else None,
                )
                if self.result_model.base_offset != expected_offset:
                    item["page_load_unavailable"] = True
                    self.result_model.set_paging_state(pending=False, available=False)
                    self._set_result_controls()
                    return
                item["rows"] = self.result_model.rows
                item["window_start_offset"] = self.result_model.base_offset
                if item.get("view_id"):
                    item["source_offsets"] = list(self.result_model._row_offsets)
                if not self.result_filter.text().strip() and self.result_proxy.sortColumn() < 0:
                    QTimer.singleShot(
                        0,
                        lambda value=scroll_before + page_count: scrollbar.setValue(
                            min(scrollbar.maximum(), value)
                        ),
                    )
                page_description = "earlier"
            else:
                evicted = self.result_model.append_rows(
                    page_rows,
                    source_offsets=source_offsets if item.get("view_id") else None,
                )
                item["rows"] = self.result_model.rows
                item["window_start_offset"] = self.result_model.base_offset
                if item.get("view_id"):
                    item["source_offsets"] = list(self.result_model._row_offsets)
                if evicted:
                    QTimer.singleShot(
                        0,
                        lambda value=max(0, scroll_before - evicted): scrollbar.setValue(value),
                    )
                page_description = "additional"

            loaded_rows = item["rows"]
            if item.get("view_id"):
                item["view_row_count"] = total
                try:
                    item["row_count"] = max(
                        total, int(result.get("source_row_count", item.get("row_count", 0)) or 0)
                    )
                except (TypeError, ValueError, OverflowError):
                    pass
            else:
                item["row_count"] = total
            item["preview_truncated"] = (
                item.get("window_start_offset", 0) > 0
                or item.get("window_start_offset", 0) + len(loaded_rows) < total
            )
            self.result_model.set_paging_state(
                total_rows=total,
                pending=False,
                available=not bool(item.get("page_load_unavailable")),
            )
            self._result_fetched_row_count = (
                int(item.get("row_count", total) or total)
                if item.get("view_id") else total
            )

            if self.result_filter.text().strip():
                self._filter_results(self.result_filter.text())
            else:
                self._set_result_message(
                    result_window_message(
                        item,
                        int(item.get("window_start_offset", 0) or 0),
                        len(loaded_rows),
                        total,
                    )
                )
            self._set_result_controls()
            if not self._query_running:
                start, end, _ = self._result_window_bounds(item)
                self.status.setText(
                    f"Loaded {page_count:,} {page_description} row(s) from the local result cache · "
                    f"window rows {start + 1:,}–{end:,} of {total:,}. SQL was not rerun."
                )
            return
        if action == "update_table_cell":
            self._cell_edit_pending = False
            self.result_grid.setEnabled(True)
            if "transaction_open" in result:
                self._transaction_open = bool(result.get("transaction_open"))
            self._sync_connection_controls()
            if not result.get("ok"):
                detail = sanitize_error_message(result.get("error"), fallback="The cell could not be updated.")
                if result.get("update_applied"):
                    self.status.setText(
                        "MySQL applied the cell UPDATE, but the preview could not be refreshed. "
                        "The operation was not committed automatically. Refresh the table preview and inspect the transaction."
                    )
                    detail = (
                        "The UPDATE may be pending in the active MySQL transaction, but the local preview could not be refreshed. "
                        "No automatic commit was issued.\n\n" + detail
                    )
                else:
                    self.status.setText("Cell update failed · " + detail)
                QMessageBox.warning(self, "Edit table cell", detail)
                return

            result_id = str(context.get("result_id") or result.get("result_id") or "")
            item = self._result_item_by_id(result_id)
            try:
                row_index = int(context.get("row_index", result.get("row_index", -1)))
                local_row_index = int(
                    context.get(
                        "local_row_index",
                        row_index - int((item or {}).get("window_start_offset", 0) or 0),
                    )
                )
                column_index = int(context.get("column_index", result.get("column_index", -1)))
            except (TypeError, ValueError, OverflowError):
                row_index = local_row_index = column_index = -1
            display_row = result.get("display_row")
            raw_row = result.get("raw_row")
            if (
                item is None
                or not isinstance(display_row, list)
                or not isinstance(raw_row, list)
                or not 0 <= local_row_index < len(item.get("rows", []))
                or len(display_row) != len(item.get("headers", []))
                or len(raw_row) != len(display_row)
                or not 0 <= column_index < len(display_row)
            ):
                self.status.setText(
                    "Cell updated in MySQL, but the preview is no longer available to refresh. "
                    "Reload the table preview to inspect current values."
                )
                return

            edit_context = item.get("table_edit") or {}
            original_values = edit_context.get("original_values") or {}
            # The worker/spool row index is absolute; UI snapshots are relative to the
            # current bounded window. Rollback uses the former to find the correct row.
            undo_key = (result_id, row_index)
            if self._transaction_open and not result.get("no_change"):
                if undo_key not in self._pending_table_preview_undo:
                    self._pending_table_preview_undo[undo_key] = {
                        "display_row": list(item["rows"][local_row_index]),
                        "original_values": {
                            str(index): values[local_row_index]
                            for index, values in original_values.items()
                            if isinstance(values, list) and local_row_index < len(values)
                        },
                    }
            item["rows"][local_row_index] = list(display_row)
            for index, raw_value in enumerate(raw_row):
                values_for_column = original_values.get(str(index))
                if isinstance(values_for_column, list) and local_row_index < len(values_for_column):
                    values_for_column[local_row_index] = raw_value

            if self._current_result_id == result_id:
                self.result_model.update_cell_row(local_row_index, display_row)
                filter_text = self.result_filter.text().strip()
                if filter_text:
                    self._filter_results(filter_text)
                else:
                    self._set_result_message(
                        result_summary_message(item, len(item.get("rows", [])), item.get("row_count", 0))
                    )
            if result.get("no_change"):
                self.status.setText(
                    f"{context.get('column_name', 'Cell')} already had the requested value. No data changed."
                )
            elif self._transaction_open:
                self.status.setText(
                    f"Updated {context.get('table', 'table')}.{context.get('column_name', 'column')} in the active MySQL transaction. "
                    "Use Commit to persist it or Rollback to undo it."
                )
            else:
                self.status.setText(
                    f"Updated {context.get('table', 'table')}.{context.get('column_name', 'column')} according to the MySQL session's transaction policy."
                )
            self._set_result_controls()
            return
        if action == "inspect_schema_object":
            schema = str(context.get("schema") or result.get("schema") or "")
            table = str(context.get("table") or result.get("table") or "")
            qualified = qualified_identifier(schema, table) if schema and table else "the selected object"
            if not result.get("ok"):
                detail = sanitize_error_message(result.get("error"), fallback="")
                message = detail or "MySQL could not return metadata for this object."
                self.status.setText(f"Object inspection failed · {message}")
                QMessageBox.warning(self, "Object Inspector", message)
                return
            dialog = SchemaObjectInspectorDialog(result, self)
            dialog.exec()
            if result.get("warnings"):
                self.status.setText(
                    f"Opened read-only metadata for {qualified} · some sections are unavailable; see Messages."
                )
            else:
                self.status.setText(
                    f"Inspected {qualified} · no MySQL object or row data was changed."
                )
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
                detail = sanitize_error_message(result.get("error"), fallback="")
                self.schema_state_label.setText(
                    "Schema metadata could not be loaded."
                    + (f"\n{detail}" if detail else " Check the connection and try again.")
                )
                self.status.setText(detail or "Could not load schema metadata. Use Refresh to retry.")
            return
        if action == "use_schema":
            schema = str(context.get("schema") or result.get("schema") or "")
            if not result.get("ok") or not schema.strip():
                detail = sanitize_error_message(result.get("error"), fallback="")
                current_schema = str(
                    self.connect_result.get("database")
                    or self.config.get("default_schema", "")
                    or "(no default schema)"
                )
                message = (
                    f"Could not switch active schema to {schema!r}; "
                    f"the previous schema remains {current_schema!r}."
                )
                if detail:
                    message += f" {detail}"
                if result.get("connection_lost"):
                    message += " The MySQL connection was lost; reconnect before retrying."
                self.schema_state_label.setText(message)
                self.status.setText(message)
                return

            self.config["default_schema"] = schema
            self.connect_result["database"] = schema
            self.profile["default_schema"] = schema
            if "transaction_open" in result:
                self._transaction_open = bool(result["transaction_open"])

            persistence_error = ""
            # Respect the user's current "remember this connection" choice. The
            # live session still switches, but a disabled saving preference must
            # not silently write the changed default into local profile metadata.
            if self.config.get("save_profile"):
                profile_id = str(self.profile.get("id") or "")
                try:
                    saved_profile = next(
                        (profile for profile in self.repository.profiles() if profile.id == profile_id),
                        None,
                    )
                    if saved_profile is not None:
                        self.repository.save_profile(ConnectionProfile(**self.profile))
                except Exception as exc:
                    persistence_error = sanitize_error_message(exc, fallback="The operation failed.")

            self._update_connection_status()
            active_context = self._current_connection_context()
            # Tabs follow schema changes within their own profile, but tabs pinned
            # to a different profile keep their target and still require confirmation.
            for index in range(self.editors.count()):
                editor = self.editors.widget(index)
                if not isinstance(editor, SqlEditor):
                    continue
                bound = getattr(editor, "_mysql_editor_connection_context", None)
                if connection_context_matches(bound, active_context):
                    self._bind_editor_connection_context(editor, active_context)
            self.refresh_schema()
            if persistence_error:
                QMessageBox.warning(
                    self,
                    "Schema switched; profile not saved",
                    f"The active MySQL session switched to {schema!r}, but the saved connection "
                    "profile could not be updated. This session is using the new schema; a future "
                    "connection may still use the previous default.\n\n" + persistence_error,
                )
            return
        if action == "disconnect":
            self._disconnect_pending = False
            if result.get("ok"):
                self._connection_available = False
                self._transaction_open = False
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

                profile_name = str(self.profile.get("name", "Connection") or "Connection")
                host = str(self.config.get("host", "MySQL") or "MySQL")
                port = self.config.get("port", 3306)
                username = str(self.config.get("username", "") or "")
                schema = str(self.config.get("default_schema", "") or "(no default schema)")
                detail = (
                    "Disconnected from MySQL. Query tabs and fetched results are preserved; "
                    "connect again to run SQL."
                )
                self.connection_badge.setText(f"○  {profile_name} · {host} · Disconnected")
                self.connection_badge.setToolTip(detail)
                self.connection_badge.setAccessibleName("MySQL connection disconnected")
                self.connection_badge.setAccessibleDescription(detail)
                self._set_connection_badge_state("disconnected")
                self.connection_details.setText(
                    f"{username}@{host}:{port} · {schema} · Disconnected"
                )
                self.connection_details.setToolTip(detail)
                self.connection_details.setAccessibleName("Disconnected MySQL connection details")
                self.connection_details.setAccessibleDescription(detail)
                self.schema_state_label.setText(
                    "Disconnected. Connect to a MySQL server to browse schema metadata."
                )
                self.query_meta.setText("Disconnected")
                self.status.setText(
                    f"Disconnected from {profile_name} at {host}. "
                    "Query tabs and fetched results were kept."
                )
            else:
                detail = sanitize_error_message(result.get("error"), fallback="Disconnect failed.")
                self.status.setText(
                    "Could not disconnect from MySQL. " + (detail or "The session may still be active.")
                )
            self._sync_connection_controls()
            return
        if action in {"commit", "rollback"}:
            if result.get("ok"):
                self._transaction_open = bool(result.get("transaction_open", False))
                if action == "commit":
                    self._pending_table_preview_undo.clear()
                else:
                    # Returned rows have already been restored above. Any remaining
                    # entries can no longer be rolled back in this transaction.
                    self._pending_table_preview_undo.clear()
            if result.get("ok"):
                self.status.setText(str(result.get("message") or action.title()))
            else:
                detail = sanitize_error_message(
                    result.get("error"), fallback=f"{action.title()} failed."
                )
                self.status.setText(detail)
                QMessageBox.warning(self, action.title(), detail)
            return
        if action in EXPORT_ACTIONS:
            export_result = dict(result or {})
            export_format = action.removeprefix("export_")
            export_result.setdefault("format", export_format)
            if self._query_running:
                # A newer query owns the status area. Defer modal feedback until it completes.
                self._deferred_export_notifications.append({
                    "ok": bool(export_result.get("ok")),
                    "format": export_format,
                    "row_count": export_result.get("row_count", 0),
                    "path": str(export_result.get("path") or ""),
                    "error": sanitize_error_message(
                        export_result.get("error"), fallback="Export failed."
                    ),
                })
                return
            query_submitted_after_export = (
                task_sequence is not None and self._latest_query_sequence > task_sequence
            )
            self._show_export_notification(
                export_result, update_status=not query_submitted_after_export
            )

    def _handle_explain_plan_completed(self, result: dict, context: dict) -> None:
        """Show a structured JSON plan without loading optimizer data into the result grid."""
        explained_sql = str(context.get("explained_sql") or "").strip()
        if not result.get("ok"):
            detail = sanitize_error_message(
                result.get("error"), fallback="MySQL could not produce a JSON execution plan."
            )
            self.query_meta.setText("Execution plan unavailable")
            self._set_result_message(
                "The execution plan could not be produced. The original SELECT was not executed."
                + (f"\n{detail}" if detail else "")
            )
            self.status.setText("Explain failed · SELECT was not executed.")
            QMessageBox.warning(
                self,
                "Explain SELECT",
                "MySQL could not produce an EXPLAIN FORMAT=JSON plan. The original SELECT was not "
                "executed. Check server support and permissions.\n\n" + detail,
            )
            return

        try:
            plan = extract_explain_json(result)
        except ExplainPlanError as exc:
            detail = sanitize_error_message(exc, fallback="The operation failed.")
            self.query_meta.setText("Execution plan unavailable")
            self._set_result_message(
                "MySQL returned a response that could not be shown as a JSON plan."
                + (f"\n{detail}" if detail else "")
            )
            self.status.setText("Explain failed · SELECT was not executed.")
            QMessageBox.warning(
                self,
                "Explain SELECT",
                "A JSON execution plan could not be read. The original SELECT was not executed."
                + (f"\n\n{detail}" if detail else ""),
            )
            return

        dialog = ExplainPlanDialog(plan, explained_sql, self)
        dialog.exec()
        self.query_meta.setText("JSON execution plan")
        self._set_result_message(
            "Visual execution plan loaded. This view shows optimizer estimates; it does not run the SELECT."
        )
        self.status.setText(
            "Execution plan ready · the SELECT was not executed; row counts and costs are estimates."
        )

    def _apply_query_outcome(self, outcome: str | None, result: dict):
        error = sanitize_error_message(result.get("error"), fallback="Query failed.")
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
        """Show persistent, non-modal feedback without interrupting query work."""
        export_format = str(result.get("format") or "csv").casefold()
        format_name = EXPORT_FORMAT_LABELS.get(export_format, "CSV")
        if result.get("ok"):
            try:
                row_count = max(0, int(result.get("row_count", 0) or 0))
            except (TypeError, ValueError):
                row_count = 0
            path = str(result.get("path") or "the chosen destination")
            if export_format == "csv":
                detail = CSV_EXPORT_SEMANTICS
            elif export_format == "json":
                detail = (
                    RESULT_EXPORT_SEMANTICS + " Each JSON object represents one row; "
                    "SQL NULL is JSON null and empty text is an empty string. Duplicate column "
                    "labels receive numbered suffixes so no values are lost."
                )
            else:
                detail = (
                    RESULT_EXPORT_SEMANTICS + " Each line is one JSON row object; SQL NULL is "
                    "JSON null and empty text is an empty string. Duplicate column labels receive "
                    "numbered suffixes so no values are lost."
                )
            self.export_feedback.setObjectName("statusSuccess")
            self.export_feedback.setText(
                f"{format_name} export complete · {row_count:,} row(s) saved to {path}. {detail}"
            )
            self.export_feedback.setToolTip(f"{format_name} saved to: {path}\n{detail}")
            self.export_feedback.setAccessibleDescription(
                f"{format_name} export completed successfully. {row_count:,} row(s). "
                f"Saved to {path}. {detail}"
            )
            if update_status:
                self.status.setText(
                    f"{format_name} exported · {row_count:,} row(s); saved path shown in Results."
                )
        else:
            error = sanitize_error_message(result.get("error"), fallback="Export failed.")
            if not error:
                error = "Export failed."
            self.export_feedback.setObjectName("statusDanger")
            self.export_feedback.setText(f"{format_name} export failed · {error}")
            self.export_feedback.setToolTip(error)
            self.export_feedback.setAccessibleDescription(
                f"{format_name} export failed. Error details: {error}"
            )
            if update_status:
                self.status.setText(f"{format_name} export failed · see details in Results.")

        style = self.export_feedback.style()
        style.unpolish(self.export_feedback)
        style.polish(self.export_feedback)
        self.export_feedback.setVisible(True)

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
        if action != "query" and action not in EXPORT_ACTIONS:
            return
        if action in EXPORT_ACTIONS:
            task_sequence = self._task_sequences.get(job_id)
            if (
                task_sequence is not None
                and self._latest_query_sequence > task_sequence
            ):
                # This export began before a later query. Its queued progress signals
                # remain stale even after that query completes.
                return
        self._on_activity(message)

    def _on_activity(self, message: str):
        if self._query_running and message.startswith(("Exporting ", "Exported ")):
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
        elif message.startswith("Exporting "):
            self.status.setText(message)
        elif message.startswith("Exported "):
            self.status.setText(message)

    def export_results(self):
        result_id = self._current_result_id
        if not result_id:
            return
        item = self._result_item_by_id(result_id)
        if item is not None and item.get("export_unavailable"):
            self.status.setText(
                "Result export is disabled because the preview cache could not be restored after rollback. "
                "Reload the table preview before exporting."
            )
            return
        filters = "CSV files (*.csv);;JSON array (*.json);;NDJSON files (*.ndjson)"
        path, selected_filter = QFileDialog.getSaveFileName(
            self,
            "Export result grid",
            "mysql-query-results.csv",
            filters,
            "CSV files (*.csv)",
        )
        path, export_format = result_export_target(path, selected_filter)
        if path:
            # Clear stale feedback only once the user has committed to a new export.
            self.export_feedback.clear()
            self.export_feedback.hide()
            self.export_feedback.setToolTip("")
            self.export_feedback.setAccessibleDescription(
                "Result export status. CSV, JSON, and NDJSON export results will appear here."
            )
            action = f"export_{export_format}"
            self._dispatch(action, {"result_id": result_id, "path": path})

    def _show_result_context(self, point):
        if self._cell_edit_pending:
            return
        clicked = self.result_grid.indexAt(point)
        selection = self.result_grid.selectionModel()
        if clicked.isValid() and clicked not in self.result_grid.selectedIndexes():
            selection.select(clicked, QItemSelectionModel.SelectionFlag.ClearAndSelect)

        menu = QMenu(self)
        details_action = menu.addAction("View cell details")
        details_action.setEnabled(clicked.isValid())
        edit_action = None
        if (
            clicked.isValid()
            and self._connection_available
            and not self._disconnect_pending
            and not self._query_running
            and not self._cell_edit_pending
            and not self._mysql_task_pending()
            and self._table_cell_edit_entry(clicked)
        ):
            edit_action = menu.addAction("Edit table preview cell…")
            edit_action.setToolTip(
                "Edit a single non-primary-key cell in a Schema Explorer base-table preview. "
                "Ordinary SQL query results remain read-only."
            )
        menu.addSeparator()
        copy_cells_action = menu.addAction("Copy selected cells")
        copy_rows_action = menu.addAction("Copy selected rows")
        copy_headers_action = menu.addAction("Copy column headers")
        menu.addSeparator()
        export_action = menu.addAction("Export fetched result… (CSV, JSON, or NDJSON)")
        chosen = menu.exec(self.result_grid.viewport().mapToGlobal(point))
        if chosen == details_action:
            self.show_cell_details(clicked)
        elif edit_action is not None and chosen == edit_action:
            self._edit_table_preview_cell(clicked)
        elif chosen == copy_cells_action:
            self.copy_selected_cells()
        elif chosen == copy_rows_action:
            self.copy_selected_rows()
        elif chosen == copy_headers_action:
            self.copy_column_headers()
        elif chosen == export_action:
            self.export_results()

    def _restore_table_preview_rows(
        self, rows: list[dict[str, Any]], *, disable_editing: bool = False
    ) -> None:
        """Restore visible rows and raw cell metadata after MySQL rolls back edits."""
        current_result_changed = False
        for entry in rows:
            if not isinstance(entry, dict):
                continue
            result_id = str(entry.get("result_id") or "")
            try:
                row_index = int(entry.get("row_index", -1))
            except (TypeError, ValueError, OverflowError):
                continue
            if not result_id or row_index < 0:
                continue
            item = self._result_item_by_id(result_id)
            undo = self._pending_table_preview_undo.pop((result_id, row_index), None)
            baseline = undo.get("display_row") if isinstance(undo, dict) else entry.get("display_row")
            if item is None or not isinstance(baseline, list):
                continue
            if row_index >= len(item.get("rows", [])) or len(baseline) != len(item.get("headers", [])):
                continue

            restored_row = list(baseline)
            item["rows"][row_index] = restored_row
            edit_context = item.get("table_edit")
            if disable_editing:
                item["export_unavailable"] = True
            if isinstance(edit_context, dict):
                if disable_editing:
                    edit_context["enabled"] = False
                    edit_context["reason"] = (
                        "The preview cache could not be restored reliably; refresh before editing."
                    )
                elif isinstance(undo, dict):
                    raw_baselines = undo.get("original_values") or {}
                    current_originals = edit_context.get("original_values") or {}
                    for column_key, raw_value in raw_baselines.items():
                        per_column = current_originals.get(str(column_key))
                        if isinstance(per_column, list) and row_index < len(per_column):
                            per_column[row_index] = raw_value
                else:
                    # A worker-reported rollback without a matching live UI snapshot
                    # cannot safely restore raw Python values such as datetimes.
                    # Show the confirmed display row but require a fresh preview to edit.
                    edit_context["enabled"] = False
                    edit_context["reason"] = (
                        "This preview was restored after rollback; refresh it before editing again."
                    )

            if self._current_result_id == result_id:
                self.result_model.update_cell_row(row_index, restored_row)
                current_result_changed = True

        if current_result_changed:
            filter_text = self.result_filter.text().strip()
            if filter_text:
                self._filter_results(filter_text)
            else:
                item = self._result_item_by_id(self._current_result_id)
                if item is not None:
                    self._set_result_message(
                        result_summary_message(
                            item, len(item.get("rows", [])), item.get("row_count", 0)
                        )
                    )
        self._set_result_controls()

    def _merge_table_preview_edit_page(
        self,
        item: dict,
        page_edit: dict | None,
        *,
        direction: str,
        page_count: int,
        evicted: int,
    ) -> None:
        """Keep raw key/value snapshots aligned with the bounded source-row window."""
        if not item.get("table_preview"):
            return
        current = item.get("table_edit")
        if not isinstance(current, dict):
            item["table_edit"] = {
                "enabled": False,
                "reason": "Refresh this table preview before editing.",
            }
            return

        def disable(reason: str) -> None:
            current["enabled"] = False
            current["reason"] = reason
            current["row_keys"] = []
            current["original_values"] = {}

        if not current.get("enabled"):
            return
        if not isinstance(page_edit, dict) or not page_edit.get("enabled"):
            disable(
                str((page_edit or {}).get("reason")
                    or "The source metadata could not be verified for this page. Refresh before editing.")
            )
            return

        identity_keys = (
            "schema", "table", "session_token", "primary_key_columns",
            "primary_key_indices", "editable_column_indices",
        )
        if any(current.get(key) != page_edit.get(key) for key in identity_keys):
            disable("The table metadata changed while paging. Refresh before editing.")
            return

        displayed_rows = item.get("rows") or []
        page_count = max(0, int(page_count))
        evicted = max(0, int(evicted))
        old_count = len(displayed_rows) - page_count + evicted
        if old_count < 0:
            disable("The preview row window changed while paging. Refresh before editing.")
            return

        old_keys = current.get("row_keys")
        new_keys = page_edit.get("row_keys")
        if (
            not isinstance(old_keys, list)
            or not isinstance(new_keys, list)
            or len(old_keys) != old_count
            or len(new_keys) != page_count
        ):
            disable("The primary-key snapshot does not match the visible preview rows. Refresh before editing.")
            return

        old_originals = current.get("original_values")
        new_originals = page_edit.get("original_values")
        if not isinstance(old_originals, dict) or not isinstance(new_originals, dict):
            disable("The cell-value snapshot is unavailable. Refresh before editing.")
            return

        merged_originals: dict[str, list[Any]] = {}
        editable_indices = [int(value) for value in current.get("editable_column_indices", [])]
        for column_index in editable_indices:
            key = str(column_index)
            old_values = old_originals.get(key)
            page_values = new_originals.get(key)
            if (
                not isinstance(old_values, list)
                or len(old_values) != old_count
                or not isinstance(page_values, list)
                or len(page_values) != page_count
            ):
                disable("The raw cell-value snapshot does not match the visible preview rows. Refresh before editing.")
                return
            if direction == "previous":
                kept_old = old_values[:max(0, old_count - evicted)]
                merged = list(page_values) + list(kept_old)
            else:
                merged = list(old_values[evicted:]) + list(page_values)
            merged_originals[key] = merged

        if direction == "previous":
            kept_old_keys = old_keys[:max(0, old_count - evicted)]
            merged_keys = list(new_keys) + list(kept_old_keys)
        else:
            merged_keys = list(old_keys[evicted:]) + list(new_keys)

        expected_count = len(displayed_rows)
        if len(merged_keys) != expected_count or any(
            len(values) != expected_count for values in merged_originals.values()
        ):
            disable("The edit snapshot no longer matches the bounded result window. Refresh before editing.")
            return
        current["row_keys"] = merged_keys
        current["original_values"] = merged_originals
        current["reason"] = ""

    def _table_cell_edit_entry(self, index):
        """Return a verified local preview target for a single-cell edit action."""
        if not index.isValid() or not self._current_result_id or self._cell_edit_pending:
            return None
        source_index = self.result_proxy.mapToSource(index)
        item = self._result_item_by_id(self._current_result_id)
        if item is None or str(item.get("kind", "")).casefold() != "rows":
            return None
        table_edit = item.get("table_edit")
        if not isinstance(table_edit, dict) or not table_edit.get("enabled"):
            return None
        if item.get("view_id"):
            # Filtering/sorting creates a different row order. Keep table editing disabled
            # on any materialized view until a primary-key-aligned view is implemented.
            return None
        local_row_index, column_index = source_index.row(), source_index.column()
        absolute_row_index = self.result_model.absolute_row_index(local_row_index)
        if absolute_row_index is None:
            return None
        editable_columns = table_edit.get("editable_column_indices") or []
        if column_index not in editable_columns:
            return None
        row_keys = table_edit.get("row_keys") or []
        original_values = table_edit.get("original_values") or {}
        old_values = original_values.get(str(column_index))
        primary_key_columns = table_edit.get("primary_key_columns") or []
        if (
            not 0 <= local_row_index < len(row_keys)
            or not isinstance(old_values, list)
            or not 0 <= local_row_index < len(old_values)
            or len(row_keys[local_row_index]) != len(primary_key_columns)
        ):
            return None
        headers = item.get("headers") or []
        if not 0 <= column_index < len(headers):
            return None
        return {
            "item": item,
            "table_edit": table_edit,
            "row_index": absolute_row_index,
            "local_row_index": local_row_index,
            "column_index": column_index,
            "column_name": str(headers[column_index]),
            "old_value": old_values[local_row_index],
            "primary_key_values": list(row_keys[local_row_index]),
            "primary_key_columns": list(primary_key_columns),
        }

    def _edit_table_preview_cell(self, index) -> None:
        """Request confirmation, then submit one optimistic, parameterized cell update."""
        if (
            self._query_running
            or self._cell_edit_pending
            or self._disconnect_pending
            or self._mysql_task_pending()
        ):
            self.status.setText("Cell editing is paused while another MySQL operation is active.")
            return
        if not self._connection_available:
            self.status.setText("Cell editing requires an active MySQL connection.")
            return
        entry = self._table_cell_edit_entry(index)
        if entry is None:
            self.status.setText(
                "This cell is read-only. Only non-primary-key cells from a verified base-table preview can be edited."
            )
            return

        table_edit = entry["table_edit"]
        key_summary = ", ".join(
            f"{name}={'(NULL)' if value is None else str(value)}"
            for name, value in zip(entry["primary_key_columns"], entry["primary_key_values"], strict=False)
        )
        dialog = EditTableCellDialog(
            schema=str(table_edit.get("schema") or ""),
            table=str(table_edit.get("table") or ""),
            column=entry["column_name"],
            current_value=entry["old_value"],
            primary_key_summary=key_summary,
            parent=self,
        )
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return
        new_value = dialog.new_value()
        old_value = entry["old_value"]
        if (
            new_value is None and old_value is None
            or new_value is not None and old_value is not None and str(new_value) == str(old_value)
        ):
            self.status.setText("Cell edit cancelled · the requested value is unchanged.")
            return

        result_id = str(entry["item"].get("result_id") or "")
        context = {
            "result_id": result_id,
            "row_index": entry["row_index"],
            "local_row_index": entry["local_row_index"],
            "column_index": entry["column_index"],
            "schema": str(table_edit.get("schema") or ""),
            "table": str(table_edit.get("table") or ""),
            "column_name": entry["column_name"],
        }
        payload = {
            "result_id": result_id,
            "session_token": str(table_edit.get("session_token") or ""),
            "row_index": entry["row_index"],
            "column_index": entry["column_index"],
            "schema": context["schema"],
            "table": context["table"],
            "column_name": entry["column_name"],
            "primary_key_columns": entry["primary_key_columns"],
            "primary_key_values": entry["primary_key_values"],
            "expected_old": old_value,
            "new_value": new_value,
        }
        job_id = self._dispatch("update_table_cell", payload, context)
        if job_id:
            self._cell_edit_pending = True
            self._sync_connection_controls()
            self.result_grid.setEnabled(False)
            self.status.setText(
                f"Updating {context['schema']}.{context['table']}.{context['column_name']}… "
                "The current MySQL transaction remains under your control."
            )

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
        absolute_row = self.result_model.absolute_row_index(source_index.row())
        display_row_number = (
            absolute_row + 1 if absolute_row is not None else source_index.row() + 1
        )
        state = QLabel(
            f"Row {display_row_number:,} · Column {column_name} · "
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
            self.saved_list.setToolTip(sanitize_error_message(exc))
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
                + sanitize_error_message(exc),
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
                + sanitize_error_message(exc),
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
                "The saved-queries folder could not be created.\n\n" + sanitize_error_message(exc),
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
        if self._cell_edit_pending:
            self.status.setText("Connection change paused · wait for the cell update to finish.")
            return
        if self._query_running:
            self._report_query_busy("connection")
            return
        if self._disconnect_pending:
            self.status.setText("Connection change blocked · disconnect is still in progress.")
            return
        dialog = ConnectionDialog(
            self.worker, self.repository, self.credentials, self,
            master_unlocked=True, before_connect=self._confirm_connection_switch,
        )
        dialog.connected.connect(self._switch_connection)
        dialog.exec()

    def _switch_connection(self, profile: dict, config: dict, connect_result: dict):
        if self._cell_edit_pending:
            self.status.setText("Connection change blocked · the cell update is still finishing.")
            return
        preview_rollback_rows = connect_result.get("preview_rollback_rows") or []
        if preview_rollback_rows:
            self._restore_table_preview_rows(preview_rollback_rows)
        if connect_result.get("preview_transaction_finalized"):
            self._pending_table_preview_undo.clear()
        if self._query_running:
            self._report_query_busy("connection")
            return
        self._disconnect_pending = False
        self._connection_available = True
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
                "The password was not written to a file.\n\n" + sanitize_error_message(exc),
            )

    def _set_connection_badge_state(self, state: str) -> None:
        self.connection_badge.setProperty("connectionState", state)
        style = self.connection_badge.style()
        style.unpolish(self.connection_badge)
        style.polish(self.connection_badge)
        self.connection_badge.update()

    def _sync_connection_controls(self) -> None:
        """Keep database-only controls consistent with connection, query and refresh state."""
        available = self._connection_available and not self._disconnect_pending
        idle = available and not self._query_running and not self._cell_edit_pending
        self.connect_button.setEnabled(not self._disconnect_pending and not self._cell_edit_pending)
        self.disconnect_button.setEnabled(idle)
        self.run_button.setEnabled(idle)
        self.run_selection_button.setEnabled(idle)
        self.explain_button.setEnabled(idle)
        self.commit_button.setEnabled(idle)
        self.rollback_button.setEnabled(idle)
        self.stop_button.setEnabled(self._query_running)
        self.schema_refresh_button.setEnabled(
            available and self._schema_request_id is None and not self._cell_edit_pending
        )

    def disconnect_from_mysql(self) -> None:
        """Queue a session close without blocking the UI or discarding local query work."""
        if self._cell_edit_pending:
            self.status.setText("Disconnect paused · wait for the cell update to finish.")
            return
        if self._query_running:
            self._report_query_busy("connection")
            return
        if self._disconnect_pending:
            self.status.setText("Disconnect already in progress.")
            return
        if not self._connection_available:
            self.status.setText("No active MySQL session. Use Connect to reconnect.")
            return
        if self._transaction_open:
            answer = QMessageBox.warning(
                self,
                "Disconnect with an open transaction",
                "The active MySQL session has an open transaction. Disconnecting may cause "
                "MySQL to roll back uncommitted work. Disconnect anyway?",
                QMessageBox.StandardButton.Cancel | QMessageBox.StandardButton.Yes,
                QMessageBox.StandardButton.Cancel,
            )
            if answer != QMessageBox.StandardButton.Yes:
                self.status.setText(
                    "Disconnect cancelled · the active MySQL session remains connected."
                )
                return

        self._disconnect_pending = True
        self._schema_request_id = None
        self._schema_expansion_requests.clear()
        self._schema_expand_items.clear()
        self._sync_connection_controls()
        self.status.setText("Disconnecting from MySQL…")
        self._dispatch("disconnect", {})

    def _mark_connection_lost(self, error_message: str = "") -> None:
        """Show a lost database session without discarding query buffers or target details."""
        host = str(self.config.get("host", "MySQL") or "MySQL")
        profile_name = str(self.profile.get("name", "Connection") or "Connection")
        schema = self.connect_result.get("database") or self.config.get("default_schema") or "(no default schema)"
        hint = "MySQL session lost. Reconnect before running more SQL."
        detail = sanitize_error_message(error_message, fallback="")
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
        self._connection_available = False
        self.status.setText(hint)
        self._sync_connection_controls()

    def _update_connection_status(self):
        self._connection_available = True
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
        self._sync_connection_controls()

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
        # A deferred close repeats no confirmation: the user has already approved
        # closing, and the window was disabled while the bounded update request exited.
        close_already_approved = self._close_after_update_check_approved
        if close_already_approved:
            self._close_after_update_check_approved = False
        else:
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

            update_thread = self._update_check_thread
            if update_thread is not None and update_thread.isRunning():
                # Keep the event loop responsive while the bounded network request
                # finishes. Never wait synchronously for a QThread in a UI callback.
                self._close_after_update_check = True
                self.setEnabled(False)
                self.status.setText("Finishing the update check before closing…")
                event.ignore()
                return
        self._settings.setValue("ui/windowGeometry", self.saveGeometry())
        self._settings.setValue("ui/mainSplitterSizes", self.main_split.sizes())
        self._settings.setValue("ui/editorResultsSplitterSizes", self.editor_results_split.sizes())
        self._settings.setValue("ui/inspectorTab", self.inspector_tabs.currentIndex())
        self._settings.sync()
        self.worker.submit("disconnect", {})
        self.worker.shutdown()
        self.worker.wait(5000)
        event.accept()
