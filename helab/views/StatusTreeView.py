import logging
from typing import Optional, Set

from PyQt6.QtCore import Qt, QModelIndex, QTimer, QEvent, QRect, QPoint, QObject, pyqtSignal, QDir, QFile, QFileInfo
from PyQt6.QtGui import QMouseEvent, QFocusEvent, QPainter
from PyQt6.QtWidgets import QTreeView, QWidget, QVBoxLayout, QPushButton, QLabel, QHBoxLayout, QProxyStyle, QStyle

from helab.models.HelabFileSystemModel import HelabFileSystemModel
from helab.utils.caching_setup import status_cache, data_ram_cache, fnum
from helab.utils.constants import *
from helab.views.StatusIconDelegate import StatusIconDelegate
from helab.models.StatusReport import StatusReport


# class OptionalBranchIconStyle(QProxyStyle):
#     def drawPrimitive(self, element, option, painter, widget: QWidget | None = None) -> None:
#         # logging.debug(f"drawPrimitive: {element}")
#         if element == QStyle.PrimitiveElement.PE_IndicatorBranch:
#             index = option.index
#             # logging.debug(f"drawPrimitive: {index}")
#             model = widget.model()
#             if index and model:
#                 # logging.debug(f"drawPrimitive: {index.model = }")
#                 if not self.index_has_subdirectories(index, model):
#                     return  # Do not draw the branch icon if there are no subdirectories
#         super().drawPrimitive(element, option, painter, widget)
#
#     def index_has_subdirectories(self, index: QModelIndex, model: HelabFileSystemModel) -> bool:
#         logging.debug(f"index_has_subdirectories: {index = }")
#         logging.debug(f"index_has_subdirectories: {index.model() = }, {model = }")
#         logging.debug(f"index_has_subdirectories: {model.filePath(index) = }")
#         logging.debug(f"index_has_subdirectories: {model.fileInfo(index).filePath() = }")
#         # model = index.model()
#         # if not model:
#         #     return False
#         # file_info = model.fileInfo(index)
#         # logging.debug(f"index_has_subdirectories: {file_info.absolutePath() = }")
#         # logging.debug(f"index_has_subdirectories: file = {file_path}")
#         # file_info = QFileInfo(file_path)
#         # if file_info.isDir():
#         # #     # logging.debug(f"index_has_subdirectories: {file_path.absoluteFilePath() = }")
#         #     logging.debug(f"index_has_subdirectories: {file_info.absoluteFilePath() = }")
#         # #     model_root_path = file_path.absoluteFilePath()
#         #     directory = QDir(file_info)
#         # #     # Exclude '.' and '..' entries
#         #     entry_list = directory.entryList(QDir.Filter.Dirs | QDir.Filter.NoDotAndDotDot)
#         # #     return len(entry_list) > 0
#         return False


