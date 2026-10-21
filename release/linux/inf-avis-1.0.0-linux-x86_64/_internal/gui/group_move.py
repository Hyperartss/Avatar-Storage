"""Move favourites between VRChat favourite groups.

VRChat offers no way to edit a favourite's group tags in place: PUT
/favorites/{id} answers 405 and the official SDK has no UpdateFavorite call.
A favourite does accept several tags at once, but POST refuses an avatar that
is already favourited, so changing groups is inherently remove-then-add. That
makes this a destructive operation on somebody's VRChat account, so the dialog
is explicit about what will happen, shows what each avatar is in now, and runs
off the GUI thread with per-avatar results.
"""

import threading
import time

from PyQt6.QtCore import QThread, Qt, pyqtSignal
from PyQt6.QtWidgets import (
    QCheckBox, QDialog, QDialogButtonBox, QGroupBox, QHBoxLayout, QLabel,
    QListWidget, QListWidgetItem, QMessageBox, QProgressBar, QPushButton,
    QTextEdit, QVBoxLayout,
)

from api.vrchat_api import VRChatAPI, VRChatAPIError
from gui.otp import prompt_for_code

# Space out the delete/add pairs so a large batch is not throttled.
REQUEST_DELAY = 1.0


class GroupMoveWorker(QThread):
    """Applies a set of group changes, reporting each avatar's outcome."""

    progress = pyqtSignal(int, int, str)
    finished_one = pyqtSignal(str, bool, str)
    needs_two_factor = pyqtSignal()
    completed = pyqtSignal(dict)

    def __init__(self, api, assignments):
        super().__init__()
        self.api = api
        # [(avatar_id, avatar_name, [slugs]), ...]
        self.assignments = assignments
        self._cancel = False
        self._otp = threading.Event()

    def cancel(self):
        self._cancel = True
        self._otp.set()

    def confirm_two_factor(self):
        self._otp.set()

    def run(self):
        summary = {"moved": 0, "unchanged": 0, "failed": 0, "cancelled": False}
        total = len(self.assignments)

        for index, (avatar_id, name, groups) in enumerate(self.assignments):
            if self._cancel:
                summary["cancelled"] = True
                break

            self.progress.emit(index, total, name)

            ok, message = self._with_otp(
                self.api.set_favorite_groups, avatar_id, groups,
                delay=REQUEST_DELAY)

            if ok:
                if message.startswith("Already"):
                    summary["unchanged"] += 1
                else:
                    summary["moved"] += 1
            else:
                summary["failed"] += 1

            self.finished_one.emit(name, ok, message)

            if index < total - 1 and not self._cancel:
                time.sleep(REQUEST_DELAY)

        summary["total"] = total
        self.completed.emit(summary)

    def _with_otp(self, call, *args, **kwargs):
        """Call an API method, absorbing a two-factor demand mid-batch.

        `call` is invoked with `*args` and `**kwargs`, so keyword-only options
        on the API method survive the retry wrapper.
        """
        attempts = kwargs.pop("_attempts", 2)
        last = None
        for attempt in range(attempts):
            try:
                return call(*args, **kwargs)
            except VRChatAPIError as error:
                last = error
                if not error.needs_2fa or attempt == attempts - 1:
                    raise
                self._otp.clear()
                self.needs_two_factor.emit()
                if not self._otp.wait(180):
                    return False, "Timed out waiting for a two-factor code"
                if self.api.two_factor_required:
                    return False, "Two-factor verification did not complete"
        return False, str(last)


