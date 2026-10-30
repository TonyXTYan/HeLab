"""Pictures of plots released to free RAM (the RAM budget, helab/analysis/budget.py):
``snapshot`` takes one, ``ReleasedPlot`` shows it with Reload."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Callable, Optional

from PyQt6.QtCore import QBuffer, QByteArray, QIODevice, QRect, QSize, Qt
from PyQt6.QtGui import QHideEvent, QImage, QPainter, QPaintEvent, QPixmap
from PyQt6.QtWidgets import QHBoxLayout, QLabel, QPushButton, QSizePolicy, QVBoxLayout, QWidget

from helab.utils.accessible import identify
from helab.utils.ram_buffers import Buffers


@dataclass(frozen=True)
class Picture:
    """A plot as drawn, kept as PNG bytes (decoded only to paint): a fraction of a pixmap's RAM."""
    png: bytes
    ratio: float = 1.0  # The device pixel ratio it was grabbed at

    @property
    def size(self) -> QSize:
        """In device-independent pixels (invalid if there is none)."""
        image = QImage.fromData(self.png, "PNG") if self.png else QImage()
        if image.isNull():
            return QSize()
        return QSize(round(image.width() / self.ratio), round(image.height() / self.ratio))

    def pixmap(self) -> QPixmap:
        pixmap = QPixmap()
        if self.png and pixmap.loadFromData(self.png, "PNG"):
            pixmap.setDevicePixelRatio(self.ratio)
        return pixmap


def snapshot(content: QWidget, area: QSize) -> Picture:
    """A picture of a plot as drawn. A plot never laid out (always behind another tab) is
    first given the plot area's size, ``area``."""
    if (not content.isVisible() and area.isValid()
            and (content.width() < area.width() // 2 or content.height() < area.height() // 2)):
        content.resize(area)
    grabbed = content.grab()
    if grabbed.isNull():
        return Picture(b"")
    data = QByteArray()
    buffer = QBuffer(data)
    buffer.open(QIODevice.OpenModeFlag.WriteOnly)
    grabbed.save(buffer, "PNG")
    buffer.close()
    return Picture(bytes(data.data()), grabbed.devicePixelRatio())


class PlotPicture(QWidget):
    """A released plot's picture, scaled to fit and centred (not interactive). The PNG is
    decoded once while it shows, and the decoded pixmap dropped when it is hidden (behind
    another tab), so only the PNG stays in RAM then."""

    def __init__(self, picture: Picture, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self.picture = picture
        self._size = picture.size
        self.decoded: Optional[QPixmap] = None
        self.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Ignored)

    def sizeHint(self) -> QSize:
        return self._size if self._size.isValid() else QSize(200, 150)

    def hideEvent(self, a0: Optional[QHideEvent]) -> None:
        self.decoded = None
        super().hideEvent(a0)

    def paintEvent(self, a0: Optional[QPaintEvent]) -> None:
        if self.decoded is None:
            self.decoded = self.picture.pixmap()
        pixmap = self.decoded
        if pixmap.isNull():
            return
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
        size = pixmap.deviceIndependentSize().toSize().scaled(self.size(), Qt.AspectRatioMode.KeepAspectRatio)
        left, top = (self.width() - size.width()) // 2, (self.height() - size.height()) // 2
        painter.drawPixmap(QRect(left, top, size.width(), size.height()), pixmap)


class ReleasedPlot(QWidget):
    """A plot released to free RAM: one line (what happened, its reload's state) with Reload,
    over the picture of the plot as it was last drawn."""

    RELEASED = "Released to free RAM: a picture, not interactive"

    def __init__(self, picture: Picture, reload: Callable[[], None], parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        row = QHBoxLayout()
        row.setContentsMargins(0, 0, 0, 0)
        self.state = QLabel(self.RELEASED, self)
        self.state.setObjectName("released_state")
        self.state.setTextFormat(Qt.TextFormat.PlainText)
        self.state.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Fixed)
        row.addWidget(self.state, 1)
        self.reload_button = identify(QPushButton("Reload", self), "plot_reload", "Reload plot")
        self.reload_button.setToolTip("Draw this plot again from its data in RAM or in the disk cache "
                                      "(never from its folder): exactly its shots, by their fingerprints")
        self.reload_button.clicked.connect(lambda: reload())
        row.addWidget(self.reload_button)
        layout.addLayout(row)
        self.picture = PlotPicture(picture, self)
        if not picture.png:
            self.picture.hide()
            layout.addWidget(QLabel("(no picture: the plot couldn't be captured)", self), 1)
        else:
            layout.addWidget(self.picture, 1)
        self.set_state("")

    def set_state(self, text: str, busy: bool = False) -> None:
        """The reload's state after the line's first words ("" when none); Reload waits while busy."""
        line = " · ".join(filter(None, (self.RELEASED, text)))
        self.state.setText(line)
        self.state.setToolTip(
            f"{line}\nHeLab released this plot when RAM in use passed 80 % of the RAM budget "
            "(Settings → Cache). Reload draws it again from RAM or the disk cache, never from its folder "
            "(a plot on another TXY source than the default, whose data isn't disk cached, loads it again).")
        self.reload_button.setEnabled(not busy)

    def ram_buffers(self) -> Buffers:
        """What the picture keeps in RAM (counted in the budget)."""
        png = self.picture.picture.png
        return {id(png): len(png)} if png else {}


