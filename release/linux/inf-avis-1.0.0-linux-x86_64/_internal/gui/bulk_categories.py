"""File several avatars into categories at once.

Reached from the grid's selection bar once more than one avatar is picked. The
per-avatar picker cannot express "put all of these in Cool", which is the whole
point of selecting several, so this applies one tick pattern to the lot.

Each checkbox starts out partially checked when only some of the selected
avatars are in that category. That is the difference between "transfer these"
and "overwrite these": a partial tick means the user has not decided about that
category yet, so pressing Save leaves those avatars alone instead of emptying
the category for them.

Everything here is local SQLite, so there is no worker and no progress bar.
"""

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import (
    QCheckBox, QDialog, QDialogButtonBox, QFrame, QHBoxLayout, QLabel,
    QLineEdit, QMessageBox, QPushButton, QScrollArea, QVBoxLayout, QWidget,
)

import database as db

# States a box can be in on open. Anything the user has not touched is UNSET
# and is passed through untouched on save.
UNSET = "unset"
PARTIAL = "partial"
ON = "on"
OFF = "off"


class BulkCategoryDialog(QDialog):
    def __init__(self, parent, avatars):
        super().__init__(parent)
        # Rows out of the database are sqlite3.Row and have no .get().
        self.avatars = [dict(a) if not isinstance(a, dict) else a
                        for a in avatars]
        self.boxes = []

        count = len(self.avatars)
        self.setWindowTitle("Move to Categories")
        self.setMinimumSize(420, 480)

        layout = QVBoxLayout(self)

        heading = QLabel(f"{count} avatar(s) selected")
        heading.setStyleSheet("font-weight: bold;")
        layout.addWidget(heading)

        intro = QLabel(
            "Tick a category to put every selected avatar in it. Unticking "
            "takes them all out. A dashed box means only some of them are in "
            "there — clicking it decides, and leaving it alone changes "
            "nothing.")
        intro.setWordWrap(True)
        layout.addWidget(intro)

        layout.addWidget(QLabel("Categories"))

        holder = QWidget()
        self.boxes_layout = QVBoxLayout(holder)
        self.boxes_layout.setContentsMargins(0, 0, 0, 0)
        self._build_boxes()

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        scroll.setWidget(holder)
        layout.addWidget(scroll, 1)

        new_row = QHBoxLayout()
        self.new_name = QLineEdit()
        self.new_name.setPlaceholderText("New category name...")
        self.new_name.returnPressed.connect(self.add_category)
        new_btn = QPushButton("Add")
        new_btn.clicked.connect(self.add_category)
        new_row.addWidget(self.new_name, 1)
        new_row.addWidget(new_btn)
        layout.addLayout(new_row)

        self.notice = QLabel("")
        self.notice.setWordWrap(True)
        layout.addWidget(self.notice)

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Save
            | QDialogButtonBox.StandardButton.Cancel)
        buttons.accepted.connect(self.on_save)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    # ------------------------------------------------------------------ setup

    def _build_boxes(self):
        """One box per category, showing how many of the selection is in it."""
        self.membership = {}
        for avatar in self.avatars:
            self.membership[avatar["avatar_id"]] = {
                row["id"] for row in
                db.get_avatar_categories(avatar["avatar_id"])}

        for category in db.get_all_categories():
            inside = sum(1 for avatar in self.avatars
                         if category["id"] in
                         self.membership.get(avatar["avatar_id"], set()))
            total = db.get_category_avatar_count(category["id"])

            box = QCheckBox(f"{category['name']}  ({inside}/{len(self.avatars)}"
                            f" selected, {total} total)")
            box.category_id = category["id"]
            box.state = (ON if inside == len(self.avatars)
                         else OFF if inside == 0
                         else PARTIAL)
            self._apply_state(box, box.state)
            # Reading the tick back must not mark the box as decided.
            box.stateChanged.connect(
                lambda _s, b=box: setattr(b, "state", self._new_state(b)))
            self.boxes.append(box)
            self.boxes_layout.addWidget(box)

        if not self.boxes:
            self.notice.setText("You have no categories yet. Add one below.")

        self.boxes_layout.addStretch()

    @staticmethod
    def _new_state(box):
        state = box.checkState()
        if state == Qt.CheckState.Checked:
            return ON
        if state == Qt.CheckState.Unchecked:
            return OFF
        return PARTIAL

    def _apply_state(self, box, state):
        box.blockSignals(True)
        if state == PARTIAL:
            box.setTristate(True)
            box.setCheckState(Qt.CheckState.PartiallyChecked)
        else:
            box.setTristate(False)
            box.setCheckState(Qt.CheckState.Checked
                              if state == ON else Qt.CheckState.Unchecked)
        box.blockSignals(False)

    def add_category(self):
        name = self.new_name.text().strip()
        if not name:
            return

        for box in self.boxes:
            if box.text().split("  (")[0].strip().lower() == name.lower():
                self.notice.setText(f'"{name}" already exists.')
                self._apply_state(box, ON)
                box.state = ON
                return

        category_id = db.create_category(name)
        if not category_id:
            self.notice.setText(f'Could not create "{name}".')
            return

        box = QCheckBox(f"{name}  (0/{len(self.avatars)} selected, 0 total)")
        box.category_id = category_id
        box.state = OFF
        self._apply_state(box, OFF)
        box.stateChanged.connect(
            lambda _s, b=box: setattr(b, "state", self._new_state(b)))
        self.boxes.append(box)
        self.boxes_layout.insertWidget(self.boxes_layout.count() - 1, box)
        self.new_name.clear()
        self.notice.setText(f'Added "{name}". Tick it, then press Save.')

    # ----------------------------------------------------------------- saving

    def plan(self):
        """[(avatar_id, category_ids), ...] -- one entry per selected avatar.

        A category whose box the user never touched is absent from that
        avatar's list, and set_avatar_categories leaves it alone.
        """
        for avatar in self.avatars:
            avatar_id = avatar["avatar_id"]
            current = self.membership.get(avatar_id, set())

            # ON means "in", OFF means "out", PARTIAL means "leave it alone".
            keep = {box.category_id for box in self.boxes
                    if box.state == PARTIAL}
            wanted = {box.category_id for box in self.boxes
                      if box.state == ON}
            final = (current & keep) | wanted

            if final == current:
                continue
            yield avatar_id, sorted(final)

    def on_save(self):
        changes = list(self.plan())
        if not changes:
            self.accept()
            return

        failed = []
        for avatar_id, category_ids in changes:
            if not db.set_avatar_categories(avatar_id, category_ids):
                failed.append(avatar_id)

        if failed:
            QMessageBox.warning(
                self, "Partly saved",
                f"Moved {len(changes) - len(failed)} of {len(changes)}. "
                f"These could not be saved:\n\n"
                + "\n".join(failed[:10])
                + ("\n..." if len(failed) > 10 else ""))
        self.accept()