class MoveFavoritesDialog(QDialog):
    """Pick avatars and the groups they should end up in."""

    def __init__(self, parent, api: VRChatAPI, avatars):
        super().__init__(parent)
        self.api = api
        # Rows out of the database are sqlite3.Row, which has no .get(). They
        # also behave differently enough from dict to bite, so normalise here
        # rather than making every consumer cope with both.
        self.avatars = [dict(a) if not isinstance(a, dict) else a
                        for a in avatars]
        self.groups = []                  # [{id, slug, display_name}]
        self.assignments = []
        self.worker = None
        self.otp_shown = False

        self.setWindowTitle("Move Between Favourite Groups")
        self.setMinimumSize(760, 620)

        layout = QVBoxLayout(self)

        intro = QLabel(
            "This changes your favourites on vrchat.com. VRChat cannot edit a "
            "favourite's groups in place, so each avatar is briefly removed "
            "from your favourites and added again with its new groups.")
        intro.setWordWrap(True)
        layout.addWidget(intro)

        self.status = QLabel("Loading your favourite groups...")
        layout.addWidget(self.status)

        body = QHBoxLayout()

        # Left: which avatars.
        left = QGroupBox("Avatars")
        left_layout = QVBoxLayout(left)
        self.select_all_btn = QPushButton("Select all")
        self.select_none_btn = QPushButton("Select none")
        row = QHBoxLayout()
        row.addWidget(self.select_all_btn)
        row.addWidget(self.select_none_btn)
        left_layout.addLayout(row)

        self.avatar_list = QListWidget()
        self.avatar_list.setSelectionMode(
            QListWidget.SelectionMode.NoSelection)
        left_layout.addWidget(self.avatar_list)
        body.addWidget(left, 3)

        # Right: which groups.
        right = QGroupBox("They should end up in")
        right_layout = QVBoxLayout(right)
        self.group_boxes = []
        self.group_hint = QLabel(
            "Tick every group an avatar should belong to. Unticking all of "
            "them unfavourites it.")
        self.group_hint.setWordWrap(True)
        right_layout.addWidget(self.group_hint)
        self.groups_layout = QVBoxLayout()
        right_layout.addLayout(self.groups_layout)
        body.addWidget(right, 2)

        layout.addLayout(body)

        self.progress = QProgressBar()
        self.progress.setVisible(False)
        layout.addWidget(self.progress)

        self.log = QTextEdit()
        self.log.setReadOnly(True)
        self.log.setMaximumHeight(120)
        layout.addWidget(self.log)

        buttons = QDialogButtonBox()
        self.move_btn = buttons.addButton(
            "Move", QDialogButtonBox.ButtonRole.AcceptRole)
        buttons.addButton(QDialogButtonBox.StandardButton.Close)
        self.move_btn.clicked.connect(self.on_move)
        buttons.rejected.connect(self.on_close)
        layout.addWidget(buttons)

        self.select_all_btn.clicked.connect(lambda: self.set_all_selected(True))
        self.select_none_btn.clicked.connect(lambda: self.set_all_selected(False))

        self._load_groups()

    # ------------------------------------------------------------------ setup

    def _load_groups(self):
        try:
            self.groups = [g for g in self.api.get_favorite_groups("avatar")
                           if g.get("slug")]
        except VRChatAPIError as error:
            self.status.setText(f"Could not load groups: {error.message}")
            self.move_btn.setEnabled(False)
            return

        if not self.groups:
            self.status.setText("This account has no avatar favourite groups.")
            self.move_btn.setEnabled(False)

        self.status.setText(f"{len(self.groups)} group(s). "
                            "Tick the boxes for the avatars you selected.")

        for group in self.groups:
            box = QCheckBox(f"{group['name']}   ({group['slug']})")
            self.groups_layout.addWidget(box)
            self.group_boxes.append(box)

        for avatar in self.avatars:
            name = avatar.get("name") or avatar.get("avatar_id", "")
            item = QListWidgetItem(name)
            item.setFlags(item.flags() | Qt.ItemFlag.ItemIsUserCheckable)
            item.setCheckState(Qt.CheckState.Unchecked)
            self.avatar_list.addItem(item)

    def set_all_selected(self, checked):
        state = (Qt.CheckState.Checked if checked
                 else Qt.CheckState.Unchecked)
        for index in range(self.avatar_list.count()):
            self.avatar_list.item(index).setCheckState(state)

    # ----------------------------------------------------------------- moving

    def build_assignments(self):
        chosen = []
        for index in range(self.avatar_list.count()):
            item = self.avatar_list.item(index)
            if item.checkState() != Qt.CheckState.Checked:
                continue
            avatar = self.avatars[index]
            groups = [box.text().split("(")[-1].rstrip(")")
                      for box in self.group_boxes if box.isChecked()]
            chosen.append((avatar["avatar_id"], item.text(), groups))
        return chosen

    def on_move(self):
        if self.worker is not None and self.worker.isRunning():
            return

        assignments = self.build_assignments()
        if not assignments:
            QMessageBox.information(
                self, "Nothing selected",
                "Tick at least one avatar to move.")
            return

        if not any(box.isChecked() for box in self.group_boxes):
            confirm = QMessageBox.question(
                self, "Unfavourite these?",
                "No groups are ticked, so these avatars will be removed from "
                "your VRChat favourites entirely.\n\n"
                f"Affects {len(assignments)} avatar(s). Continue?",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No)
            if confirm != QMessageBox.StandardButton.Yes:
                return

        self.assignments = assignments
        self.log.clear()
        self.log.append(f"Moving {len(assignments)} avatar(s)...")
        self.set_busy(True)
        self.progress.setMaximum(len(assignments))
        self.progress.setValue(0)

        self.worker = GroupMoveWorker(self.api, assignments)
        self.worker.progress.connect(self.on_progress)
        self.worker.finished_one.connect(self.on_one)
        self.worker.needs_two_factor.connect(self.on_two_factor)
        self.worker.completed.connect(self.on_completed)
        self.worker.start()

    def on_two_factor(self):
        if self.otp_shown:
            return
        self.otp_shown = True
        self.log.append("VRChat asked for a two-factor code...")
        if not prompt_for_code(self, self.api,
                               "Required to change your favourites."):
            if self.worker:
                self.worker.cancel()
        self.otp_shown = False

    def on_progress(self, index, total, name):
        self.progress.setValue(index)

    def on_one(self, name, ok, message):
        mark = "ok  " if ok else "FAIL"
        self.log.append(f"{mark} {name}: {message}")

    def on_completed(self, summary):
        self.set_busy(False)
        self.progress.setValue(self.progress.maximum())

        parts = [f"{summary['total']} avatar(s) processed",
                 f"{summary['moved']} moved"]
        if summary["unchanged"]:
            parts.append(f"{summary['unchanged']} already correct")
        if summary["failed"]:
            parts.append(f"{summary['failed']} failed")
        if summary["cancelled"]:
            parts.append("stopped early")
        self.log.append("")
        self.log.append(", ".join(parts) + ".")

        if summary["failed"]:
            self.log.append("Check your VRChat favourites: a failed move "
                            "removes the avatar before adding it back.")

    def set_busy(self, busy):
        for widget in (self.move_btn, self.select_all_btn,
                       self.select_none_btn):
            widget.setEnabled(not busy)
        self.progress.setVisible(busy)
        if busy:
            self.move_btn.setText("Stop")
        else:
            self.move_btn.setText("Move")
            self.move_btn.setEnabled(True)

    def on_close(self):
        if self.worker is not None and self.worker.isRunning():
            self.worker.cancel()
            self.worker.wait(3000)
        self.accept()

    def closeEvent(self, event):
        self.on_close()
        event.accept()