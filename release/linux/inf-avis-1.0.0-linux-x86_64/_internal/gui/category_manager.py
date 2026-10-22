from PyQt6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QPushButton, QListWidget,
    QListWidgetItem, QInputDialog, QMessageBox, QLabel
)
from PyQt6.QtCore import Qt
import database as db

class CategoryManager(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Manage Categories")
        self.setMinimumSize(350, 400)
        self.setup_ui()
        self.load_categories()

    def setup_ui(self):
        layout = QVBoxLayout(self)
        layout.addWidget(QLabel("Categories:"))

        self.list_widget = QListWidget()
        layout.addWidget(self.list_widget)

        btn_layout = QHBoxLayout()
        self.add_btn = QPushButton("Add")
        self.rename_btn = QPushButton("Rename")
        self.delete_btn = QPushButton("Delete")
        self.close_btn = QPushButton("Close")

        btn_layout.addWidget(self.add_btn)
        btn_layout.addWidget(self.rename_btn)
        btn_layout.addWidget(self.delete_btn)
        btn_layout.addStretch()
        btn_layout.addWidget(self.close_btn)
        layout.addLayout(btn_layout)

        self.add_btn.clicked.connect(self.add_category)
        self.rename_btn.clicked.connect(self.rename_category)
        self.delete_btn.clicked.connect(self.delete_category)
        self.close_btn.clicked.connect(self.accept)

    def load_categories(self):
        self.list_widget.clear()
        for cat in db.get_all_categories():
            count = db.get_category_avatar_count(cat["id"])
            item = QListWidgetItem(f"{cat['name']} ({count})")
            item.setData(Qt.ItemDataRole.UserRole, cat["id"])
            self.list_widget.addItem(item)

    def add_category(self):
        name, ok = QInputDialog.getText(self, "Add Category", "Category name:")
        if ok and name.strip():
            cat_id = db.create_category(name.strip())
            if cat_id is None:
                QMessageBox.warning(self, "Error", f"Category '{name}' already exists.")
            self.load_categories()

    def rename_category(self):
        item = self.list_widget.currentItem()
        if not item:
            return
        cat_id = item.data(Qt.ItemDataRole.UserRole)
        old_name = item.text().split(" (")[0]
        name, ok = QInputDialog.getText(self, "Rename Category", "New name:", text=old_name)
        if ok and name.strip() and name.strip() != old_name:
            if db.rename_category(cat_id, name.strip()):
                self.load_categories()
            else:
                QMessageBox.warning(self, "Error", f"Category '{name}' already exists.")

    def delete_category(self):
        item = self.list_widget.currentItem()
        if not item:
            return
        cat_id = item.data(Qt.ItemDataRole.UserRole)
        name = item.text().split(" (")[0]
        confirm = QMessageBox.question(self, "Delete Category",
                                       f"Delete '{name}'? Avatars in this category will not be deleted.",
                                       QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No)
        if confirm == QMessageBox.StandardButton.Yes:
            db.delete_category(cat_id)
            self.load_categories()
