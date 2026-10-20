"""Regression tests for incremental, scroll-triggered result paging."""

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QModelIndex, Qt
from PySide6.QtWidgets import QApplication

from mysql_editor.database import RESULT_PAGE_ROWS as RESULT_PAGE_SIZE
from mysql_editor.ui.main_window import MainWindow, ResultsFilterProxyModel, ResultsModel

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

def test_proxy_vertical_headers_keep_absolute_row_numbers_after_sorting():
    model = ResultsModel(headers=["id"], rows=[[9], [1], [5]])
    model.update(["id"], [[9], [1], [5]], base_offset=500)
    model.set_paging_state(total_rows=2_000)
    proxy = ResultsFilterProxyModel()
    proxy.setSourceModel(model)

    try:
        proxy.sort(0, Qt.SortOrder.AscendingOrder)
        assert [proxy.index(row, 0).data() for row in range(proxy.rowCount())] == ["1", "5", "9"]
        assert [proxy.headerData(row, Qt.Orientation.Vertical) for row in range(proxy.rowCount())] == [
            "502", "503", "501",
        ]
        # A partial source window must not be sorted in place, because page
        # offsets must continue to address the original fetch order in SQLite.
        assert [row[0] for row in model.rows] == [9, 1, 5]
        assert model.base_offset == 500
    finally:
        proxy.setSourceModel(None)
        proxy.deleteLater()
        model.deleteLater()
        _APP.processEvents()

def test_manual_page_action_can_load_earlier_rows_when_filter_hides_scrollbar():
    class Scrollbar:
        def __init__(self, maximum):
            self.maximum_value = maximum

        def maximum(self):
            return self.maximum_value

    class Grid:
        def __init__(self, maximum):
            self.scrollbar = Scrollbar(maximum)

        def verticalScrollBar(self):
            return self.scrollbar

    class Window:
        _current_result_id = "result"

        def __init__(self, *, start, end, total, scrollbar_maximum):
            self.item = {"result_id": "result", "row_count": total, "kind": "rows"}
            self.bounds = (start, end, total)
            self.result_grid = Grid(scrollbar_maximum)
            self.previous_requests = 0
            self.next_requests = 0

        def _result_item_by_id(self, result_id):
            return self.item if result_id == "result" else None

        def _result_window_bounds(self, _item):
            return self.bounds

        def fetch_previous_result_rows(self):
            self.previous_requests += 1

        def fetch_more_result_rows(self):
            self.next_requests += 1

    filtered = Window(start=5_000, end=10_000, total=50_000, scrollbar_maximum=0)
    MainWindow.fetch_result_page_manually(filtered)
    assert filtered.previous_requests == 1
    assert filtered.next_requests == 0

    ordinary = Window(start=5_000, end=10_000, total=50_000, scrollbar_maximum=300)
    MainWindow.fetch_result_page_manually(ordinary)
    assert ordinary.previous_requests == 0
    assert ordinary.next_requests == 1

    final_window = Window(start=45_000, end=50_000, total=50_000, scrollbar_maximum=0)
    MainWindow.fetch_result_page_manually(final_window)
    assert final_window.previous_requests == 1
    assert final_window.next_requests == 0

