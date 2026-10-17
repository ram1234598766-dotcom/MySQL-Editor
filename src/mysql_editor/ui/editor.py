"""SQL editor with line numbers, MySQL syntax highlighting and completion."""
from __future__ import annotations

import re

from PySide6.QtCore import QRect, QSize, QStringListModel, Qt
from PySide6.QtGui import (
    QColor,
    QFont,
    QPainter,
    QSyntaxHighlighter,
    QTextCharFormat,
    QTextCursor,
    QTextFormat,
)
from PySide6.QtWidgets import QCompleter, QPlainTextEdit, QTextEdit, QWidget


SQL_KEYWORDS = frozenset("""
ADD ALL ALTER ANALYZE AND AS ASC BEFORE BETWEEN BIGINT BINARY BOTH BY CALL CASCADE
CASE CHANGE CHAR CHARACTER CHECK COLLATE COLUMN COLUMNS COMMENT COMMIT CONDITION
CONSTRAINT CONTINUE CONVERT CREATE CROSS CUBE CUME_DIST CURRENT_DATE CURRENT_TIME
CURRENT_TIMESTAMP CURRENT_USER CURSOR DATABASE DATABASES DAY_HOUR DAY_MICROSECOND
DAY_MINUTE DAY_SECOND DEC DECIMAL DECLARE DEFAULT DELAYED DELETE DENSE_RANK DESC
DESCRIBE DETERMINISTIC DISTINCT DISTINCTROW DIV DOUBLE DROP DUAL EACH ELSE ELSEIF
EMPTY ENCLOSED END ESCAPE ESCAPED EXCEPT EXISTS EXIT EXPLAIN FALSE FETCH FIRST FLOAT
FOLLOWING FOR FORCE FOREIGN FROM FULLTEXT FUNCTION GENERATED GET GRANT GROUP GROUPING
HAVING HIGH_PRIORITY HOUR_MICROSECOND HOUR_MINUTE HOUR_SECOND IF IGNORE IN INDEX
INFILE INNER INOUT INSENSITIVE INSERT INT INTEGER INTERSECT INTERVAL INTO IO_AFTER_GTIDS
IO_BEFORE_GTIDS IS ITERATE JOIN JSON_TABLE KEY KEYS KILL LAG LAST_VALUE LATERAL LEAD
LEADING LEAVE LEFT LIKE LIMIT LINEAR LINES LOAD LOCALTIME LOCALTIMESTAMP LOCK LONG
LONGBLOB LONGTEXT LOOP LOW_PRIORITY MASTER_BIND MASTER_SSL_VERIFY_SERVER_CERT MATCH
MAXVALUE MEDIUMBLOB MEDIUMINT MEDIUMTEXT MIDDLEINT MINUTE_MICROSECOND MINUTE_SECOND
MOD MODIFIES NATURAL NOT NO_WRITE_TO_BINLOG NTH_VALUE NTILE NULL NUMERIC OF ON
OPTIMIZE OPTION OPTIONALLY OR ORDER OUT OUTER OUTFILE OVER PARTITION PERCENT_RANK
PRECISION PRIMARY PROCEDURE PURGE RANGE RANK READ READS READ_WRITE REAL RECURSIVE
REFERENCES REGEXP RELEASE RENAME REPEAT REPLACE REQUIRE RESIGNAL RESTRICT RETURN
REVOKE RIGHT RLIKE ROLE ROLLBACK ROLLUP ROW ROW_NUMBER ROWS SCHEMA SCHEMAS
SECOND_MICROSECOND SELECT SENSITIVE SEPARATOR SET SHOW SIGNAL SMALLINT SPATIAL SPECIFIC
SQL SQLEXCEPTION SQLSTATE SQLWARNING SQL_BIG_RESULT SQL_CALC_FOUND_ROWS SQL_SMALL_RESULT
SSL START STARTING STORED STRAIGHT_JOIN SYSTEM TABLE TABLES TERMINATED THEN TINYBLOB
TINYINT TINYTEXT TO TRAILING TRANSACTION TRIGGER TRUE UNDO UNION UNIQUE UNLOCK UNSIGNED
UPDATE USAGE USE USING UTC_DATE UTC_TIME UTC_TIMESTAMP VALUES VARBINARY VARCHAR
VARYING VIRTUAL WHEN WHERE WHILE WINDOW WITH WRITE XOR YEAR_MONTH ZEROFILL
""".split())

