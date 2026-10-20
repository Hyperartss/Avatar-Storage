import requests
import re
import json
import os
import base64
import sys
import time
from datetime import datetime, timezone
from urllib.parse import quote
from typing import Optional, Tuple, Union

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import paths

BASE_URL = "https://api.vrchat.cloud/api/1"
SESSION_FILE = str(paths.session_path())

AVATAR_URL = "https://vrchat.com/home/avatar/{id}"
USER_URL = "https://vrchat.com/home/user/{id}"

# avtr_/usr_ ids are a fixed-width uuid after the prefix.
AVATAR_ID_RE = re.compile(r"avtr_[0-9a-fA-F-]{36}")
USER_ID_RE = re.compile(r"usr_[0-9a-fA-F-]{36}")

# Guards against a runaway paginated crawl.
MAX_PAGES = 50
MAX_RESULTS = 2000

# /favorites ignores `limit` and always answers with this many rows per page,
# paging forward by `offset`. Confirmed against the live API: limit=10, 100,
# 200 and 500 each return exactly 10, while offset=20 returns the final 6.
OFFSET_PAGE_SIZE = 10

# VRChat has no rate-limit headers: it returns plain 404s. Real pages come back
# fast, so a gap this large means we were throttled rather than served an empty
# page, and the correct move is to back off and ask again.
PAGE_GAP_SECONDS = 2.0


# The only two verification endpoints the API actually exposes. There is no
# endpoint to *send* an email code: VRChat emails it as part of the challenge,
# so the client only ever verifies it.
TWO_FACTOR_ENDPOINTS = {
    "totp": "/auth/twofactorauth/totp/verify",
    "emailOtp": "/auth/twofactorauth/emailotp/verify",
}

TWO_FACTOR_LABELS = {
    "totp": "Authenticator app",
    "emailOtp": "Email code",
}


class VRChatAPIError(Exception):
    """Raised for anything the caller is expected to report to the user."""

    def __init__(self, message: str, status_code: Optional[int] = None):
        super().__init__(message)
        self.message = message
        self.status_code = status_code

    @property
    def needs_login(self) -> bool:
        return self.status_code in (401, 403)

    @property
    def needs_2fa(self) -> bool:
        """True when VRChat accepted the session but wants a fresh OTP.

        A saved cookie keeps identifying the account after login, so /auth/user
        still succeeds, but calls that touch data come back 403 asking for
        two-factor. Prompting for the code is the fix.
        """
        return self.status_code == 403 and "two-factor" in self.message.lower()


def _safe_json(resp):
    try:
        return resp.json()
    except (json.JSONDecodeError, ValueError, TypeError):
        return {}

def _basic_auth(username: str, password: str) -> str:
    token = base64.b64encode(
        f"{quote(username)}:{quote(password)}".encode("utf-8")
    ).decode("ascii")
    return f"Basic {token}"

def _error_message(data, fallback: str) -> str:
    if isinstance(data, dict):
        error = data.get("error")
        if isinstance(error, dict):
            return error.get("message", "") or fallback
        if isinstance(error, str):
            return error or fallback
    return fallback

def _retry_after(resp) -> Optional[float]:
    """Seconds to wait, from the Retry-After header if VRChat sent one."""
    raw = resp.headers.get("Retry-After")
    if not raw:
        return None
    try:
        return max(0.0, float(raw))
    except (TypeError, ValueError):
        return None

def _iso_to_epoch(value) -> int:
    """VRChat sends ISO-8601 with a trailing Z; store epoch seconds."""
    if not value or not isinstance(value, str):
        return 0
    text = value.replace("Z", "+00:00")
    try:
        return int(datetime.fromisoformat(text).timestamp())
    except ValueError:
        return 0