class StatusHoverIconInfo(QWidget):
    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent, Qt.WindowType.Popup)

        self.status_report: Optional[StatusReport] = None
        self.d_union_shots: Optional[Set[int]] = None
        self.d_inter_shots: Optional[Set[int]] = None
        self.d_only_dld_shots: Optional[Set[int]] = None
        self.d_only_txy_shots: Optional[Set[int]] = None
        self.d_union_shots_len: Optional[int] = None
        self.d_inter_shots_len: Optional[int] = None
        self.d_only_dld_shots_len: Optional[int] = None
        self.d_only_txy_shots_len: Optional[int] = None


        # Update window flags to include WindowStaysOnTopHint and remove FramelessWindowHint
        self.setWindowFlags(
            Qt.WindowType.Popup |
            Qt.WindowType.WindowStaysOnTopHint
        )
        # self.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose)

        layout = QVBoxLayout()
        # Reduce the margins and spacing to minimize padding
        layout.setContentsMargins(8, 6, 8, 2)  # left, top, right, bottom
        layout.setSpacing(4)  # space between widgets

        self.label = QLabel("Detailed Info")
        self.button1 = QPushButton("Fill missing DLD ∖ TXY")
        self.button2 = QPushButton("Recalculate ill formated TXY")

        # Connect buttons to placeholder functions
        self.button1.clicked.connect(self.action1_fill_missing_dld)
        self.button2.clicked.connect(self.action2_recalc_txys)

        self.button1.setEnabled(False)
        self.button2.setEnabled(False)

        layout.addWidget(self.label)

        button_layout = QHBoxLayout()
        # Remove margins and reduce spacing between buttons
        button_layout.setContentsMargins(0, 0, 0, 0)
        button_layout.setSpacing(2)

        button_layout.addWidget(self.button1)
        button_layout.addWidget(self.button2)

        layout.addLayout(button_layout)
        self.setLayout(layout)

    def hide(self) -> None:
        super().hide()
        self.button1.setEnabled(False)
        self.button2.setEnabled(False)
        self.status_report = None
        self.label.setText("Nothing (this should not be visible)")
        self.d_union_shots = None
        self.d_inter_shots = None
        self.d_only_dld_shots = None
        self.d_only_txy_shots = None
        self.d_union_shots_len = None
        self.d_inter_shots_len = None
        self.d_only_dld_shots_len = None
        self.d_only_txy_shots_len = None


    def set_status_report(self, status_report: StatusReport) -> None:
        self.status_report = status_report
        self.refresh_info()

    def refresh_info(self) -> None:
        if not hasattr(self, 'status_report'):
            return
        if self.status_report is None:
            return

        status_report = self.status_report
        status = status_report.status
        count = status_report.count
        file_path = status_report.path
        extra_icons = status_report.extra_icons
        info_text = f"Path: {file_path}\nStatus: {status}\nCount: {count}\nExtra Icons: {', '.join(extra_icons) if extra_icons else 'None'}"

        if status_report.d_dld_shots is not None and status_report.d_txy_shots is not None:
            # Warning: duplicate code to StatusWorker.py
            self.d_union_shots = set(status_report.d_dld_shots) | set(status_report.d_txy_shots)
            self.d_inter_shots = set(status_report.d_dld_shots) & set(status_report.d_txy_shots)
            self.d_only_dld_shots = set(status_report.d_dld_shots) - self.d_inter_shots
            self.d_only_txy_shots = set(status_report.d_txy_shots) - self.d_inter_shots

            self.d_union_shots_len = len(self.d_union_shots)
            self.d_inter_shots_len = len(self.d_inter_shots)
            self.d_only_dld_shots_len = len(self.d_only_dld_shots)
            self.d_only_txy_shots_len = len(self.d_only_txy_shots)

            info_text += "\n\n"
            info_text += f"  DLD ∪ TXY: {fnum(self.d_union_shots_len)} \n"
            info_text += f"  DLD ∩ TXY: {fnum(self.d_inter_shots_len)} \n"
            info_text += f"  DLD ∖ TXY: {fnum(self.d_only_dld_shots_len)} \n"
            info_text += f"  TXY ∖ DLD: {fnum(self.d_only_txy_shots_len)} \n"

            if self.d_only_dld_shots_len > 0:
                self.button1.setEnabled(True)

        if status_report.problematic_txy_ns is not None:
            info_text += "\n\n"
            info_text += f"Problematic TXY files: {status_report.problematic_txy_ns}\n"
            self.button2.setEnabled(True)


        if status_report.path in data_ram_cache:
            info_text += "\n\n"
            info_text += f"Data cached in RAM \n"
            info_text += f"  Loaded Timestamp:     {status_report.time_load_ram} \n"
            info_text += f"  Loaded txy files:     {fnum(status_report.loaded_txy_files_count)} \n"
            info_text += f"  Loaded txy rows:      {fnum(status_report.loaded_txy_rows_count)} \n"
            info_text += f"  Data compressed size: {fnum(status_report.data_comp_bytes)}B \n"
            info_text += f"  Data loaded RAM size: {fnum(status_report.data_dict_bytes)}B \n"

        self.label.setText(info_text)

    # Placeholder function for Action 1
    # TODO move to a separate file
    def action1_fill_missing_dld(self) -> None:
        import matlab.engine    # type: ignore[reportMissingImports, import-error, import, no-name-in-module, unused-ignore]
        self.button1.setEnabled(False)
        if self.d_only_dld_shots is None:
            logging.fatal("action1_fill_missing_dld: Impossible state")
            return
        if self.status_report is None:
            logging.fatal("action1_fill_missing_dld: Impossible state")
            return

        eng = matlab.engine.start_matlab()
        # eng.addpath(DEV_PATH_TO_TDC_AUTOCONVERTER_GIT_FOLDER)
        eng.addpath(eng.genpath(DEV_PATH_TO_TDC_AUTOCONVERTER_GIT_FOLDER))                          # type: ignore[reportOptionalMemberAccess, unused-ignore]
        file_list = [f"d{shot}.txt" for shot in self.d_only_dld_shots]
        logging.debug(f"action1_fill_missing_dld: {file_list = }, {self.status_report.path = }")
        eng.tdc_convert_filelist(file_list, self.status_report.path, nargout=0)                     # type: ignore[reportOptionalMemberAccess, unused-ignore]

        status_cache.pop(self.status_report.path)
        data_ram_cache.pop(self.status_report.path)

        pass

    # Placeholder function for Action 2
    def action2_recalc_txys(self) -> None:
        import matlab.engine    # type: ignore[reportMissingImports, import-error, import, no-name-in-module, unused-ignore]
        logging.debug("action2_recalc_txys: called")
        self.button2.setEnabled(False)
        if self.status_report is None:
            logging.fatal("action2_recalc_txys: Impossible state")
            return
        if self.status_report.problematic_txy_ns is None:
            logging.fatal("action2_recalc_txys: Impossible state")
            return

        eng = matlab.engine.start_matlab()
        eng.addpath(eng.genpath(DEV_PATH_TO_TDC_AUTOCONVERTER_GIT_FOLDER))                          # type: ignore[reportOptionalMemberAccess, unused-ignore]
        file_list = [f"d{shot}.txt" for shot in self.status_report.problematic_txy_ns]
        logging.debug(f"action2_recalc_txys: {file_list = }, {self.status_report.path = }")
        eng.tdc_convert_filelist(file_list, self.status_report.path, nargout=0)                     # type: ignore[reportOptionalMemberAccess, unused-ignore]

        status_cache.pop(self.status_report.path)
        data_ram_cache.pop(self.status_report.path)

        pass


