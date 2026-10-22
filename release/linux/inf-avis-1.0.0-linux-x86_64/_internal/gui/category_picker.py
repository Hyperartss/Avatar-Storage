"""File an avatar into categories.

Reached from the folder icon on an avatar card. The star beside it does
something else entirely: it changes your favourites on vrchat.com.

Unlike the VRChat group dialog next door, everything here is local SQLite and
happens instantly, so there is no worker thread and no progress reporting.
"""

from PyQt6.QtWidgets import (
    QCheckBox, QDialog, QDialogButtonBox, QFrame, QHBoxLayout, QLabel,
    QLineEdit, QMessageBox, QPushButton, QScrollArea, QVBoxLayout, QWidget,
)

import database as db


class CategoryPickerDialog(QDialog):
    """Choose which categories an avatar belongs to, and optionally rename
    the set by creating one on the spot.
    """

    def __init__(self, parent, avatar_id: str, avatar_name: str = ""):
        super().__init__(parent)
        self.avatar_id = avatar_id
        # Rows from the database are sqlite3.Row and have no .get(); normalise
        # at the boundary rather than making every consumer cope with both.
        avatar = db.get_avatar(avatar_id)
        self.avatar_id = avatar_id
        self.avatar_name = avatar_name or (avatar["name"] if avatar else "") \
            or avatar_id

        self.setWindowTitle("Categories")
        self.setMinimumSize(380, 440)

        layout = QVBoxLayout(self)

        heading = QLabel(self.avatar_name)
        heading.setWordWrap(True)
        heading.setStyleSheet("font-weight: bold;")
        layout.addWidget(heading)

        intro = QLabel("Tick every category this avatar should be in. "
                       "Unticking all of them just leaves it uncategorised.")
        intro.setWordWrap(True)
        layout.addWidget(intro)

        # Favouriting on VRChat is the star's job, not this dialog's. See
        # gui/favorite_toggle.py. This checkbox only flips the local favourite
        # flag so the avatar shows up under the Favourites filter.

        avatar = db.get_avatar(self.avatar_id)
        is_favorite = bool(avatar["favorite"]) if avatar else False
        self.fav_box = QCheckBox("Mark as favourite")
        self.fav_box.setChecked(is_favorite)
        self.fav_box.setToolTip(
            "Sets the local favourite flag. The star on the card writes to "
            "vrchat.com.")
        layout.addWidget(self.fav_box)

        layout.addWidget(QLabel("Categories"))

        # Categories scroll rather than push the buttons off screen, because a
        # library can easily have more than a dozen.
        self.boxes = []
        self._build_boxes()

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        holder = QWidget()
        self.boxes_layout = QVBoxLayout(holder)
        self.boxes_layout.setContentsMargins(0, 0, 0, 0)
        for box in self.boxes:
            self.boxes_layout.addWidget(box)
        self.boxes_layout.addStretch()
        scroll.setWidget(holder)
        layout.addWidget(scroll, 1)

        # Creating a category here saves a trip through Manage Categories,
        # which is otherwise the only way to get a new one.
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

    @staticmethod
    def _rule():
        line = QFrame()
        line.setFrameShape(QFrame.Shape.HLine)
        line.setStyleSheet("color: #ddd;")
        return line

    def _build_boxes(self):
        """Create one checkbox per category, pre-ticked if already filed."""
        current = {row["id"] for row in db.get_avatar_categories(self.avatar_id)}

        for category in db.get_all_categories():
            count = db.get_category_avatar_count(category["id"])
            box = QCheckBox(f"{category['name']}  ({count})")
            box.setChecked(category["id"] in current)
            box.category_id = category["id"]
            self.boxes.append(box)

        if not self.boxes:
            self.notice.setText("You have no categories yet. "
                                "Add one below.")

    def add_category(self):
        """Create a category and tick it, without saving the dialog yet."""
        name = self.new_name.text().strip()
        if not name:
            return

        for box in self.boxes:
            if box.text().split("  (")[0].strip().lower() == name.lower():
                self.notice.setText(f'"{name}" already exists.')
                box.setChecked(True)
                return

        category_id = db.create_category(name)
        if not category_id:
            self.notice.setText(f'Could not create "{name}".')
            return

        count = db.get_category_avatar_count(category_id)
        box = QCheckBox(f"{name}  ({count})")
        box.setChecked(True)
        box.category_id = category_id
        self.boxes.append(box)
        self.boxes_layout.insertWidget(self.boxes_layout.count() - 1, box)
        self.new_name.clear()
        self.notice.setText(f'Added "{name}". Remember to press Save.')

    # ------------------------------------------------------------------ saving

    def selected_category_ids(self):
        return [box.category_id for box in self.boxes if box.isChecked()]

    def on_save(self):
        if not db.set_avatar_categories(self.avatar_id,
                                        self.selected_category_ids()):
            QMessageBox.warning(self, "Not saved",
                                "Could not update the categories. "
                                "Nothing was changed.")
            return
        # Keep the local favourite flag in step with the checkbox.
        db.set_favorite_flag(self.avatar_id, self.fav_box.isChecked())
        self.accept()
