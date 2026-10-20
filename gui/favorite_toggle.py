"""Add or remove VRChat favourites from the star on an avatar card.

The star writes to vrchat.com, so unlike local filing it is a network call that
can be slow, can be rate-limited, and can be interrupted by a two-factor prompt
in the middle of a batch. Hence a worker, and per-avatar results.

VRChat refuses to favourite the same avatar twice, and removing needs the
favourite's own id rather than the avatar id, so the local vrchat_favorites
table is what makes the toggle possible at all. If that table has drifted from
the server, adding comes back as "already favorited"; that is treated as
success and repaired, because reporting a failure the user cannot act on would
be worse than quietly fixing it.
"""

import time

from PyQt6.QtCore import pyqtSignal

from api.vrchat_api import VRChatAPIError
from gui.worker_base import OtpAwareWorker
import database as db

# VRChat rate-limits hard; a gap between a burst of stars keeps it survivable.
REQUEST_DELAY = 0.7


def _describe(error) -> str:
    return (getattr(error, "message", "") or "").strip('"') or "Request failed"


def _already_favorited(message: str) -> bool:
    lowered = (message or "").lower()
    return "already" in lowered and "favorit" in lowered


class FavoriteToggleWorker(OtpAwareWorker):
    """Runs a list of (avatar_id, name, make_favorite) toggles in the
    background, reporting each outcome."""

    progress = pyqtSignal(int, int, str)
    completed = pyqtSignal(dict)

    def __init__(self, api, toggles):
        super().__init__(api)
        self.toggles = list(toggles)
        self.done_ids = []      # ids confirmed server-side, for the UI refresh

    def run(self):
        summary = {"added": 0, "removed": 0, "failed": 0, "cancelled": False,
                   "problems": [], "total": len(self.toggles)}

        for index, (avatar_id, name, make_favorite) in enumerate(self.toggles):
            if self._cancel:
                summary["cancelled"] = True
                break

            self.progress.emit(index, summary["total"], name)
            ok, message = self._toggle(avatar_id, make_favorite)

            if ok:
                summary["added" if make_favorite else "removed"] += 1
                self.done_ids.append(avatar_id)
            else:
                summary["failed"] += 1
                summary["problems"].append(f"{name}: {message}")

            if index < summary["total"] - 1 and not self._cancel:
                time.sleep(REQUEST_DELAY)

        if self._cancel:
            summary["cancelled"] = True
        self.completed.emit(summary)

    # ------------------------------------------------------------------ one

    def _toggle(self, avatar_id, make_favorite):
        """Returns (ok, message). Never raises."""
        if not self.api.authenticated:
            return False, "Not logged in"

        try:
            if make_favorite:
                return self._add(avatar_id)
            return self._remove(avatar_id)
        except VRChatAPIError as error:
            # _with_otp has already prompted and retried by this point, so a
            # 401 landing here means the session is genuinely unusable.
            return False, _describe(error)
        except Exception as error:
            return False, str(error)

    def _add(self, avatar_id):
        ok, message = self._with_otp(self.api.add_favorite, avatar_id)
        if ok:
            self._store(avatar_id, message)
            return True, message

        if _already_favorited(message):
            # The local table was behind. Re-read the id and carry on rather
            # than reporting a failure the user cannot do anything about.
            favorite_id, _ = self._with_otp(self.api.get_favorite_tags,
                                            avatar_id)
            if favorite_id:
                self._store(avatar_id, favorite_id)
                return True, "Already a favourite on VRChat"
        if "tags is required" in message.lower():
            # Some VRChat endpoints refuse to favourite an avatar unless a group
            # is specified. Try again with the default 'avatars1' group slug if
            # one exists on this account, otherwise let the error surface.
            slugs = []
            try:
                groups = self._with_otp(self.api.get_favorite_groups, "avatar")
                slugs = [g.get("slug") for g in groups if g.get("slug")]
            except Exception:
                slugs = []
            if slugs:
                ok, message = self._with_otp(self.api.add_favorite,
                                             avatar_id, slugs[0])
                if ok:
                    self._store(avatar_id, message)
                    return True, message
                if _already_favorited(message):
                    favorite_id, _ = self._with_otp(self.api.get_favorite_tags,
                                                    avatar_id)
                    if favorite_id:
                        self._store(avatar_id, favorite_id)
                        return True, "Already a favourite on VRChat"
        return False, message

    def _remove(self, avatar_id):
        record = db.get_favorite_record(avatar_id)
        favorite_id = record["favorite_id"] if record else None

        if not favorite_id:
            # No local record, so look it up rather than failing on an id the
            # user never sees.
            favorite_id, _ = self._with_otp(self.api.get_favorite_tags,
                                            avatar_id)
            if not favorite_id:
                # Already not a favourite: the goal is met.
                self._clear(avatar_id)
                return True, "Was not a favourite"

        ok, message = self._with_otp(self.api.remove_favorite, favorite_id)
        if ok:
            self._clear(avatar_id)
            return True, message
        return False, message

    # ------------------------------------------------------------------ store

    @staticmethod
    def _store(avatar_id, favorite_id):
        # group_id "" keeps any category link the record already had.
        db.record_favorites([{"avatar_id": avatar_id,
                              "favorite_id": favorite_id,
                              "group_id": ""}])
        db.set_favorite_flag(avatar_id, True)

    @staticmethod
    def _clear(avatar_id):
        db.delete_favorite_record(avatar_id)
        db.set_favorite_flag(avatar_id, False)
