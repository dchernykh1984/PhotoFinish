"""The input and output lists: crossing lines as rows that follow the video.

Each list marks the line nearest the video's time and keeps it in view (FR-012);
picking a line asks the window to move the video to that line's time. Rows carry
what the referee must notice: an input line the chronometer changed since it was
taken, an output line whose input line is gone, how an output time was had.
"""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass, replace

from PySide6.QtCore import (
    QAbstractTableModel,
    QModelIndex,
    QPersistentModelIndex,
    Qt,
    Signal,
)
from PySide6.QtGui import QColor, QFont
from PySide6.QtWidgets import QAbstractItemView, QHeaderView, QTableView

from app.input_follow import InputLine
from app.lines import parse_line
from app.output_list import OutputLine

_METHODS = {
    "frame": "from a frame",
    "interpolated": "between two frames",
    "hand": "picked by hand",
    "typed": "typed",
    "outside": "found in the file",
}
_WARN = QColor(255, 214, 140)
_NEAR = QColor(190, 220, 255)

type ModelIndex = QModelIndex | QPersistentModelIndex


@dataclass(frozen=True)
class Row:
    number: str
    time: str
    action: str
    note: str
    ms: int | None  # the line's time, on the line scale
    warn: bool = False
    key: object = None  # the line it shows: the choice follows it, not its row


def input_rows(lines: list[InputLine]) -> list[Row]:
    rows, seen = [], Counter[str]()
    for line in lines:
        note = "" if line.taken is None else f"changed; taken as {line.taken}"
        row = _row(line.text, note, warn=line.taken is not None)
        seen[line.text] += 1  # twin lines: the first, the second...
        rows.append(replace(row, key=(line.text, seen[line.text])))
    return rows


def output_rows(lines: list[OutputLine]) -> list[Row]:
    rows = []
    for line in lines:
        notes = [_METHODS.get(line.method, "")]
        if line.removed_from_input:
            notes.append("removed from input")
        row = _row(line.text, "; ".join(n for n in notes if n), line.removed_from_input)
        if row.ms is None:
            row = replace(row, note=f"no time; {row.note}", warn=True)
        rows.append(replace(row, key=id(line)))
    return rows


def _row(text: str, note: str, warn: bool) -> Row:
    crossing = parse_line(text)
    fields = text.split("#")
    shown = fields[1] if len(fields) > 1 else ""
    if crossing.ms is not None:
        shown = shown.strip().partition(" ")[
            2
        ]  # the time of day; the day is the race's
    return Row(crossing.number, shown, crossing.action, note, crossing.ms, warn)


class LinesModel(QAbstractTableModel):
    HEADERS = ("Number", "Time", "Action", "Note")

    def __init__(self) -> None:
        super().__init__()
        self.rows: list[Row] = []
        self.near: int | None = None

    def set_rows(self, rows: list[Row]) -> None:
        self.beginResetModel()
        self.rows, self.near = rows, None
        self.endResetModel()

    def set_near(self, row: int | None) -> None:
        old, self.near = self.near, row
        for changed in (old, row):
            if changed is not None:
                self.dataChanged.emit(self.index(changed, 0), self.index(changed, 3))

    def rowCount(self, parent: ModelIndex = QModelIndex()) -> int:  # noqa: B008, N802
        return 0 if parent.isValid() else len(self.rows)

    def columnCount(self, parent: ModelIndex = QModelIndex()) -> int:  # noqa: B008, N802
        return 0 if parent.isValid() else len(self.HEADERS)

    def data(
        self, index: ModelIndex, role: int = Qt.ItemDataRole.DisplayRole
    ) -> object:
        row = self.rows[index.row()]
        if role == Qt.ItemDataRole.DisplayRole:
            return (row.number, row.time, row.action, row.note)[index.column()]
        if role == Qt.ItemDataRole.ToolTipRole:
            return row.note or None
        if role == Qt.ItemDataRole.BackgroundRole:
            if index.row() == self.near:
                return _NEAR
            return _WARN if row.warn else None
        if role == Qt.ItemDataRole.FontRole and index.row() == self.near:
            font = QFont()
            font.setBold(True)
            return font
        return None

    def headerData(  # noqa: N802 - Qt's name
        self,
        section: int,
        orientation: Qt.Orientation,
        role: int = Qt.ItemDataRole.DisplayRole,
    ) -> object:
        if (
            orientation == Qt.Orientation.Horizontal
            and role == Qt.ItemDataRole.DisplayRole
        ):
            return self.HEADERS[section]
        return None


class LinesView(QTableView):
    """A list of crossings; picking a line asks for the video at its time."""

    picked = Signal(object)  # the line's time on the line scale, ms

    def __init__(self) -> None:
        super().__init__()
        self.lines = LinesModel()
        self.setModel(self.lines)
        self.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.verticalHeader().hide()
        header = self.horizontalHeader()
        header.setSectionResizeMode(QHeaderView.ResizeMode.ResizeToContents)
        header.setStretchLastSection(True)
        self.clicked.connect(self._pick)

    def show_rows(self, rows: list[Row]) -> None:
        """New rows; the line chosen stays chosen wherever it moved, and nothing is
        chosen once it is gone."""
        chosen = self.chosen()
        key = None if chosen is None else self.lines.rows[chosen].key
        self.lines.set_rows(rows)
        found = next(
            (i for i, row in enumerate(rows) if key is not None and row.key == key),
            None,
        )
        if found is None:
            self.clearSelection()
        else:
            self.selectRow(found)

    def chosen(self) -> int | None:
        rows = self.selectionModel().selectedRows()
        return rows[0].row() if rows else None

    def follow(self, line_ms: int) -> None:
        """Mark the line nearest ``line_ms`` and bring it into view."""
        timed = [
            (abs(row.ms - line_ms), i)
            for i, row in enumerate(self.lines.rows)
            if row.ms is not None
        ]
        near = min(timed)[1] if timed else None
        if near != self.lines.near:
            self.lines.set_near(near)
            if near is not None:
                self.scrollTo(
                    self.lines.index(near, 0),
                    QAbstractItemView.ScrollHint.EnsureVisible,
                )

    def _pick(self, index: QModelIndex) -> None:
        ms = self.lines.rows[index.row()].ms
        if ms is not None:
            self.picked.emit(ms)