def normalize_avatar(data: dict) -> dict:
    """Map a raw VRChat avatar payload onto the library's column names."""
    avatar_id = data.get("id", "")
    if not avatar_id:
        return {}

    statistics = data.get("statistics") or {}
    tags = data.get("tags")
    if not isinstance(tags, list):
        tags = []

    return {
        "id": avatar_id,
        "name": data.get("name") or "Unknown",
        "author": data.get("authorName") or "",
        "author_id": data.get("authorId") or "",
        "thumbnail_url": data.get("thumbnailImageUrl") or data.get("imageUrl") or "",
        "description": data.get("description") or "",
        "tags": tags,
        "release_status": data.get("releaseStatus") or "",
        "version": str(data.get("version") or ""),
        "unity_version": data.get("unityVersion") or "",
        "date_published": _iso_to_epoch(data.get("created_at")),
        "date_updated": _iso_to_epoch(data.get("updated_at")),
        "downloads": int(statistics.get("downloadCount") or 0),
        "favorites_count": int(data.get("favoritesCount") or 0),
        "rating": float(data.get("rating") or 0),
        "is_public": bool(data.get("public", True)),
        "url": AVATAR_URL.format(id=avatar_id),
    }

def normalize_favorite_group(data: dict) -> dict:
    """A favourite group, e.g. fvgrp_abc123.

    Two different names matter and they are not interchangeable:
      - `name`        the internal slug ("avatars1"). This is the value the
                      API expects in a favourite's `tags` array, so it is
                      what has to be sent when moving something into a group.
      - `display_name` the label the user sees on the website ("Mains"), used
                      for local category names and shown in dialogs.

    `slug` is kept as an alias of `name` so callers cannot mix them up by
    accident. This listing also omits order/capacity/favoritesCount entirely,
    which is why those come back as 0 rather than being absent.
    """
    slug = data.get("name") or ""
    return {
        "id": data.get("id", ""),
        "name": data.get("displayName") or slug,
        "slug": slug,
        "display_name": data.get("displayName") or slug,
        "type": data.get("type", "avatar"),
        "order": int(data.get("order") or 0),
        "capacity": int(data.get("capacity") or 0),
        "favorites_count": int(data.get("favoritesCount") or 0),
    }

def normalize_favorite(data: dict) -> dict:
        """One entry from a favourites listing.

        The API serves this shape two ways: `/favorites` yields favourite
        records (a `fav_` id, `favoriteId` holding the avatar, and `tags`
        naming the groups), while `/avatars/favorited` yields bare avatar
        objects. Both are accepted so callers do not have to care which came
        back.

        `favorite_id` is what unfavouriting needs and is NOT the avatar id, so
        it is only set when the entry really is a favourite record.
        """
        if not isinstance(data, dict):
            return {}

        tags = data.get("tags")
        tags = [t for t in tags if isinstance(t, str)] if isinstance(tags, list) else []

        entry_id = data.get("id") or ""
        avatar_id = data.get("favoriteId") or ""
        favorite_id = ""

        if avatar_id.startswith("avtr_"):
            # /favorites form: `id` is the fav_ id.
            favorite_id = entry_id
        elif entry_id.startswith("avtr_"):
            # /avatars/favorited form: the entry is the avatar itself.
            avatar_id = entry_id

        if not avatar_id:
            return {}

        return {
            "favorite_id": favorite_id,
            "avatar_id": avatar_id,
            "group_ids": tags,
            "tags": tags,
            "is_record": bool(favorite_id),
        }

def _wrong_code_hint(method: str, detail: str = "") -> str:
    """A rejection that says what to actually try next."""
    detail = detail.strip('"')
    if method == "emailOtp":
        hint = ("VRChat rejected that code. It wants the code emailed to your "
                "account, not an authenticator app code — check your inbox and "
                "spam folder for the most recent one.")
    else:
        hint = ("VRChat rejected that code. Codes change every 30 seconds, so "
                "use the current one from your authenticator app, and make sure "
                "it has not already been used.")
    return f"{detail}. {hint}" if detail else hint