SQL_FUNCTIONS = frozenset("""
ABS ACOS ADDDATE ADDTIME AES_DECRYPT AES_ENCRYPT ANY_VALUE ASCII ASIN ATAN ATAN2 AVG
BENCHMARK BIN BINARY BINDING BIT_AND BIT_COUNT BIT_OR BIT_XOR CEIL CEILING CHAR
CHAR_LENGTH CHARACTER_LENGTH COALESCE COERCIBILITY COLLATION COMPRESS CONCAT CONCAT_WS
CONNECTION_ID CONV CONVERT_TZ COS COT COUNT CRC32 CURDATE CURRENT_ROLE CURTIME DATABASE
DATE DATE_ADD DATE_FORMAT DATE_SUB DATEDIFF DAY DAYNAME DAYOFMONTH DAYOFWEEK DAYOFYEAR
DECODE DEFAULT DEGREES ELT ENCODE ENCRYPT EXP EXPORT_SET EXTRACT FIELD FIND_IN_SET
FIRST_VALUE FLOOR FORMAT FOUND_ROWS FROM_BASE64 FROM_DAYS FROM_UNIXTIME GET_FORMAT
GREATEST GROUP_CONCAT HEX HOUR IF IFNULL INET_ATON INET_NTOA INET6_ATON INSTR JSON_ARRAY
JSON_ARRAYAGG JSON_CONTAINS JSON_EXTRACT JSON_OBJECT JSON_OBJECTAGG JSON_PRETTY JSON_QUOTE
JSON_SEARCH JSON_SET JSON_TYPE JSON_UNQUOTE JSON_VALID LCASE LEAST LEFT LENGTH LN LOAD_FILE
LOCALTIME LOCALTIMESTAMP LOCATE LOG LOG10 LOG2 LOWER LPAD LTRIM MAKEDATE MAKETIME MAKE_SET
MASTER_POS_WAIT MAX MD5 MICROSECOND MID MIN MINUTE MOD MONTH MONTHNAME NOW NULLIF OCT
OCTET_LENGTH ORD PASSWORD PERIOD_ADD PERIOD_DIFF PI POSITION POW POWER QUARTER QUOTE
RADIANS RAND REGEXP_REPLACE REPEAT REPLACE REVERSE RIGHT ROUND RPAD RTRIM SECOND SEC_TO_TIME
SESSION_USER SHA SHA1 SHA2 SIGN SIN SLEEP SOUNDEX SPACE SQRT STD STDDEV STDDEV_POP
STDDEV_SAMP STR_TO_DATE STRCMP SUBDATE SUBSTR SUBSTRING SUBSTRING_INDEX SUM SYSDATE SYSTEM_USER
TAN TIME TIME_FORMAT TIMEDIFF TIMESTAMP TIMESTAMPADD TIMESTAMPDIFF TO_BASE64 TRIM TRUNCATE
UCASE UNCOMPRESS UNHEX UNIX_TIMESTAMP UPPER USER UTC_DATE UTC_TIME UTC_TIMESTAMP UUID UUID_SHORT
VALUES VARIANCE VAR_POP VAR_SAMP VERSION WEEK WEEKDAY WEEKOFYEAR YEAR YEARWEEK
""".split())

