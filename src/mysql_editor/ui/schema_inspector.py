"""Read-only inspector dialog for MySQL table and view metadata."""
from __future__ import annotations

from typing import Any

from PySide6.QtGui import QFontDatabase
from PySide6.QtWidgets import (
    QApplication,
    QAbstractItemView,
    QDialog,
    QDialogButtonBox,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QPlainTextEdit,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)


_COLUMN_FIELDS = (
    ("Position", "position"),
    ("Column", "name"),
    ("Type", "type"),
    ("Nullable", "nullable"),
    ("Default", "default"),
    ("Key", "key"),
    ("Extra", "extra"),
    ("Character set", "charset"),
    ("Collation", "collation"),
    ("Comment", "comment"),
)
_INDEX_FIELDS = (
    ("Index", "name"),
    ("Unique", "unique"),
    ("Position", "position"),
    ("Column", "column"),
    ("Expression", "expression"),
    ("Collation", "collation"),
    ("Cardinality", "cardinality"),
    ("Prefix length", "prefix_length"),
    ("Index type", "type"),
    ("Visible", "visible"),
    ("Comment", "comment"),
)
_CONSTRAINT_FIELDS = (
    ("Constraint", "name"),
    ("Type", "type"),
    ("Column", "column"),
    ("Position", "position"),
    ("Referenced schema", "referenced_schema"),
    ("Referenced table", "referenced_table"),
    ("Referenced column", "referenced_column"),
)


def _display_value(value: Any) -> str:
    if value is None:
        return "(NULL)"
    return str(value)