def parse_reference(text: str) -> list:
    """Pull avatar and user references out of arbitrary pasted text.

    Accepts bare ids, vrchat.com URLs, or a mixture of both in one blob, which
    is what you get when copying straight out of a browser.

    Returns a list of (kind, id) with kind either 'avatar' or 'user', in the
    order they appear and without duplicates.
    """
    found = []
    seen = set()

    for match in AVATAR_ID_RE.finditer(text or ""):
        ref = ("avatar", match.group(0).lower())
        if ref not in seen:
            seen.add(ref)
            found.append(ref)

    for match in USER_ID_RE.finditer(text or ""):
        ref = ("user", match.group(0).lower())
        if ref not in seen:
            seen.add(ref)
            found.append(ref)

    return found

class VRChatAPI:
    def __init__(self):
        self.session = requests.Session()
        self.session.headers.update({
            "User-Agent": "INF-Avis/1.0 (https://github.com/INF-Avis)",
            "Content-Type": "application/json",
        })
        self.authenticated = False
        self.current_user = None
        # Set when VRChat asks for a fresh OTP on a data call.
        self.two_factor_required = False
        # What VRChat says it wants, e.g. ["totp"] or ["emailOtp"]. An
        # authenticator code is rejected outright when the account uses email.
        self.two_factor_methods = []
        self._load_session()

    def _save_session(self):
        data = {
            "cookies": self.session.cookies.get_dict(),
            "current_user": self.current_user,
        }
        try:
            paths.ensure_dirs()
            with open(SESSION_FILE, "w") as f:
                json.dump(data, f)
            paths.protect_session_file()
        except OSError:
            pass

    def _load_session(self):
        try:
            paths.protect_session_file()
            with open(SESSION_FILE) as f:
                data = json.load(f)
            if data.get("cookies"):
                self.session.cookies.update(data["cookies"])
                self.current_user = data.get("current_user")
                r = self.session.get(f"{BASE_URL}/auth/user", timeout=15)
                if r.status_code == 200:
                    user_data = _safe_json(r)
                    self.authenticated = True
                    self.current_user = user_data.get("displayName") or user_data.get("username") or self.current_user
                    # /auth/user answers 200 even while two-factor is pending,
                    # so this is how we learn the session is blocked.
                    required = user_data.get("requiresTwoFactorAuth")
                    self.two_factor_methods = required if isinstance(required, list) else []
                    if self.two_factor_methods:
                        self.two_factor_required = True
                    return
        except (OSError, json.JSONDecodeError, requests.RequestException):
            pass
        self.authenticated = False

    def login(self, username: str, password: str) -> Tuple[bool, str]:
        try:
            r = self.session.get(
                f"{BASE_URL}/auth/user",
                headers={"Authorization": _basic_auth(username, password)},
                timeout=30,
            )
            
            data = _safe_json(r)
            
            if r.status_code == 200:
                self.authenticated = True
                self.current_user = data.get("displayName") or data.get("username") or username
                required = data.get("requiresTwoFactorAuth")
                self.two_factor_methods = required if isinstance(required, list) else []
                if self.two_factor_methods:
                    # Logged in, but still blocked until a code is submitted.
                    self.two_factor_required = True
                    self._save_session()
                    return False, "requires_2fa"
                self._save_session()
                return True, "Logged in successfully"

            if r.status_code == 401:
                err_msg = ""
                if isinstance(data.get("error"), dict):
                    err_msg = data["error"].get("message", "")
                required = data.get("requiresTwoFactorAuth")
                if isinstance(required, list):
                    self.two_factor_methods = required
                if "2 Factor" in err_msg or self.two_factor_methods:
                    return False, "requires_2fa"
                if isinstance(data.get("error"), str):
                    err_msg = data["error"]
                return False, err_msg or "Invalid credentials"
            
            err_msg = ""
            if isinstance(data.get("error"), dict):
                err_msg = data["error"].get("message", "")
            return False, f"Unexpected response: {r.status_code} - {err_msg or r.reason}"
        except requests.RequestException as e:
            return False, f"Connection error: {e}"
        except Exception as e:
            return False, f"Unexpected error: {e}"

    def required_two_factor_method(self) -> str:
        """Which code VRChat is waiting for.

        Answers from the last /auth/user response when available, because that
        is where VRChat states the requirement; falls back to an authenticator
        app, which is the common setup.
        """
        for name in ("totp", "emailOtp"):
            if name in self.two_factor_methods:
                return name
        return "totp"

    def refresh_two_factor_methods(self) -> list:
        """Ask VRChat which verification method this session needs.

        /auth/user answers 200 even while two-factor is outstanding, with the
        requirement in `requiresTwoFactorAuth`, so this works without a failing
        data call.
        """
        if not self.authenticated:
            return []
        try:
            resp = self.session.get(f"{BASE_URL}/auth/user", timeout=15)
        except requests.RequestException:
            return self.two_factor_methods

        if resp.status_code == 200:
            data = _safe_json(resp)
            required = data.get("requiresTwoFactorAuth")
            self.two_factor_methods = required if isinstance(required, list) else []
            if isinstance(data.get("displayName"), str):
                self.current_user = data["displayName"]
        return self.two_factor_methods

    def verify_2fa(self, code: str, method: Optional[str] = None) -> Tuple[bool, str]:
        """Submit a two-factor code to lift the block on this session.

        `method` is 'totp' for an authenticator app or 'emailOtp' for the code
        VRChat emails. Left unset, uses whatever VRChat said it wanted.
        """
        code = "".join((code or "").split())
        if not code:
            return False, "Enter a code."

        method = method or self.required_two_factor_method()
        endpoint = TWO_FACTOR_ENDPOINTS.get(method)
        if endpoint is None:
            return False, f"Unsupported two-factor method: {method}"

        try:
            r = self.session.post(f"{BASE_URL}{endpoint}",
                                  json={"code": code}, timeout=15)
        except requests.RequestException as e:
            return False, f"Connection error: {e}"
        except Exception as e:
            return False, f"Unexpected error: {e}"

        data = _safe_json(r)

        if r.status_code == 200:
            # VRChat can answer 200 with verified:false, so check the body
            # rather than trusting the status code alone.
            if isinstance(data, dict) and data.get("verified") is False:
                return False, _wrong_code_hint(method)
            self.authenticated = True
            self.two_factor_required = False
            self.two_factor_methods = []
            self._save_session()
            return True, "2FA verified"

        err = ""
        if isinstance(data.get("error"), dict):
            err = data["error"].get("message", "")
        elif isinstance(data.get("error"), str):
            err = data["error"]
        err = err.strip('"')
        if r.status_code in (400, 403) or "invalid" in err.lower():
            return False, _wrong_code_hint(method, err)
        return False, err or f"HTTP {r.status_code}"

    def _get(self, path: str, params: Optional[dict] = None, retries: int = 3) -> dict:
        """GET with rate-limit handling and errors the caller can show.

        Every VRChat endpoint, public avatars included, needs the auth cookie,
        so an unauthenticated call is an error rather than an empty result.
        """
        if not self.authenticated:
            raise VRChatAPIError("Not logged in", status_code=401)

        last_error = None
        for attempt in range(retries):
            try:
                resp = self.session.get(f"{BASE_URL}{path}", params=params, timeout=30)
            except requests.RequestException as exc:
                last_error = VRChatAPIError(f"Connection error: {exc}")
                if attempt == retries - 1:
                    raise last_error
                time.sleep(2 ** attempt)
                continue

            if resp.status_code == 429:
                wait = _retry_after(resp) or float(2 ** attempt)
                last_error = VRChatAPIError(
                    f"Rate limited by VRChat, retrying in {wait:.0f}s",
                    status_code=429)
                if attempt == retries - 1:
                    raise last_error
                time.sleep(wait)
                continue

            data = _safe_json(resp)
            if resp.status_code == 404:
                raise VRChatAPIError(_error_message(data, "Not found"), status_code=404)
            if resp.status_code >= 400:
                error = VRChatAPIError(
                    _error_message(data, f"HTTP {resp.status_code}"),
                    status_code=resp.status_code)
                if error.needs_2fa:
                    self.two_factor_required = True
                raise error
            self.two_factor_required = False
            return data

        raise last_error or VRChatAPIError("Request failed")

    def _paginate(self, path: str, params: dict) -> list:
        """Collect every page of a list endpoint.

        Two pagination styles are in play. Most listings answer with
        `{"results": [...], "nextCursor": ...}` and are walked by cursor.
        /favorites instead returns a bare array, ignores `limit`, serves a
        fixed 10 rows per page and pages by `offset` -- with no cursor to
        follow. Stopping at the first array therefore truncated the list at
        10 entries no matter what the caller asked for.
        """
        results = []
        cursor = None
        offset = 0

        for _ in range(MAX_PAGES):
            page_params = dict(params)
            if cursor:
                page_params["cursor"] = cursor
            data = self._get(path, page_params)

            if isinstance(data, list):
                results.extend(data)
                # A short page means the end; a full one means keep going.
                if len(data) < OFFSET_PAGE_SIZE:
                    break
                # Full page: back off briefly so a longer list does not walk
                # straight into VRChat's undocumented throttling.
                time.sleep(PAGE_GAP_SECONDS)
                offset += OFFSET_PAGE_SIZE
                params = dict(params)
                params["offset"] = offset
                continue

            if not isinstance(data, dict):
                break

            batch = data.get("results")
            if isinstance(batch, list):
                results.extend(batch)

            if len(results) >= MAX_RESULTS:
                return results[:MAX_RESULTS]

            cursor = data.get("nextCursor")
            if not cursor:
                break

        return results

    def lookup_avatar(self, avatar_id: str) -> Optional[dict]:
        """Fetch one avatar by id or URL. Returns None if it does not exist.

        Raises VRChatAPIError when the request itself failed, which the caller
        needs to tell apart from a genuinely missing avatar.
        """
        references = parse_reference(avatar_id)
        resolved = next((i for k, i in references if k == "avatar"), None)
        if not resolved:
            raise VRChatAPIError(f"Not an avatar id or URL: {avatar_id!r}")

        try:
            data = self._get(f"/avatars/{resolved}")
        except VRChatAPIError as error:
            if error.status_code == 404:
                return None
            raise
        return normalize_avatar(_safe_json(data) if not isinstance(data, dict) else data) or None

    def get_user_avatars(self, user_id: str, release_status: str = "") -> list:
        """Every public avatar belonging to a user, following pagination."""
        references = parse_reference(user_id)
        resolved = next((i for k, i in references if k == "user"), None)
        if not resolved:
            raise VRChatAPIError(f"Not a user id or URL: {user_id!r}")

        params = {"userId": resolved, "limit": 100, "order": "updated"}
        if release_status:
            params["releaseStatus"] = release_status

        return self._normalize_all(self._paginate("/avatars", params))

    def get_my_avatars(self, release_status: str = "all") -> list:
        """Your own avatars, including ones you have not made public."""
        params = {"limit": 100}
        if release_status:
            params["releaseStatus"] = release_status
        return self._normalize_all(self._paginate("/avatars/me", params))

    @staticmethod
    def _normalize_all(raw_avatars):
        """Drop anything unusable so callers can iterate without filtering."""
        normalized = (normalize_avatar(a) for a in raw_avatars or [])
        return [a for a in normalized if a]

    def get_favorite_groups(self, group_type: str = "avatar") -> list:
        """The account's favourite groups, e.g. groups_abc123."""
        data = self._get("/favorite/groups", {"type": group_type})
        groups = data if isinstance(data, list) else data.get("results", [])
        return [normalize_favorite_group(g) for g in groups if g.get("id")]

    def get_favorites(self, favorite_type: str = "avatar",
                      group_id: str = "") -> list:
        """Favourites of a type, optionally narrowed to one favourite group.

        Without `group_id` this returns only favourites filed outside any
        group, which for an account that groups everything is legitimately
        empty. To get the whole set you must ask per group; see
        get_all_favorites.
        """
        params = {"type": favorite_type, "limit": 200}
        if group_id:
            params["groupId"] = group_id
        return self._normalize_favorites(self._paginate("/favorites", params))

    def get_all_favorites(self, favorite_type: str = "avatar",
                          group_ids: Optional[list] = None) -> list:
        """Every favourite across the given groups, plus any ungrouped ones.

        An avatar can sit in several groups at once, so results are merged by
        avatar id and their group tags combined rather than duplicated.
        """
        merged = {}

        def absorb(entries):
            for entry in entries:
                avatar_id = entry.get("avatar_id")
                if not avatar_id:
                    continue
                existing = merged.get(avatar_id)
                if existing is None:
                    merged[avatar_id] = dict(entry,
                                             group_ids=list(entry["group_ids"]))
                    continue
                for tag in entry.get("group_ids", []):
                    if tag not in existing["group_ids"]:
                        existing["group_ids"].append(tag)
                # Keep a fav_ id if any listing supplied one, so a later
                # unfavourite is still possible.
                if not existing.get("favorite_id") and entry.get("favorite_id"):
                    existing["favorite_id"] = entry["favorite_id"]

        for group_id in group_ids or []:
            absorb(self.get_favorites(favorite_type, group_id))

        # Anything filed outside a group only appears here.
        absorb(self.get_favorites(favorite_type))

        return list(merged.values())

    def get_group_favorites(self, group_id: str, limit: int = 200) -> list:
        """Favourites belonging to one group."""
        return self.get_favorites("avatar", group_id)

    @staticmethod
    def _normalize_favorites(raw_entries):
        """Normalise first, then drop unusable entries.

        Filtering before normalising silently drops everything, because raw
        records carry `id` rather than the `favorite_id` the normalised shape
        uses.
        """
        normalized = (normalize_favorite(entry) for entry in raw_entries or [])
        return [entry for entry in normalized if entry]

    def add_favorite(self, avatar_id: str, group: Union[str, list] = "") -> Tuple[bool, str]:
        """Favourite an avatar in-game.

        `group` is one slug ("avatars1") or several, and is sent as the
        favourite's tags. It is the internal slug, not the group id and not the
        display name -- that is the value the API stores and expects back.

        Returns (ok, message); on success the message carries the new favourite
        id so the caller can store it and undo the change later.
        """
        if not self.authenticated:
            return False, "Not logged in"

        tags = [group] if isinstance(group, str) else list(group or [])
        tags = [t for t in tags if t]

        payload = {"type": "avatar", "favoriteId": avatar_id}
        if tags:
            payload["tags"] = tags

        try:
            resp = self.session.post(f"{BASE_URL}/favorites", json=payload, timeout=30)
        except requests.RequestException as exc:
            return False, f"Connection error: {exc}"

        if resp.status_code == 200:
            data = _safe_json(resp)
            return True, data.get("id", "")
        if resp.status_code == 400:
            return False, _error_message(
                _safe_json(resp), "Favourite limit reached or already favourited")
        if resp.status_code == 403:
            message = _error_message(_safe_json(resp), "Forbidden")
            if "two-factor" in message.lower():
                self.two_factor_required = True
            return False, message
        return False, _error_message(_safe_json(resp), f"HTTP {resp.status_code}")

    def remove_favorite(self, favorite_id: str) -> Tuple[bool, str]:
        """Remove a favourite in-game.

        Takes the favourite id (fvrt_...), not the avatar id. Real ids use the
        fvrt_ prefix even though the older `fav_` form still appears in
        documentation.
        """
        if not self.authenticated:
            return False, "Not logged in"
        try:
            resp = self.session.delete(f"{BASE_URL}/favorites/{favorite_id}", timeout=30)
        except requests.RequestException as exc:
            return False, f"Connection error: {exc}"
        if resp.status_code == 200:
            return True, "Removed"
        return False, _error_message(_safe_json(resp), f"HTTP {resp.status_code}")

    def get_favorite_tags(self, avatar_id: str) -> Tuple[Optional[str], list]:
        """Find an avatar's favourite record: its id and its group tags.

        Returns (favorite_id or None, [slug, ...]). The ungrouped listing
        covers everything here, because VRChat does not actually filter by
        `groupId` -- asking per group just returns the whole list again.
        """
        if not self.authenticated:
            return None, []

        entries = self._normalize_favorites(
            self._paginate("/favorites", {"type": "avatar", "limit": 200}))
        for entry in entries:
            if entry.get("avatar_id") == avatar_id:
                return entry.get("favorite_id") or None, list(entry.get("group_ids", []))
        return None, []

    def set_favorite_groups(self, avatar_id: str, groups: list,
                            delay: float = 1.0) -> Tuple[bool, str]:
        """Put an avatar in exactly the given groups, and no others.

        VRChat has no endpoint for editing a favourite's tags: PUT
        /favorites/{id} answers 405, and the official SDK ships AddFavorite,
        GetFavorite, RemoveFavorite and UpdateFavoriteGroup but no
        UpdateFavorite. A favourite can hold several tags at once, but POST
        refuses an avatar that is already favourited, so changing groups means
        removing the record and adding it back with the new tag list.

        `groups` is a list of slugs ("avatars1"). An empty list removes the
        avatar from every group, which is the same as unfavouriting it.

        Because that is a destructive sequence, a failure to re-add is reported
        loudly and the original tag list is attempted again so the favourite is
        not silently lost.
        """
        if not self.authenticated:
            return False, "Not logged in"

        wanted = [g for g in dict.fromkeys(groups or []) if g]
        favorite_id, current = self.get_favorite_tags(avatar_id)

        if favorite_id is None:
            if not wanted:
                return True, "Already in no groups"
            return self.add_favorite(avatar_id, wanted)

        if sorted(wanted) == sorted(current):
            return True, "Already in those groups"

        if not wanted:
            ok, message = self.remove_favorite(favorite_id)
            return (True, "Removed from all groups") if ok else (False, message)

        ok, message = self.remove_favorite(favorite_id)
        if not ok:
            return False, f"Could not remove the existing favourite: {message}"

        # Give VRChat a moment; re-adding instantly can be refused as a
        # duplicate while the old record is still being torn down.
        if delay:
            time.sleep(delay)

        ok, message = self.add_favorite(avatar_id, wanted)
        if ok:
            return True, message

        restore, restore_message = self.add_favorite(avatar_id, current)
        if restore:
            return False, (f"Could not move the avatar ({message}). It was put "
                           f"back in its original group(s).")
        return False, (f"Could not move the avatar ({message}), and restoring it "
                       f"failed too ({restore_message}). Check your VRChat "
                       f"favourites -- this one may need re-adding.")

    def logout(self):
        self.session.cookies.clear()
        self.authenticated = False
        self.current_user = None
        try:
            if os.path.exists(SESSION_FILE):
                os.remove(SESSION_FILE)
        except OSError:
            pass

    @staticmethod
    def _extract_id(text: str) -> Optional[str]:
        m = re.search(r"avtr_[0-9a-f\-]{36}", text, re.IGNORECASE)
        return m.group(0) if m else None
