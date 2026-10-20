import os
import json
import sqlite3
from datetime import datetime
from pathlib import Path
from PyQt6.QtWidgets import (
    QMainWindow, QWidget, QVBoxLayout, QHBoxLayout, QPushButton,
    QLineEdit, QComboBox, QSplitter,
    QMessageBox, QLabel, QInputDialog, QDialog, QFormLayout,
    QCheckBox, QTextEdit, QProgressDialog, QFileDialog, QApplication
)
from PyQt6.QtCore import Qt, QTimer, QByteArray
from PyQt6.QtGui import QAction
import database as db
import paths
from gui.avatar_list import AvatarListWidget
from gui.add_dialog import AddAvatarDialog
from gui.category_manager import CategoryManager
from gui.category_sidebar import CategorySidebar
from gui.import_dialog import ImportFromWebsiteDialog
from gui.favorites_sync import FavoritesSyncDialog
from gui.group_move import MoveFavoritesDialog
from gui.category_picker import CategoryPickerDialog
from gui.bulk_categories import BulkCategoryDialog
from gui.favorite_toggle import FavoriteToggleWorker
from gui.otp import prompt_for_code
from gui.settings import DEFAULTS, load, save, set_
from gui.settings_dialog import SettingsDialog
from gui.theme import apply_theme, current_colors
from api.vrchat_api import VRChatAPI, TWO_FACTOR_LABELS