SQL_COMPLETIONS = SQL_KEYWORDS | SQL_FUNCTIONS
_IDENTIFIER_COMPLETION = re.compile(r"^[A-Za-z_$][A-Za-z0-9_$]*$")
_BRACKET_PAIRS = {"(": ")", "[": "]", "{": "}"}
_CLOSING_BRACKETS = {close: open_ for open_, close in _BRACKET_PAIRS.items()}


def _sql_code_mask(text: str) -> bytearray:
    """Mark SQL code positions, excluding quotes and comments from bracket matching."""
    mask = bytearray(b"\x01" * len(text))
    index = 0
    while index < len(text):
        char = text[index]
        if char in ("'", '"', chr(96)):
            quote = char
            mask[index] = 0
            index += 1
            while index < len(text):
                mask[index] = 0
                if text[index] == "\\" and index + 1 < len(text):
                    mask[index + 1] = 0
                    index += 2
                    continue
                if text[index] == quote:
                    if index + 1 < len(text) and text[index + 1] == quote:
                        mask[index + 1] = 0
                        index += 2
                        continue
                    index += 1
                    break
                index += 1
            continue

        is_line_comment = char == "#" or (
            text.startswith("--", index)
            and (index + 2 >= len(text) or text[index + 2].isspace())
        )
        if is_line_comment:
            end = text.find("\n", index)
            end = len(text) if end < 0 else end
            mask[index:end] = b"\x00" * (end - index)
            index = end
            continue

        if text.startswith("/*", index):
            closing = text.find("*/", index + 2)
            end = len(text) if closing < 0 else closing + 2
            mask[index:end] = b"\x00" * (end - index)
            index = end
            continue

        index += 1
    return mask


def _python_index_from_utf16(text: str, utf16_position: int) -> int:
    """Translate a Qt cursor offset (UTF-16 code units) to a Python string index."""
    units = 0
    for index, char in enumerate(text):
        if units >= utf16_position:
            return index
        units += 2 if ord(char) > 0xFFFF else 1
    return len(text)


def _cursor_is_in_sql_code(text: str, cursor_position: int) -> bool:
    """Return whether the insertion point is outside SQL strings and comments."""
    prefix = text[:max(0, min(cursor_position, len(text)))]
    quote: str | None = None
    line_comment = False
    block_comment = False
    index = 0
    while index < len(prefix):
        char = prefix[index]
        if line_comment:
            if char == "\n":
                line_comment = False
            index += 1
            continue
        if block_comment:
            if prefix.startswith("*/", index):
                block_comment = False
                index += 2
            else:
                index += 1
            continue
        if quote is not None:
            if char == "\\" and index + 1 < len(prefix):
                index += 2
                continue
            if char == quote:
                if index + 1 < len(prefix) and prefix[index + 1] == quote:
                    index += 2
                    continue
                quote = None
            index += 1
            continue
        if char in ("'", '"', chr(96)):
            quote = char
            index += 1
            continue
        if char == "#" or (
            prefix.startswith("--", index)
            and (index + 2 >= len(prefix) or prefix[index + 2].isspace())
        ):
            line_comment = True
            index += 1
            continue
        if prefix.startswith("/*", index):
            block_comment = True
            index += 2
            continue
        index += 1
    return quote is None and not line_comment and not block_comment


