import os
import requests
from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLineEdit, QComboBox,
    QPushButton, QScrollArea, QGridLayout, QLabel, QFrame,
    QMessageBox, QMenu, QCheckBox
)
from PyQt6.QtCore import Qt, QThread, pyqtSignal, QSize, QPoint, QMimeData
from PyQt6.QtGui import QPixmap, QFont, QAction, QFontDatabase, QDrag, QPainter
import database as db
from PIL import Image
from io import BytesIO

from gui.category_sidebar import AVATAR_MIME
from gui.theme import current_colors

CACHE_DIR = db.CACHE_DIR


def _card_stylesheet(colors, density="comfortable"):
    """Build the card's stylesheet from the current theme and density."""
    c = colors
    padding = "8px" if density == "comfortable" else "4px"
    return f"""
        AvatarCard {{ border: 1px solid {c['card_border']}; border-radius: 6px;
                      padding: {padding}; background: {c['card_bg']}; }}
        AvatarCard:hover {{ border-color: {c['card_hover_border']};
                      background: {c['card_hover_bg']}; }}
        AvatarCard[selected="true"] {{ border: 2px solid {c['accent']};
                      background: {c['card_selected_bg']}; }}
    """

_UI_FAMILIES = ("Inter", "Noto Sans", "Ubuntu", "DejaVu Sans", "Liberation Sans",
                "Segoe UI", "Helvetica Neue", "Arial")
_MONO_FAMILIES = ("JetBrains Mono", "Cascadia Code", "DejaVu Sans Mono",
                  "Liberation Mono", "Ubuntu Mono", "Consolas", "Menlo", "Courier New")

_resolved_families = {}

def ui_family():
    """First installed family from the UI list, or "" for the Qt default."""
    if "ui" not in _resolved_families:
        _resolved_families["ui"] = _first_available(_UI_FAMILIES)
    return _resolved_families["ui"]

def mono_family():
    if "mono" not in _resolved_families:
        _resolved_families["mono"] = _first_available(_MONO_FAMILIES)
    return _resolved_families["mono"]

def _first_available(candidates):
    installed = set(QFontDatabase.families())
    for name in candidates:
        if name in installed:
            return name
    return ""

class ThumbnailLoader(QThread):
    loaded = pyqtSignal(str, QPixmap)

    def __init__(self, url, avatar_id, session=None):
        super().__init__()
        self.url = url
        self.avatar_id = avatar_id
        # VRChat image endpoints require the auth cookie. A bare requests.get
        # gets a 403, which looked like the avatar having no picture at all.
        self.session = session

    def run(self):
        cache_path = os.path.join(CACHE_DIR, f"{self.avatar_id}.png")
        if os.path.exists(cache_path):
            pix = QPixmap(cache_path)
            if not pix.isNull():
                self.loaded.emit(self.avatar_id, pix)
                return
        if not self.url:
            return

        fetcher = self.session.get if self.session is not None else requests.get
        try:
            r = fetcher(self.url, timeout=15)
            if r.status_code != 200 or not r.content:
                return
            img = Image.open(BytesIO(r.content))
            img.thumbnail((200, 200))
            os.makedirs(CACHE_DIR, exist_ok=True)
            img.save(cache_path, "PNG")
            pix = QPixmap(cache_path)
            if not pix.isNull():
                self.loaded.emit(self.avatar_id, pix)
        except Exception:
            pass

