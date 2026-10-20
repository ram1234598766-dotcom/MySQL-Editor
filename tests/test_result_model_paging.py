"""Regression tests for incremental, scroll-triggered result paging."""

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QModelIndex, Qt
from PySide6.QtWidgets import QApplication

from mysql_editor.database import RESULT_PAGE_ROWS as RESULT_PAGE_SIZE
from mysql_editor.ui.main_window import ResultsFilterProxyModel, ResultsModel

_APP = QApplication.instance() or QApplication([])


def test_result_model_fetches_one_page_at_a_time_without_model_reset():
    model = ResultsModel(headers=["id"], rows=[[0], [1]])
    model.set_paging_state(total_rows=5)
    requests = []
    inserted = []
    resets = []
    model.more_rows_requested.connect(lambda: requests.append(len(model.rows)))
    model.rowsInserted.connect(
        lambda _parent, first, last: inserted.append((first, last))
    )
    model.modelReset.connect(lambda: resets.append(True))

    try:
        assert model.canFetchMore(QModelIndex()) is True
        model.fetchMore(QModelIndex())
        assert requests == [2]
        assert model.canFetchMore(QModelIndex()) is False

        # A pending request is not dispatched a second time.
        model.fetchMore(QModelIndex())
        assert requests == [2]

        model.append_rows([[2], [3]])
        model.set_paging_state(pending=False)
        assert model.rowCount() == 4
        assert model.canFetchMore(QModelIndex()) is True
        assert inserted == [(2, 3)]

        model.fetchMore(QModelIndex())
        assert requests == [2, 4]
        model.append_rows([[4]])
        model.set_paging_state(total_rows=5, pending=False)

        assert model.rowCount() == 5
        assert model.data(model.index(4, 0)) == "4"
        assert model.canFetchMore(QModelIndex()) is False
        assert inserted == [(2, 3), (4, 4)]
        assert resets == []
    finally:
        model.deleteLater()
        _APP.processEvents()


def test_result_model_does_not_fetch_for_child_indexes_or_after_failure():
    model = ResultsModel(headers=["id"], rows=[[1]])
    model.set_paging_state(total_rows=10)
    requests = []
    model.more_rows_requested.connect(lambda: requests.append(True))

    try:
        assert model.canFetchMore(model.index(0, 0)) is False
        model.fetchMore(model.index(0, 0))
        assert requests == []

        model.set_paging_state(available=False)
        assert model.canFetchMore(QModelIndex()) is False
        model.fetchMore(QModelIndex())
        assert requests == []
    finally:
        model.deleteLater()
        _APP.processEvents()


def test_filter_proxy_forwards_fetch_more_to_source_model():
    model = ResultsModel(headers=["id"], rows=[[0], [1]])
    model.set_paging_state(total_rows=8)
    proxy = ResultsFilterProxyModel()
    proxy.setSourceModel(model)
    requests = []
    model.more_rows_requested.connect(lambda: requests.append(len(model.rows)))

    try:
        assert proxy.canFetchMore(QModelIndex()) is True
        proxy.fetchMore(QModelIndex())
        assert requests == [2]
        assert model.canFetchMore(QModelIndex()) is False
    finally:
        proxy.setSourceModel(None)
        proxy.deleteLater()
        model.deleteLater()
        _APP.processEvents()

def test_result_model_evicts_oldest_rows_and_preserves_absolute_row_numbers():
    retained = ResultsModel.MAX_RETAINED_ROWS
    model = ResultsModel(headers=["id"], rows=[[index] for index in range(retained)])
    model.set_paging_state(total_rows=100_000)
    removed_ranges = []
    model.rowsRemoved.connect(lambda _parent, first, last: removed_ranges.append((first, last)))

    try:
        evicted = model.append_rows(
            [[index] for index in range(retained, retained + RESULT_PAGE_SIZE)]
        )

        assert evicted == RESULT_PAGE_SIZE
        assert model.rowCount() == retained
        assert len(model.rows) == retained
        assert model.base_offset == RESULT_PAGE_SIZE
        assert model.rows[0] == [RESULT_PAGE_SIZE]
        assert model.rows[-1] == [retained + RESULT_PAGE_SIZE - 1]
        assert model.headerData(0, Qt.Orientation.Vertical) == str(RESULT_PAGE_SIZE + 1)
        assert model.headerData(retained - 1, Qt.Orientation.Vertical) == str(retained + RESULT_PAGE_SIZE)
        assert model.canFetchPrevious() is True
        assert model.canFetchMore() is True
        assert removed_ranges == [(0, RESULT_PAGE_SIZE - 1)]
    finally:
        model.deleteLater()
        _APP.processEvents()


def test_result_model_prepends_previous_page_and_evicts_newest_rows():
    retained = ResultsModel.MAX_RETAINED_ROWS
    start = 4_000
    model = ResultsModel(
        headers=["id"],
        rows=[[index] for index in range(start, start + retained)],
    )
    model.update(
        ["id"],
        [[index] for index in range(start, start + retained)],
        base_offset=start,
    )
    model.set_paging_state(total_rows=100_000)

    try:
        evicted = model.prepend_rows(
            [[index] for index in range(start - RESULT_PAGE_SIZE, start)],
            start_offset=start - RESULT_PAGE_SIZE,
        )

        assert evicted == RESULT_PAGE_SIZE
        assert model.rowCount() == retained
        assert model.base_offset == start - RESULT_PAGE_SIZE
        assert model.rows[0] == [start - RESULT_PAGE_SIZE]
        assert model.rows[-1] == [start + retained - RESULT_PAGE_SIZE - 1]
        assert model.headerData(0, Qt.Orientation.Vertical) == str(start - RESULT_PAGE_SIZE + 1)
        assert model.headerData(retained - 1, Qt.Orientation.Vertical) == str(start + retained - RESULT_PAGE_SIZE)
        assert model.canFetchPrevious() is True
        assert model.canFetchMore() is True
    finally:
        model.deleteLater()
        _APP.processEvents()


def test_result_model_previous_page_signal_is_single_flight_and_offset_aware():
    model = ResultsModel(headers=["id"], rows=[[index] for index in range(100, 200)])
    model.update(["id"], [[index] for index in range(100, 200)], base_offset=100)
    model.set_paging_state(total_rows=10_000)
    requests = []
    model.previous_rows_requested.connect(lambda: requests.append(model.base_offset))

    try:
        assert model.canFetchPrevious() is True
        model.fetchPrevious()
        assert requests == [100]
        assert model.canFetchPrevious() is False
        model.fetchPrevious()
        assert requests == [100]

        model.set_paging_state(pending=False)
        model.update(["id"], [[index] for index in range(20)])
        assert model.canFetchPrevious() is False
    finally:
        model.deleteLater()
        _APP.processEvents()

