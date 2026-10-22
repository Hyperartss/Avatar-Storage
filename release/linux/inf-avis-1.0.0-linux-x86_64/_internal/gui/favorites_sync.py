"""Import the account's VRChat favourites into the library.

The fav_ ids VRChat assigns are kept alongside the avatars, because removing a
favourite later needs that id rather than the avtr_ one.
"""

import time

from PyQt6.QtCore import pyqtSignal
from PyQt6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel, QPushButton, QCheckBox,
    QMessageBox, QProgressBar, QGroupBox, QFormLayout,
    QListWidget, QListWidgetItem,
)

import database as db
from api.vrchat_api import VRChatAPI, VRChatAPIError
from gui.worker_base import OtpAwareWorker
from gui.otp import prompt_for_code

REQUEST_DELAY = 0.7


class FavoritesWorker(OtpAwareWorker):
    """Pulls favourites, then fills in each avatar's metadata.

    Two-factor prompts are handled by OtpAwareWorker; see gui/worker_base.py.
    """

    progress = pyqtSignal(int, int, str)
    groups_found = pyqtSignal(list)
    completed = pyqtSignal(dict)

    def __init__(self, api, mirror_groups=True, mark_favorite=True,
                 refresh_existing=True):
        super().__init__(api)
        self.mirror_groups = mirror_groups
        self.mark_favorite = mark_favorite
        self.refresh_existing = refresh_existing

    def run(self):
        summary = {"added": 0, "updated": 0, "unchanged": 0, "failed": 0,
                   "total_favorites": 0, "missing": [],
                   "problems": [], "cancelled": False,
                   "groups_found": 0}

        try:
            groups = self._with_otp(self.api.get_favorite_groups, "avatar")
            summary["groups_found"] = len(groups)

            # Favourites have to be requested per group. Asking for the whole
            # set at once returns only what sits outside every group, which
            # looks like an empty library when someone groups everything.
            group_ids = [g["id"] for g in groups if g.get("id")]
            favorites = self._with_otp(self.api.get_all_favorites, "avatar",
                                       group_ids)
        except VRChatAPIError as error:
            summary["problems"].append(_describe(error))
            self.completed.emit(summary)
            return
        except Exception as error:
            summary["problems"].append(f"Unexpected error: {error}")
            self.completed.emit(summary)
            return

        if self._cancel:
            summary["cancelled"] = True
            self.completed.emit(summary)
            return

        self.groups_found.emit(groups)
        summary["total_favorites"] = len(favorites)
        self.progress.emit(0, len(favorites), f"{len(favorites)} favourite(s)")

        category_by_group = {}
        if self.mirror_groups and groups:
            try:
                category_by_group = db.sync_favorite_groups(groups)
            except Exception as error:
                summary["problems"].append(f"Mirroring groups: {error}")

        for index, favorite in enumerate(favorites):
            if self._cancel:
                summary["cancelled"] = True
                break

            avatar_id = favorite.get("avatar_id") or ""
            if not avatar_id:
                summary["failed"] += 1
                summary["problems"].append(
                    f"Skipped an entry with no avatar id: {str(favorite)[:80]}")
                continue

            existing = db.get_avatar(avatar_id)

            if existing is not None and not self.refresh_existing:
                summary["unchanged"] += 1
                self._after_store(favorite, avatar_id, category_by_group,
                                  summary, False)
                self.progress.emit(index + 1, len(favorites), existing["name"])
                continue

            try:
                payload = self.api.lookup_avatar(avatar_id)
            except VRChatAPIError as error:
                summary["failed"] += 1
                if error.needs_2fa:
                    summary["problems"].append(
                        f"{avatar_id}: session needs two-factor again")
                else:
                    summary["problems"].append(f"{avatar_id}: {error.message}")
                continue
            except Exception as error:
                summary["failed"] += 1
                # Never drop an error on the floor: a silent count is how a
                # sync that imports nothing looks like a sync that worked.
                summary["problems"].append(f"{avatar_id}: {error}")
                continue

            if payload is None:
                summary["missing"].append(avatar_id)
                summary["failed"] += 1
                self.progress.emit(index + 1, len(favorites), f"{avatar_id} not found")
                continue

            try:
                _, created = db.upsert_avatar(payload)
            except Exception as error:
                summary["failed"] += 1
                summary["problems"].append(f"{avatar_id}: {error}")
                continue

            summary["added" if created else "updated"] += 1
            self._after_store(favorite, avatar_id, category_by_group,
                              summary, created)
            self.progress.emit(index + 1, len(favorites), payload.get("name", ""))

            if index < len(favorites) - 1 and not self._cancel:
                time.sleep(REQUEST_DELAY)

        if self._cancel:
            summary["cancelled"] = True
        self.completed.emit(summary)

    def _after_store(self, favorite, avatar_id, category_by_group, summary, created):
        """Record the fav_ id, favourite flag and mirrored group membership."""
        try:
            group_id = ""
            groups = favorite.get("group_ids") or []
            if groups:
                group_id = groups[0]
            db.record_favorites([{**favorite, "group_id": group_id}],
                                mark_favorite=self.mark_favorite)
            if self.mirror_groups and category_by_group:
                targets = [category_by_group[g] for g in groups
                           if g in category_by_group]
                db.link_avatar_to_group_categories(avatar_id, targets)
        except Exception as error:
            summary["problems"].append(f"{avatar_id}: {error}")


