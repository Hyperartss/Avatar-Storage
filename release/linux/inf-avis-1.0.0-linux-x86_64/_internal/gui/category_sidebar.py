"""Sidebar with favourite and category drop zones.

Clicking a category filters the grid. Dragging an avatar card onto a category
files it there; dragging onto the Favourite zone toggles the VRChat favourite.
Categories can be dragged on top of each other to reorder them.
"""

from PyQt6.QtCore import Qt, QMimeData, QSize, pyqtSignal
from PyQt6.QtGui import QDrag, QPixmap, QPainter
from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QListWidget, QListWidgetItem,
    QPushButton, QFrame, QScrollArea, QMessageBox
)

import database as db
from gui.theme import current_colors

# MIME type carried by a dragged avatar card.
AVATAR_MIME = "application/x-infavis-avatar"


def _sidebar_stylesheet(colors):
    c = colors
    return f"""
        #CategorySidebar {{ background: {c['sidebar_bg']}; border-right: 1px solid {c['sidebar_border']}; }}
        QLabel.sectionTitle {{
            font-weight: bold; font-size: 12px; color: {c['section_title']};
            padding: 10px 8px 4px 8px;
        }}
        #favouriteZone {{
            background: {c['fav_zone_bg']}; border: 2px dashed {c['fav_zone_border']};
            border-radius: 8px; margin: 6px 8px;
        }}
        #favouriteZone:hover {{
            border-color: {c['fav_zone_hover_border']}; background: {c['fav_zone_hover_bg']};
        }}
        QListWidget {{ border: none; background: transparent; outline: none; }}
        QListWidget::item {{
            padding: 8px 10px; border-radius: 6px;
            margin: 2px 8px; background: {c['item_bg']};
            border: 1px solid {c['item_border']};
            color: {c['text']};
        }}
        QListWidget::item:selected {{
            background: {c['item_selected_bg']}; border-color: {c['item_selected_border']};
        }}
        QListWidget::item:hover {{ background: {c['item_hover_bg']}; }}
    """


class _CategoryList(QListWidget):
    """Categories that accept avatar drops and can be reordered by dragging."""

    avatar_dropped = pyqtSignal(str, int)   # avatar_id, category_id
    reordered = pyqtSignal()                 # visual order changed

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setSelectionMode(
            QListWidget.SelectionMode.SingleSelection)
        self.setDragEnabled(True)
        self.setAcceptDrops(True)
        self.setDragDropMode(
            QListWidget.DragDropMode.DragDrop)
        self.setDefaultDropAction(Qt.DropAction.MoveAction)
        self.setIconSize(QSize(20, 20))
        self._drag_source_row = -1

    # -------------------------------------------------------------- drag in

    def dragEnterEvent(self, event):
        if event.mimeData().hasFormat(AVATAR_MIME):
            event.setDropAction(Qt.DropAction.CopyAction)
            event.accept()
        else:
            super().dragEnterEvent(event)

    def dragMoveEvent(self, event):
        if event.mimeData().hasFormat(AVATAR_MIME):
            event.setDropAction(Qt.DropAction.CopyAction)
            event.accept()
        else:
            super().dragMoveEvent(event)

    def dropEvent(self, event):
        if event.mimeData().hasFormat(AVATAR_MIME):
            avatar_id = bytes(
                event.mimeData().data(AVATAR_MIME)).decode()
            row = self.indexAt(event.position().toPoint()).row()
            if row < 0:
                row = self.count() - 1
            item = self.item(row)
            if item is None:
                event.ignore()
                return
            category_id = item.data(Qt.ItemDataRole.UserRole)
            event.setDropAction(Qt.DropAction.CopyAction)
            event.accept()
            self.avatar_dropped.emit(avatar_id, category_id)
            return
        # Internal drag: reorder the categories. Let the list do the visual
        # move, then persist the new order.
        super().dropEvent(event)
        self.reordered.emit()

    def startDrag(self, supportedActions):
        item = self.currentItem()
        if item is None:
            return
        self._drag_source_row = self.row(item)
        super().startDrag(supportedActions)


