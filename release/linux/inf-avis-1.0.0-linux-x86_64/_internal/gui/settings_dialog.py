"""Settings dialog: theme, density, and other quality-of-life options.

Changes take effect immediately, and everything is persisted to
``settings.json`` in the config directory.
"""

from PyQt6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel, QComboBox,
    QCheckBox, QDialogButtonBox, QGroupBox, QFormLayout,
    QMessageBox
)

from gui.settings import DEFAULTS, load, save, set_
from gui.theme import apply_theme, THEMES


class SettingsDialog(QDialog):
    def __init__(self, app, settings, parent=None):
        super().__init__(parent)
        self.app = app
        self.settings = settings
        self.setWindowTitle("Settings")
        self.setMinimumWidth(420)
        self._build_ui()
        self._load_into_ui()

    # ------------------------------------------------------------------ build

    def _build_ui(self):
        layout = QVBoxLayout(self)

        # ---- Appearance ----------------------------------------------
        appearance = QGroupBox("Appearance")
        appearance_layout = QFormLayout(appearance)

        self.theme_combo = QComboBox()
        for mode in THEMES:
            self.theme_combo.addItem(mode.title(), mode)
        self.theme_combo.currentIndexChanged.connect(self._on_theme_changed)
        appearance_layout.addRow("Theme:", self.theme_combo)

        self.density_combo = QComboBox()
        self.density_combo.addItem("Comfortable", "comfortable")
        self.density_combo.addItem("Compact", "compact")
        self.density_combo.currentIndexChanged.connect(self._on_density_changed)
        appearance_layout.addRow("Card density:", self.density_combo)

        layout.addWidget(appearance)

        # ---- Behaviour -----------------------------------------------
        behaviour = QGroupBox("Behaviour")
        behaviour_layout = QVBoxLayout(behaviour)

        self.confirm_delete_cb = QCheckBox("Confirm before deleting an avatar")
        self.confirm_delete_cb.setToolTip(
            "When off, Delete removes an avatar straight from the context menu.")
        behaviour_layout.addWidget(self.confirm_delete_cb)

        self.show_sidebar_cb = QCheckBox("Show category sidebar")
        self.show_sidebar_cb.setToolTip(
            "When off, the sidebar is hidden and you filter categories from "
            "the toolbar instead.")
        behaviour_layout.addWidget(self.show_sidebar_cb)

        self.show_ids_cb = QCheckBox("Show avatar IDs on cards")
        self.show_ids_cb.setToolTip(
            "When off, cards hide the truncated avatar id to save space.")
        behaviour_layout.addWidget(self.show_ids_cb)

        layout.addWidget(behaviour)

        layout.addStretch()

        # ---- buttons -------------------------------------------------
        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok
            | QDialogButtonBox.StandardButton.Cancel)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    # ------------------------------------------------------------------ load

    def _load_into_ui(self):
        mode = self.settings.get("theme", DEFAULTS["theme"])
        index = self.theme_combo.findData(mode)
        if index >= 0:
            self.theme_combo.setCurrentIndex(index)

        density = self.settings.get("density", DEFAULTS["density"])
        index = self.density_combo.findData(density)
        if index >= 0:
            self.density_combo.setCurrentIndex(index)

        self.confirm_delete_cb.setChecked(
            self.settings.get("confirm_delete", DEFAULTS["confirm_delete"]))
        self.show_sidebar_cb.setChecked(
            self.settings.get("show_sidebar", DEFAULTS["show_sidebar"]))
        self.show_ids_cb.setChecked(
            self.settings.get("show_avatar_ids", DEFAULTS["show_avatar_ids"]))

    # ------------------------------------------------------------------ apply

    def _on_theme_changed(self, index):
        mode = self.theme_combo.itemData(index)
        apply_theme(self.app, mode)
        set_(self.settings, "theme", mode)
        save(self.settings)

    def _on_density_changed(self, index):
        density = self.density_combo.itemData(index)
        set_(self.settings, "density", density)
        save(self.settings)
        # Density needs the cards rebuilt; the window handles that.
        if self.parent() is not None and hasattr(self.parent(), "apply_density"):
            self.parent().apply_density(density)

    def accept(self):
        set_(self.settings, "confirm_delete", self.confirm_delete_cb.isChecked())
        set_(self.settings, "show_sidebar", self.show_sidebar_cb.isChecked())
        set_(self.settings, "show_avatar_ids", self.show_ids_cb.isChecked())
        set_(self.settings, "density", self.density_combo.currentData())
        save(self.settings)
        super().accept()
