"""Bulk import of avatars from vrchat.com.

Every VRChat endpoint needs an authenticated session, public avatars included,
so the dialog refuses to start without one instead of hanging on a request that
will never return.
"""

import time

from PyQt6.QtCore import pyqtSignal
from PyQt6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel, QPushButton, QTextEdit,
    QComboBox, QMessageBox, QInputDialog, QProgressBar, QGroupBox,
    QFormLayout,
)

import database as db
from api.vrchat_api import VRChatAPI, VRChatAPIError, parse_reference
from gui.worker_base import OtpAwareWorker
from gui.otp import prompt_for_code

# VRChat rate-limits aggressively; a pause between avatars keeps a large import
# from bouncing off the limit.
REQUEST_DELAY = 0.7

NO_CATEGORY = object()
NEW_CATEGORY = "__new__"


class ImportWorker(OtpAwareWorker):
    """Resolves pasted references and writes them to the library.

    Reads and writes only the database; the dialog is driven by the signals
    below. Named 'completed' rather than 'finished' so it does not shadow
    QThread's own finished() signal.
    """

    progress = pyqtSignal(int, int, str)
    completed = pyqtSignal(dict)

    def __init__(self, api, references, category_id=None, include_own=False):
        super().__init__(api)
        self.references = references
        self.category_id = category_id
        self.include_own = include_own

    def run(self):
        summary = {"added": 0, "updated": 0, "skipped": 0, "failed": 0,
                   "missing": [], "problems": [], "cancelled": False}

        try:
            payloads = list(self._collect(summary))
            if self.include_own and not self._cancel:
                payloads.extend(self._with_otp(self.api.get_my_avatars))
        except VRChatAPIError as error:
            summary["problems"].append(_describe(error))
            summary["cancelled"] = True
            self.completed.emit(summary)
            return
        except Exception as error:  # never let the thread die silently
            summary["problems"].append(f"Unexpected error: {error}")
            self.completed.emit(summary)
            return

        total = len(payloads)
        self.progress.emit(0, total, f"Resolved {total} avatar(s)")

        for index, data in enumerate(payloads):
            if self._cancel:
                break

            outcome = self._store(data, summary)
            summary[outcome] += 1
            self.progress.emit(index + 1, total, data.get("name") or data.get("id", ""))

            if index < total - 1 and not self._cancel:
                time.sleep(REQUEST_DELAY)

        # Covers cancelling at any point, including before anything resolved,
        # so the dialog never reports an interrupted run as a clean finish.
        if self._cancel:
            summary["cancelled"] = True

        self.completed.emit(summary)

    def _collect(self, summary):
        """Turn pasted references into normalised payloads.

        Every call goes through _with_otp, so a session that needs a two-factor
        code is prompted for and retried rather than failing the whole import.
        """
        for kind, reference in self.references:
            if self._cancel:
                return
            if kind == "avatar":
                found = self._with_otp(self.api.lookup_avatar, reference)
                if found is None:
                    summary["missing"].append(reference)
                else:
                    yield found
            else:
                for avatar in self._with_otp(self.api.get_user_avatars, reference):
                    if self._cancel:
                        return
                    yield avatar

    def _store(self, data, summary):
        try:
            _, created = db.upsert_avatar(data, category_id=self.category_id)
        except Exception as error:
            summary["problems"].append(f"{data.get('id', '?')}: {error}")
            return "failed"
        return "added" if created else "updated"


def _describe(error: VRChatAPIError) -> str:
    return error.message.strip('"') or "Request failed"


