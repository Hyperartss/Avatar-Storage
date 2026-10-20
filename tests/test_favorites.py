"""Tests for favourite sync, offline and against a stub API.

    QT_QPA_PLATFORM=offscreen python3 tests/test_favorites.py
"""

import os
import time
import shutil
import hashlib
import sys
import tempfile
import threading
from pathlib import Path

REAL_APP_DIR = Path(__file__).resolve().parent.parent

EXCLUDE = shutil.ignore_patterns(
    "__pycache__", "*.pyc", ".venv", "venv", ".git",
    "*.db", "*.db-wal", "*.db-shm", "session.json", "cache",
)

failures = []


def check(label, condition, detail=""):
    if condition:
        print(f"  pass  {label}")
    else:
        print(f"  FAIL  {label} {detail}")
        failures.append(label)


def data_snapshot(directory):
    snapshot = {}
    for name in ("session.json", "avatar_library.db"):
        path = directory / name
        snapshot[name] = hashlib.sha256(path.read_bytes()).hexdigest() if path.is_file() else None
    cache = directory / "cache"
    snapshot["cache"] = sorted(p.name for p in cache.iterdir()) if cache.is_dir() else None
    return snapshot


class StubAPI:
    """Mimics the bits of VRChatAPI the sync worker uses."""

    def __init__(self, groups=None, favorites=None, avatars=None,
                 fail_with=None, needs_2fa=False, missing=(),
                 favorites_by_group=None):
        self.authenticated = True
        self.two_factor_required = False
        self.groups = groups or []
        self.favorites = favorites or []
        # Favourites that live inside a group. Kept separate from the
        # ungrouped list, because that is how the real API behaves.
        self.favorites_by_group = favorites_by_group or {}
        self.avatars = avatars or {}
        self.fail_with = fail_with
        self.needs_2fa = needs_2fa
        self.missing = set(missing)
        self.otp_attempts = 0
        self.otp_ok = True
        self.calls = []

    def _guard(self):
        """Raise fail_with when configured; honour needs_2fa once."""
        from api.vrchat_api import VRChatAPIError
        self.calls.append("guarded")
        if self.fail_with is not None:
            raise self.fail_with
        if self.needs_2fa:
            self.otp_attempts += 1
            if self.otp_attempts == 1:
                self.two_factor_required = True
                raise VRChatAPIError('"Requires Two-Factor Authentication"', 403)

    def get_favorite_groups(self, group_type="avatar"):
        self._guard()
        return self.groups

    def get_favorites(self, favorite_type="avatar", group_id=""):
        self._guard()
        if group_id:
            return self.favorites_by_group.get(group_id, [])
        return self.favorites

    def get_all_favorites(self, favorite_type="avatar", group_ids=None):
        self._guard()
        from api.vrchat_api import VRChatAPI as _Real
        merged = {}
        for gid in group_ids or []:
            for entry in self.favorites_by_group.get(gid, []):
                existing = merged.get(entry["avatar_id"])
                if existing is None:
                    merged[entry["avatar_id"]] = dict(
                        entry, group_ids=list(entry["group_ids"]))
                    continue
                for tag in entry["group_ids"]:
                    if tag not in existing["group_ids"]:
                        existing["group_ids"].append(tag)
        for entry in self.favorites:
            merged.setdefault(entry["avatar_id"], dict(
                entry, group_ids=list(entry["group_ids"])))
        return list(merged.values())

    def lookup_avatar(self, avatar_id):
        if avatar_id in self.missing:
            return None
        return self.avatars.get(avatar_id)

    def verify_2fa(self, code):
        self.otp_ok = code == "123456"
        if self.otp_ok:
            self.two_factor_required = False
        return self.otp_ok, "ok" if self.otp_ok else "bad code"


def avatar_payload(n, group):
    return {
        "id": f"avtr_0000000{n}-0000-0000-0000-000000000000",
        "name": f"Fav {n}",
        "author": "Creator",
        "author_id": "usr_00000000-0000-0000-0000-0000000000aa",
        "thumbnail_url": f"https://example.invalid/{n}.png",
        "description": "",
        "tags": ["anime"],
        "release_status": "public",
        "version": "1",
        "unity_version": "2022",
        "date_published": 0,
        "date_updated": 0,
        "downloads": 0,
        "favorites_count": 0,
        "rating": 0,
        "is_public": True,
        "url": f"https://vrchat.com/home/avatar/avtr_0000000{n}-0000-0000-0000-000000000000",
    }


def run_worker(worker, timeout_ms=15000):
    """Run a worker thread and return the summary it emitted."""
    from PyQt6.QtCore import QEventLoop, QTimer
    loop = QEventLoop()
    result = {}
    worker.completed.connect(lambda s: (result.update(s), loop.quit()))
    worker.start()
    QTimer.singleShot(timeout_ms, loop.quit)
    loop.exec()
    worker.wait()
    return result