def _matching_bracket_positions(text: str, cursor_position: int) -> tuple[int, int] | None:
    """Return the opening/closing bracket positions adjacent to the cursor, if paired."""
    left = cursor_position - 1
    right = cursor_position
    if 0 <= left < len(text) and text[left] in _BRACKET_PAIRS:
        candidate = left
    elif 0 <= right < len(text) and text[right] in _CLOSING_BRACKETS:
        candidate = right
    elif 0 <= right < len(text) and text[right] in _BRACKET_PAIRS:
        candidate = right
    elif 0 <= left < len(text) and text[left] in _CLOSING_BRACKETS:
        candidate = left
    else:
        return None

    code_mask = _sql_code_mask(text)
    if not code_mask[candidate]:
        return None

    char = text[candidate]
    if char in _BRACKET_PAIRS:
        stack = [char]
        for position in range(candidate + 1, len(text)):
            if not code_mask[position]:
                continue
            current = text[position]
            if current in _BRACKET_PAIRS:
                stack.append(current)
            elif current in _CLOSING_BRACKETS:
                if not stack or _BRACKET_PAIRS[stack[-1]] != current:
                    return None
                stack.pop()
                if not stack:
                    return (candidate, position)
        return None

    stack = [char]
    for position in range(candidate - 1, -1, -1):
        if not code_mask[position]:
            continue
        current = text[position]
        if current in _CLOSING_BRACKETS:
            stack.append(current)
        elif current in _BRACKET_PAIRS:
            if not stack or _BRACKET_PAIRS[current] != stack[-1]:
                return None
            stack.pop()
            if not stack:
                return (position, candidate)
    return None


class SqlHighlighter(QSyntaxHighlighter):
    """Comment-aware SQL highlighting, including comments spanning multiple lines."""

    def __init__(self, document):
        super().__init__(document)
        keyword = QTextCharFormat()
        keyword.setForeground(QColor("#37d6e7"))
        keyword.setFontWeight(QFont.Weight.DemiBold)
        alternatives = "|".join(re.escape(word) for word in sorted(SQL_KEYWORDS, key=len, reverse=True))
        self.rules = [(re.compile(r"\b(?:" + alternatives + r")\b", re.I), keyword)]

        string = QTextCharFormat()
        string.setForeground(QColor("#f6c56f"))
        self.rules.append((re.compile(r"'(?:''|\\.|[^'])*'|\"(?:\"\"|\\.|[^\"])*\""), string))

        number = QTextCharFormat()
        number.setForeground(QColor("#bd9cff"))
        self.rules.append((re.compile(r"\b\d+(?:\.\d+)?\b"), number))

        function = QTextCharFormat()
        function.setForeground(QColor("#69b7ff"))
        self.rules.append((re.compile(r"\b[A-Za-z_$][\w$]*(?=\s*\()"), function))

        comment = QTextCharFormat()
        comment.setForeground(QColor("#7f93ad"))
        comment.setFontItalic(True)
        self._comment_format = comment
        self.rules.append((re.compile(r"--(?=\s|$)[^\r\n]*|#[^\r\n]*"), comment))

    def highlightBlock(self, text: str) -> None:
        for pattern, style in self.rules:
            for match in pattern.finditer(text):
                self.setFormat(match.start(), match.end() - match.start(), style)
        self._highlight_block_comments(text)

    def _highlight_block_comments(self, text: str) -> None:
        start = 0
        if self.previousBlockState() == 1:
            end = text.find("*/")
            if end < 0:
                self.setFormat(0, len(text), self._comment_format)
                self.setCurrentBlockState(1)
                return
            self.setFormat(0, end + 2, self._comment_format)
            start = end + 2
        while True:
            opening = text.find("/*", start)
            if opening < 0:
                self.setCurrentBlockState(0)
                return
            closing = text.find("*/", opening + 2)
            if closing < 0:
                self.setFormat(opening, len(text) - opening, self._comment_format)
                self.setCurrentBlockState(1)
                return
            self.setFormat(opening, closing + 2 - opening, self._comment_format)
            start = closing + 2


class LineNumberArea(QWidget):
    def __init__(self, editor: SqlEditor):
        super().__init__(editor)
        self.editor = editor

    def sizeHint(self):
        return QSize(self.editor.line_number_area_width(), 0)

    def paintEvent(self, event):
        self.editor.paint_line_numbers(event)


