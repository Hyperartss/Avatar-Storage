import os
import json
import sqlite3
from PyQt6.QtWidgets import (
    QMainWindow, QWidget, QVBoxLayout, QHBoxLayout, QPushButton,
    QLineEdit, QComboBox, QListWidget, QListWidgetItem, QSplitter,
    QMessageBox, QLabel, QInputDialog, QDialog, QFormLayout,
    QCheckBox, QTextEdit, QProgressDialog
)
from PyQt6.QtCore import Qt, QTimer
from PyQt6.QtGui import QAction
import database as db
from gui.avatar_list import AvatarListWidget
from gui.add_dialog import AddAvatarDialog
from gui.category_manager import CategoryManager
from api.vrchat_api import VRChatAPI

VRCX_DB_CANDIDATES = [
    os.path.expandvars(r"%APPDATA%\VRCX\VRCX.sqlite3"),
    os.path.expandvars(r"%LOCALAPPDATA%\VRCX\VRCX.sqlite3"),
]

class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.vrchat_api = VRChatAPI()
        self.current_category_id = None
        self.current_favorite_only = False
        self.current_search = ""
        self.setWindowTitle("INF Avis - VRChat Avatar Library Manager")
        self.setMinimumSize(900, 600)
        self.setup_ui()
        self.setup_menu()
        self.load_categories()
        self.load_avatars()

    def setup_ui(self):
        central = QWidget()
        self.setCentralWidget(central)
        main_layout = QVBoxLayout(central)
        main_layout.setContentsMargins(6, 6, 6, 6)

        toolbar = QHBoxLayout()

        self.search_input = QLineEdit()
        self.search_input.setPlaceholderText("Search avatars...")
        self.search_input.setMinimumWidth(200)
        self.search_input.textChanged.connect(self.on_search)
        toolbar.addWidget(self.search_input)

        self.filter_combo = QComboBox()
        self.filter_combo.setMinimumWidth(150)
        self.filter_combo.currentIndexChanged.connect(self.on_filter_changed)
        toolbar.addWidget(QLabel("Category:"))

        toolbar.addWidget(self.filter_combo)

        self.fav_filter_cb = QCheckBox("Favorites Only")
        self.fav_filter_cb.toggled.connect(self.on_fav_filter)
        toolbar.addWidget(self.fav_filter_cb)

        toolbar.addStretch()

        self.add_btn = QPushButton("+ Add Avatar")
        self.add_btn.clicked.connect(self.add_avatar_dialog)
        toolbar.addWidget(self.add_btn)

        self.import_vrcx_btn = QPushButton("Import from VRCX")
        self.import_vrcx_btn.clicked.connect(self.import_vrcx)
        toolbar.addWidget(self.import_vrcx_btn)

        main_layout.addLayout(toolbar)

        self.avatar_list = AvatarListWidget()
        main_layout.addWidget(self.avatar_list)

    def setup_menu(self):
        menubar = self.menuBar()

        file_menu = menubar.addMenu("&File")
        file_menu.addAction("Manage Categories...", self.manage_categories)
        file_menu.addSeparator()
        file_menu.addAction("&Exit", self.close)

        api_menu = menubar.addMenu("&VRChat API")
        self.api_login_action = QAction("&Login...", self)
        self.api_login_action.triggered.connect(self.api_login_dialog)
        api_menu.addAction(self.api_login_action)
        self.api_logout_action = QAction("&Logout", self)
        self.api_logout_action.triggered.connect(self.api_logout)
        self.api_logout_action.setEnabled(False)
        api_menu.addAction(self.api_logout_action)
        self.api_status_label = QAction("Not logged in", self)
        self.api_status_label.setEnabled(False)
        api_menu.addSeparator()
        api_menu.addAction(self.api_status_label)

        help_menu = menubar.addMenu("&Help")
        help_menu.addAction("&About", lambda: QMessageBox.about(self, "About",
            "INF Avis - VRChat Avatar Library Manager\n\n"
            "Manage your personal VRChat avatar library offline.\n"
            "Paste avatar IDs, look up via API, or import from VRCX."))

        self.update_api_menu()

    def update_api_menu(self):
        if self.vrchat_api.authenticated:
            self.api_status_label.setText(f"Logged in as: {self.vrchat_api.current_user}")
            self.api_login_action.setEnabled(False)
            self.api_logout_action.setEnabled(True)
        else:
            self.api_status_label.setText("Not logged in")
            self.api_login_action.setEnabled(True)
            self.api_logout_action.setEnabled(False)

    def api_login_dialog(self):
        dialog = QDialog(self)
        dialog.setWindowTitle("VRChat API Login")
        dialog.setMinimumWidth(350)
        layout = QFormLayout(dialog)
        username_input = QLineEdit()
        password_input = QLineEdit()
        password_input.setEchoMode(QLineEdit.EchoMode.Password)
        layout.addRow("Username/Email:", username_input)
        layout.addRow("Password:", password_input)

        btn_layout = QHBoxLayout()
        login_btn = QPushButton("Login")
        cancel_btn = QPushButton("Cancel")
        btn_layout.addStretch()
        btn_layout.addWidget(login_btn)
        btn_layout.addWidget(cancel_btn)
        layout.addRow(btn_layout)

        result = {"ok": False}

        def do_login():
            username = username_input.text().strip()
            password = password_input.text().strip()
            if not username or not password:
                QMessageBox.warning(dialog, "Error", "Enter username and password.")
                return
            login_btn.setEnabled(False)
            login_btn.setText("Logging in...")
            QTimer.singleShot(100, lambda: _do_login_work())

        def _do_login_work():
            try:
                ok, msg = self.vrchat_api.login(username_input.text().strip(),
                                                 password_input.text().strip())
                if ok:
                    result["ok"] = True
                    dialog.accept()
                elif msg == "requires_2fa":
                    code, ok2 = QInputDialog.getText(dialog, "2FA Required",
                                                      "Enter 2FA code from authenticator:")
                    if ok2 and code.strip():
                        ok3, msg3 = self.vrchat_api.verify_2fa(code.strip())
                        if ok3:
                            result["ok"] = True
                            dialog.accept()
                        else:
                            QMessageBox.warning(dialog, "2FA Error", msg3)
                    else:
                        self.vrchat_api.logout()
                else:
                    QMessageBox.warning(dialog, "Login Failed", msg)
            except Exception as e:
                QMessageBox.critical(dialog, "Error", f"An unexpected error occurred:\n{e}")
            finally:
                login_btn.setEnabled(True)
                login_btn.setText("Login")

        login_btn.clicked.connect(do_login)
        cancel_btn.clicked.connect(dialog.reject)
        dialog.exec()

        if result["ok"]:
            self.update_api_menu()

    def api_logout(self):
        self.vrchat_api.logout()
        self.update_api_menu()

    def load_categories(self):
        self.filter_combo.blockSignals(True)
        self.filter_combo.clear()
        self.filter_combo.addItem("All Avatars", None)
        for cat in db.get_all_categories():
            count = db.get_category_avatar_count(cat["id"])
            self.filter_combo.addItem(f"{cat['name']} ({count})", cat["id"])
        self.filter_combo.blockSignals(False)

    def load_avatars(self):
        self.avatar_list.load_avatars(
            category_id=self.current_category_id if not self.current_favorite_only else None,
            favorite_only=self.current_favorite_only,
            search=self.current_search,
        )

    def on_search(self, text):
        self.current_search = text.strip()
        self.load_avatars()

    def on_filter_changed(self, index):
        self.current_category_id = self.filter_combo.currentData()
        self.load_avatars()

    def on_fav_filter(self, checked):
        self.current_favorite_only = checked
        self.filter_combo.setEnabled(not checked)
        self.load_avatars()

    def add_avatar_dialog(self):
        dialog = AddAvatarDialog(vrchat_api=self.vrchat_api, parent=self)
        if dialog.exec():
            self.load_categories()
            self.load_avatars()

    def manage_categories(self):
        dialog = CategoryManager(self)
        dialog.exec()
        self.load_categories()
        self.load_avatars()

    def import_vrcx(self):
        db_path = self._find_vrcx_db()
        if not db_path:
            QMessageBox.information(self, "VRCX Not Found",
                "Could not find VRCX database.\n\n"
                f"Looked in:\n" + "\n".join(VRCX_DB_CANDIDATES) +
                "\n\nYou can manually copy your VRCX.sqlite3 file to the app folder.")
            return

        confirm = QMessageBox.question(self, "Import from VRCX",
            f"Import avatars from VRCX database?\n\n{db_path}\n\nThis will add any new avatars "
            f"found in your VRCX history/favorites to your library.",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No)
        if confirm != QMessageBox.StandardButton.Yes:
            return

        progress = QProgressDialog("Importing from VRCX...", "Cancel", 0, 100, self)
        progress.setWindowTitle("Import")
        progress.setMinimumDuration(0)

        try:
            conn = sqlite3.connect(db_path)
            conn.row_factory = sqlite3.Row
            imported = 0
            skipped = 0

            tables = conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table' AND name IN ('avatars', 'favorites')"
            ).fetchall()
            table_names = {t["name"] for t in tables}

            if "avatars" in table_names:
                rows = conn.execute("""
                    SELECT DISTINCT id, name, author_name, thumbnail_url, description
                    FROM avatars ORDER BY id
                """).fetchall()
                progress.setMaximum(len(rows) if rows else 1)
                for i, row in enumerate(rows):
                    if progress.wasCanceled():
                        break
                    progress.setValue(i)
                    aid = row["id"]
                    if not aid:
                        continue
                    existing = db.get_avatar(aid)
                    if existing:
                        skipped += 1
                        continue
                    db.add_avatar(
                        avatar_id=aid,
                        name=row.get("name", "") or "Unknown",
                        author=row.get("author_name", "") or "",
                        thumbnail_url=row.get("thumbnail_url", "") or "",
                        description=row.get("description", "") or "",
                    )
                    imported += 1

            if "favorites" in table_names and imported < 500:
                rows = conn.execute("""
                    SELECT DISTINCT id, name, author_name, thumbnail_url, description
                    FROM favorites WHERE type = 'avatar' ORDER BY id
                """).fetchall()
                progress.setMaximum(len(rows) if rows else 1)
                for i, row in enumerate(rows):
                    if progress.wasCanceled():
                        break
                    progress.setValue(i)
                    aid = row["id"]
                    if not aid:
                        continue
                    existing = db.get_avatar(aid)
                    if existing:
                        skipped += 1
                        continue
                    db.add_avatar(
                        avatar_id=aid,
                        name=row.get("name", "") or "Unknown",
                        author=row.get("author_name", "") or "",
                        thumbnail_url=row.get("thumbnail_url", "") or "",
                        description=row.get("description", "") or "",
                    )
                    imported += 1

            conn.close()
            progress.setValue(progress.maximum())

            QMessageBox.information(self, "Import Complete",
                f"Imported {imported} new avatars.\n{skipped} already existed.\n\n"
                f"Source: VRCX database")

        except Exception as e:
            QMessageBox.critical(self, "Import Error", f"Failed to import: {e}")

        self.load_categories()
        self.load_avatars()

    def _find_vrcx_db(self):
        for path in VRCX_DB_CANDIDATES:
            if os.path.exists(path):
                return path
        return None
