import os
import requests
from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLineEdit, QComboBox,
    QPushButton, QScrollArea, QGridLayout, QLabel, QFrame,
    QMessageBox, QMenu, QCheckBox
)
from PyQt6.QtCore import Qt, QThread, pyqtSignal, QSize
from PyQt6.QtGui import QPixmap, QFont, QAction
import database as db
from PIL import Image
from io import BytesIO

CACHE_DIR = db.CACHE_DIR

class ThumbnailLoader(QThread):
    loaded = pyqtSignal(str, QPixmap)

    def __init__(self, url, avatar_id):
        super().__init__()
        self.url = url
        self.avatar_id = avatar_id

    def run(self):
        cache_path = os.path.join(CACHE_DIR, f"{self.avatar_id}.png")
        if os.path.exists(cache_path):
            pix = QPixmap(cache_path)
            if not pix.isNull():
                self.loaded.emit(self.avatar_id, pix)
                return
        if not self.url:
            return
        try:
            r = requests.get(self.url, timeout=10)
            if r.status_code == 200:
                img = Image.open(BytesIO(r.content))
                img.thumbnail((200, 200))
                img.save(cache_path, "PNG")
                pix = QPixmap(cache_path)
                if not pix.isNull():
                    self.loaded.emit(self.avatar_id, pix)
        except Exception:
            pass

class AvatarCard(QFrame):
    def __init__(self, avatar_data, on_favorite_toggle, on_delete):
        super().__init__()
        self.avatar_id = avatar_data["avatar_id"]
        self.avatar_data = avatar_data
        self.on_favorite_toggle = on_favorite_toggle
        self.on_delete = on_delete
        self.setFrameShape(QFrame.Shape.StyledPanel)
        self.setStyleSheet("""
            AvatarCard { border: 1px solid #ccc; border-radius: 6px; padding: 6px; background: #fafafa; }
            AvatarCard:hover { border-color: #4a90d9; background: #eef5ff; }
        """)
        self.setMinimumSize(180, 240)
        self.setMaximumSize(220, 280)
        self.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.customContextMenuRequested.connect(self.show_context_menu)
        self.setup_ui()

    def setup_ui(self):
        layout = QVBoxLayout(self)
        layout.setSpacing(4)
        layout.setContentsMargins(6, 6, 6, 6)

        self.thumb_label = QLabel()
        self.thumb_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.thumb_label.setMinimumSize(160, 120)
        self.thumb_label.setStyleSheet("background: #ddd; border-radius: 4px;")
        layout.addWidget(self.thumb_label)

        fav_emoji = "★" if self.avatar_data["favorite"] else "☆"
        self.fav_btn = QPushButton(fav_emoji)
        self.fav_btn.setFixedSize(28, 28)
        self.fav_btn.setStyleSheet(
            "QPushButton { font-size: 18px; border: none; }"
            "QPushButton:hover { background: #eee; border-radius: 4px; }"
        )
        self.fav_btn.clicked.connect(lambda: self.on_favorite_toggle(self.avatar_id))

        top_row = QHBoxLayout()
        top_row.addStretch()
        top_row.addWidget(self.fav_btn)
        layout.addLayout(top_row)

        self.name_label = QLabel(self.avatar_data["name"])
        self.name_label.setWordWrap(True)
        self.name_label.setFont(QFont("Segoe UI", 10, QFont.Weight.Bold))
        self.name_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(self.name_label)

        author = self.avatar_data["author"] or "Unknown"
        self.author_label = QLabel(author)
        self.author_label.setFont(QFont("Segoe UI", 8))
        self.author_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.author_label.setStyleSheet("color: #666;")
        layout.addWidget(self.author_label)

        self.id_label = QLabel(self.avatar_id[:12] + "...")
        self.id_label.setFont(QFont("Consolas", 7))
        self.id_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.id_label.setStyleSheet("color: #999;")
        layout.addWidget(self.id_label)

    def set_thumbnail(self, pixmap):
        scaled = pixmap.scaled(160, 120, Qt.AspectRatioMode.KeepAspectRatio,
                               Qt.TransformationMode.SmoothTransformation)
        self.thumb_label.setPixmap(scaled)

    def show_context_menu(self, pos):
        menu = QMenu(self)
        view_detail = QAction("View Details", self)
        delete_action = QAction("Delete", self)
        menu.addAction(view_detail)
        menu.addAction(delete_action)
        action = menu.exec(self.mapToGlobal(pos))
        if action == delete_action:
            self.on_delete(self.avatar_id)

class AvatarListWidget(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.avatars = []
        self.thumbnail_loaders = []
        self.setup_ui()

    def setup_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)

        self.scroll = QScrollArea()
        self.scroll.setWidgetResizable(True)
        self.scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        layout.addWidget(self.scroll)

        self.container = QWidget()
        self.grid = QGridLayout(self.container)
        self.grid.setSpacing(8)
        self.scroll.setWidget(self.container)

    def load_avatars(self, category_id=None, favorite_only=False, search=""):
        self.avatars = db.get_all_avatars(category_id=category_id,
                                          favorite_only=favorite_only,
                                          search=search)
        self.thumbnail_loaders.clear()
        self.clear_layout()
        cols = max(1, self.width() // 200)

        for i, av in enumerate(self.avatars):
            card = AvatarCard(av, self.toggle_favorite, self.delete_avatar)
            self.grid.addWidget(card, i // cols, i % cols)
            if av["thumbnail_url"] or os.path.exists(os.path.join(CACHE_DIR, f"{av['avatar_id']}.png")):
                loader = ThumbnailLoader(av["thumbnail_url"], av["avatar_id"])
                loader.loaded.connect(card.set_thumbnail)
                self.thumbnail_loaders.append(loader)
                loader.start()
            else:
                placeholder = QPixmap(160, 120)
                placeholder.fill(Qt.GlobalColor.lightGray)
                card.set_thumbnail(placeholder)

    def clear_layout(self):
        while self.grid.count():
            item = self.grid.takeAt(0)
            if item.widget():
                item.widget().deleteLater()

    def toggle_favorite(self, avatar_id):
        db.toggle_favorite(avatar_id)
        self.refresh()

    def delete_avatar(self, avatar_id):
        confirm = QMessageBox.question(self, "Delete Avatar",
                                       f"Remove this avatar from library?",
                                       QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No)
        if confirm == QMessageBox.StandardButton.Yes:
            db.delete_avatar(avatar_id)
            self.refresh()

    def refresh(self):
        self.load_avatars()

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self.load_avatars()