class AvatarCard(QFrame):
    # Selection is managed by the list rather than a QAbstractItemView, so the
    # card paints itself and reports clicks upwards.
    SELECTED = "selected"

    def __init__(self, avatar_data, on_edit_categories, on_delete,
                 on_move=None, on_toggle_favorite=None, on_select=None,
                 colors=None, density="comfortable", show_ids=True):
        super().__init__()
        self.avatar_id = avatar_data["avatar_id"]
        self.avatar_data = avatar_data
        self.on_edit_categories = on_edit_categories
        self.on_delete = on_delete
        # None hides the menu entry, so the widget still works standalone.
        self.on_move = on_move
        self.on_toggle_favorite = on_toggle_favorite
        self.on_select = on_select
        self._selected = False
        self._press_pos = QPoint()
        self.colors = colors or current_colors()
        self.density = density
        self.show_ids = show_ids
        self.setFrameShape(QFrame.Shape.StyledPanel)
        self.setStyleSheet(_card_stylesheet(self.colors, self.density))
        self.setMinimumSize(180, 240)
        self.setMaximumSize(220, 280)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.customContextMenuRequested.connect(self.show_context_menu)
        self.setup_ui()

    def setup_ui(self):
        layout = QVBoxLayout(self)
        compact = self.density == "compact"
        spacing = 3 if compact else 4
        margin = 5 if compact else 6
        layout.setSpacing(spacing)
        layout.setContentsMargins(margin, margin, margin, margin)

        self.thumb_label = QLabel()
        self.thumb_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.thumb_label.setMinimumSize(160, 120)
        self.thumb_label.setStyleSheet(
            f"background: {self.colors['mid']}; border-radius: 4px;")
        layout.addWidget(self.thumb_label)

        # Two separate controls on purpose: the star is the VRChat favourite
        # (it writes to vrchat.com) and the folder is local filing. Sharing
        # one button made neither discoverable.
        self.favorite = bool(self.avatar_data["favorite"])
        self.fav_btn = QPushButton("★" if self.favorite else "☆")
        self.fav_btn.setFixedSize(28, 28)
        self.fav_btn.setToolTip(
            "Un-favourite on vrchat.com" if self.favorite
            else "Favourite this on vrchat.com")
        self.fav_btn.setStyleSheet(
            f"QPushButton {{ font-size: 18px; border: none; }}"
            f"QPushButton:hover {{ background: {self.colors['accent_hover']}; border-radius: 4px; }}"
        )
        self.fav_btn.clicked.connect(self.toggle_favorite)

        self.move_btn = QPushButton("\U0001f4c1")
        self.move_btn.setFixedSize(28, 28)
        self.move_btn.setToolTip("File this avatar into categories")
        self.move_btn.setStyleSheet(
            f"QPushButton {{ font-size: 14px; border: none; }}"
            f"QPushButton:hover {{ background: {self.colors['accent_hover']}; border-radius: 4px; }}"
        )
        self.move_btn.clicked.connect(self.open_categories)

        top_row = QHBoxLayout()
        top_row.addStretch()
        top_row.addWidget(self.move_btn)
        top_row.addWidget(self.fav_btn)
        layout.addLayout(top_row)

        self.name_label = QLabel(self.avatar_data["name"])
        self.name_label.setWordWrap(True)
        self.name_label.setFont(QFont(ui_family(), 10, QFont.Weight.Bold))
        self.name_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(self.name_label)

        author = self.avatar_data["author"] or "Unknown"
        self.author_label = QLabel(author)
        self.author_label.setFont(QFont(ui_family(), 7 if compact else 8))
        self.author_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.author_label.setStyleSheet(f"color: {self.colors['muted_text']};")
        layout.addWidget(self.author_label)

        self.id_label = QLabel(self.avatar_id[:12] + "...")
        self.id_label.setFont(QFont(mono_family(), 6 if compact else 7))
        self.id_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.id_label.setStyleSheet(f"color: {self.colors['dim_text']};")
        self.id_label.setVisible(self.show_ids)
        layout.addWidget(self.id_label)

    def set_thumbnail(self, *args):
        """Accept the loader's (avatar_id, pixmap) signal.

        Threaded loaders emit both so the list can route several cards, which
        means the slot here has to take the id too. It also has to tolerate a
        direct call with just a pixmap.
        """
        pixmap = args[-1] if args else None
        if not isinstance(pixmap, QPixmap) or pixmap.isNull():
            return
        scaled = pixmap.scaled(160, 120, Qt.AspectRatioMode.KeepAspectRatio,
                               Qt.TransformationMode.SmoothTransformation)
        self.thumb_label.setPixmap(scaled)

    def set_selected(self, selected: bool):
        """Repaint for selection. Cheap, so it is safe to call on every click."""
        if self._selected == selected:
            return
        self._selected = selected
        self.setProperty(self.SELECTED, "true" if selected else "false")
        # A dynamic property only takes effect after the style is recomputed.
        self.style().unpolish(self)
        self.style().polish(self)
        self.update()

    def is_selected(self) -> bool:
        return self._selected

    def mousePressEvent(self, event):
        """Record the press point so a drag can start, then report the click."""
        if event.button() == Qt.MouseButton.LeftButton:
            self._press_pos = event.position().toPoint()
        if (event.button() == Qt.MouseButton.LeftButton
                and self.on_select is not None):
            modifiers = event.modifiers()
            self.on_select(
                self.avatar_id,
                modifiers & Qt.KeyboardModifier.ControlModifier
                or modifiers & Qt.KeyboardModifier.ShiftModifier,
                modifiers & Qt.KeyboardModifier.ShiftModifier)
            event.accept()
            return
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event):
        """Start a drag when the card is moved far enough with the left button."""
        if (event.buttons() & Qt.MouseButton.LeftButton
                and self.on_select is not None):
            distance = (event.position().toPoint() - self._press_pos).manhattanLength()
            if distance >= 12:
                self._start_drag(event)
                return
        super().mouseMoveEvent(event)

    def _start_drag(self, event):
        """Drag this card, carrying its avatar id for drop targets."""
        drag = QDrag(self)
        mime = QMimeData()
        mime.setData(AVATAR_MIME, self.avatar_id.encode())
        drag.setMimeData(mime)

        # Drag preview: a semi-transparent snapshot of the card.
        pixmap = QPixmap(self.size())
        pixmap.fill(Qt.GlobalColor.transparent)
        painter = QPainter(pixmap)
        painter.setOpacity(0.85)
        self.render(painter)
        painter.end()
        drag.setPixmap(pixmap)
        drag.setHotSpot(event.position().toPoint() - self.pos())

        drag.exec(Qt.DropAction.CopyAction)

    def keyPressEvent(self, event):
        if event.key() in (Qt.Key.Key_Return, Qt.Key.Key_Enter,
                            Qt.Key.Key_Space):
            if self.on_select is not None:
                self.on_select(self.avatar_id, False, False)
                event.accept()
                return
        super().keyPressEvent(event)

    def toggle_favorite(self):
        """Star: writes to vrchat.com, not to the local database."""
        if self.on_toggle_favorite is not None:
            self.on_toggle_favorite(self.avatar_data, self.favorite)
            return
        # No window behind it: fall back to the local flag so the button is
        # never simply dead.
        db.toggle_favorite(self.avatar_id)
        self.favorite = not self.favorite
        self.fav_btn.setText("★" if self.favorite else "☆")

    def set_favorite_state(self, favorite: bool, tooltip: str = ""):
        """Reflect a confirmed server-side change."""
        self.favorite = bool(favorite)
        self.fav_btn.setText("★" if self.favorite else "☆")
        if tooltip:
            self.fav_btn.setToolTip(tooltip)
        else:
            self.fav_btn.setToolTip(
                "Un-favourite on vrchat.com" if self.favorite
                else "Favourite this on vrchat.com")

    def open_categories(self):
        """Hand the click up; the window owns the dialog and the refresh."""
        if self.on_edit_categories is not None:
            self.on_edit_categories(self.avatar_data)

    def show_context_menu(self, pos):
        menu = QMenu(self)
        view_detail = QAction("View Details", self)
        # Named apart from the VRChat one on purpose: these are two different
        # destinations and the user has both within reach of each other.
        categories_action = QAction("Categories...", self)
        move_action = QAction("Move to VRChat Favourite Group...", self)
        delete_action = QAction("Delete", self)
        menu.addAction(view_detail)
        menu.addAction(categories_action)
        if self.on_move is not None:
            menu.addSeparator()
            menu.addAction(move_action)
        menu.addAction(delete_action)
        action = menu.exec(self.mapToGlobal(pos))
        if action == delete_action:
            self.on_delete(self.avatar_id)
        elif action == move_action and self.on_move is not None:
            self.on_move(self.avatar_data)
        elif action == categories_action:
            self.open_categories()

