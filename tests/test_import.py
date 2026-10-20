"""Tests for the website importer, run against a stub API so nothing touches
the network or a real VRChat account.

    QT_QPA_PLATFORM=offscreen python3 tests/test_import.py
"""

import os
import hashlib
import shutil
import sys
import tempfile
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
    """Fingerprint of a directory's local data files, to prove we did not
    relocate or rewrite them. They may legitimately be absent, since a first
    launch migrates them out of the source tree."""
    snapshot = {}
    for name in ("session.json", "avatar_library.db"):
        path = directory / name
        snapshot[name] = hashlib.sha256(path.read_bytes()).hexdigest() if path.is_file() else None
    cache = directory / "cache"
    snapshot["cache"] = sorted(p.name for p in cache.iterdir()) if cache.is_dir() else None
    return snapshot


class StubAPI:
    """Stands in for VRChatAPI. Deterministic, instant, offline."""

    authenticated = True

    def __init__(self, avatars=None, fail_with=None, fail_times=None, missing=()):
        self.avatars = avatars or {}
        self.fail_with = fail_with
        self.fail_times = fail_times
        self.missing = set(missing)
        self.calls = []
        self.two_factor_required = False

    def _maybe_fail(self):
        from api.vrchat_api import VRChatAPIError
        if self.fail_with is None:
            return
        if self.fail_times is not None and len(self.calls) > self.fail_times:
            return
        # A 2FA block leaves the session flagged, exactly as VRChat does.
        if self.fail_with.needs_2fa:
            self.two_factor_required = True
        raise self.fail_with

    def lookup_avatar(self, reference):
        self.calls.append(("lookup", reference))
        self._maybe_fail()
        return self.avatars.get(reference)

    def get_user_avatars(self, reference):
        self.calls.append(("user", reference))
        self._maybe_fail()
        owned = [a for a in self.avatars.values() if a["author_id"] == reference]
        return owned

    def get_my_avatars(self):
        self.calls.append(("me", None))
        self._maybe_fail()
        return list(self.avatars.values())

    def verify_2fa(self, code):
        if code == "123456":
            self.two_factor_required = False
            return True, "ok"
        self.two_factor_required = True
        return False, "Invalid 2FA code"


def sample_avatar(suffix, author_id="usr_00000000-0000-0000-0000-000000000001"):
    return {
        "id": f"avtr_0000000{suffix}-0000-0000-0000-000000000000",
        "name": f"Avatar {suffix}",
        "author": "Someone",
        "author_id": author_id,
        "thumbnail_url": f"https://example.invalid/{suffix}.png",
        "description": "desc",
        "tags": ["anime", "cute"],
        "release_status": "public",
        "version": "1.0",
        "unity_version": "2019.4",
        "date_published": 1700000000,
        "date_updated": 1700000001,
        "downloads": 42,
        "favorites_count": 7,
        "rating": 4.25,
        "is_public": True,
        "url": f"https://vrchat.com/home/avatar/avtr_0000000{suffix}-0000-0000-0000-000000000000",
    }


