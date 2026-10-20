"""Headless smoke test: builds the real MainWindow against a throwaway copy of
the app, so it exercises path resolution, the database and the widgets.

    QT_QPA_PLATFORM=offscreen python3 tests/smoke_test.py

The app tree is copied to a scratch directory first. Running the real tree would
be wrong: paths.migrate_legacy() relocates files relative to the directory
holding paths.py, so the real avatar_library.db and session.json would be moved
out of the repository. The copy keeps APP_DIR inside the scratch tree.
"""

import os
import hashlib
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

REAL_APP_DIR = Path(__file__).resolve().parent.parent

# Never copied: caches, local data, and the VRChat session cookie.
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


def scratch_app():
    root = Path(tempfile.mkdtemp(prefix="infavis-smoke-"))
    app = root / "app"
    shutil.copytree(REAL_APP_DIR, app, ignore=EXCLUDE)
    return root, app


def data_snapshot(directory):
    """Fingerprint of a directory's local data files.

    Compared before and after the run. These files may legitimately be absent,
    because a first launch migrates them out of the source tree, so the test
    asserts they are left exactly as it found them rather than expecting them
    to exist.
    """
    snapshot = {}
    for name in ("session.json", "avatar_library.db"):
        path = directory / name
        snapshot[name] = hashlib.sha256(path.read_bytes()).hexdigest() if path.is_file() else None
    cache = directory / "cache"
    snapshot["cache"] = sorted(p.name for p in cache.iterdir()) if cache.is_dir() else None
    return snapshot


def main():
    root, app = scratch_app()
    sys.path.insert(0, str(app))

    # Taken before anything runs, so the comparison at the end catches the test
    # relocating or rewriting the user's own data.
    repo_before = data_snapshot(REAL_APP_DIR)

    # Every location is pinned inside the scratch tree.
    os.environ["HOME"] = str(root / "home")
    os.environ["INF_AVIS_DATA_DIR"] = str(root / "data")
    os.environ["INF_AVIS_CONFIG_DIR"] = str(root / "config")
    os.environ["INF_AVIS_CACHE_DIR"] = str(root / "cache")

    from PyQt6.QtWidgets import QApplication
    from PyQt6.QtCore import Qt

    import paths
    import database as db
    from gui.main_window import MainWindow

    app_ = QApplication(sys.argv)

    # Guard: if this ever fails, the test is about to write to the real repo.
    check("running against a scratch copy", paths.APP_DIR == app,
          f"APP_DIR is {paths.APP_DIR}")

    print("paths")
    check("data dir is the override", str(paths.db_path()) ==
          str(root / "data" / "avatar_library.db"), str(paths.db_path()))
    check("session path is the override", str(paths.session_path()) ==
          str(root / "config" / "session.json"), str(paths.session_path()))
    paths.ensure_dirs()
    check("data dir created", paths.data_dir().is_dir())
    check("cache dir created", paths.cache_dir().is_dir())
    config_mode = paths.config_dir().stat().st_mode & 0o777
    check("config dir is owner-only", config_mode == 0o700, oct(config_mode))
    check("config dir holds no db", not (paths.config_dir() / "avatar_library.db").exists())

    # A directory left behind by an older build must be tightened, not trusted.
    paths.config_dir().chmod(0o777)
    paths.ensure_dirs()
    tightened = paths.config_dir().stat().st_mode & 0o777
    check("loose config dir is tightened", tightened == 0o700, oct(tightened))

    # session.json must not be world-readable: it is a live auth cookie.
    paths.session_path().write_text('{"cookies": {}, "current_user": null}')
    paths.protect_session_file()
    session_mode = paths.session_path().stat().st_mode & 0o777
    check("session file is owner-only", session_mode == 0o600, oct(session_mode))

    print("fonts")
    from gui.avatar_list import ui_family, mono_family
    check("ui font resolved on this system", bool(ui_family()), "no candidate installed")
    check("mono font resolved on this system", bool(mono_family()), "no candidate installed")

    print("database")
    avatar_id = "avtr_00000000-0000-0000-0000-000000000000"
    db.add_avatar(avatar_id, name="Test Avatar", author="tester")
    cat_id = db.create_category("Snaz")
    check("category created", cat_id is not None)
    check("duplicate category rejected", db.create_category("Snaz") is None)
    check("avatar stored", db.get_avatar(avatar_id) is not None)
    db.add_avatar_to_category(avatar_id, cat_id)
    check("category has one avatar", db.get_category_avatar_count(cat_id) == 1)
    check("category filter works", len(db.get_all_avatars(category_id=cat_id)) == 1)
    check("search works", len(db.get_all_avatars(search="Test")) == 1)
    check("empty search returns everything", len(db.get_all_avatars()) == 1)

    print("window")
    window = MainWindow()
    window.show()
    app_.processEvents()
    check("window created", window is not None)
    check("window has a title", bool(window.windowTitle()))
    check("avatar grid populated", window.avatar_list.grid.count() >= 1,
          f"count={window.avatar_list.grid.count()}")
    check("category appears in sidebar", window.sidebar.list.count() >= 1,
          f"count={window.sidebar.list.count()}")

    # VRCX discovery must not explode when nothing is installed.
    found = paths.find_vrcx_databases()
    check("vrcx discovery returns a list", isinstance(found, list))
    check("choose_vrcx_db reachable", callable(window._choose_vrcx_db))

    # Resizing used to rebuild every card; it must not raise now.
    window.resize(1200, 800)
    app_.processEvents()
    check("resize survives", True)

    window.close()
    app_.processEvents()

    print("repository untouched")
    repo_after = data_snapshot(REAL_APP_DIR)
    for name in repo_before:
        check(f"repo {name} unchanged", repo_before[name] == repo_after[name],
              f"{repo_before[name]!r} -> {repo_after[name]!r}")
    check("repo has no leftover cache dir",
          not (REAL_APP_DIR / "cache").exists() or repo_before["cache"] is not None)

    shutil.rmtree(root, ignore_errors=True)

    print()
    if failures:
        print(f"{len(failures)} FAILURE(S): {', '.join(failures)}")
        return 1
    print("all checks passed")
    return 0


if __name__ == "__main__":
    sys.exit(main())