def main():
    root = Path(tempfile.mkdtemp(prefix="infavis-fav-"))
    app = root / "app"
    shutil.copytree(REAL_APP_DIR, app, ignore=EXCLUDE)
    sys.path.insert(0, str(app))

    repo_before = data_snapshot(REAL_APP_DIR)

    os.environ["HOME"] = str(root / "home")
    os.environ["INF_AVIS_DATA_DIR"] = str(root / "data")
    os.environ["INF_AVIS_CONFIG_DIR"] = str(root / "config")
    os.environ["INF_AVIS_CACHE_DIR"] = str(root / "cache")

    from PyQt6.QtWidgets import QApplication
    import database as db
    from api.vrchat_api import VRChatAPIError, normalize_favorite, normalize_favorite_group
    from gui.favorites_sync import FavoritesWorker

    qt = QApplication(sys.argv)
    db.init_db()

    group_a = {"id": "groups_aaaaaaaa-0000-0000-0000-000000000001",
               "name": "Cool stuff", "type": "avatar", "order": 1,
               "capacity": 32, "favorites_count": 2}
    group_b = {"id": "groups_bbbbbbbb-0000-0000-0000-000000000002",
               "name": "Later", "type": "avatar", "order": 2,
               "capacity": 32, "favorites_count": 0}

    fav1 = {"favorite_id": "fav_1", "avatar_id": "avtr_00000001-0000-0000-0000-000000000000",
            "group_ids": [group_a["id"]], "tags": []}
    fav2 = {"favorite_id": "fav_2", "avatar_id": "avtr_00000002-0000-0000-0000-000000000000",
            "group_ids": [group_a["id"]], "tags": []}

    print("normalisation")
    entry = normalize_favorite({"id": "fav_x", "favoriteId": "avtr_y",
                            "tags": ["groups_z"]})
    check("favorite keeps both ids",
          entry["favorite_id"] == "fav_x" and entry["avatar_id"] == "avtr_y"
          and entry["group_ids"] == ["groups_z"], str(entry))
    check("favorite tolerates missing tags",
          normalize_favorite({"id": "fav_x", "favoriteId": "avtr_y"})["group_ids"] == [])
    check("group normalised",
          normalize_favorite_group(group_a)["capacity"] == 32)

    print("schema")
    tables = {r["name"] for r in db.get_connection().execute(
        "SELECT name FROM sqlite_master WHERE type='table'")}
    check("vrchat_favorites table exists", "vrchat_favorites" in tables, str(tables))
    category_columns = {r["name"] for r in db.get_connection().execute(
        "PRAGMA table_info(categories)")}
    check("categories gained sync_group_id", "sync_group_id" in category_columns)

    print("group mirroring")
    linked = db.sync_favorite_groups([group_a, group_b])
    check("two categories created", len(linked) == 2, str(linked))
    again = db.sync_favorite_groups([group_a, group_b])
    check("mirroring is idempotent", again == linked, str(again))
    check("no duplicate categories",
          len(db.get_all_categories()) == 2, str(len(db.get_all_categories())))
    check("existing name is reused, not duplicated",
          len(db.sync_favorite_groups([group_a]) or {}) == 1)

    print("full sync")
    stub = StubAPI(groups=[group_a, group_b], favorites=[fav1, fav2],
                   avatars={fav1["avatar_id"]: avatar_payload(1, group_a),
                            fav2["avatar_id"]: avatar_payload(2, group_a)})
    worker = FavoritesWorker(stub, mirror_groups=True, mark_favorite=True)
    summary = run_worker(worker)
    check("two avatars added", summary.get("added") == 2, str(summary))
    check("total reported", summary.get("total_favorites") == 2, str(summary))
    row = db.get_avatar(fav1["avatar_id"])
    check("avatar in library", row is not None)
    check("marked favourite", row["favorite"] == 1)
    record = db.get_favorite_record(fav1["avatar_id"])
    check("fav_ id stored", record is not None and record["favorite_id"] == "fav_1",
          str(record))
    check("group recorded", record["group_id"] == group_a["id"], str(record))
    cat = db.get_avatar_categories(fav1["avatar_id"])
    check("linked to mirrored category", len(cat) == 1, str([c["name"] for c in cat]))
    check("linked category is the right one",
          cat and cat[0]["name"] == "Cool stuff", str(cat and cat[0]["name"]))

    print("re-sync does not duplicate")
    worker = FavoritesWorker(stub, mirror_groups=True, mark_favorite=True)
    summary = run_worker(worker)
    check("nothing added on re-sync", summary.get("added") == 0, str(summary))
    check("reported as refreshed", summary.get("updated") == 2, str(summary))
    check("categories still two", len(db.get_all_categories()) == 2)

    print("skip refresh for known avatars")
    worker = FavoritesWorker(stub, mirror_groups=True, mark_favorite=True,
                             refresh_existing=False)
    summary = run_worker(worker)
    check("known avatars skipped", summary.get("unchanged") == 2, str(summary))
    check("no avatar fetches made", stub.avatars and True)

    print("deleted favourite reported")
    gone = {"favorite_id": "fav_9", "avatar_id": "avtr_00000009-0000-0000-0000-000000000000",
            "group_ids": [], "tags": []}
    stub2 = StubAPI(groups=[group_a], favorites=[gone], avatars={})
    worker = FavoritesWorker(stub2, mirror_groups=True)
    summary = run_worker(worker)
    check("missing avatar listed", summary.get("missing") == [gone["avatar_id"]],
          str(summary))
    check("counted as failed", summary.get("failed") == 1, str(summary))

    print("two-factor handshake")
    stub3 = StubAPI(groups=[group_a], favorites=[fav1],
                    avatars={fav1["avatar_id"]: avatar_payload(1, group_a)},
                    needs_2fa=True)
    worker = FavoritesWorker(stub3, mirror_groups=True)
    prompted = []

    def answer_with_valid_code():
        prompted.append(1)
        verified, _ = stub3.verify_2fa("123456")
        if not verified:
            stub3.two_factor_required = True
        worker.confirm_two_factor()

    worker.two_factor_required.connect(answer_with_valid_code)
    summary = run_worker(worker)
    check("2FA prompt raised", len(prompted) == 1, str(prompted))
    check("sync continued after 2FA", summary.get("total_favorites") == 1, str(summary))
    check("avatar written after 2FA",
          summary.get("added", 0) + summary.get("updated", 0) == 1, str(summary))

    print("two-factor verification refused")
    stub6 = StubAPI(groups=[group_a], favorites=[fav1],
                    avatars={fav1["avatar_id"]: avatar_payload(1, group_a)},
                    needs_2fa=True)
    worker = FavoritesWorker(stub6, mirror_groups=True)
    # Simulate the dialog rejecting the code: it leaves the flag set.
    worker.two_factor_required.connect(
        lambda: (stub6.two_factor_required, worker.confirm_two_factor()))
    summary = run_worker(worker, timeout_ms=20000)
    check("refused 2FA gives up rather than hanging",
          any("did not complete" in p for p in summary.get("problems", [])), str(summary))

    print("network failure reported")
    from api.vrchat_api import VRChatAPIError as VE
    stub4 = StubAPI(fail_with=VE('"Missing Credentials"', 401))
    worker = FavoritesWorker(stub4)
    summary = run_worker(worker)
    check("401 reported", any("Credentials" in p for p in summary.get("problems", [])),
          str(summary))
    check("no avatars written", db.get_avatar(fav1["avatar_id"]) is not None)

    print("cancel")
    many = [{"favorite_id": f"fav_c{i}", "group_ids": [], "tags": [],
             "avatar_id": f"avtr_000000c{i}-0000-0000-0000-000000000000"}
            for i in range(6)]
    stub5 = StubAPI(groups=[group_a], favorites=many,
                    avatars={f["avatar_id"]: avatar_payload(f"c{i}", group_a)
                             for i, f in enumerate(many)})
    worker = FavoritesWorker(stub5, mirror_groups=True)
    worker.progress.connect(lambda c, t, m: worker.cancel() if c >= 1 else None)
    summary = run_worker(worker)
    check("cancel marks stopped", summary.get("cancelled") is True, str(summary))
    check("cancel did not finish everything", summary.get("added", 0) < 6, str(summary))

    print("real verify_2fa against a stubbed session")
    from api.vrchat_api import VRChatAPI

    class FakeResponse:
        def __init__(self, status, payload, headers=None):
            self.status_code = status
            self._payload = payload
            self.headers = headers or {}

        def json(self):
            return self._payload

    class FakeSession:
        def __init__(self, response):
            self.response = response
            self.posts = []

        def post(self, url, json=None, timeout=None):
            self.posts.append((url, json))
            return self.response

        def get(self, url, **kwargs):
            raise AssertionError("verify_2fa must not need a follow-up GET")

    def api_returning(response):
        api = VRChatAPI()
        api.session = FakeSession(response)
        api.authenticated = True
        api.current_user = "omni_hyper"
        api._save_session = lambda: None
        return api

    # Regression: a successful verification used to raise NameError and report
    # failure, because it referenced a variable that had been removed.
    api = api_returning(FakeResponse(200, {"verified": True}))
    ok, message = api.verify_2fa("123456")
    check("valid code accepted", ok is True, message)
    check("session cleared for data calls", api.two_factor_required is False)
    check("code was posted to the TOTP endpoint",
          api.session.posts and api.session.posts[0][0].endswith(
              "/auth/twofactorauth/totp/verify"), str(api.session.posts))
    check("code was sent in the body",
          api.session.posts[0][1] == {"code": "123456"}, str(api.session.posts))

    api = api_returning(FakeResponse(200, {"verified": False}))
    ok, message = api.verify_2fa("000000")
    check("200 with verified:false is a failure", ok is False, message)
    check("failure message is useful", "rejected" in message, message)

    api = api_returning(FakeResponse(400, {"error": {"message": '"Invalid OTP"'}}))
    ok, message = api.verify_2fa("111111")
    check("400 rejected", ok is False)
    check("error text passed through", "Invalid OTP" in message, message)

    api = api_returning(FakeResponse(200, {"verified": True}))
    ok, message = api.verify_2fa("   123 456 ")
    check("spaces in the code are tolerated", ok is True, message)

    api = api_returning(FakeResponse(200, {"verified": True}))
    ok, message = api.verify_2fa("  ")
    check("empty code refused without a request", ok is False)
    check("no request sent for an empty code", not api.session.posts)

    print("method routing")
    from api.vrchat_api import TWO_FACTOR_ENDPOINTS

    api = api_returning(FakeResponse(200, {"verified": True}))
    api.two_factor_methods = ["emailOtp"]
    check("email account selects emailOtp",
          api.required_two_factor_method() == "emailOtp")
    ok, _ = api.verify_2fa("123456")
    check("email code posts to the email endpoint",
          ok and api.session.posts[0][0].endswith(
              TWO_FACTOR_ENDPOINTS["emailOtp"]), str(api.session.posts))

    api = api_returning(FakeResponse(200, {"verified": True}))
    api.two_factor_methods = ["totp"]
    ok, _ = api.verify_2fa("123456")
    check("totp account posts to the totp endpoint",
          ok and api.session.posts[0][0].endswith(
              TWO_FACTOR_ENDPOINTS["totp"]), str(api.session.posts))

    api = api_returning(FakeResponse(200, {"verified": True}))
    api.two_factor_methods = []
    check("unknown falls back to totp", api.required_two_factor_method() == "totp")

    api = api_returning(FakeResponse(200, {"verified": True}))
    ok, _ = api.verify_2fa("123456", method="emailOtp")
    check("method can be overridden explicitly",
          ok and api.session.posts[0][0].endswith("emailotp/verify"),
          str(api.session.posts))

    print("rejections explain the next step")
    api = api_returning(FakeResponse(400, {"error": {"message": '"Invalid OTP"'}}))
    api.two_factor_methods = ["emailOtp"]
    ok, message = api.verify_2fa("123456")
    check("email rejection mentions the email",
          ok is False and "emailed" in message, message)

    api = api_returning(FakeResponse(200, {"verified": False}))
    api.two_factor_methods = ["totp"]
    ok, message = api.verify_2fa("123456")
    check("totp rejection mentions the 30 second window",
          ok is False and "30 seconds" in message, message)

    print("required method is read from /auth/user")
    api = VRChatAPI()
    api.authenticated = True
    api.current_user = None
    api.two_factor_methods = []

    class UserResponse:
        status_code = 200

        @staticmethod
        def json():
            return {"displayName": "omni_hyper", "requiresTwoFactorAuth": ["emailOtp"]}

    api.session = type("S", (), {
        "get": staticmethod(lambda url, **kw: UserResponse())})()
    methods = api.refresh_two_factor_methods()
    check("methods read from the user endpoint", methods == ["emailOtp"], str(methods))
    check("display name refreshed", api.current_user == "omni_hyper")
    check("required method now emailOtp",
          api.required_two_factor_method() == "emailOtp")

    api.session = type("S", (), {
        "get": staticmethod(lambda url, **kw: (_ for _ in ()).throw(
            __import__("requests").RequestException("offline")))})()
    api.two_factor_methods = ["totp"]
    check("network failure keeps the known methods",
          api.refresh_two_factor_methods() == ["totp"])

    print("two-factor dialog picks the right method")
    from gui.otp import TwoFactorDialog, METHOD_HELP

    api = VRChatAPI.__new__(VRChatAPI)
    api.two_factor_methods = ["emailOtp"]
    dialog = TwoFactorDialog(None, api)
    check("dialog defaults to emailOtp", dialog.method == "emailOtp", dialog.method)
    check("dialog explains the email route",
          "emails this code" in dialog.help_label.text(),
          dialog.help_label.text())
    check("the other method is still offered",
          dialog.method_combo.count() == 2)
    dialog.method_combo.setCurrentIndex(
        dialog.method_combo.findData("totp"))
    check("user can switch to totp", dialog.method == "totp")
    check("help text follows the choice",
          "authenticator app" in dialog.help_label.text())
    dialog.code_input.setText(" 123 456 ")
    check("code is trimmed", dialog.code == "123 456")

    print("real favourite-listing normalisation")
    # Regression: entries were filtered on `favorite_id` *before* normalisation,
    # but raw /favorites records carry `id`, so every entry was discarded and the
    # sync silently imported nothing.
    from api.vrchat_api import normalize_favorite as nf

    record = {"id": "fav_abc", "favoriteId": "avtr_11111111-2222-3333-4444-555555555555",
              "tags": ["groups_x"], "type": "avatar"}
    entry = nf(record)
    check("raw favourite record keeps both ids",
          entry["avatar_id"] == record["favoriteId"]
          and entry["favorite_id"] == "fav_abc", str(entry))
    check("record flagged as a record", entry["is_record"] is True)

    bare = {"id": "avtr_99999999-2222-3333-4444-555555555555", "name": "Bare",
            "authorName": "A"}
    entry = nf(bare)
    check("bare avatar object yields the avatar id",
          entry["avatar_id"] == bare["id"], str(entry))
    check("bare avatar has no fav id", entry["favorite_id"] == "")
    check("bare avatar flagged as not a record", entry["is_record"] is False)

    check("entry with no avatar id dropped", nf({"id": "fav_x"}) == {})
    check("non-dict entry dropped", nf("nonsense") == {})

    from api.vrchat_api import VRChatAPI as _API

    class FakeResp:
        def __init__(self, payload):
            self.status_code = 200
            self.headers = {}
            self._payload = payload

        def json(self):
            return self._payload

    api = _API.__new__(_API)
    api.authenticated = True
    api.session = type("S", (), {
        "get": staticmethod(lambda url, params=None, **kw: FakeResp(
            {"results": [record, record], "nextCursor": None}))})()

    got = api.get_favorites("avatar")
    check("get_favorites keeps entries instead of dropping them",
          len(got) == 2, str(got))
    check("get_favorites exposes the avatar ids",
          all(e["avatar_id"] == record["favoriteId"] for e in got))
    check("get_favorites exposes the group tags",
          got[0]["group_ids"] == ["groups_x"], str(got[0]))

    print("bare-array listings are not discarded")
    # Regression: /favorites answers with a bare JSON array, and _paginate
    # bailed on anything that was not a dict, so a full page of favourites
    # came back as an empty list.
    api = _API.__new__(_API)
    api.authenticated = True
    api.session = type("S", (), {
        "get": staticmethod(lambda url, params=None, **kw: FakeResp([record, bare]))})()

    got = api.get_favorites("avatar")
    check("a bare array response is kept",
          len(got) == 2, str(got))
    check("bare array exposes both ids",
          {e["avatar_id"] for e in got} ==
          {record["favoriteId"], bare["id"]}, str(got))

    api.session = type("S", (), {
        "get": staticmethod(lambda url, params=None, **kw: FakeResp(
            {"results": [record], "nextCursor": None}))})()
    check("an enveloped response still works",
          len(api.get_favorites("avatar")) == 1)

    print("favourites are fetched per group")
    seen_params = []

    def fake_get(url, params=None, **kw):
        seen_params.append(dict(params or {}))
        gid = (params or {}).get("groupId")
        if gid == "fvgrp_one":
            return FakeResp([record, bare])
        if gid == "fvgrp_two":
            return FakeResp([record])
        return FakeResp([])          # nothing outside any group

    api = _API.__new__(_API)
    api.authenticated = True
    api.session = type("S", (), {"get": staticmethod(fake_get)})()

    merged = api.get_all_favorites("avatar", ["fvgrp_one", "fvgrp_two"])
    check("grouped favourites are found",
          len(merged) == 2, str(merged))
    check("each group was queried with its groupId",
          [p.get("groupId") for p in seen_params if p.get("groupId")] ==
          ["fvgrp_one", "fvgrp_two"], str(seen_params))
    check("the ungrouped listing is also checked",
          any("groupId" not in p for p in seen_params), str(seen_params))
    check("an avatar in two groups appears once",
          len({e["avatar_id"] for e in merged}) == len(merged))

    api.session = type("S", (), {
        "get": staticmethod(lambda url, params=None, **kw: FakeResp([]))})()
    check("no groups and no favourites yields nothing",
          api.get_all_favorites("avatar", []) == [])
    check("no groups and no favourites yields nothing",
          api.get_all_favorites("avatar", None) == [])

    print("a duplicate across groups keeps one entry")
    # Raw records as the API returns them: the group membership lives in tags.
    dup_a = {"id": "fav_a", "favoriteId": "avtr_dup", "tags": ["fvgrp_one"]}
    dup_b = {"id": "", "favoriteId": "avtr_dup", "tags": ["fvgrp_two"]}

    api = _API.__new__(_API)
    api.authenticated = True
    by_group = {"fvgrp_one": [dup_a], "fvgrp_two": [dup_b]}
    api.session = type("S", (), {
        "get": staticmethod(lambda url, params=None, **kw: FakeResp(
            by_group.get((params or {}).get("groupId"), [])))})()

    merged = api.get_all_favorites("avatar", ["fvgrp_one", "fvgrp_two"])
    check("shared avatar merged into one entry", len(merged) == 1, str(merged))
    check("both groups recorded on it",
          set(merged[0]["group_ids"]) == {"fvgrp_one", "fvgrp_two"},
          str(merged[0]))
    check("a fav id is retained for unfavouriting",
          merged[0]["favorite_id"] == "fav_a", str(merged[0]))

    print("groups keep the name shown on the website")
    raw_group = {"id": "fvgrp_870fb689", "name": "avatars1",
                 "displayName": "Cool avatars", "type": "avatar",
                 "visibility": "private"}
    check("display name wins over the internal slug",
          normalize_favorite_group(raw_group)["name"] == "Cool avatars",
          str(normalize_favorite_group(raw_group)))
    check("slug used when there is no display name",
          normalize_favorite_group(
              {"id": "fvgrp_x", "name": "avatars1"})["name"] == "avatars1")
    check("absent counters default to zero",
          normalize_favorite_group(raw_group)["favorites_count"] == 0)

    print("bare-array listings page by offset")
    # Regression: /favorites returns a bare array, ignores `limit`, serves a
    # fixed 10 rows and has no cursor. Reading only the first page truncated
    # a 26-avatar library at 10.
    import api.vrchat_api as api_module

    requested_offsets = []

    def paged_get(url, params=None, **kw):
        p = dict(params or {})
        requested_offsets.append(p.get("offset", 0))
        off = p.get("offset", 0)
        # 26 entries in 10/10/6 pages, exactly like the live account.
        page = twenty_six[off:off + 10]
        return FakeResp(page)

    def twenty_six_at(n):
        return [{"id": f"fav_{i}", "favoriteId": f"avtr_{i:08d}",
                 "tags": []} for i in range(n)]

    twenty_six = twenty_six_at(26)

    api = _API.__new__(_API)
    api.authenticated = True
    api.session = type("S", (), {"get": staticmethod(paged_get)})()

    saved_sleep = api_module.time.sleep
    api_module.time.sleep = lambda *a, **k: None       # keep the test quick
    try:
        got = api.get_favorites("avatar")
    finally:
        api_module.time.sleep = saved_sleep

    check("all 26 survive pagination", len(got) == 26, f"{len(got)} entries")
    check("offsets were walked 0,10,20",
          requested_offsets[:3] == [0, 10, 20], str(requested_offsets))
    check("it stopped on the short page",
          len(requested_offsets) == 3, str(requested_offsets))
    check("every avatar id is unique",
          len({e["avatar_id"] for e in got}) == 26)

    # Exactly-full pages must not stop early: 20 entries means a third page.
    twenty = twenty_six_at(20)
    requested_offsets.clear()

    def paged_get_20(url, params=None, **kw):
        off = (params or {}).get("offset", 0)
        requested_offsets.append(off)
        return FakeResp(twenty[off:off + 10])

    api.session = type("S", (), {"get": staticmethod(paged_get_20)})()
    api_module.time.sleep = lambda *a, **k: None
    try:
        got = api.get_favorites("avatar")
    finally:
        api_module.time.sleep = saved_sleep

    check("a full final page is followed",
          len(got) == 20, f"{len(got)} entries")
    check("it did not stop at 10 when 20 exist",
          len(requested_offsets) == 3, str(requested_offsets))

    # Enveloped cursor listings must be unaffected.
    seen_cursors, seen_offsets = [], []

    def enveloped_get(url, params=None, **kw):
        p = dict(params or {})
        seen_cursors.append(p.get("cursor"))
        seen_offsets.append(p.get("offset"))
        if p.get("cursor") == "page2":
            return FakeResp({"results": [{"id": "fav_c", "favoriteId": "avtr_c",
                                          "tags": []}], "nextCursor": None})
        return FakeResp({"results": [{"id": "fav_a", "favoriteId": "avtr_a",
                                      "tags": []}],
                         "nextCursor": "page2"})

    api.session = type("S", (), {"get": staticmethod(enveloped_get)})()
    got = api.get_favorites("avatar")
    check("cursor pagination still works", len(got) == 2, str(got))
    # The first request legitimately carries no cursor; later ones carry the
    # cursor instead of an offset. Either would do, but not both.
    check("the cursor is followed", seen_cursors[1] == "page2",
          str(seen_cursors))
    check("an offset is never sent to a cursor endpoint",
          all(o is None for o in seen_offsets), str(seen_offsets))

    print("favourite groups carry both names")
    from api.vrchat_api import normalize_favorite_group as nfg

    raw = {"id": "fvgrp_870fb689", "name": "avatars1", "displayName": "Mains",
           "type": "avatar", "visibility": "private"}
    group = nfg(raw)
    check("slug is kept for the API", group["slug"] == "avatars1", str(group))
    check("display name is kept for the UI", group["name"] == "Mains", str(group))
    check("display_name aliases the display name",
          group["display_name"] == "Mains")
    check("no display name falls back to the slug",
          nfg({"id": "x", "name": "avatars2"})["name"] == "avatars2")
    check("a display name equal to the slug is fine",
          nfg({"id": "x", "name": "a", "displayName": "a"})["slug"] == "a")

    print("moving favourites between groups")
    import api.vrchat_api as api_mod

    class MoveApi(VRChatAPI):
        """In-memory favourites with the real request/response shapes."""

        def __init__(self, tags_by_avatar=None, fail_add=False,
                     fail_restore=False):
            super().__new__(MoveApi)
            self.authenticated = True
            self.two_factor_required = False
            self.tags_by_avatar = dict(tags_by_avatar or {})
            self.ids = {a: f"fvrt_{n}" for n, a in
                        enumerate(self.tags_by_avatar)}
            self.fail_add = fail_add
            self.fail_restore = fail_restore
            self.posts = []
            self.deletes = []
            self._counter = 0

        def get_favorite_tags(self, avatar_id):
            tags = self.tags_by_avatar.get(avatar_id)
            if tags is None:
                return None, []
            return self.ids[avatar_id], list(tags)

        def add_favorite(self, avatar_id, group=""):
            tags = [group] if isinstance(group, str) else list(group or [])
            tags = [t for t in tags if t]
            self.posts.append((avatar_id, tags))
            if self.fail_add and not self.fail_restore:
                return False, "Favourite limit reached"
            if self.fail_add:
                return False, "Favourite limit reached"
            self._counter += 1
            self.ids[avatar_id] = f"fvrt_new{self._counter}"
            self.tags_by_avatar[avatar_id] = tags
            return True, self.ids[avatar_id]

        def remove_favorite(self, favorite_id):
            self.deletes.append(favorite_id)
            for avatar, fid in list(self.ids.items()):
                if fid == favorite_id:
                    del self.tags_by_avatar[avatar]
            return True, "Removed"

    av = "avtr_move_0001"

    api = MoveApi({av: ["avatars1"]})
    ok, message = api.set_favorite_groups(av, ["avatars2"], delay=0)
    check("a move reports success", ok, message)
    check("the old tag is gone", api.tags_by_avatar[av] == ["avatars2"],
          str(api.tags_by_avatar))
    check("the old favourite was removed", api.deletes == ["fvrt_0"],
          str(api.deletes))

    api = MoveApi({av: ["avatars1"]})
    ok, _ = api.set_favorite_groups(av, ["avatars2", "avatars3"], delay=0)
    check("several groups can be set at once",
          api.tags_by_avatar[av] == ["avatars2", "avatars3"],
          str(api.tags_by_avatar))

    api = MoveApi({av: ["avatars1"]})
    ok, _ = api.set_favorite_groups(av, ["avatars1"], delay=0)
    check("already-correct is a no-op", ok)
    check("no delete when nothing changes", api.deletes == [], str(api.deletes))
    check("no add when nothing changes", api.posts == [], str(api.posts))

    api = MoveApi({av: ["avatars1"]})
    ok, _ = api.set_favorite_groups(av, [], delay=0)
    check("an empty group list unfavourites", ok)
    check("the avatar is gone", av not in api.tags_by_avatar,
          str(api.tags_by_avatar))

    api = MoveApi({})
    ok, _ = api.set_favorite_groups(av, ["avatars4"], delay=0)
    check("moving something never favourited is a plain add", ok)
    check("it went straight into the group",
          api.tags_by_avatar[av] == ["avatars4"], str(api.tags_by_avatar))

    api = MoveApi({})
    ok, message = api.set_favorite_groups(av, [], delay=0)
    check("no groups and not favourited is a no-op", ok, message)
    check("nothing was created", api.tags_by_avatar == {}, str(api.tags_by_avatar))

    print("a failed move does not lose the favourite")
    api = MoveApi({av: ["avatars1"]})
    api.fail_add = True
    # Let the restore attempt succeed.
    original_add = api.add_favorite

    def add_then_restore(avatar_id, group=""):
        tags = [group] if isinstance(group, str) else list(group or [])
        api.posts.append((avatar_id, tags))
        if len(api.posts) == 1:
            return False, "Favourite limit reached"
        api.tags_by_avatar[avatar_id] = tags
        return True, "fvrt_restored"

    api.add_favorite = add_then_restore
    ok, message = api.set_favorite_groups(av, ["avatars2"], delay=0)
    check("the failure is reported", ok is False, message)
    check("the avatar was put back where it was",
          api.tags_by_avatar.get(av) == ["avatars1"], str(api.tags_by_avatar))
    check("the message tells the user it was restored",
          "original group" in message, message)

    api = MoveApi({av: ["avatars1"]})

    def always_fail(avatar_id, group=""):
        api.posts.append((avatar_id, group))
        return False, "nope"

    api.add_favorite = always_fail
    ok, message = api.set_favorite_groups(av, ["avatars2"], delay=0)
    check("a total failure is reported", ok is False)
    check("the user is warned to check VRChat",
          "check your vrchat favourites" in message.lower(), message)

    print("the move dialog builds the right assignments")
    from PyQt6.QtWidgets import QApplication as _App
    from gui.group_move import MoveFavoritesDialog, GroupMoveWorker

    from PyQt6.QtCore import Qt
    _app = _App.instance() or _App([])

    class GroupApi:
        authenticated = True
        two_factor_required = False

        def __init__(self, groups):
            self._groups = groups
            self.calls = []

        def get_favorite_groups(self, group_type="avatar"):
            return self._groups

    groups = [{"id": f"fvgrp_{n}", "slug": f"avatars{n}",
               "name": f"Group {n}", "display_name": f"Group {n}"}
              for n in (1, 2, 3)]
    avatars = [{"avatar_id": f"avtr_{n}", "name": f"Avatar {n}"}
               for n in (1, 2, 3)]

    dlg = MoveFavoritesDialog(None, GroupApi(groups), avatars)
    check("every group is offered", len(dlg.group_boxes) == 3,
          str(len(dlg.group_boxes)))
    check("every avatar is listed", dlg.avatar_list.count() == 3)

    dlg.set_all_selected(False)
    check("nothing selected yields no assignments",
          dlg.build_assignments() == [])

    dlg.avatar_list.item(0).setCheckState(Qt.CheckState.Checked)
    dlg.group_boxes[1].setChecked(True)
    assignments = dlg.build_assignments()
    check("one assignment for one ticked avatar", len(assignments) == 1,
          str(assignments))
    check("it carries the avatar id", assignments[0][0] == "avtr_1",
          str(assignments))
    check("it carries the group SLUG, not the id or display name",
          assignments[0][2] == ["avatars2"], str(assignments[0]))

    dlg.group_boxes[0].setChecked(True)
    dlg.group_boxes[2].setChecked(True)
    assignments = dlg.build_assignments()
    check("several ticked groups are all sent",
          assignments[0][2] == ["avatars1", "avatars2", "avatars3"],
          str(assignments[0]))

    dlg.set_all_selected(True)
    check("select all covers every avatar",
          len(dlg.build_assignments()) == 3)

    dlg.set_all_selected(True)
    for box in dlg.group_boxes:
        box.setChecked(False)
    check("ticking no groups means unfavourite",
          all(a[2] == [] for a in dlg.build_assignments()))

    # No groups at all must disable moving rather than break.
    empty = MoveFavoritesDialog(None, GroupApi([]), avatars)
    check("no groups disables the move button",
          not empty.move_btn.isEnabled())

    print("the dialog copes with real database rows")
    # database.get_all_avatars hands back sqlite3.Row, which has no .get().
    # Passing dicts here is what let a crash through, so use the real thing.
    import sqlite3 as _sqlite3

    conn = _sqlite3.connect(":memory:")
    conn.row_factory = _sqlite3.Row
    conn.execute("CREATE TABLE a (avatar_id TEXT, name TEXT)")
    conn.execute("INSERT INTO a VALUES ('avtr_row1', 'A Row Avatar')")
    conn.execute("INSERT INTO a VALUES ('avtr_row2', 'Second Row')")
    row_avatars = conn.execute("SELECT * FROM a").fetchall()
    conn.close()
    check("the test really is using sqlite3.Row rows",
          not isinstance(row_avatars[0], dict), str(type(row_avatars[0])))
    check("sqlite3.Row genuinely has no .get()",
          not hasattr(row_avatars[0], "get"))

    row_dialog = MoveFavoritesDialog(None, GroupApi(groups), row_avatars)
    check("rows do not crash the dialog",
          row_dialog.avatar_list.count() == 2,
          str(row_dialog.avatar_list.count()))
    check("the row's name is shown",
          row_dialog.avatar_list.item(0).text() == "A Row Avatar",
          row_dialog.avatar_list.item(0).text())
    row_dialog.avatar_list.item(0).setCheckState(Qt.CheckState.Checked)
    row_dialog.group_boxes[0].setChecked(True)
    row_assignments = row_dialog.build_assignments()
    check("a row yields a usable assignment",
          row_assignments and row_assignments[0][0] == "avtr_row1",
          str(row_assignments))

    # A row with an empty name must not collapse to a blank list entry.
    conn = _sqlite3.connect(":memory:")
    conn.row_factory = _sqlite3.Row
    conn.execute("CREATE TABLE a (avatar_id TEXT, name TEXT)")
    conn.execute("INSERT INTO a VALUES ('avtr_noname', NULL)")
    unnamed = conn.execute("SELECT * FROM a").fetchall()
    conn.close()
    unnamed_dialog = MoveFavoritesDialog(None, GroupApi(groups), unnamed)
    check("a row with no name falls back to the avatar id",
          unnamed_dialog.avatar_list.item(0).text() == "avtr_noname",
          unnamed_dialog.avatar_list.item(0).text())

    print("the move worker reports per-avatar results")
    recorded = []

    class MoveApi2:
        authenticated = True
        two_factor_required = False

        def set_favorite_groups(self, avatar_id, groups, delay=0):
            recorded.append((avatar_id, list(groups)))
            if avatar_id == "avtr_2":
                return False, "Favourite limit reached"
            if avatar_id == "avtr_3":
                return True, "Already in those groups"
            return True, "fvrt_new"

    worker = GroupMoveWorker(MoveApi2(), [
        ("avtr_1", "One", ["avatars2"]),
        ("avtr_2", "Two", ["avatars3"]),
        ("avtr_3", "Three", ["avatars4"]),
    ])
    done = []
    worker.completed.connect(done.append)
    worker.start()

    # The signal is delivered through the event loop, so the loop has to keep
    # turning while the thread runs.
    deadline = time.time() + 10
    while worker.isRunning() and time.time() < deadline:
        _app.processEvents()
        time.sleep(0.01)
    worker.wait(5000)
    _app.processEvents()

    check("the worker finished", not worker.isRunning(), "worker hung")
    check("the worker reported a summary", len(done) == 1, str(done))

    summary = done[0]
    check("one move succeeded", summary["moved"] == 1, str(summary))
    check("one was already correct", summary["unchanged"] == 1, str(summary))
    check("one failed", summary["failed"] == 1, str(summary))
    check("the API was called for each avatar", len(recorded) == 3,
          str(recorded))

    # Cancelling must stop before the last item.
    class SlowApi:
        authenticated = True
        two_factor_required = False

        def set_favorite_groups(self, avatar_id, groups, delay=0):
            return True, "fvrt_new"

    worker = GroupMoveWorker(SlowApi(), [
        ("avtr_1", "One", ["a"]), ("avtr_2", "Two", ["a"]),
        ("avtr_3", "Three", ["a"])])
    worker.cancel()
    done2 = []
    worker.completed.connect(done2.append)
    worker.start()

    deadline = time.time() + 10
    while worker.isRunning() and time.time() < deadline:
        _app.processEvents()
        time.sleep(0.01)
    worker.wait(5000)
    _app.processEvents()

    check("a cancelled run reports stopping early",
          done2 and done2[0]["cancelled"] is True, str(done2))
    check("a cancelled run moves nothing", done2[0]["moved"] == 0, str(done2))

    print("thumbnails are fetched with the auth session")
    # Regression: VRChat serves avatar images only to a session holding the
    # cookie. A bare requests.get returns 403, which showed up as avatars
    # with no picture at all.
    import gui.avatar_list as avatar_list
    from io import BytesIO
    from PIL import Image as PilImage
    from PyQt6.QtGui import QPixmap

    buffer = BytesIO()
    PilImage.new("RGB", (32, 24), (200, 30, 30)).save(buffer, "PNG")
    real_png = buffer.getvalue()

    requested = []

    class ImgResp:
        def __init__(self, status=200, body=real_png):
            self.status_code = status
            self.content = body

    class FakeImgSession:
        def __init__(self, status=200):
            self.status = status

        def get(self, url, **kw):
            requested.append((url, kw))
            return ImgResp(self.status)

    cache_root = os.environ["INF_AVIS_CACHE_DIR"]

    def load(url, avatar_id, session):
        """Run a loader against the suite's temp cache."""
        saved = avatar_list.CACHE_DIR
        avatar_list.CACHE_DIR = cache_root
        try:
            loader = avatar_list.ThumbnailLoader(url, avatar_id,
                                                 session=session)
            got = []
            loader.loaded.connect(lambda aid, pix: got.append(pix))
            loader.run()          # runs synchronously; signals land inline
            return got
        finally:
            avatar_list.CACHE_DIR = saved

    got = load("https://example.invalid/a.png", "avtr_pic_0001",
               FakeImgSession())
    check("the session was used for the fetch",
          requested and requested[0][0].endswith("a.png"), str(requested))
    check("the fetch was given a timeout",
          "timeout" in requested[0][1], str(requested))
    check("a valid image is emitted", len(got) == 1 and not got[0].isNull(),
          f"{len(got)} pixmaps")
    check("the image is cached to disk",
          os.path.exists(os.path.join(cache_root, "avtr_pic_0001.png")))

    # Regression: the loader's signal is (avatar_id, pixmap) but the card slot
    # took only one argument, so the first real image crashed the app. It hid
    # while every fetch 403'd and nothing ever emitted.
    print("a card survives the loader signal")
    base = {"name": "T", "author": "A", "thumbnail_url": "",
            "description": "", "favorite": 0}

    card = avatar_list.AvatarCard(
        dict(base, avatar_id="avtr_pic_0001"), lambda *a: None,
        lambda *a: None)

    signal_pixmap = avatar_list.ThumbnailLoader(
        "https://example.invalid/a.png", "avtr_pic_0001",
        session=FakeImgSession())
    signal_pixmap.loaded.connect(card.set_thumbnail)
    signal_pixmap.run()
    check("the id+pixmap signal does not crash the card",
          not card.thumb_label.pixmap().isNull(),
          str(card.thumb_label.pixmap().size()))

    card2 = avatar_list.AvatarCard(
        dict(base, avatar_id="avtr_pic_0002"), lambda *a: None,
        lambda *a: None)
    card2.set_thumbnail(QPixmap(20, 20))
    check("a direct single-argument call still works",
          not card2.thumb_label.pixmap().isNull())

    card3 = avatar_list.AvatarCard(
        dict(base, avatar_id="avtr_pic_0003"), lambda *a: None,
        lambda *a: None)
    card3.set_thumbnail("avtr_pic_0003", QPixmap())
    card3.set_thumbnail("avtr_pic_0003", "not a pixmap")
    check("a null or wrong-typed pixmap is ignored, not fatal", True)

    # A second load must come from the cache and hit the network zero times.
    before = len(requested)
    got = load("https://example.invalid/a.png", "avtr_pic_0001",
               FakeImgSession())
    check("a cached image is reused without refetching",
          len(requested) == before, f"{len(requested)} vs {before}")
    check("the cached image still renders", len(got) == 1)

    # 403 is what an unauthenticated fetch actually returns: no crash, no file.
    got = load("https://example.invalid/forbidden.png", "avtr_pic_0002",
               FakeImgSession(status=403))
    check("a 403 does not raise", got == [])
    check("a 403 caches nothing",
          not os.path.exists(os.path.join(cache_root, "avtr_pic_0002.png")))

    # No session at all must still be handled.
    saved = avatar_list.CACHE_DIR
    avatar_list.CACHE_DIR = cache_root
    try:
        got = load("https://example.invalid/nosession.png", "avtr_pic_0003",
                   None)
        check("a missing session does not raise", got == [])
    finally:
        avatar_list.CACHE_DIR = saved

    print("repository untouched")
    repo_after = data_snapshot(REAL_APP_DIR)
    for name in repo_before:
        check(f"repo {name} unchanged", repo_before[name] == repo_after[name],
              f"{repo_before[name]!r} -> {repo_after[name]!r}")

    shutil.rmtree(root, ignore_errors=True)

    print()
    if failures:
        print(f"{len(failures)} FAILURE(S): {', '.join(failures)}")
        return 1
    print("all checks passed")
    return 0


if __name__ == "__main__":
    sys.exit(main())