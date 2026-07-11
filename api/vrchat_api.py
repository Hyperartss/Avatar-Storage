import requests
import re
import json
import os
import base64
from urllib.parse import quote
from typing import Optional, Tuple

BASE_URL = "https://api.vrchat.cloud/api/1"
SESSION_FILE = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "session.json")

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

class VRChatAPI:
    def __init__(self):
        self.session = requests.Session()
        self.session.headers.update({
            "User-Agent": "INF-Avis/1.0 (https://github.com/INF-Avis)",
            "Content-Type": "application/json",
        })
        self.authenticated = False
        self.current_user = None
        self._load_session()

    def _save_session(self):
        data = {
            "cookies": self.session.cookies.get_dict(),
            "current_user": self.current_user,
        }
        try:
            with open(SESSION_FILE, "w") as f:
                json.dump(data, f)
        except OSError:
            pass

    def _load_session(self):
        try:
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
                self._save_session()
                return True, "Logged in successfully"
            
            if r.status_code == 401:
                err_msg = ""
                if isinstance(data.get("error"), dict):
                    err_msg = data["error"].get("message", "")
                if "2 Factor" in err_msg or "requiresTwoFactor" in str(data):
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

    def verify_2fa(self, code: str) -> Tuple[bool, str]:
        try:
            r = self.session.post(f"{BASE_URL}/auth/twofactorauth/totp/verify",
                                  json={"code": code}, timeout=15)
            data = _safe_json(r)
            if r.status_code == 200:
                self.authenticated = True
                user_data = _safe_json(self.session.get(f"{BASE_URL}/auth/user", timeout=10))
                self.current_user = user_data.get("displayName") or user_data.get("username") or "authenticated_user"
                self._save_session()
                return True, "2FA verified"
            err = data.get("error", {}).get("message", "") if isinstance(data.get("error"), dict) else data.get("error", "")
            return False, err or "Invalid 2FA code"
        except requests.RequestException as e:
            return False, f"Connection error: {e}"
        except Exception as e:
            return False, f"Unexpected error: {e}"

    def lookup_avatar(self, avatar_id: str) -> Optional[dict]:
        if not re.match(r"^avtr_[0-9a-f\-]{36}$", avatar_id, re.IGNORECASE):
            avatar_id = self._extract_id(avatar_id)
            if not avatar_id:
                return None
        
        try:
            r = self.session.get(f"{BASE_URL}/avatars/{avatar_id}", timeout=15)
            if r.status_code == 200:
                data = r.json()
                return {
                    "id": data.get("id", avatar_id),
                    "name": data.get("name", "Unknown"),
                    "author": data.get("authorName", ""),
                    "thumbnail_url": data.get("thumbnailImageUrl", ""),
                    "description": data.get("description", ""),
                }
        except requests.RequestException:
            pass
        return None

    def get_favorite_groups(self) -> list:
        if not self.authenticated:
            return []
        try:
            r = self.session.get(f"{BASE_URL}/favorite/groups", timeout=15)
            if r.status_code == 200:
                return r.json()
        except requests.RequestException:
            pass
        return []

    def add_favorite(self, avatar_id: str, group_id: str) -> Tuple[bool, str]:
        if not self.authenticated:
            return False, "Not authenticated"
        try:
            r = self.session.post(f"{BASE_URL}/favorites", json={
                "type": "avatar",
                "favoriteId": avatar_id,
                "tags": [group_id],
            }, timeout=15)
            if r.status_code == 200:
                return True, "Favorited in-game"
            if r.status_code == 400:
                return False, "Favorite slot limit reached or already favorited"
            return False, f"Error: {r.status_code}"
        except requests.RequestException as e:
            return False, f"Connection error: {e}"
        except Exception as e:
            return False, f"Unexpected error: {e}"

    def remove_favorite(self, favorite_id: str) -> bool:
        if not self.authenticated:
            return False
        try:
            r = self.session.delete(f"{BASE_URL}/favorites/{favorite_id}", timeout=15)
            return r.status_code == 200
        except requests.RequestException:
            return False
        except Exception:
            return False

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