class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.vrchat_api = VRChatAPI()
        self.current_category_id = None
        self.current_search = ""
        self.settings = load()
        self.setWindowTitle("INF Avis - VRChat Avatar Library Manager")
        self.setMinimumSize(900, 600)
        self.setup_ui()
        self.setup_menu()
        self._apply_settings()
        self.load_categories()
        self.load_avatars()
        self._restore_geometry()

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

        toolbar.addStretch()

        self.sort_combo = QComboBox()
        self.sort_combo.addItem("Newest first", "date_added")
        self.sort_combo.addItem("Oldest first", "date_added_oldest")
        self.sort_combo.addItem("Name A-Z", "name")
        self.sort_combo.addItem("Name Z-A", "name_desc")
        self.sort_combo.addItem("Author A-Z", "author")
        self.sort_combo.addItem("Author Z-A", "author_desc")
        self.sort_combo.addItem("Most favourited", "favorites_count")
        self.sort_combo.addItem("Most downloaded", "downloads")
        self.sort_combo.addItem("Highest rated", "rating")
        self.sort_combo.addItem("Recently updated on VRChat", "date_updated")
        self.sort_combo.currentIndexChanged.connect(self.on_sort_changed)
        self.sort_combo.setToolTip("Order the avatars however you like")
        toolbar.addWidget(self.sort_combo)

        self.add_btn = QPushButton("+ Add Avatar")
        self.add_btn.clicked.connect(self.add_avatar_dialog)
        toolbar.addWidget(self.add_btn)

        main_layout.addLayout(toolbar)

        splitter = QSplitter()
        splitter.setChildrenCollapsible(False)

        self.sidebar = CategorySidebar()
        self.sidebar.categorySelected.connect(self.on_category_selected)
        self.sidebar.avatarFiled.connect(self.on_avatar_filed)
        self.sidebar.avatarFavourited.connect(self.on_avatar_favourited)
        splitter.addWidget(self.sidebar)

        self.avatar_list = AvatarListWidget(session=self.vrchat_api.session)
        self.avatar_list.on_move_favorite = self.move_single_favorite
        self.avatar_list.on_edit_categories = self.edit_avatar_categories
        self._favorite_queue = []
        self.avatar_list.on_toggle_favorite = self.toggle_vrchat_favorite
        self.avatar_list.on_bulk_categories = self.bulk_edit_categories
        # Live worker for the star, kept so a second star press can reuse it.
        self.favorite_worker = None
        splitter.addWidget(self.avatar_list)

        # Give the avatar grid most of the space, keep the sidebar compact.
        splitter.setStretchFactor(0, 0)
        splitter.setStretchFactor(1, 1)

        main_layout.addWidget(splitter, 1)

    # Sort choices that need a direction the combo label cannot express.
    SORT_OVERRIDES = {
        "date_added_oldest": ("date_added", "ASC"),
        "name": ("name", "ASC"),
        "name_desc": ("name", "DESC"),
        "author": ("author", "ASC"),
        "author_desc": ("author", "DESC"),
    }

    def setup_menu(self):
        menubar = self.menuBar()

        file_menu = menubar.addMenu("&File")
        file_menu.addAction("Import from VRChat Website...", self.import_from_website)
        file_menu.addAction("Import &Favourites from VRChat...", self.sync_favorites)
        file_menu.addAction("&Move Favourites Between Groups...", self.move_favorites)
        file_menu.addAction("&Add Avatar Manually...", self.add_avatar_dialog)
        file_menu.addSeparator()
        file_menu.addAction("Manage Categories...", self.manage_categories)
        file_menu.addAction("&Settings...", self.open_settings)
        file_menu.addSeparator()
        file_menu.addAction("E&xit", self.close)

        api_menu = menubar.addMenu("&VRChat API")
        self.api_login_action = QAction("&Login...", self)
        self.api_login_action.triggered.connect(self.api_login_dialog)
        api_menu.addAction(self.api_login_action)
        self.api_logout_action = QAction("&Logout", self)
        self.api_logout_action.triggered.connect(self.api_logout)
        self.api_logout_action.setEnabled(False)
        api_menu.addAction(self.api_logout_action)
        self.api_2fa_action = QAction("Verify Two-Factor &Code...", self)
        self.api_2fa_action.triggered.connect(self.api_verify_2fa)
        self.api_2fa_action.setEnabled(False)
        api_menu.addAction(self.api_2fa_action)
        self.api_status_label = QAction("Not logged in", self)
        self.api_status_label.setEnabled(False)
        api_menu.addSeparator()
        api_menu.addAction(self.api_status_label)

        help_menu = menubar.addMenu("&Help")
        help_menu.addAction("&About", lambda: QMessageBox.about(self, "About",
            "INF Avis - VRChat Avatar Library Manager\n\n"
            "Manage your personal VRChat avatar library offline.\n"
            "Paste avatar IDs or look up via API."))

        self.update_api_menu()

    def update_api_menu(self):
        if self.vrchat_api.authenticated:
            if self.vrchat_api.two_factor_required:
                method = self.vrchat_api.required_two_factor_method()
                self.api_status_label.setText(
                    f"Logged in as: {self.vrchat_api.current_user} "
                    f"— needs {TWO_FACTOR_LABELS.get(method, method)} code")
            else:
                self.api_status_label.setText(f"Logged in as: {self.vrchat_api.current_user}")
            self.api_login_action.setEnabled(False)
            self.api_logout_action.setEnabled(True)
            self.api_2fa_action.setEnabled(True)
        else:
            self.api_status_label.setText("Not logged in")
            self.api_login_action.setEnabled(True)
            self.api_logout_action.setEnabled(False)
            self.api_2fa_action.setEnabled(False)

    def api_verify_2fa(self):
        """Enter a two-factor code without having to log in again.

        VRChat accepts a saved session for identification but refuses data calls
        until a code is submitted, which is the state a restart leaves you in.
        """
        if not self.vrchat_api.authenticated:
            QMessageBox.information(
                self, "Not logged in",
                "Log in first, then enter your two-factor code.")
            return

        # Ask VRChat which kind of code it wants rather than assuming an
        # authenticator app: an email-code account rejects app codes outright.
        self.vrchat_api.refresh_two_factor_methods()
        if prompt_for_code(self, self.vrchat_api):
            QMessageBox.information(
                self, "Two-Factor Verified",
                "Code accepted. Imports and favourites sync will work again.")
        self.update_api_menu()

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
                    if prompt_for_code(dialog, self.vrchat_api,
                                       "VRChat needs a verification code to finish signing in."):
                        result["ok"] = True
                        dialog.accept()
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
        self.sidebar.refresh()

    def _apply_settings(self):
        """Apply the persisted theme, density and visibility options."""
        apply_theme(QApplication.instance(), self.settings.get(
            "theme", DEFAULTS["theme"]))
        self.sidebar.apply_theme(current_colors())

        density = self.settings.get("density", DEFAULTS["density"])
        show_ids = self.settings.get("show_avatar_ids", DEFAULTS["show_avatar_ids"])
        confirm_delete = self.settings.get("confirm_delete", DEFAULTS["confirm_delete"])
        self.avatar_list.apply_settings(current_colors(), density, show_ids,
                                        confirm_delete)

        show_sidebar = self.settings.get("show_sidebar", DEFAULTS["show_sidebar"])
        self.sidebar.setVisible(show_sidebar)

        # Restore the last sort choice.
        last_sort = self.settings.get("last_sort", DEFAULTS["last_sort"])
        for index in range(self.sort_combo.count()):
            if self.sort_combo.itemData(index) == last_sort:
                self.sort_combo.setCurrentIndex(index)
                break

    def apply_theme(self, mode: str):
        """User picked a new theme: apply it everywhere and persist."""
        set_(self.settings, "theme", mode)
        save(self.settings)
        self._apply_settings()

    def apply_density(self, density: str):
        set_(self.settings, "density", density)
        save(self.settings)
        self._apply_settings()

    # -------------------------------------------------------------- geometry

    def _restore_geometry(self):
        geo = self.settings.get("window_geometry")
        state = self.settings.get("window_state")
        if geo is not None:
            self.restoreGeometry(QByteArray.fromBase64(geo.encode()))
        if state is not None:
            self.restoreState(QByteArray.fromBase64(state.encode()))

    def _save_geometry(self):
        set_(self.settings, "window_geometry",
             self.saveGeometry().toBase64().data().decode())
        set_(self.settings, "window_state",
             self.saveState().toBase64().data().decode())
        save(self.settings)

    def closeEvent(self, event):
        self._save_geometry()
        super().closeEvent(event)

    def load_avatars(self):
        self.avatar_list.load_avatars(
            category_id=self.current_category_id,
            favorite_only=False,
            search=self.current_search,
            sort_by=self.current_sort()[0],
            sort_dir=self.current_sort()[1],
        )

    def current_sort(self):
        """Resolve the combo choice to a (column, direction) pair."""
        key = self.sort_combo.currentData()
        if key in self.SORT_OVERRIDES:
            return self.SORT_OVERRIDES[key]
        return key or "date_added", "DESC"

    def on_sort_changed(self, index):
        self.load_avatars()
        # Remember the user's sort choice so it survives a restart.
        key = self.sort_combo.currentData()
        if key:
            set_(self.settings, "last_sort", key)
            save(self.settings)

    def on_search(self, text):
        self.current_search = text.strip()
        self.load_avatars()

    def on_category_selected(self, category_id):
        self.current_category_id = category_id
        self.load_avatars()

    def on_avatar_filed(self, avatar_id, category_id):
        # The sidebar already refreshed its counts; reload the grid so the
        # filed card leaves or enters the current filtered view.
        self.load_avatars()

    def on_avatar_favourited(self, avatar_id):
        avatar = db.get_avatar(avatar_id)
        if avatar is None:
            return
        self.toggle_vrchat_favorite(
            dict(avatar), bool(avatar["favorite"]))

    def add_avatar_dialog(self):
        dialog = AddAvatarDialog(vrchat_api=self.vrchat_api, parent=self)
        if dialog.exec():
            self.load_categories()
            self.load_avatars()

    def import_from_website(self):
        dialog = ImportFromWebsiteDialog(self.vrchat_api, self)
        dialog.exec()
        self.load_categories()
        self.load_avatars()

    def sync_favorites(self):
        dialog = FavoritesSyncDialog(self.vrchat_api, self)
        dialog.exec()
        self.load_categories()
        self.load_avatars()

    def edit_avatar_categories(self, avatar_data):
        """Star button on a card: file this avatar into local categories."""
        # Rows from the database have no .get(); read defensively so the dialog
        # gets a plain name whatever shape it is handed.
        name = (avatar_data.get("name") if isinstance(avatar_data, dict)
                else avatar_data["name"]) or ""

        dialog = CategoryPickerDialog(self, avatar_data["avatar_id"], name)
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return

        # The sidebar shows per-category counts and the list may have been
        # filtered by the category just changed, so both have to be rebuilt.
        self.load_categories()
        self.load_avatars()

    def toggle_vrchat_favorite(self, avatar_data, current_favorite):
        """The star: favourite or un-favourite this on vrchat.com.

        Local filing is the folder button's job, so this only ever talks to
        VRChat. Several cards can be toggled in one go, which is why the work
        takes a list rather than a single avatar.
        """
        if not self.vrchat_api.authenticated:
            QMessageBox.information(
                self, "Not logged in",
                "The star changes your favourites on vrchat.com, so log in "
                "first. To sort avatars into categories here instead, use the "
                "folder icon.")
            return

        avatar_id = avatar_data["avatar_id"]
        make_favorite = not current_favorite
        name = avatar_data["name"] or avatar_id

        # Whatever else is already in flight goes first, so the order the user
        # clicked in is the order VRChat sees.
        pending = list(getattr(self, "_favorite_queue", []))
        pending.append((avatar_id, name, make_favorite))
        self._favorite_queue = pending
        self._run_favorite_queue()

    def _run_favorite_queue(self):
        if self.favorite_worker is not None and self.favorite_worker.isRunning():
            return

        queue = getattr(self, "_favorite_queue", [])
        if not queue:
            return

        self._favorite_queue = []
        self.favorite_worker = FavoriteToggleWorker(self.vrchat_api, queue)
        self.favorite_worker.progress.connect(self.on_favorite_progress)
        self.favorite_worker.two_factor_required.connect(
            self.on_favorite_two_factor)
        self.favorite_worker.completed.connect(self.on_favorite_completed)
        self.favorite_worker.start()

    def on_favorite_progress(self, index, total, name):
        self.statusBar().showMessage(
            f"Updating vrchat.com favourites ({index + 1}/{total}): {name}")

    def on_favorite_two_factor(self):
        prompt_for_code(self, self.vrchat_api,
                        "Required to change your VRChat favourites.")
        if self.favorite_worker is not None:
            self.favorite_worker.confirm_two_factor()

    def on_favorite_completed(self, summary):
        self.statusBar().showMessage("")

        if summary["problems"]:
            # Never let a silent partial failure pass: the star will look
            # wrong afterwards and the user needs to know why.
            QMessageBox.warning(
                self, "Some favourites did not update",
                "\n".join(summary["problems"][:10])
                + (f"\n... and {len(summary['problems']) - 10} more"
                   if len(summary["problems"]) > 10 else ""))

        self.load_avatars()
        # Anything still queued went in while this batch was running.
        self._run_favorite_queue()

    def bulk_edit_categories(self, avatars):
        """Transfer the selection between local categories."""
        if not avatars:
            return
        dialog = BulkCategoryDialog(self, avatars)
        dialog.exec()
        self.load_categories()
        self.load_avatars()

    def move_favorites(self):
        """Reassign VRChat favourite groups for the avatars on screen."""
        if not self.vrchat_api.authenticated:
            QMessageBox.information(
                self, "Not logged in",
                "Log in first, then move favourites between groups.")
            return

        avatars = list(self.avatar_list.avatars)
        if not avatars:
            QMessageBox.information(
                self, "Nothing to move",
                "No avatars to show. Import your favourites first, or clear "
                "the current filter.")
            return

        dialog = MoveFavoritesDialog(self, self.vrchat_api, avatars)
        dialog.exec()
        self.load_categories()
        self.load_avatars()

    def move_single_favorite(self, avatar_data):
        """The card context menu entry: same dialog, one avatar preselected."""
        if not self.vrchat_api.authenticated:
            QMessageBox.information(
                self, "Not logged in",
                "Log in first, then move favourites between groups.")
            return

        dialog = MoveFavoritesDialog(self, self.vrchat_api, [avatar_data])
        dialog.avatar_list.item(0).setCheckState(Qt.CheckState.Checked)
        dialog.exec()
        self.load_categories()
        self.load_avatars()

    def manage_categories(self):
        dialog = CategoryManager(self)
        dialog.exec()
        self.load_categories()
        self.load_avatars()

    def open_settings(self):
        dialog = SettingsDialog(QApplication.instance(), self.settings, self)
        if dialog.exec():
            # Density or sidebar visibility may have changed.
            self._apply_settings()
            self.load_categories()
            self.load_avatars()

    @staticmethod
    def _format_mtime(path):
        try:
            return datetime.fromtimestamp(os.path.getmtime(path)).strftime("%Y-%m-%d %H:%M")
        except OSError:
            return "unknown date"