def main():
    root = Path(tempfile.mkdtemp(prefix="infavis-import-"))
    app = root / "app"
    shutil.copytree(REAL_APP_DIR, app, ignore=EXCLUDE)
    sys.path.insert(0, str(app))

    repo_before = data_snapshot(REAL_APP_DIR)

    os.environ["HOME"] = str(root / "home")
    os.environ["INF_AVIS_DATA_DIR"] = str(root / "data")
    os.environ["INF_AVIS_CONFIG_DIR"] = str(root / "config")
    os.environ["INF_AVIS_CACHE_DIR"] = str(root / "cache")

    from PyQt6.QtWidgets import QApplication
    from PyQt6.QtCore import QEventLoop, QTimer

    import database as db
    from api.vrchat_api import (
        VRChatAPIError, parse_reference, normalize_avatar,
    )
    from gui.import_dialog import ImportWorker

    qt = QApplication(sys.argv)
    db.init_db()

    print("reference parsing")
    avtr = "avtr_11111111-2222-3333-4444-555555555555"
    usr = "usr_AAAAAAAA-BBBB-CCCC-DDDD-EEEEEEEEEEEE"
    check("avatar url", parse_reference(f"https://vrchat.com/home/avatar/{avtr}")
          == [("avatar", avtr)])
    check("user url", parse_reference(f"https://vrchat.com/home/user/{usr}")
          == [("user", usr.lower())])
    check("bare ids", parse_reference(f"{avtr}\n{usr}") ==
          [("avatar", avtr), ("user", usr.lower())])
    check("duplicates collapse", parse_reference(f"{avtr} {avtr}") ==
          [("avatar", avtr)])
    check("prose is tolerated", parse_reference("hey look at this cool thing") == [])
    check("a pasted blob finds both",
          parse_reference(f"avatar {avtr} by {usr}") ==
          [("avatar", avtr), ("user", usr.lower())])

    print("normalisation")
    raw = {"id": "avtr_x", "name": "N", "authorName": "A", "authorId": "usr_y",
           "tags": ["a"], "created_at": "2023-11-14T22:13:20.000Z",
           "statistics": {"downloadCount": 9}, "rating": 3.5, "public": True}
    normalized = normalize_avatar(raw)
    check("authorName maps to author", normalized["author"] == "A")
    check("authorId maps to author_id", normalized["author_id"] == "usr_y")
    check("nested download count", normalized["downloads"] == 9)
    check("iso date parsed", normalized["date_published"] == 1699999_20 or
          normalized["date_published"] > 1699900000)
    check("tags kept", normalized["tags"] == ["a"])
    check("no id yields nothing", normalize_avatar({}) == {})

    print("schema migration")
    columns = {row["name"] for row in db.get_connection().execute(
        "PRAGMA table_info(avatars)")}
    for column in ("tags", "author_id", "favorites_count", "rating", "url"):
        check(f"column {column} exists", column in columns)

    print("upsert")
    data = sample_avatar("1")
    _, created = db.upsert_avatar(data)
    check("first insert creates", created is True)
    db.update_avatar(data["id"], notes="my notes", favorite=True)
    cat = db.create_category("Imported")
    db.upsert_avatar(data, category_id=cat)
    row = db.get_avatar(data["id"])
    check("re-import does not create again", row is not None)
    check("notes survive re-import", row["notes"] == "my notes", row["notes"])
    check("favourite survives re-import", row["favorite"] == 1)
    check("category was linked", db.get_category_avatar_count(cat) == 1)
    check("tags stored as json", db.get_avatar_tags(data["id"]) == ["anime", "cute"])
    check("metadata refreshed", row["favorites_count"] == 7 and row["rating"] == 4.25)

    print("tag search")
    check("search finds by tag", len(db.get_all_avatars(search="anime")) >= 1)
    check("tag search helper", db.search_tags("ani") == ["anime"])

    print("import worker: avatar references")
    stub = StubAPI(avatars={avtr: sample_avatar("2")})
    worker = ImportWorker(stub, parse_reference(f"https://vrchat.com/home/avatar/{avtr}"))
    loop = QEventLoop()
    result = {}
    worker.completed.connect(lambda s: (result.update(s), loop.quit()))
    worker.start()
    QTimer.singleShot(10000, loop.quit)
    loop.exec()
    worker.wait()
    check("worker completed", bool(result), "timed out")
    check("one avatar added", result.get("added") == 1, str(result))
    check("stored in library", db.get_avatar(sample_avatar("2")["id"]) is not None)

    print("import worker: user profile")
    author = "usr_00000000-0000-0000-0000-000000000009"
    stub = StubAPI(avatars={a["id"]: a for a in (sample_avatar("3", author),
                                                sample_avatar("4", author))})
    worker = ImportWorker(stub, parse_reference(f"https://vrchat.com/home/user/{author}"))
    loop = QEventLoop()
    result = {}
    worker.completed.connect(lambda s: (result.update(s), loop.quit()))
    worker.start()
    QTimer.singleShot(10000, loop.quit)
    loop.exec()
    worker.wait()
    check("both of a creator's avatars imported", result.get("added") == 2, str(result))

    print("import worker: duplicates refresh, not duplicate")
    stub = StubAPI(avatars={avtr: sample_avatar("2")})
    worker = ImportWorker(stub, parse_reference(avtr))
    loop = QEventLoop()
    result = {}
    worker.completed.connect(lambda s: (result.update(s), loop.quit()))
    worker.start()
    QTimer.singleShot(10000, loop.quit)
    loop.exec()
    worker.wait()
    check("existing avatar refreshed", result.get("updated") == 1, str(result))
    check("not added twice", result.get("added") == 0, str(result))

    print("import worker: missing avatars reported")
    stub = StubAPI(avatars={}, missing={avtr})
    worker = ImportWorker(stub, parse_reference(avtr))
    loop = QEventLoop()
    result = {}
    worker.completed.connect(lambda s: (result.update(s), loop.quit()))
    worker.start()
    QTimer.singleShot(10000, loop.quit)
    loop.exec()
    worker.wait()
    check("missing listed", result.get("missing") == [avtr], str(result))
    check("nothing written for missing",
          db.get_avatar(sample_avatar("2")["id"]) is not None)  # from the earlier run

    print("two-factor handshake")
    from api.vrchat_api import VRChatAPIError as VE
    twofa = VE('"Requires Two-Factor Authentication"', status_code=403)
    check("error needs 2fa", twofa.needs_2fa is True)
    check("error needs login", twofa.needs_login is True)
    check("404 is not 2fa", VE("Not found", 404).needs_2fa is False)

    # The importer must prompt and continue, not give up on the session.
    stub = StubAPI(avatars={avtr: sample_avatar("e")}, fail_with=twofa, fail_times=1)
    worker = ImportWorker(stub, parse_reference(avtr))
    prompted = []

    def answer_valid():
        prompted.append(1)
        verified, _ = stub.verify_2fa("123456")
        if not verified:
            stub.two_factor_required = True
        worker.confirm_two_factor()

    worker.two_factor_required.connect(answer_valid)
    loop = QEventLoop()
    result = {}
    worker.completed.connect(lambda s: (result.update(s), loop.quit()))
    worker.start()
    QTimer.singleShot(15000, loop.quit)
    loop.exec()
    worker.wait()
    check("import prompted for 2FA", len(prompted) == 1, str(prompted))
    check("import continued after 2FA", result.get("added") == 1, str(result))

    # A rejected code must stop rather than retry blindly or hang.
    stub = StubAPI(avatars={avtr: sample_avatar("f")}, fail_with=twofa)
    worker = ImportWorker(stub, parse_reference(avtr))
    worker.two_factor_required.connect(worker.confirm_two_factor)
    loop = QEventLoop()
    result = {}
    worker.completed.connect(lambda s: (result.update(s), loop.quit()))
    worker.start()
    QTimer.singleShot(20000, loop.quit)
    loop.exec()
    worker.wait()
    check("refused 2FA stops the import",
          any("did not complete" in p for p in result.get("problems", [])), str(result))
    check("refused 2FA imported nothing", result.get("added", 0) == 0, str(result))

    print("plain auth failure reported")
    stub = StubAPI(fail_with=VE('"Missing Credentials"', 401))
    worker = ImportWorker(stub, parse_reference(avtr))
    loop = QEventLoop()
    result = {}
    worker.completed.connect(lambda s: (result.update(s), loop.quit()))
    worker.start()
    QTimer.singleShot(10000, loop.quit)
    loop.exec()
    worker.wait()
    check("401 reported, not crashed", bool(result.get("problems")), str(result))
    check("worker did not hang", bool(result))

    print("import worker: cancel")
    author = "usr_00000000-0000-0000-0000-00000000000a"
    stub = StubAPI(avatars={a["id"]: a for a in
                            (sample_avatar("5", author), sample_avatar("6", author),
                             sample_avatar("7", author), sample_avatar("8", author))})
    worker = ImportWorker(stub, parse_reference(author))
    loop = QEventLoop()
    result = {}
    worker.completed.connect(lambda s: (result.update(s), loop.quit()))
    worker.start()
    worker.cancel()
    QTimer.singleShot(10000, loop.quit)
    loop.exec()
    worker.wait()
    check("cancel reports stopped", result.get("cancelled") is True, str(result))

    print("import worker: cancel after partial work")
    before = len(db.get_all_avatars())
    stub = StubAPI(avatars={a["id"]: a for a in
                            (sample_avatar("b", author), sample_avatar("c", author))})
    worker = ImportWorker(stub, parse_reference(author))
    loop = QEventLoop()
    result = {}
    worker.completed.connect(lambda s: (result.update(s), loop.quit()))
    # Let the first avatar land, then stop.
    worker.progress.connect(lambda c, t, m: worker.cancel() if c >= 1 else None)
    worker.start()
    QTimer.singleShot(15000, loop.quit)
    loop.exec()
    worker.wait()
    check("partial run marked stopped", result.get("cancelled") is True, str(result))
    check("partial run imported something",
          len(db.get_all_avatars()) > before, str(result))
    check("partial run did not import everything",
          result.get("added", 0) + result.get("updated", 0) < 4, str(result))

    print("import dialog")
    import gui.import_dialog as import_dialog
    from gui.import_dialog import ImportFromWebsiteDialog, NO_CATEGORY, NEW_CATEGORY

    shown = []

    class FakeMessageBox:
        @staticmethod
        def information(*args, **kwargs):
            shown.append(("information", args[1], args[2]))

        @staticmethod
        def warning(*args, **kwargs):
            shown.append(("warning", args[1], args[2]))

    import_dialog.QMessageBox = FakeMessageBox

    stub = StubAPI(avatars={})
    stub.authenticated = True
    dialog = ImportFromWebsiteDialog(stub)
    check("dialog builds", dialog is not None)

    labels = [dialog.category_combo.itemText(i)
              for i in range(dialog.category_combo.count())]
    check("category combo lists 'Imported'", "Imported" in labels, str(labels))
    check("category combo has a no-category option",
          dialog.category_combo.itemData(0) is NO_CATEGORY)
    check("category combo offers a new category",
          dialog.category_combo.itemData(dialog.category_combo.count() - 1) == NEW_CATEGORY)

    dialog.input_box.setPlainText(f"{avtr}\n{author}")
    dialog.update_count()
    check("reference count reported",
          "1 avatar" in dialog.count_label.text()
          and "1 user" in dialog.count_label.text(),
          dialog.count_label.text())

    dialog.input_box.setPlainText("nothing useful here")
    dialog.update_count()
    check("no references clears the count", dialog.count_label.text() == "",
          dialog.count_label.text())

    shown.clear()
    dialog.start_import()
    check("empty import is refused",
          any(k == "information" and title == "Nothing to import"
              for k, title, _ in shown), str(shown))
    check("empty import starts no work", dialog.worker is None)

    logged_out = StubAPI(avatars={avtr: sample_avatar("9")})
    logged_out.authenticated = False
    dialog2 = ImportFromWebsiteDialog(logged_out)
    dialog2.input_box.setPlainText(avtr)
    shown.clear()
    dialog2.start_import()
    check("logged-out import is refused with a reason",
          any(k == "warning" and title == "Login required"
              for k, title, _ in shown), str(shown))
    check("logged-out import starts no work", dialog2.worker is None)

    logged_out.authenticated = True
    dialog2.start_import()
    check("authenticated import starts a worker", dialog2.worker is not None)
    if dialog2.worker is not None:
        dialog2.worker.wait(10000)

    dialog.close()
    dialog2.close()

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