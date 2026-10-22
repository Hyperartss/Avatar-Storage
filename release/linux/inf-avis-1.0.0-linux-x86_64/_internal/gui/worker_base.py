"""Shared two-factor handling for the background workers.

VRChat can accept a saved session for identification while still refusing data
calls until a fresh TOTP is submitted. Every worker that talks to those
endpoints needs the same handshake, and it has to be a handshake rather than a
prompt because the prompt belongs on the GUI thread.
"""

import threading

from PyQt6.QtCore import QThread, pyqtSignal

from api.vrchat_api import VRChatAPIError

# How long a worker waits for the GUI to come back with a verified code.
OTP_TIMEOUT = 180


class OtpAwareWorker(QThread):
    """A worker that can ask the GUI to collect a two-factor code.

    Subclasses emit `two_factor_required` through _with_otp, which then blocks
    until the GUI calls confirm_two_factor().
    """

    two_factor_required = pyqtSignal()

    def __init__(self, api):
        super().__init__()
        self.api = api
        self._cancel = False
        self._otp_event = threading.Event()

    def cancel(self):
        self._cancel = True
        # Release anything waiting on a prompt that will never be answered.
        self._otp_event.set()

    def confirm_two_factor(self):
        self._otp_event.set()

    def _with_otp(self, call, *args, attempts: int = 2):
        """Run an API call, asking for a two-factor code if VRChat demands one.

        Retries at most once. If the GUI could not verify the code it leaves
        `two_factor_required` set, and we give up immediately rather than
        blocking on an event nobody is going to set.
        """
        last = VRChatAPIError("Request failed")

        for attempt in range(attempts):
            try:
                return call(*args)
            except VRChatAPIError as error:
                last = error
                if not error.needs_2fa or attempt == attempts - 1:
                    raise

                # Clear first: the GUI answers the signal, and a stale set
                # would make the wait below return before the prompt is shown.
                self._otp_event.clear()
                self.two_factor_required.emit()

                if not self._otp_event.wait(OTP_TIMEOUT):
                    raise VRChatAPIError(
                        "Timed out waiting for a two-factor code", status_code=403)
                if self.api.two_factor_required:
                    raise VRChatAPIError(
                        "Two-factor verification did not complete", status_code=403)

        raise last