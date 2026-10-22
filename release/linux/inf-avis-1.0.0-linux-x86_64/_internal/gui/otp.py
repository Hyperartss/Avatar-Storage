"""One place to ask for a two-factor code, so every entry point behaves the
same way: login, the website importer, and favourites sync.

VRChat states which kind of code it wants in `requiresTwoFactorAuth`. Accounts
set up for email codes reject authenticator codes outright, which used to look
like "invalid code" no matter what was typed, so the prompt defaults to the
method VRChat asked for and lets the other one be picked deliberately.
"""

from PyQt6.QtWidgets import (
    QComboBox, QDialog, QDialogButtonBox, QFormLayout, QLabel, QLineEdit,
    QMessageBox, QVBoxLayout,
)

from api.vrchat_api import VRChatAPI, TWO_FACTOR_LABELS

METHOD_HELP = {
    "totp": "Open your authenticator app and enter the current 6-digit code "
            "for VRChat. It changes every 30 seconds.",
    "emailOtp": "VRChat emails this code to the address on your account. Use "
                "the most recent one — earlier emails are no longer valid.",
}


class TwoFactorDialog(QDialog):
    def __init__(self, parent, api: VRChatAPI, reason: str = ""):
        super().__init__(parent)
        self.api = api
        self.setWindowTitle("Two-Factor Required")
        self.setMinimumWidth(420)

        layout = QVBoxLayout(self)

        if reason:
            intro = QLabel(reason)
            intro.setWordWrap(True)
            layout.addWidget(intro)

        preferred = api.required_two_factor_method()

        form = QFormLayout()
        self.method_combo = QComboBox()
        # Offer both, but select the one VRChat asked for.
        for name in ("totp", "emailOtp"):
            self.method_combo.addItem(TWO_FACTOR_LABELS[name], name)
        index = self.method_combo.findData(preferred)
        if index >= 0:
            self.method_combo.setCurrentIndex(index)

        self.help_label = QLabel(METHOD_HELP[preferred])
        self.help_label.setWordWrap(True)

        self.code_input = QLineEdit()
        self.code_input.setPlaceholderText("000000")
        self.code_input.setMaxLength(12)

        form.addRow("Code from:", self.method_combo)
        form.addRow("Enter code:", self.code_input)
        layout.addLayout(form)
        layout.addWidget(self.help_label)

        self.method_combo.currentIndexChanged.connect(self.on_method_changed)
        self.code_input.returnPressed.connect(self.accept)

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def on_method_changed(self, index):
        self.help_label.setText(METHOD_HELP[self.method_combo.itemData(index)])

    @property
    def method(self):
        return self.method_combo.currentData()

    @property
    def code(self):
        return self.code_input.text().strip()


def prompt_for_code(parent, api: VRChatAPI, reason: str = "", attempts: int = 3):
    """Ask for a two-factor code and verify it.

    Returns True when the session is cleared for data calls. Lets the user retry
    a rejected code a couple of times, because a stale authenticator code is the
    single most common cause and retrying once fixes it.
    """
    if not api.authenticated:
        QMessageBox.warning(
            parent, "Not logged in",
            "Log in first, then enter your two-factor code.")
        return False

    for _ in range(max(1, attempts)):
        dialog = TwoFactorDialog(parent, api, reason)
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return False
        if not dialog.code:
            continue

        verified, message = api.verify_2fa(dialog.code, dialog.method)
        if verified:
            return True

        # Leave the flag set so background workers give up rather than retry.
        api.two_factor_required = True
        choice = QMessageBox.warning(
            parent, "Two-Factor Error", message,
            QMessageBox.StandardButton.Retry | QMessageBox.StandardButton.Cancel)
        if choice != QMessageBox.StandardButton.Retry:
            return False

    return False