"""SQL editor with line numbers, syntax highlighting and indentation."""
from __future__ import annotations
import re
from PySide6.QtCore import QRect, QSize, Qt
from PySide6.QtGui import QColor, QFont, QPainter, QSyntaxHighlighter, QTextCharFormat, QTextFormat, QTextEdit
from PySide6.QtWidgets import QPlainTextEdit, QWidget

class SqlHighlighter(QSyntaxHighlighter):
    def __init__(self, document):
        super().__init__(document)
        keyword = QTextCharFormat()
        keyword.setForeground(QColor("#37d6e7"))
        keyword.setFontWeight(QFont.Weight.DemiBold)
        words = (
            "SELECT FROM WHERE JOIN LEFT RIGHT INNER OUTER ON GROUP BY ORDER HAVING LIMIT OFFSET "
            "INSERT INTO VALUES UPDATE SET DELETE REPLACE CREATE ALTER DROP TRUNCATE TABLE DATABASE "
            "VIEW INDEX PRIMARY KEY FOREIGN REFERENCES NOT NULL UNIQUE DEFAULT CHECK CONSTRAINT "
            "AS DISTINCT ALL UNION CASE WHEN THEN ELSE END AND OR IN IS LIKE BETWEEN EXISTS WITH "
            "RECURSIVE DESC ASC TRUE FALSE NULL IF IFNULL COALESCE COUNT SUM AVG MIN MAX CAST CONVERT "
            "DATE INTERVAL CURRENT_DATE CURRENT_TIMESTAMP BEGIN COMMIT ROLLBACK START TRANSACTION "
            "EXPLAIN DESCRIBE SHOW USE GRANT REVOKE"
        ).split()
        self.rules = [(re.compile(r"\b(?:" + "|".join(words) + r")\b", re.I), keyword)]
        string = QTextCharFormat()
        string.setForeground(QColor("#f6c56f"))
        self.rules.append((re.compile(r"'(?:''|\\.|[^'])*'|\"(?:\"\"|\\.|[^\"])*\""), string))
        comment = QTextCharFormat()
        comment.setForeground(QColor("#7f93ad"))
        comment.setFontItalic(True)
        self.rules.extend([
            (re.compile(r"--[^\r\n]*|#[^\r\n]*"), comment),
            (re.compile(r"/\*.*?\*/"), comment),
        ])
        number = QTextCharFormat()
        number.setForeground(QColor("#bd9cff"))
        self.rules.append((re.compile(r"\b\d+(?:\.\d+)?\b"), number))
        function = QTextCharFormat()
        function.setForeground(QColor("#69b7ff"))
        self.rules.append((re.compile(r"\b[A-Za-z_]\w*(?=\s*\()"), function))

    def highlightBlock(self, text: str) -> None:
        for pattern, style in self.rules:
            for match in pattern.finditer(text):
                self.setFormat(match.start(), match.end() - match.start(), style)

class LineNumberArea(QWidget):
    def __init__(self, editor: SqlEditor):
        super().__init__(editor)
        self.editor = editor

    def sizeHint(self):
        return QSize(self.editor.line_number_area_width(), 0)

    def paintEvent(self, event):
        self.editor.paint_line_numbers(event)

class SqlEditor(QPlainTextEdit):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.line_number_area = LineNumberArea(self)
        self.highlighter = SqlHighlighter(self.document())
        self.setObjectName("sqlEditor")
        self.setLineWrapMode(QPlainTextEdit.LineWrapMode.NoWrap)
        font = QFont("Cascadia Code")
        font.setStyleHint(QFont.StyleHint.Monospace)
        font.setPointSize(10)
        self.setFont(font)
        self.setTabStopDistance(self.fontMetrics().horizontalAdvance(" ") * 4)
        self.setPlaceholderText(
            "-- Write a query after connecting to MySQL.\n"
            "SELECT table_name\nFROM information_schema.tables\n"
            "WHERE table_schema = DATABASE()\nORDER BY table_name;"
        )
        self.blockCountChanged.connect(self.update_line_number_area_width)
        self.updateRequest.connect(self.update_line_number_area)
        self.cursorPositionChanged.connect(self.highlight_current_line)
        self.update_line_number_area_width(0)
        self.highlight_current_line()

    def line_number_area_width(self) -> int:
        digits = max(2, len(str(max(1, self.blockCount()))))
        return 18 + self.fontMetrics().horizontalAdvance("9") * digits

    def update_line_number_area_width(self, _):
        self.setViewportMargins(self.line_number_area_width(), 0, 0, 0)

    def update_line_number_area(self, rect, dy):
        if dy:
            self.line_number_area.scroll(0, dy)
        else:
            self.line_number_area.update(0, rect.y(), self.line_number_area.width(), rect.height())
        if rect.contains(self.viewport().rect()):
            self.update_line_number_area_width(0)

    def resizeEvent(self, event):
        super().resizeEvent(event)
        content = self.contentsRect()
        self.line_number_area.setGeometry(
            QRect(content.left(), content.top(), self.line_number_area_width(), content.height())
        )

    def paint_line_numbers(self, event):
        painter = QPainter(self.line_number_area)
        painter.fillRect(event.rect(), QColor("#0a111b"))
        block = self.firstVisibleBlock()
        number = block.blockNumber()
        top = int(self.blockBoundingGeometry(block).translated(self.contentOffset()).top())
        bottom = top + int(self.blockBoundingRect(block).height())
        while block.isValid() and top <= event.rect().bottom():
            if block.isVisible() and bottom >= event.rect().top():
                color = "#d2deed" if number == self.textCursor().blockNumber() else "#71839d"
                painter.setPen(QColor(color))
                painter.drawText(
                    0, top, self.line_number_area.width() - 8, self.fontMetrics().height(),
                    Qt.AlignmentFlag.AlignRight, str(number + 1),
                )
            block = block.next()
            top = bottom
            bottom = top + int(self.blockBoundingRect(block).height())
            number += 1

    def highlight_current_line(self):
        selection = QTextEdit.ExtraSelection()
        selection.format.setBackground(QColor("#122136"))
        selection.format.setProperty(QTextFormat.Property.FullWidthSelection, True)
        selection.cursor = self.textCursor()
        selection.cursor.clearSelection()
        self.setExtraSelections([selection] if not self.isReadOnly() else [])

    def keyPressEvent(self, event):
        if event.key() == Qt.Key.Key_Tab and not event.modifiers():
            self.insertPlainText("    ")
            return
        if event.key() in (Qt.Key.Key_Return, Qt.Key.Key_Enter) and not event.modifiers():
            indent = re.match(r"\s*", self.textCursor().block().text()).group(0)
            if self.textCursor().block().text().rstrip().endswith(("(", ",")):
                indent += "    "
            super().keyPressEvent(event)
            self.insertPlainText(indent)
            return
        super().keyPressEvent(event)
