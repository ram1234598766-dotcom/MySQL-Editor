"""Result-grid copy and cell-detail formatting helpers."""
from __future__ import annotations

import csv
import io
from collections.abc import Mapping, Sequence
from typing import Any

NULL_COPY_MARKER = "NULL"


def _tsv_text(rows: Sequence[Sequence[Any]]) -> str:
    stream = io.StringIO(newline="")
    writer = csv.writer(stream, delimiter="\t", quotechar='"', lineterminator="\n")
    for row in rows:
        writer.writerow([NULL_COPY_MARKER if value is None else str(value) for value in row])
    return stream.getvalue().removesuffix("\n")


def selected_cells_tsv(cells: Mapping[tuple[int, int], Any]) -> str:
    """Serialize selected display coordinates as a rectangular TSV clipboard payload."""
    if not cells:
        return ""
    min_row = min(row for row, _ in cells)
    max_row = max(row for row, _ in cells)
    min_column = min(column for _, column in cells)
    max_column = max(column for _, column in cells)
    matrix = [
        [cells.get((row, column), "") for column in range(min_column, max_column + 1)]
        for row in range(min_row, max_row + 1)
    ]
    return _tsv_text(matrix)


def rows_tsv(rows: Sequence[Sequence[Any]]) -> str:
    """Serialize complete result rows for clipboard, marking SQL NULL explicitly."""
    return _tsv_text(rows)


def column_headers_tsv(headers: Sequence[str]) -> str:
    """Serialize column names as a single clipboard row."""
    return _tsv_text([headers])


def cell_detail_text(value: Any) -> str:
    """Return a faithful human-readable detail value; SQL NULL is distinct from empty text."""
    return "SQL NULL (no value)" if value is None else str(value)
