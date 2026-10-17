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


def cell_copy_text(value: Any) -> str:
    """Return a scalar clipboard payload, using the existing explicit SQL NULL marker."""
    return NULL_COPY_MARKER if value is None else str(value)


def result_filter_message(
    query: str,
    visible_rows: int,
    preview_rows: int,
    fetched_rows: int,
) -> str:
    """Describe quick-filter matches without confusing the visible preview with CSV rows."""
    term = str(query or "").strip()
    if not term:
        return ""

    preview_count = max(0, int(preview_rows))
    fetched_count = max(preview_count, int(fetched_rows))
    visible_count = max(0, min(int(visible_rows), preview_count))
    if visible_count == 0:
        return (
            f"No rows in the visible preview match {term!r}. "
            f"{preview_count:,} preview row(s) checked; CSV export still includes "
            f"all {fetched_count:,} fetched row(s)."
        )
    return (
        f"Quick filter: {visible_count:,} of {preview_count:,} preview row(s) match. "
        f"CSV export still includes all {fetched_count:,} fetched row(s)."
    )


def column_width_samples(
    headers: Sequence[Any],
    rows: Sequence[Sequence[Any]],
    *,
    max_sample_rows: int = 32,
    max_chars: int = 160,
) -> list[list[str]]:
    """Prepare bounded display samples for column sizing without scanning whole results.

    Sampling is capped even if callers pass very large values. Long cell contents are
    truncated for measuring; the full value remains in the result model and cell details.
    """
    try:
        sample_limit = min(64, max(0, int(max_sample_rows)))
    except (TypeError, ValueError, OverflowError):
        sample_limit = 32
    try:
        char_limit = min(512, max(16, int(max_chars)))
    except (TypeError, ValueError, OverflowError):
        char_limit = 160

    def display_sample(value: Any) -> str:
        text = "(NULL)" if value is None else str(value)
        return text if len(text) <= char_limit else text[:char_limit] + "…"

    samples = [[display_sample(header)] for header in headers]
    for row in list(rows[:sample_limit]):
        for column in range(len(samples)):
            if column < len(row):
                samples[column].append(display_sample(row[column]))
    return samples


def result_picker_label(item: dict, result_index: int) -> str:
    """Label a result with its script statement and warning count when available."""
    try:
        display_index = max(1, int(result_index))
    except (TypeError, ValueError, OverflowError):
        display_index = 1
    try:
        row_count = max(0, int(item.get("row_count", 0) or 0))
    except (TypeError, ValueError, OverflowError):
        row_count = 0
    kind = str(item.get("kind", "result") or "result").title()
    prefix = ""
    try:
        statement_index = int(item.get("statement_index", 0) or 0)
        statement_count = int(item.get("statement_count", 0) or 0)
    except (TypeError, ValueError, OverflowError):
        statement_index, statement_count = 0, 0
    if statement_index > 0:
        if statement_count >= statement_index:
            prefix = f"Statement {statement_index} of {statement_count} · "
        else:
            prefix = f"Statement {statement_index} · "
    label = f"{prefix}Result {display_index} · {kind} · {row_count:,} row(s)"
    try:
        warning_count = max(0, int(item.get("warning_count", 0) or 0))
    except (TypeError, ValueError, OverflowError):
        warning_count = 0
    if warning_count:
        label += f" · {warning_count:,} warning(s)"
    return label


def result_summary_message(item: dict, preview_rows: int, fetched_rows: int) -> str:
    """Describe a row result, status result, or error without confusing their meanings."""
    kind = str(item.get("kind", "result")).casefold()
    preview_count = max(0, int(preview_rows))
    fetched_count = max(preview_count, int(fetched_rows))

    if kind == "rows":
        if fetched_count == 0:
            return "Query completed successfully. No rows were returned."
        message = f"Rows result · {fetched_count:,} row(s) fetched."
        if item.get("preview_truncated") or fetched_count > preview_count:
            message += (
                f" Showing first {preview_count:,}; CSV export includes all "
                f"{fetched_count:,} fetched row(s)."
            )
        return message

    if kind == "status":
        try:
            affected = max(0, int(item.get("affected_rows", 0) or 0))
        except (TypeError, ValueError):
            affected = 0
        if affected == 0:
            return "Statement completed. No rows were affected."
        return f"Statement completed. {affected:,} row(s) affected."

    if kind == "error":
        return "Statement failed. Review the error details in this result."
    return f"{kind.title()} result · {fetched_count:,} row(s) received."