class StatusTreeView(QTreeView):

    itemExpandedSignal = pyqtSignal(QModelIndex)

    def __init__(self, parent: QTreeView | None = None) -> None:
        super().__init__(parent)
        self.setMouseTracking(True)
        self.popup = StatusHoverIconInfo()
        self.popup.setParent(None)  # Make it a top-level window
        self.popup.installEventFilter(self)
        self.current_hover_index = QModelIndex()
        self.popup_visible = False

        icon_delegate = StatusIconDelegate(self)
        self.setItemDelegateForColumn(HelabFileSystemModel.COLUMN_STATUS_ICON, icon_delegate)

        # Timer to delay hiding the popup
        self.hover_timer = QTimer()
        self.hover_timer.setSingleShot(True)
        self.hover_timer.timeout.connect(self.hide_popup)

        self.popup.installEventFilter(self)
        self.expanded.connect(self.on_item_expanded)
        # self.setStyle(OptionalBranchIconStyle())

    def eventFilter(self, object: QObject | None, event: QEvent | None) -> bool:
        if event is None: return False
        if object == self.popup:
            if event.type() == QEvent.Type.Enter:
                # Stop the hide timer when cursor enters the popup
                self.hover_timer.stop()
            elif event.type() == QEvent.Type.Leave:
                # Start the hide timer when cursor leaves the popup
                self.hover_timer.start(500)  # Delay hiding by 500 ms
        return super().eventFilter(object, event)

    def mouseMoveEvent(self, event: QMouseEvent | None) -> None:
        if event is None: return
        pos = event.pos()
        index = self.indexAt(pos)
        if index.isValid() and index.column() == HelabFileSystemModel.COLUMN_STATUS_ICON:
            # Determine if the mouse is over the icon area
            rect = self.visualRect(index)
            icon_size = self.iconSize()
            padding = 5  # Adjust based on your delegate's padding
            status_icon_rect = QRect(
                rect.left() + padding,
                rect.top() + (rect.height() - icon_size.height()) // 2,
                icon_size.width(),
                icon_size.height()
            )
            extra_icons = index.data(HelabFileSystemModel.STATUS_EXTRA_ICONS_ROLE)
            extra_icon_rects = []
            if extra_icons:
                x_offset = status_icon_rect.right() + 2  # 2px spacing between icons
                for _ in extra_icons:
                    extra_rect = QRect(
                        x_offset,
                        rect.top() + (rect.height() - icon_size.height()) // 2,
                        icon_size.width(),
                        icon_size.height()
                    )
                    extra_icon_rects.append(extra_rect)
                    x_offset += icon_size.width() + 2

            # Check if the mouse is within any icon rect
            over_icon = False
            if status_icon_rect.contains(event.pos()):
                over_icon = True
            else:
                for extra_rect in extra_icon_rects:
                    if extra_rect.contains(event.pos()):
                        over_icon = True
                        break

            if over_icon:
                if index != self.current_hover_index:
                    self.current_hover_index = index
                    self.show_popup(event.globalPosition().toPoint(), index)
            else:
                self.hover_timer.start(500)  # Delay hiding by 300ms
        else:
            self.hover_timer.start(500)  # Delay hiding by 300ms
        super().mouseMoveEvent(event)

    def leaveEvent(self, a0: QEvent | None) -> None:
        if a0 is None: return
        self.hover_timer.start(500)  # Delay hiding by 300ms
        super().leaveEvent(a0)

    def show_popup(self, global_pos: QPoint, index: QModelIndex) -> None:
        if not index.isValid():
            return
        model = self.model()
        if model is None or not hasattr(model, 'filePath') or not hasattr(model, 'fetch_status'):
            logging.error("show_popup: model is bad")
            return
        if not isinstance(model, HelabFileSystemModel):
            logging.error("show_popup: model is not HelabFileSystemModel")
            return
        # Get data from the model
        file_path = model.filePath(index)
        # status, count, extra_icons = self.model().get_status(file_path)
        # status, count, extra_icons = model.fetch_status(file_path)
        status_report = model.fetch_status(file_path)
        if isinstance(status_report, StatusReport):
            self.popup.set_status_report(status_report)

            # self.popup.refresh_info(info_text)
        # Position the popup near the cursor
        # self.popup.(global_pos + QPoint(10, 10))  # Slight offset
        self.popup.move(global_pos - QPoint(1, 1))  # Slight offset
        self.popup.show()
        self.popup_visible = True

    def hide_popup(self) -> None:
        if self.popup_visible and self.popup is not None:
            try:
                self.popup.hide()
            except RuntimeError:
                logging.error("Attempted to hide a deleted popup")
            # self.popup.hide()
            self.popup_visible = False
            self.current_hover_index = QModelIndex()

    def focusOutEvent(self, e: QFocusEvent | None) -> None:
        if e is None: return
        super().focusOutEvent(e)
        self.hide_popup()
        # QTimer.singleShot(500, self.hide_popup)

    def on_item_expanded(self, index: QModelIndex) -> None:
        model = self.model()
        if isinstance(model, HelabFileSystemModel):
            logging.debug(f"StatusTreeView.on_item_expanded: {model.filePath(index)}")
            model.on_item_expanded(index)
        else:
            logging.debug(f"StatusTreeView.on_item_expanded: invalid model {index}")
        self.hide_popup()
        self.itemExpandedSignal.emit(index)

    