class AvatarListWidget(QWidget):
    def __init__(self, parent=None, session=None):
        super().__init__(parent)
        self.avatars = []
        self.thumbnail_loaders = []
        # VRChat serves avatar images only to a session holding the auth
        # cookie, so the list needs the API's session to show any pictures.
        self.session = session
        # Set by the window to open the group-move dialog; None hides the
        # menu entry.
        self.on_move_favorite = None
        # Set by the window to open the local category picker.
        self.on_edit_categories = None
        # Set by the window to favourite on vrchat.com.
        self.on_toggle_favorite = None
        # Set by the window to transfer the whole selection between categories.
        self.on_bulk_categories = None
        # Selection is kept by avatar id, not by row, so it survives a refresh
        # or a re-sort of the same avatars.
        self.selected_ids = set()
        self._anchor_id = None
        # Remembered so a refresh or a resize does not silently drop the
        # category, search or ordering the user had chosen.
        self.current_category_id = None
        self.current_favorite_only = False
        self.current_search = ""
        self.current_sort_by = "date_added"
        self.current_sort_dir = "DESC"
        self.colors = current_colors()
        self.density = "comfortable"
        self.show_ids = True
        self.confirm_delete = True
        self.setup_ui()

    def setup_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(4)

        # Only visible with something selected, so it costs nothing when the
        # user is just browsing.
        self.selection_bar = QFrame()
        self.selection_bar.setFrameShape(QFrame.Shape.StyledPanel)
        self.selection_bar.setStyleSheet(
            "QFrame { background: #dcebff; border-radius: 4px; }")
        bar = QHBoxLayout(self.selection_bar)
        bar.setContentsMargins(8, 4, 8, 4)

        self.selection_label = QLabel("")
        bar.addWidget(self.selection_label)
        bar.addStretch()

        self.select_all_btn = QPushButton("Select all")
        self.select_all_btn.clicked.connect(self.select_all)
        bar.addWidget(self.select_all_btn)

        self.transfer_btn = QPushButton("Move to Category...")
        self.transfer_btn.clicked.connect(self.transfer_selection)
        bar.addWidget(self.transfer_btn)

        self.clear_btn = QPushButton("Clear")
        self.clear_btn.clicked.connect(self.clear_selection)
        bar.addWidget(self.clear_btn)

        layout.addWidget(self.selection_bar)

        self.scroll = QScrollArea()
        self.scroll.setWidgetResizable(True)
        self.scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        layout.addWidget(self.scroll, 1)

        self.container = QWidget()
        self.grid = QGridLayout(self.container)
        self.grid.setSpacing(8)
        self.scroll.setWidget(self.container)

        self.update_selection_bar()

    # -------------------------------------------------------------- selection

    def update_selection_bar(self):
        count = len(self.selected_ids)
        self.selection_bar.setVisible(count > 0)
        self.selection_label.setText(f"{count} selected")

    def cards(self):
        """Every card currently in the grid, skipping layout spacer items."""
        return [self.grid.itemAt(i).widget()
                for i in range(self.grid.count())
                if self.grid.itemAt(i).widget() is not None]

    def card_by_id(self, avatar_id):
        for card in self.cards():
            if card.avatar_id == avatar_id:
                return card
        return None

    def on_card_clicked(self, avatar_id, additive, extend=False):
        if extend and self._anchor_id:
            self._select_range(self._anchor_id, avatar_id, additive)
        elif additive:
            if avatar_id in self.selected_ids:
                self.selected_ids.discard(avatar_id)
            else:
                self.selected_ids.add(avatar_id)
            self._anchor_id = avatar_id
        else:
            self.selected_ids = {avatar_id}
            self._anchor_id = avatar_id
        self.refresh_selection()

    def _select_range(self, anchor_id, target_id, keep_existing):
        """Shift-click: everything between the anchor and the target."""
        ids = [a["avatar_id"] for a in self.avatars]
        if anchor_id not in ids or target_id not in ids:
            self.selected_ids = {target_id}
            return
        first, last = sorted((ids.index(anchor_id), ids.index(target_id)))
        span = set(ids[first:last + 1])
        if keep_existing:
            self.selected_ids |= span
        else:
            self.selected_ids = span

    def select_all(self):
        self.selected_ids = {a["avatar_id"] for a in self.avatars}
        self._anchor_id = None
        self.refresh_selection()

    def clear_selection(self):
        self.selected_ids.clear()
        self._anchor_id = None
        self.refresh_selection()

    def refresh_selection(self):
        for card in self.cards():
            card.set_selected(card.avatar_id in self.selected_ids)
        self.update_selection_bar()

    def selected_avatars(self):
        """The selected rows, in the order they appear on screen."""
        return [a for a in self.avatars if a["avatar_id"] in self.selected_ids]

    def transfer_selection(self):
        avatars = self.selected_avatars()
        if not avatars:
            return
        if self.on_bulk_categories is None:
            return
        self.on_bulk_categories(avatars)

    def load_avatars(self, category_id=None, favorite_only=False, search="",
                     sort_by=None, sort_dir=None):
        self.current_category_id = category_id
        self.current_favorite_only = favorite_only
        self.current_search = search
        if sort_by is not None:
            self.current_sort_by = sort_by
        if sort_dir is not None:
            self.current_sort_dir = sort_dir

        self.avatars = db.get_all_avatars(category_id=category_id,
                                          favorite_only=favorite_only,
                                          search=search,
                                          sort_by=self.current_sort_by,
                                          sort_dir=self.current_sort_dir)
        self.thumbnail_loaders.clear()
        # Anything filtered out is no longer selectable, and keeping the id
        # around would silently re-select it the moment the filter is cleared.
        visible = {a["avatar_id"] for a in self.avatars}
        self.selected_ids &= visible
        self.rebuild_cards()
        self.refresh_selection()

    def rebuild_cards(self):
        """Recreate the cards for the current result set."""
        self.clear_layout()
        cols = max(1, self.width() // 200)

        for i, av in enumerate(self.avatars):
            card = AvatarCard(av, self.edit_categories, self.delete_avatar,
                              on_move=getattr(self, "on_move_favorite", None),
                              on_toggle_favorite=self.request_favorite_toggle,
                              on_select=self.on_card_clicked,
                              colors=self.colors, density=self.density,
                              show_ids=self.show_ids)
            self.grid.addWidget(card, i // cols, i % cols)
            if av["thumbnail_url"] or os.path.exists(os.path.join(CACHE_DIR, f"{av['avatar_id']}.png")):
                loader = ThumbnailLoader(av["thumbnail_url"], av["avatar_id"],
                                         session=getattr(self, "session", None))
                loader.loaded.connect(card.set_thumbnail)
                self.thumbnail_loaders.append(loader)
                loader.start()
            else:
                placeholder = QPixmap(160, 120)
                placeholder.fill(Qt.GlobalColor.lightGray)
                card.set_thumbnail(placeholder)

    def request_favorite_toggle(self, avatar_data, current_favorite):
        """The star: hand the intent up, because it hits vrchat.com."""
        handler = getattr(self, "on_toggle_favorite", None)
        if handler is None:
            # Standalone: fall back to the local flag so the star is not dead.
            db.toggle_favorite(avatar_data["avatar_id"])
            self.refresh()
            return
        handler(avatar_data, current_favorite)

    def clear_layout(self):
        while self.grid.count():
            item = self.grid.takeAt(0)
            if item.widget():
                item.widget().deleteLater()

    def edit_categories(self, avatar_data):
        """The folder button's handler. The window owns the dialog so it can
        refresh the sidebar counts afterwards."""
        handler = getattr(self, "on_edit_categories", None)
        if handler is None:
            return
        handler(avatar_data)

    def toggle_favorite(self, avatar_id):
        db.toggle_favorite(avatar_id)
        self.refresh()

    def delete_avatar(self, avatar_id):
        if self.confirm_delete:
            confirm = QMessageBox.question(self, "Delete Avatar",
                                           f"Remove this avatar from library?",
                                           QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No)
            if confirm != QMessageBox.StandardButton.Yes:
                return
        db.delete_avatar(avatar_id)
        self.refresh()

    def refresh(self):
        """Reload using the filters and ordering currently in effect."""
        self.load_avatars(category_id=self.current_category_id,
                          favorite_only=self.current_favorite_only,
                          search=self.current_search)

    def apply_settings(self, colors, density, show_ids, confirm_delete=True):
        """Apply theme/density/visibility and refresh all cards."""
        changed = (
            self.colors != colors
            or self.density != density
            or self.show_ids != show_ids
            or self.confirm_delete != confirm_delete)
        self.colors = colors
        self.density = density
        self.show_ids = show_ids
        self.confirm_delete = confirm_delete
        if changed:
            # Rebuilding re-applies the per-card stylesheet and density.
            self.load_avatars(category_id=self.current_category_id,
                              favorite_only=self.current_favorite_only,
                              search=self.current_search)

    def relayout(self):
        """Re-flow the existing cards after a resize.

        Rebuilding would drop in-flight thumbnail downloads and cost a database
        query on every pixel of a drag, so only the positions are recomputed.
        """
        cards = [self.grid.itemAt(i).widget() for i in range(self.grid.count())
                 if self.grid.itemAt(i) and self.grid.itemAt(i).widget()]
        cols = max(1, self.width() // 200)
        for index, card in enumerate(cards):
            self.grid.addWidget(card, index // cols, index % cols)

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self.relayout()
