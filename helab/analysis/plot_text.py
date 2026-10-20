"""Plot titles and notes that fit their plot: ``WrapLabel`` wraps a title to the width its layout
gives it (a pyqtgraph ``LabelItem`` never wraps: its unwrapped width became the layout's minimum,
so a long title pushed the axes out of a narrow dock), and the HTML helpers write each line the
same way in every bundled plot: escaped, one note per line, and whatever follows a "⚠" in amber
(``AMBER``, shared with the rest of the app)."""
from __future__ import annotations

import html
import re
from typing import Any, Iterable

import pyqtgraph as pg
from PyQt6 import sip
from PyQt6.QtCore import QRectF, Qt, QTimer
from PyQt6.QtGui import QTextOption

from helab.utils.colours import AMBER

WARNING = "⚠"
TRAILING_DETAIL = re.compile(r"\s*\([^()]*\)$")
# The narrowest a title gets before its words break anywhere: about one short word.
MIN_TITLE_WIDTH = 60.0
ALIGNMENTS = {"left": Qt.AlignmentFlag.AlignLeft, "center": Qt.AlignmentFlag.AlignHCenter,
              "right": Qt.AlignmentFlag.AlignRight}

__all__ = ["AMBER", "WrapLabel", "add_label", "amber_html", "line_html", "lines_html", "notes_html",
           "set_plot_title"]


def amber_html(text: str) -> str:
    """``text``, escaped, in amber."""
    return f'<span style="color: {AMBER}">{html.escape(text)}</span>'


def line_html(line: str) -> str:
    """One title line, escaped; from its first "⚠" on, amber (the titles put their warnings last)."""
    at = line.find(WARNING)
    if at < 0:
        return html.escape(line)
    head = line[:at]
    return html.escape(head) + amber_html(line[at:])


def lines_html(lines: Iterable[str]) -> str:
    """Title lines, one per ``<br>`` (empty ones left out)."""
    return "<br>".join(line_html(line) for line in lines if line)


def notes_html(notes: Iterable[Any], short: bool = False) -> str:
    """Notes in amber, escaped, each on a line of its own after a ``<br>`` ("" for none);
    ``short``: without a closing parenthesis's details (the dock's record keeps them whole)."""
    return "".join(f"<br>{amber_html(short_note(str(note)) if short else str(note))}" for note in notes if note)


def short_note(note: str) -> str:
    """``the weights did not settle in 10 rounds (moved up to 0.8 SE)`` → ``… in 10 rounds``."""
    return TRAILING_DETAIL.sub("", note) or note


class WrapLabel(pg.LabelItem):  # type: ignore[misc]
    """A ``LabelItem`` that wraps its text to the width its layout gives it, and asks for the
    height that takes: its minimum width is a short word's, its preferred width the text's
    unwrapped width, so a wide plot still shows each line whole."""

    def __init__(self, text: str = " ", parent: Any = None, **args: Any) -> None:
        self._wrap_width = -1.0
        self._natural_width = 0.0
        self._refit_pending = False
        super().__init__(text, parent, **args)
        option = QTextOption(ALIGNMENTS.get(str(self.opts.get("justify", "center")), Qt.AlignmentFlag.AlignHCenter))
        option.setWrapMode(QTextOption.WrapMode.WrapAtWordBoundaryOrAnywhere)
        document = self.item.document()
        assert document is not None
        document.setDefaultTextOption(option)

    def setText(self, text: str, **args: Any) -> None:
        self.item.setTextWidth(-1)  # Unwrapped, to measure its natural width.
        self._wrap_width = -1.0
        super().setText(text, **args)
        self._natural_width = float(self.item.boundingRect().width())
        width = float(self.size().width())
        if width > 0:
            self._wrap(width)

    def _wrap(self, width: float) -> None:
        # Never narrower than the minimum: a layout's first pass may give 0 px, and a title
        # wrapped one letter per line would ask for a height the window keeps.
        width = max(width, MIN_TITLE_WIDTH)
        self._wrap_width = width
        before = self.minimumHeight()
        self.item.setTextWidth(width)
        self.updateMin()
        self.resizeEvent(None)
        if self.minimumHeight() < before and not self._refit_pending:
            self._refit_pending = True
            QTimer.singleShot(0, self._refit)

    def _refit(self) -> None:
        """A shorter title: the view's top item, which ``setGeometry`` grew to fit the taller one
        (a pyqtgraph view sets it only when it is resized), back to the view's size."""
        if sip.isdeleted(self):
            return
        self._refit_pending = False
        scene = self.scene()
        for view in scene.views() if scene is not None else ():
            central, area = getattr(view, "centralWidget", None), getattr(view, "range", None)
            if central is not None and area is not None and central.geometry() != area:
                central.setGeometry(area)

    def setGeometry(self, *args: Any, **kwargs: Any) -> None:
        rect = kwargs["rect"] if "rect" in kwargs else args[0] if len(args) == 1 else QRectF(*args)
        if abs(max(float(rect.width()), MIN_TITLE_WIDTH) - self._wrap_width) > 0.5:
            self._wrap(float(rect.width()))  # The new height asks the layout again.
        super().setGeometry(rect)

    def updateMin(self) -> None:
        bounds = self.itemRect()
        natural = max(getattr(self, "_natural_width", 0.0), 0.0) or float(bounds.width())
        height = float(bounds.height())
        minimum = min(MIN_TITLE_WIDTH, natural)
        self.setMinimumWidth(minimum)
        self.setMinimumHeight(height)
        self._sizeHint = {
            Qt.SizeHint.MinimumSize: (minimum, height),
            Qt.SizeHint.PreferredSize: (natural, height),
            Qt.SizeHint.MaximumSize: (-1, -1),
            Qt.SizeHint.MinimumDescent: (0, 0),
        }
        self.updateGeometry()

    def natural_width(self) -> float:
        """The text's unwrapped width."""
        return self._natural_width


def add_label(layout: Any, text: str = "", **args: Any) -> WrapLabel:
    """A ``WrapLabel`` in a pyqtgraph layout (a ``GraphicsLayout`` or ``GraphicsLayoutWidget``):
    ``addLabel``'s arguments (row, col, colspan, justify, …)."""
    place = {key: args.pop(key) for key in ("row", "col", "rowspan", "colspan") if key in args}
    label = WrapLabel(text or " ", **args)
    target = getattr(layout, "ci", layout)
    target.addItem(label, **place)
    return label


def set_plot_title(plot: Any, text: str, **args: Any) -> WrapLabel:
    """Set a ``PlotItem``'s title as a ``WrapLabel`` (its own label, swapped in once, keeps the
    plot's ``titleLabel`` name): the title row takes the height the wrapped text needs instead
    of ``setTitle``'s fixed 30 px."""
    label = plot.titleLabel
    if not isinstance(label, WrapLabel):
        old = label
        plot.layout.removeItem(old)
        old.setParentItem(None)
        if old.scene() is not None:
            old.scene().removeItem(old)
        label = WrapLabel(" ", parent=plot, **args)  # The app's font, as the plots' headers.
        plot.layout.addItem(label, 0, 1)
        plot.titleLabel = label
    plot.layout.setRowMinimumHeight(0, 0)
    plot.layout.setRowMaximumHeight(0, 1e6)
    label.setVisible(bool(text))
    label.setMaximumHeight(1e6 if text else 0)
    label.setText(text or " ")
    return label