class CategorySidebar(QWidget):
    """Left-hand navigator: Favourite zone plus the category list.

    Signals
    -------
    categorySelected(int)
        The user clicked a category; the grid should filter to it.
    avatarFavourited(str)
        An avatar was dropped on the Favourite zone.
    avatarFiled(str, int)
        An avatar was dropped onto a category.
    """

    categorySelected = pyqtSignal(int)
    avatarFavourited = pyqtSignal(str)
    avatarFiled = pyqtSignal(str, int)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setMinimumWidth(220)
        self.setObjectName("CategorySidebar")
        self.colors = current_colors()
        self.setup_ui()

    # -------------------------------------------------------------- theming

    def apply_theme(self, colors):
        """Re-style the sidebar for a new theme."""
        self.colors = colors
        self.setStyleSheet(_sidebar_stylesheet(colors))
        self.favourite_zone.setObjectName("favouriteZone")
        self.fav_icon.setStyleSheet(f"font-size: 30px; color: {colors['accent']};")
        self.fav_label.setStyleSheet(
            f"color: {colors['accent']}; font-size: 11px;")
        self.new_btn.setStyleSheet(
            f"QPushButton {{ background: {colors['accent']}; color: white; "
            f"border: none; border-radius: 6px; font-weight: bold; }}"
            f"QPushButton:hover {{ background: {colors['accent_hover']}; }}")

    # -------------------------------------------------------------- build

    def setup_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        self.setStyleSheet(_sidebar_stylesheet(self.colors))

        # ---- Favourite zone ---------------------------------------
        fav_title = QLabel("Favourites")
        fav_title.setObjectName("sectionTitle")
        fav_title.setStyleSheet(
            f"font-weight: bold; font-size: 12px; color: {self.colors['section_title']}; "
            f"padding: 10px 8px 4px 8px;")
        layout.addWidget(fav_title)

        self.favourite_zone = QFrame()
        self.favourite_zone.setObjectName("favouriteZone")
        self.favourite_zone.setAcceptDrops(True)
        self.favourite_zone.setFixedHeight(90)
        fav_layout = QVBoxLayout(self.favourite_zone)
        fav_layout.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.fav_icon = QLabel("★")
        self.fav_icon.setStyleSheet(
            f"font-size: 30px; color: {self.colors['accent']};")
        self.fav_icon.setAlignment(Qt.AlignmentFlag.AlignCenter)
        fav_layout.addWidget(self.fav_icon)
        self.fav_label = QLabel("Drop avatars here\nto favourite / unfavourite")
        self.fav_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.fav_label.setStyleSheet(
            f"color: {self.colors['accent']}; font-size: 11px;")
        fav_layout.addWidget(self.fav_label)
        layout.addWidget(self.favourite_zone)

        self.favourite_zone.dragEnterEvent = self._fav_drag_enter
        self.favourite_zone.dragMoveEvent = self._fav_drag_move
        self.favourite_zone.dropEvent = self._fav_drop

        # ---- Categories -------------------------------------------
        cat_title = QLabel("Categories")
        cat_title.setStyleSheet(
            f"font-weight: bold; font-size: 12px; color: {self.colors['section_title']}; "
            f"padding: 10px 8px 4px 8px;")
        layout.addWidget(cat_title)

        self.list = _CategoryList(self)
        self.list.avatar_dropped.connect(self._on_avatar_dropped)
        self.list.reordered.connect(self._on_reordered)
        self.list.itemClicked.connect(self._on_item_clicked)
        layout.addWidget(self.list, 1)

        self.new_btn = QPushButton("+ New Category")
        self.new_btn.setFixedHeight(30)
        self.new_btn.setStyleSheet(
            f"QPushButton {{ background: {self.colors['accent']}; color: white; "
            f"border: none; border-radius: 6px; font-weight: bold; }}"
            f"QPushButton:hover {{ background: {self.colors['accent_hover']}; }}")
        self.new_btn.clicked.connect(self._add_category)
        layout.addWidget(self.new_btn)

        layout.addStretch()

        self._rebuild()

    # -------------------------------------------------------------- building

    def _rebuild(self, keep_selection=True):
        current_id = None
        if keep_selection:
            item = self.list.currentItem()
            if item is not None:
                current_id = item.data(Qt.ItemDataRole.UserRole)

        self.list.clear()
        self._category_rows = []
        for cat in db.get_all_categories():
            count = db.get_category_avatar_count(cat["id"])
            item = QListWidgetItem(f"{cat['name']} ({count})")
            item.setData(Qt.ItemDataRole.UserRole, cat["id"])
            self.list.addItem(item)
            self._category_rows.append(cat["id"])

        if current_id is not None:
            for index in range(self.list.count()):
                if self.list.item(index).data(Qt.ItemDataRole.UserRole) == current_id:
                    self.list.setCurrentRow(index)
                    break

    def refresh(self):
        """Reload category names and counts without losing selection."""
        self._rebuild()

    # -------------------------------------------------------------- events

    def _on_item_clicked(self, item):
        cat_id = item.data(Qt.ItemDataRole.UserRole)
        self.categorySelected.emit(cat_id)

    def _on_avatar_dropped(self, avatar_id, category_id):
        db.add_avatar_to_category(avatar_id, category_id)
        self.avatarFiled.emit(avatar_id, category_id)
        self.refresh()

    def _on_reordered(self):
        """Persist the new visual order of categories."""
        order = [
            self.list.item(i).data(Qt.ItemDataRole.UserRole)
            for i in range(self.list.count())
        ]
        for position, cat_id in enumerate(order):
            db.reorder_category(cat_id, position)
        self.refresh()

    def _add_category(self):
        from PyQt6.QtWidgets import QInputDialog
        name, ok = QInputDialog.getText(
            self, "New Category", "Category name:")
        if ok and name.strip():
            if db.create_category(name.strip()):
                self.refresh()
            else:
                QMessageBox.warning(
                    self, "Exists", f'Category "{name.strip()}" already exists.')

    # ---- favourite zone drag handling -----------------------------

    def _fav_drag_enter(self, event):
        if event.mimeData().hasFormat(AVATAR_MIME):
            event.setDropAction(Qt.DropAction.CopyAction)
            event.accept()
        else:
            event.ignore()

    def _fav_drag_move(self, event):
        if event.mimeData().hasFormat(AVATAR_MIME):
            event.setDropAction(Qt.DropAction.CopyAction)
            event.accept()
        else:
            event.ignore()

    def _fav_drop(self, event):
        if event.mimeData().hasFormat(AVATAR_MIME):
            avatar_id = bytes(
                event.mimeData().data(AVATAR_MIME)).decode()
            event.setDropAction(Qt.DropAction.CopyAction)
            event.accept()
            self.avatarFavourited.emit(avatar_id)
        else:
            event.ignore()