class SqlEditor(QPlainTextEdit):
    """SQL editor with Ctrl+Space and inline MySQL/schema-name completion."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.line_number_area = LineNumberArea(self)
        self.highlighter = SqlHighlighter(self.document())
        self.setObjectName("sqlEditor")
        self.setAccessibleName("SQL query editor")
        self.setAccessibleDescription(
            "Write MySQL queries here. Press Ctrl+Space to open completion; Enter preserves "
            "indentation, and matching brackets are highlighted."
        )
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

        self._extra_completion_words: set[str] = set()
        self._completion_databases: set[str] = set()
        self._completion_tables: set[str] = set()
        self._completion_columns_by_table: dict[str, set[str]] = {}
        self._completion_active_schema = ""
        self._completion_model = QStringListModel(self)
        self._completer = QCompleter(self._completion_model, self)
        self._completer.setWidget(self)
        self._completer.setCompletionMode(QCompleter.CompletionMode.PopupCompletion)
        self._completer.setCaseSensitivity(Qt.CaseSensitivity.CaseInsensitive)
        self._completer.setFilterMode(Qt.MatchFlag.MatchStartsWith)
        self._completer.setMaxVisibleItems(14)
        self._completer.setWrapAround(False)
        self._completer.activated.connect(self.insert_completion)
        self._refresh_completions()

        self.blockCountChanged.connect(self.update_line_number_area_width)
        self.updateRequest.connect(self.update_line_number_area)
        self.cursorPositionChanged.connect(self.highlight_current_line)
        self.update_line_number_area_width(0)
        self.highlight_current_line()

    @staticmethod
    def _safe_identifiers(words) -> set[str]:
        return {
            str(word) for word in (words or ())
            if _IDENTIFIER_COMPLETION.fullmatch(str(word))
        }

    def set_completion_words(self, words) -> None:
        """Backwards-compatible setter for safe schema/result identifiers."""
        self._extra_completion_words = self._safe_identifiers(words)
        self._refresh_completions()

    def set_completion_context(
        self, *, databases=(), tables=(), columns_by_table=None,
        extra_words=(), active_schema: str = "",
    ) -> None:
        """Set bounded schema metadata used for context-sensitive suggestions."""
        self._completion_databases = self._safe_identifiers(databases)
        self._completion_tables = self._safe_identifiers(tables)
        self._completion_columns_by_table = {
            str(table): self._safe_identifiers(columns)
            for table, columns in (columns_by_table or {}).items()
            if _IDENTIFIER_COMPLETION.fullmatch(str(table))
        }
        self._completion_active_schema = str(active_schema or "")
        self._extra_completion_words = self._safe_identifiers(extra_words)
        self._refresh_completions()

    def _all_completion_words(self) -> set[str]:
        words = set(SQL_COMPLETIONS)
        words.update(self._extra_completion_words)
        words.update(self._completion_databases)
        words.update(self._completion_tables)
        for columns in self._completion_columns_by_table.values():
            words.update(columns)
        return words

    def completion_words(self) -> tuple[str, ...]:
        """Expose all available suggestions for regression tests and diagnostics."""
        return tuple(sorted(self._all_completion_words(), key=str.casefold))

    def _table_for_qualifier(self, qualifier: str) -> str | None:
        key = qualifier.casefold()
        for table in self._completion_columns_by_table:
            if table.casefold() == key:
                return table

        # Resolve aliases from the whole current SQL buffer. This also supports the
        # common editing order where SELECT columns are typed before FROM/JOIN.
        sql = self.toPlainText()
        reserved = {
            "JOIN", "LEFT", "RIGHT", "INNER", "OUTER", "CROSS", "STRAIGHT_JOIN",
            "WHERE", "ON", "USING", "GROUP", "ORDER", "HAVING", "LIMIT", "OFFSET",
            "UNION", "EXCEPT", "INTERSECT", "SET", "VALUES", "FOR", "LOCK",
        }
        table_pattern = re.compile(
            r"\b(?:FROM|JOIN)\s+"
            r"((?:[A-Za-z_$][A-Za-z0-9_$]*\s*\.\s*)?[A-Za-z_$][A-Za-z0-9_$]*)"
            r"(?:\s+(?:AS\s+)?([A-Za-z_$][A-Za-z0-9_$]*))?",
            re.IGNORECASE,
        )
        for match in table_pattern.finditer(sql):
            table_ref = re.sub(r"\s", "", match.group(1)).split(".")[-1]
            alias = match.group(2)
            if table_ref.casefold() == key:
                return table_ref
            if alias and alias.upper() not in reserved and alias.casefold() == key:
                return table_ref
        return None

    def _referenced_tables_in_current_statement(self) -> set[str]:
        """Return known table names referenced by the statement around the cursor.

        This intentionally handles common FROM/JOIN/UPDATE/INTO contexts rather than
        attempting to parse the full MySQL grammar. Strings and comments are masked
        before scanning so their contents cannot introduce false table references.
        """
        sql = self.toPlainText()
        cursor_position = self.textCursor().position()
        code_mask = _sql_code_mask(sql)
        code_sql = "".join(
            char if code_mask[position] else " "
            for position, char in enumerate(sql)
        )

        start = 0
        for position in range(min(cursor_position, len(sql))):
            if sql[position] == ";" and code_mask[position]:
                start = position + 1
        end = len(sql)
        for position in range(min(cursor_position, len(sql)), len(sql)):
            if sql[position] == ";" and code_mask[position]:
                end = position
                break
        statement = code_sql[start:end]

        reserved_aliases = {
            "ALL", "AND", "AS", "BY", "CROSS", "EXCEPT", "FOR", "GROUP",
            "HAVING", "INNER", "INTERSECT", "JOIN", "LEFT", "LIMIT", "LOCK",
            "OFFSET", "ON", "OR", "ORDER", "OUTER", "RIGHT", "SET", "UNION",
            "USE", "USING", "WHERE", "WINDOW",
        }
        table_pattern = re.compile(
            r"\b(?:FROM|JOIN|UPDATE|INTO|REFERENCES|TABLE)\s+"
            r"(?:`?([A-Za-z_$][A-Za-z0-9_$]*)`?\s*\.\s*)?"
            r"`?([A-Za-z_$][A-Za-z0-9_$]*)`?"
            r"(?:\s+(?:AS\s+)?`?([A-Za-z_$][A-Za-z0-9_$]*)`?)?",
            re.IGNORECASE,
        )
        known_tables = {
            name.casefold(): name for name in self._completion_columns_by_table
        }
        referenced: set[str] = set()
        for match in table_pattern.finditer(statement):
            name = known_tables.get(match.group(2).casefold())
            if name is not None:
                referenced.add(name.casefold())
            alias = match.group(3)
            if alias and alias.upper() not in reserved_aliases and name is not None:
                referenced.add(name.casefold())
        return referenced

    def _context_completion_words(self) -> tuple[str, ...]:
        """Choose suggestions for the SQL clause around the cursor without parsing all MySQL."""
        all_words = self._all_completion_words()
        before = self.toPlainText()[:self.textCursor().position()]
        database_context = re.search(r"\bUSE\s+[A-Za-z_$0-9]*$", before, re.IGNORECASE)
        if database_context:
            return tuple(sorted(self._completion_databases or all_words, key=str.casefold))

        qualified = re.search(
            r"([A-Za-z_$][A-Za-z0-9_$]*)\s*\.\s*[A-Za-z0-9_$]*$",
            before,
        )
        if qualified:
            qualifier = qualified.group(1)
            table = self._table_for_qualifier(qualifier)
            if table:
                columns = next(
                    (value for name, value in self._completion_columns_by_table.items()
                     if name.casefold() == table.casefold()),
                    set(),
                )
                if columns:
                    return tuple(sorted(columns, key=str.casefold))
            if (self._completion_active_schema and
                    qualifier.casefold() == self._completion_active_schema.casefold()):
                return tuple(sorted(self._completion_tables or all_words, key=str.casefold))
            if any(db.casefold() == qualifier.casefold() for db in self._completion_databases):
                return tuple(sorted(all_words, key=str.casefold))

        table_context = re.search(
            r"\b(?:FROM|JOIN|UPDATE|INTO|REFERENCES|TABLE)\s+(?:[A-Za-z_$][A-Za-z0-9_$]*)?$",
            before,
            re.IGNORECASE,
        )
        if table_context:
            tables = self._completion_tables | self._completion_databases
            return tuple(sorted(tables or all_words, key=str.casefold))

        column_context = re.search(
            r"\b(?:SELECT|WHERE|ON|AND|OR|HAVING|SET|BY|RETURNING)\s+[A-Za-z_$0-9]*$",
            before,
            re.IGNORECASE,
        )
        if column_context:
            columns = set(self._extra_completion_words)
            referenced_tables = self._referenced_tables_in_current_statement()
            for table, table_columns in self._completion_columns_by_table.items():
                if not referenced_tables or table.casefold() in referenced_tables:
                    columns.update(table_columns)
            return tuple(sorted(set(SQL_COMPLETIONS) | columns, key=str.casefold))

        return tuple(sorted(all_words, key=str.casefold))

    def _refresh_completions(self) -> None:
        self._completion_model.setStringList(
            sorted(self._all_completion_words(), key=str.casefold)
        )

    def _completion_prefix(self) -> str:
        cursor = self.textCursor()
        cursor.select(QTextCursor.SelectionType.WordUnderCursor)
        return cursor.selectedText()

    def _show_completion(self, force: bool = False) -> None:
        prefix = self._completion_prefix()
        if not force and len(prefix) < 2:
            self._completer.popup().hide()
            return
        self._completion_model.setStringList(list(self._context_completion_words()))
        self._completer.setCompletionPrefix(prefix)
        popup = self._completer.popup()
        if self._completer.completionCount() == 0:
            popup.hide()
            return
        popup.setCurrentIndex(self._completer.completionModel().index(0, 0))
        rectangle = self.cursorRect()
        rectangle.setWidth(
            popup.sizeHintForColumn(0) + popup.verticalScrollBar().sizeHint().width()
        )
        self._completer.complete(rectangle)

    def insert_completion(self, completion: str) -> None:
        if self._completer.widget() is not self:
            return
        cursor = self.textCursor()
        cursor.select(QTextCursor.SelectionType.WordUnderCursor)
        cursor.insertText(completion)
        self.setTextCursor(cursor)

    def _accept_current_completion(self) -> bool:
        """Insert the selected suggestion, with a deterministic first-item fallback."""
        completion_model = self._completer.completionModel()
        index = self._completer.popup().currentIndex()
        if not index.isValid():
            index = completion_model.index(0, 0)
        if not index.isValid():
            self._completer.popup().hide()
            return False
        value = index.data()
        if value is None:
            self._completer.popup().hide()
            return False
        self.insert_completion(str(value))
        self._completer.popup().hide()
        return True

    def _insert_newline_with_indentation(self) -> None:
        """Carry leading whitespace and indent one level after common SQL block openers."""
        cursor = self.textCursor()
        current_line = cursor.block().text()
        prefix = current_line[:cursor.positionInBlock()]
        leading = re.match(r"[ \t]*", current_line).group(0)
        trimmed = prefix.rstrip()
        opens_block = trimmed.endswith("(") or bool(re.search(
            r"\b(?:BEGIN|THEN|ELSE|CASE|LOOP|REPEAT|WHILE|DO)\s*$",
            trimmed,
            re.IGNORECASE,
        ))
        indent = leading + ("    " if opens_block else "")
        cursor.beginEditBlock()
        cursor.insertText("\n" + indent)
        cursor.endEditBlock()
        self.setTextCursor(cursor)
        self.ensureCursorVisible()
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
        if self.isReadOnly():
            self.setExtraSelections([])
            return

        selections = []
        line_selection = QTextEdit.ExtraSelection()
        line_selection.format.setBackground(QColor("#122136"))
        line_selection.format.setProperty(QTextFormat.Property.FullWidthSelection, True)
        line_selection.cursor = self.textCursor()
        line_selection.cursor.clearSelection()
        selections.append(line_selection)

        matched = _matching_bracket_positions(
            self.toPlainText(), self.textCursor().position()
        )
        if matched is not None:
            for position in matched:
                bracket_selection = QTextEdit.ExtraSelection()
                bracket_selection.format.setBackground(QColor("#2B526D"))
                bracket_selection.format.setForeground(QColor("#F5FAFF"))
                bracket_selection.format.setFontWeight(QFont.Weight.Bold)
                bracket_selection.cursor = QTextCursor(self.document())
                bracket_selection.cursor.setPosition(position)
                bracket_selection.cursor.setPosition(
                    position + 1, QTextCursor.MoveMode.KeepAnchor
                )
                selections.append(bracket_selection)

        self.setExtraSelections(selections)

    def _handle_bracket_typing(self, event) -> bool:
        """Auto-pair SQL brackets in code, wrap selections, and skip existing closers."""
        if self.isReadOnly():
            return False
        modifiers = event.modifiers()
        forbidden = (
            Qt.KeyboardModifier.ControlModifier
            | Qt.KeyboardModifier.AltModifier
            | Qt.KeyboardModifier.MetaModifier
        )
        if modifiers & forbidden:
            return False

        typed = event.text()
        if typed not in _BRACKET_PAIRS and typed not in _CLOSING_BRACKETS:
            return False

        cursor = self.textCursor()
        text = self.toPlainText()
        qt_position = cursor.selectionStart() if cursor.hasSelection() else cursor.position()
        position = _python_index_from_utf16(text, qt_position)
        if not _cursor_is_in_sql_code(text, position):
            return False

        if typed in _BRACKET_PAIRS:
            closing = _BRACKET_PAIRS[typed]
            cursor.beginEditBlock()
            if cursor.hasSelection():
                start = cursor.selectionStart()
                end = cursor.selectionEnd()
                cursor.setPosition(end)
                cursor.insertText(closing)
                cursor.setPosition(start)
                cursor.insertText(typed)
                cursor.setPosition(end + 1)
            else:
                cursor.insertText(typed + closing)
                cursor.setPosition(qt_position + 1)
            cursor.endEditBlock()
            self.setTextCursor(cursor)
            self.ensureCursorVisible()
            self.highlight_current_line()
            return True

        # Typing a closer already placed by pairing moves over it instead of duplicating it.
        if position < len(text) and text[position] == typed:
            code_mask = _sql_code_mask(text)
            if code_mask[position]:
                cursor.setPosition(qt_position + 1)
                self.setTextCursor(cursor)
                self.highlight_current_line()
                return True
        return False

    def keyPressEvent(self, event):
        key = event.key()
        popup = self._completer.popup()
        if key == Qt.Key.Key_Space and event.modifiers() & Qt.KeyboardModifier.ControlModifier:
            self._show_completion(force=True)
            event.accept()
            return
        if popup.isVisible():
            if key == Qt.Key.Key_Escape:
                popup.hide()
                event.accept()
                return
            if key in (Qt.Key.Key_Enter, Qt.Key.Key_Return, Qt.Key.Key_Tab):
                self._accept_current_completion()
                event.accept()
                return
            if key == Qt.Key.Key_Backtab:
                popup.hide()
                event.accept()
                return
        if not popup.isVisible() and self._handle_bracket_typing(event):
            event.accept()
            return
        if (
            key in (Qt.Key.Key_Enter, Qt.Key.Key_Return)
            and not self.textCursor().hasSelection()
        ):
            self._insert_newline_with_indentation()
            event.accept()
            return
        super().keyPressEvent(event)
        typed = event.text()
        if typed and (typed[-1].isalnum() or typed[-1] in "_$"):
            self._show_completion()