def _describe(error: VRChatAPIError) -> str:
    return error.message.strip('"') or "Request failed"


class FavoritesSyncDialog(QDialog):
    def __init__(self, vrchat_api: VRChatAPI, parent=None):
        super().__init__(parent)
        self.api = vrchat_api
        self.worker = None
        self.setWindowTitle("Sync VRChat Favourites")
        self.setMinimumSize(580, 520)
        self.setup_ui()

    def setup_ui(self):
        layout = QVBoxLayout(self)

        intro = QLabel(
            "Reads the avatars you have favourited on vrchat.com, including "
            "your own favourites, and adds them to the library.")
        intro.setWordWrap(True)
        layout.addWidget(intro)

        options = QGroupBox("Options")
        form = QFormLayout(options)

        self.mirror_cb = QCheckBox("Create a category for each VRChat favourite group")
        self.mirror_cb.setChecked(True)
        form.addRow("", self.mirror_cb)

        self.mark_cb = QCheckBox("Mark imported avatars as favourites")
        self.mark_cb.setChecked(True)
        form.addRow("", self.mark_cb)

        self.refresh_cb = QCheckBox("Refresh avatars already in the library")
        self.refresh_cb.setToolTip(
            "Off is much faster: avatars already saved are linked without "
            "fetching their details again.")
        self.refresh_cb.setChecked(False)
        form.addRow("", self.refresh_cb)

        layout.addWidget(options)

        groups_label = QLabel("Favourite groups found:")
        layout.addWidget(groups_label)

        self.groups_list = QListWidget()
        self.groups_list.setMaximumHeight(140)
        layout.addWidget(self.groups_list)

        self.summary_label = QLabel("")
        self.summary_label.setWordWrap(True)
        layout.addWidget(self.summary_label)

        self.progress = QProgressBar()
        self.progress.setVisible(False)
        layout.addWidget(self.progress)

        btn_layout = QHBoxLayout()
        self.close_btn = QPushButton("Close")
        self.sync_btn = QPushButton("Sync Now")
        btn_layout.addStretch()
        btn_layout.addWidget(self.close_btn)
        btn_layout.addWidget(self.sync_btn)
        layout.addLayout(btn_layout)

        self.sync_btn.clicked.connect(self.start_sync)
        self.close_btn.clicked.connect(self.on_close)

    # ------------------------------------------------------------------

    def start_sync(self):
        if not self.api.authenticated:
            QMessageBox.warning(
                self, "Login required",
                "Favourites are private, so this needs a logged-in session.\n\n"
                "Use 'VRChat API -> Login...' first, then try again.")
            return

        self.set_busy(True)
        self.groups_list.clear()
        self.summary_label.setText("Reading your favourites...")

        self.worker = FavoritesWorker(
            self.api,
            mirror_groups=self.mirror_cb.isChecked(),
            mark_favorite=self.mark_cb.isChecked(),
            refresh_existing=self.refresh_cb.isChecked(),
        )
        self.worker.progress.connect(self.on_progress)
        self.worker.groups_found.connect(self.on_groups)
        self.worker.two_factor_required.connect(self.on_two_factor)
        self.worker.completed.connect(self.on_completed)
        self.worker.start()

    def set_busy(self, busy):
        for widget in (self.sync_btn, self.mirror_cb, self.mark_cb, self.refresh_cb):
            widget.setEnabled(not busy)
        self.progress.setVisible(busy)
        self.close_btn.setText("Stop" if busy else "Close")

    def on_groups(self, groups):
        for group in groups:
            capacity = group.get("capacity") or 0
            count = group.get("favorites_count") or 0
            suffix = f" ({count}/{capacity})" if capacity else f" ({count})"
            self.groups_list.addItem(QListWidgetItem(f"{group['name']}{suffix}"))

    def on_two_factor(self):
        """Runs on the GUI thread while the worker waits."""
        self.summary_label.setText("VRChat asked for a two-factor code...")
        if not prompt_for_code(self, self.api, "Required to read your favourites."):
            self.worker.cancel()
            return
        self.summary_label.setText("Verified, continuing...")
        self.worker.confirm_two_factor()

    def on_progress(self, count, total, message):
        self.progress.setMaximum(max(total, 1))
        self.progress.setValue(count)
        self.summary_label.setText(f"{count}/{total}  {message}")

    def on_completed(self, summary):
        self.set_busy(False)
        self.progress.setValue(self.progress.maximum())

        total = summary["total_favorites"]
        parts = [f"{total} favourite(s) from VRChat",
                 f"{summary['added']} added",
                 f"{summary['updated']} refreshed"]
        if summary["unchanged"]:
            parts.append(f"{summary['unchanged']} already here")
        if summary["failed"]:
            parts.append(f"{summary['failed']} failed")
        if summary["cancelled"]:
            parts.append("stopped early")

        lines = [", ".join(parts) + "."]

        if summary["groups_found"]:
            lines.append(f"Across {summary['groups_found']} favourite group(s).")

        if total == 0:
            lines.append("")
            if summary["groups_found"]:
                lines.append("VRChat returned no favourites from any group. "
                             "Check the account shown in the menu bar, then "
                             "Log out and back in to refresh the session.")
            else:
                lines.append("No favourite groups exist for this account, and "
                             "nothing is favourited outside a group.")
        elif summary["added"] == 0 and summary["updated"] == 0 and summary["unchanged"] == 0:
            lines.append("")
            lines.append("Favourites were found but none could be imported — "
                         "see the errors below.")

        if summary["missing"]:
            lines.append("")
            lines.append("No longer available in-game:")
            lines += [f"  {ref}" for ref in summary["missing"][:8]]
            if len(summary["missing"]) > 8:
                lines.append(f"  ... and {len(summary['missing']) - 8} more")
        if summary["problems"]:
            lines.append("")
            lines.append("Errors:")
            lines += [f"  {problem}" for problem in summary["problems"][:8]]
            if len(summary["problems"]) > 8:
                lines.append(f"  ... and {len(summary['problems']) - 8} more")

        self.summary_label.setText("\n".join(lines))
        self.sync_btn.setEnabled(True)

    def on_close(self):
        if self.worker is not None and self.worker.isRunning():
            self.worker.cancel()
            self.close_btn.setEnabled(False)
            self.summary_label.setText("Stopping after the current avatar...")
            return
        self.accept()

    def closeEvent(self, event):
        if self.worker is not None and self.worker.isRunning():
            self.worker.cancel()
            self.worker.wait(5000)
        super().closeEvent(event)