class SchemaObjectInspectorDialog(QDialog):
    """Inspect definition, columns, indexes, constraints and object properties without editing them."""

    def __init__(self, metadata: dict[str, Any], parent=None) -> None:
        super().__init__(parent)
        self.metadata = dict(metadata or {})
        schema = str(self.metadata.get("schema") or "")
        table = str(self.metadata.get("table") or "")
        object_type = str(self.metadata.get("object_type") or "MySQL object")
        def quote_identifier(value: str) -> str:
            return chr(96) + value.replace(chr(96), chr(96) * 2) + chr(96)

        qualified = f"{quote_identifier(schema)}.{quote_identifier(table)}"
        self.setWindowTitle(f"Object Inspector — {qualified}")
        self.setMinimumSize(760, 520)
        self.resize(1080, 700)

        layout = QVBoxLayout(self)
        heading = QLabel(qualified)
        heading.setObjectName("panelTitle")
        heading.setAccessibleName("Qualified MySQL object name")
        layout.addWidget(heading)

        subtitle = QLabel(
            f"{object_type} · Read-only metadata from the current MySQL connection"
        )
        subtitle.setObjectName("mutedText")
        subtitle.setWordWrap(True)
        layout.addWidget(subtitle)

        self.tabs = QTabWidget(self)
        self.tabs.setAccessibleName("Schema object metadata")
        layout.addWidget(self.tabs, 1)

        definition_page = QWidget(self.tabs)
        definition_layout = QVBoxLayout(definition_page)
        self.definition_view = QPlainTextEdit(definition_page)
        self.definition_view.setObjectName("schemaObjectDefinition")
        self.definition_view.setAccessibleName("CREATE definition")
        self.definition_view.setAccessibleDescription(
            "Read-only CREATE TABLE or CREATE VIEW statement returned by MySQL."
        )
        self.definition_view.setReadOnly(True)
        self.definition_view.setLineWrapMode(QPlainTextEdit.LineWrapMode.NoWrap)
        self.definition_view.setFont(
            QFontDatabase.systemFont(QFontDatabase.SystemFont.FixedFont)
        )
        definition = str(self.metadata.get("definition") or "")
        self.definition_view.setPlainText(definition)
        if not definition:
            self.definition_view.setPlaceholderText(
                "MySQL did not return a CREATE definition. Check the Messages tab."
            )
        definition_layout.addWidget(self.definition_view, 1)

        definition_footer = QHBoxLayout()
        definition_note = QLabel(
            "Copying this definition only places the text on the clipboard; it does not execute it."
        )
        definition_note.setObjectName("mutedText")
        definition_note.setWordWrap(True)
        definition_footer.addWidget(definition_note, 1)
        self.copy_status_label = QLabel("")
        self.copy_status_label.setObjectName("statusSuccess")
        definition_footer.addWidget(self.copy_status_label)
        self.copy_ddl_button = QPushButton("Copy DDL")
        self.copy_ddl_button.setAccessibleName("Copy CREATE definition")
        self.copy_ddl_button.setToolTip("Copy the read-only CREATE statement to the clipboard.")
        self.copy_ddl_button.setEnabled(bool(definition))
        self.copy_ddl_button.clicked.connect(self._copy_definition)
        definition_footer.addWidget(self.copy_ddl_button)
        definition_layout.addLayout(definition_footer)
        self.tabs.addTab(definition_page, "Definition")

        self.columns_table = self._add_metadata_table(
            "Columns", "Column definitions and attributes",
            self.metadata.get("columns") or [], _COLUMN_FIELDS, "schemaObjectColumns",
        )
        self.indexes_table = self._add_metadata_table(
            "Indexes", "Index rows are listed in index-column order",
            self.metadata.get("indexes") or [], _INDEX_FIELDS, "schemaObjectIndexes",
        )
        self.constraints_table = self._add_metadata_table(
            "Constraints", "Constraint columns and referenced columns, when applicable",
            self.metadata.get("constraints") or [], _CONSTRAINT_FIELDS, "schemaObjectConstraints",
        )
        self.properties_table = self._add_properties_table(
            self.metadata.get("properties") or {}
        )
        self.messages_view = QPlainTextEdit(self)
        self.messages_view.setObjectName("schemaObjectMessages")
        self.messages_view.setAccessibleName("Object inspector messages")
        self.messages_view.setReadOnly(True)
        warnings = [str(value) for value in (self.metadata.get("warnings") or []) if str(value).strip()]
        self.messages_view.setPlainText(
            "\n".join(warnings) if warnings else "No metadata warnings. All available sections loaded."
        )
        self.tabs.addTab(self.messages_view, "Messages")
        if warnings:
            self.tabs.setTabText(5, f"Messages ({len(warnings)})")

        footer = QHBoxLayout()
        footer_note = QLabel(
            "This inspector does not alter the object or its data. SQL permissions remain enforced by MySQL."
        )
        footer_note.setObjectName("mutedText")
        footer_note.setWordWrap(True)
        footer.addWidget(footer_note, 1)
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Close, parent=self)
        buttons.rejected.connect(self.reject)
        footer.addWidget(buttons)
        layout.addLayout(footer)

    def _add_metadata_table(
        self,
        title: str,
        description: str,
        rows: list[dict[str, Any]],
        fields: tuple[tuple[str, str], ...],
        object_name: str,
    ) -> QTableWidget:
        page = QWidget(self.tabs)
        layout = QVBoxLayout(page)
        note = QLabel(description)
        note.setObjectName("mutedText")
        note.setWordWrap(True)
        layout.addWidget(note)
        table = QTableWidget(len(rows), len(fields), page)
        table.setObjectName(object_name)
        table.setAccessibleName(f"Schema object {title.lower()} metadata")
        table.setHorizontalHeaderLabels([heading for heading, _key in fields])
        table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        table.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)
        table.setAlternatingRowColors(True)
        table.setWordWrap(False)
        table.verticalHeader().setVisible(False)
        header = table.horizontalHeader()
        header.setSectionResizeMode(QHeaderView.ResizeMode.Interactive)
        header.setStretchLastSection(True)
        for row_index, record in enumerate(rows):
            for column_index, (_heading, key) in enumerate(fields):
                value = _display_value(record.get(key))
                item = QTableWidgetItem(value)
                item.setToolTip(value)
                table.setItem(row_index, column_index, item)
        if not rows:
            table.setRowCount(0)
        layout.addWidget(table, 1)
        self.tabs.addTab(page, title)
        return table

    def _add_properties_table(self, properties: dict[str, Any]) -> QTableWidget:
        page = QWidget(self.tabs)
        layout = QVBoxLayout(page)
        note = QLabel("Server-reported properties. Row counts and size estimates may be approximate.")
        note.setObjectName("mutedText")
        note.setWordWrap(True)
        layout.addWidget(note)
        entries = list(properties.items())
        table = QTableWidget(len(entries), 2, page)
        table.setObjectName("schemaObjectProperties")
        table.setAccessibleName("Table or view properties")
        table.setHorizontalHeaderLabels(["Property", "Value"])
        table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        table.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)
        table.setAlternatingRowColors(True)
        table.verticalHeader().setVisible(False)
        table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Interactive)
        table.horizontalHeader().setStretchLastSection(True)
        for row_index, (name, raw_value) in enumerate(entries):
            value = _display_value(raw_value)
            name_item = QTableWidgetItem(str(name))
            value_item = QTableWidgetItem(value)
            value_item.setToolTip(value)
            table.setItem(row_index, 0, name_item)
            table.setItem(row_index, 1, value_item)
        if not entries:
            table.setRowCount(0)
        layout.addWidget(table, 1)
        self.tabs.addTab(page, "Properties")
        return table

    def _copy_definition(self) -> None:
        definition = str(self.metadata.get("definition") or "")
        if not definition:
            return
        QApplication.clipboard().setText(definition)
        self.copy_status_label.setText("Copied to clipboard.")
