import re
from PyQt6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel, QLineEdit, QPushButton,
    QCheckBox, QTextEdit, QMessageBox, QGroupBox, QFormLayout
)
from PyQt6.QtCore import Qt, QThread, pyqtSignal
import database as db
from api.vrchat_api import VRChatAPI, VRChatAPIError

class AvatarLookupThread(QThread):
    """Looks up one avatar, always reporting back.

    The failure signal matters: a lookup that returns nothing used to leave the
    dialog stuck on "Looking up..." forever.
    """

    finished = pyqtSignal(dict)
    failed = pyqtSignal(str)

    def __init__(self, api, avatar_id):
        super().__init__()
        self.api = api
        self.avatar_id = avatar_id

    def run(self):
        try:
            data = self.api.lookup_avatar(self.avatar_id)
        except VRChatAPIError as error:
            self.failed.emit(error.message.strip('"'))
            return
        except Exception as error:
            self.failed.emit(str(error))
            return

        if data is None:
            self.failed.emit("VRChat has no avatar with that id.")
        else:
            self.finished.emit(data)

class AddAvatarDialog(QDialog):
    def __init__(self, vrchat_api: VRChatAPI = None, parent=None):
        super().__init__(parent)
        self.vrchat_api = vrchat_api
        self.lookup_data = None
        self.setWindowTitle("Add Avatar")
        self.setMinimumWidth(450)
        self.setup_ui()

    def setup_ui(self):
        layout = QVBoxLayout(self)

        form = QFormLayout()

        self.id_input = QLineEdit()
        self.id_input.setPlaceholderText("avtr_... or full URL")
        self.id_input.textChanged.connect(self.on_id_changed)
        form.addRow("Avatar ID / URL:", self.id_input)

        self.lookup_btn = QPushButton("Look Up (via API)")
        self.lookup_btn.setEnabled(False)
        form.addRow("", self.lookup_btn)
        self.lookup_btn.clicked.connect(self.do_lookup)

        self.name_input = QLineEdit()
        self.name_input.setPlaceholderText("Avatar name")
        form.addRow("Name:", self.name_input)

        self.author_input = QLineEdit()
        self.author_input.setPlaceholderText("Author name")
        form.addRow("Author:", self.author_input)

        self.thumbnail_input = QLineEdit()
        self.thumbnail_input.setPlaceholderText("Thumbnail URL")
        form.addRow("Thumbnail:", self.thumbnail_input)

        self.notes_input = QTextEdit()
        self.notes_input.setMaximumHeight(80)
        self.notes_input.setPlaceholderText("Optional notes...")
        form.addRow("Notes:", self.notes_input)

        self.favorite_cb = QCheckBox("Mark as favorite")
        form.addRow("", self.favorite_cb)

        layout.addLayout(form)

        btn_layout = QHBoxLayout()
        self.add_btn = QPushButton("Add to Library")
        self.cancel_btn = QPushButton("Cancel")
        btn_layout.addStretch()
        btn_layout.addWidget(self.add_btn)
        btn_layout.addWidget(self.cancel_btn)
        layout.addLayout(btn_layout)

        self.add_btn.clicked.connect(self.add_avatar)
        self.cancel_btn.clicked.connect(self.reject)

    def on_id_changed(self, text):
        parsed = self._parse_id(text)
        # VRChat needs a session even for public avatars, so do not offer a
        # lookup that is guaranteed to fail.
        self.lookup_btn.setEnabled(
            bool(parsed) and self.vrchat_api is not None and self.vrchat_api.authenticated)

    def do_lookup(self):
        parsed = self._parse_id(self.id_input.text())
        if not parsed:
            return
        self.lookup_btn.setEnabled(False)
        self.lookup_btn.setText("Looking up...")
        self.thread = AvatarLookupThread(self.vrchat_api, parsed)
        self.thread.finished.connect(self.on_lookup_result)
        self.thread.failed.connect(self.on_lookup_failed)
        self.thread.start()

    def on_lookup_failed(self, message):
        self.lookup_btn.setText("Look Up (via API)")
        self.lookup_btn.setEnabled(True)
        QMessageBox.warning(self, "Lookup Failed", message)

    def on_lookup_result(self, data):
        self.lookup_data = data
        self.name_input.setText(data.get("name", ""))
        self.author_input.setText(data.get("author", ""))
        self.thumbnail_input.setText(data.get("thumbnail_url", ""))
        self.lookup_btn.setText("Look Up (via API)")
        self.lookup_btn.setEnabled(True)

    def add_avatar(self):
        avatar_id = self._parse_id(self.id_input.text())
        if not avatar_id:
            QMessageBox.warning(self, "Error", "Invalid avatar ID. Expected avtr_... format.")
            return
        name = self.name_input.text().strip() or "Unknown"
        author = self.author_input.text().strip()
        thumbnail = self.thumbnail_input.text().strip()
        notes = self.notes_input.toPlainText().strip()
        favorite = self.favorite_cb.isChecked()

        existing = db.get_avatar(avatar_id)
        if existing:
            QMessageBox.warning(self, "Error", f"Avatar '{avatar_id}' already exists in library.")
            return

        db.add_avatar(avatar_id, name=name, author=author,
                      thumbnail_url=thumbnail, notes=notes, favorite=favorite)
        self.accept()

    @staticmethod
    def _parse_id(text: str) -> str | None:
        m = re.search(r"avtr_[0-9a-f\-]{36}", text, re.IGNORECASE)
        return m.group(0) if m else None