class ImportFromWebsiteDialog(QDialog):
    def __init__(self, vrchat_api: VRChatAPI, parent=None):
        super().__init__(parent)
        self.api = vrchat_api
        self.worker = None
        self.setWindowTitle("Import from VRChat")
        self.setMinimumSize(640, 540)
        self.setup_ui()

    def setup_ui(self):
        layout = QVBoxLayout(self)

        intro = QLabel(
            "Paste anything copied from vrchat.com — avatar links, user "
            "profile links, or bare avtr_/usr_ ids. One per line, or a whole "
            "selection at once.")
        intro.setWordWrap(True)
        layout.addWidget(intro)

        self.input_box = QTextEdit()
        self.input_box.setPlaceholderText(
            "https://vrchat.com/home/avatar/avtr_...\n"
            "https://vrchat.com/home/user/usr_...\n"
            "avtr_...\n"
            "usr_...")
        self.input_box.setMinimumHeight(160)
        layout.addWidget(self.input_box)

        options = QGroupBox("Options")
        form = QFormLayout(options)

        self.own_cb = QComboBox()
        self.own_cb.addItem("No", False)
        self.own_cb.addItem("Yes — also import my own avatars", True)
        form.addRow("Include my own avatars:", self.own_cb)

        self.category_combo = QComboBox()
        self.category_combo.addItem("No category", NO_CATEGORY)
        for cat in db.get_all_categories():
            self.category_combo.addItem(cat["name"], cat["id"])
        self.category_combo.addItem("+ New category...", NEW_CATEGORY)
        form.addRow("Put results in:", self.category_combo)

        layout.addWidget(options)

        self.count_label = QLabel("")
        self.count_label.setWordWrap(True)
        layout.addWidget(self.count_label)

        self.summary_label = QLabel("")
        self.summary_label.setWordWrap(True)
        self.summary_label.setTextInteractionFlags(
            self.summary_label.textInteractionFlags())
        layout.addWidget(self.summary_label)

        self.progress = QProgressBar()
        self.progress.setVisible(False)
        layout.addWidget(self.progress)

        btn_layout = QHBoxLayout()
        self.close_btn = QPushButton("Close")
        self.import_btn = QPushButton("Import")
        btn_layout.addStretch()
        btn_layout.addWidget(self.close_btn)
        btn_layout.addWidget(self.import_btn)
        layout.addLayout(btn_layout)

        self.import_btn.clicked.connect(self.start_import)
        self.close_btn.clicked.connect(self.on_close)
        self.input_box.textChanged.connect(self.update_count)

    # ------------------------------------------------------------------

    def collected_references(self):
        return parse_reference(self.input_box.toPlainText())

    def update_count(self):
        avatars = sum(1 for kind, _ in self.collected_references() if kind == "avatar")
        users = sum(1 for kind, _ in self.collected_references() if kind == "user")
        bits = []
        if avatars:
            bits.append(f"{avatars} avatar reference(s)")
        if users:
            bits.append(f"{users} user profile(s)")
        self.count_label.setText("Found: " + ", ".join(bits) if bits else "")

    def resolve_category(self):
        """Return a category id, creating one if the user asked for a new one."""
        data = self.category_combo.currentData()
        if data is NO_CATEGORY:
            return None
        if data is not NEW_CATEGORY:
            return data

        name, ok = QInputDialog.getText(self, "New Category", "Category name:")
        name = name.strip() if ok else ""
        if not name:
            return None
        existing = next((c["id"] for c in db.get_all_categories()
                         if c["name"].lower() == name.lower()), None)
        return existing if existing is not None else db.create_category(name)

    def start_import(self):
        references = self.collected_references()
        include_own = bool(self.own_cb.currentData())

        if not references and not include_own:
            QMessageBox.information(
                self, "Nothing to import",
                "No avatar or user references found.\n\n"
                "A reference is avtr_ or usr_ followed by a uuid. Paste the "
                "whole vrchat.com address if you are copying from a browser.")
            return

        if not self.api.authenticated:
            QMessageBox.warning(
                self, "Login required",
                "VRChat requires a logged-in session for these requests, "
                "including for public avatars.\n\n"
                "Use 'VRChat API -> Login...' first, then try again.")
            return

        category_id = self.resolve_category()

        self.set_busy(True)
        self.summary_label.setText("Resolving references...")

        self.worker = ImportWorker(self.api, references, category_id, include_own)
        self.worker.progress.connect(self.on_progress)
        self.worker.two_factor_required.connect(self.on_two_factor)
        self.worker.completed.connect(self.on_completed)
        self.worker.start()

    def set_busy(self, busy):
        for widget in (self.import_btn, self.input_box, self.own_cb,
                       self.category_combo):
            widget.setEnabled(not busy)
        self.progress.setVisible(busy)
        self.close_btn.setText("Stop" if busy else "Close")

    def on_progress(self, count, total, message):
        self.progress.setMaximum(max(total, 1))
        self.progress.setValue(count)
        self.summary_label.setText(f"{count}/{total}  {message}")

    def on_two_factor(self):
        """Runs on the GUI thread while the worker waits."""
        self.summary_label.setText("VRChat asked for a two-factor code...")
        if not prompt_for_code(self, self.api, "Required to read avatar details."):
            self.worker.cancel()
            return
        self.summary_label.setText("Verified, continuing...")
        self.worker.confirm_two_factor()

    def on_completed(self, summary):
        self.set_busy(False)
        self.progress.setValue(self.progress.maximum())

        parts = [f"{summary['added']} added",
                 f"{summary['updated']} refreshed",
                 f"{summary['skipped']} skipped"]
        if summary["failed"]:
            parts.append(f"{summary['failed']} failed")
        if summary["cancelled"]:
            parts.append("stopped early")

        lines = [", ".join(parts) + "."]

        if summary["missing"]:
            lines.append("")
            lines.append("Not found on VRChat (deleted or private):")
            lines += [f"  {ref}" for ref in summary["missing"][:10]]
            if len(summary["missing"]) > 10:
                lines.append(f"  ... and {len(summary['missing']) - 10} more")
        if summary["problems"]:
            lines.append("")
            lines += [f"  {problem}" for problem in summary["problems"][:8]]

        self.summary_label.setText("\n".join(lines))
        self.import_btn.setEnabled(True)

    def on_close(self):
        if self.worker is not None and self.worker.isRunning():
            self.worker.cancel()
            self.summary_label.setText("Stopping after the current avatar...")
            self.close_btn.setEnabled(False)
            return
        self.accept()

    def closeEvent(self, event):
        # Closing via the window button must not destroy a running thread.
        if self.worker is not None and self.worker.isRunning():
            self.worker.cancel()
            self.worker.wait(5000)
        super().closeEvent(event)