"""Tests for paths.py that need a controlled HOME:

    python3 tests/test_paths.py

Covers the one-time migration of the old next-to-main.py layout, which is the
part most likely to surprise someone upgrading.
"""

import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

TESTS_DIR = Path(__file__).resolve().parent
APP_DIR = TESTS_DIR.parent
PATHS_PY = APP_DIR / "paths.py"

failures = []


def check(label, condition, detail=""):
    if condition:
        print(f"  pass  {label}")
    else:
        print(f"  FAIL  {label} {detail}")
        failures.append(label)


def run_paths(snippet, home, env_extra=None):
    """Import a copy of paths.py from a scratch 'app dir' and run `snippet`."""
    env = {
        "PATH": os.environ.get("PATH", "/usr/bin:/bin"),
        "HOME": str(home),
        "PYTHONPATH": str(home / "app"),
        # XDG vars must not leak in from the calling shell.
        "XDG_DATA_HOME": "",
        "XDG_CONFIG_HOME": "",
        "XDG_CACHE_HOME": "",
    }
    if env_extra:
        env.update(env_extra)
    result = subprocess.run(
        [sys.executable, "-c", f"import paths\n{snippet}"],
        capture_output=True, text=True, env=env, cwd=str(home),
    )
    if result.returncode != 0:
        return None, result.stderr.strip()
    return result.stdout.strip(), ""


def make_legacy_tree(root):
    """A copy of paths.py plus the pre-1.0 files it should migrate."""
    app = root / "app"
    app.mkdir(parents=True)
    shutil.copy2(PATHS_PY, app / "paths.py")
    (app / "avatar_library.db").write_text("legacy db")
    (app / "session.json").write_text('{"cookies": {}}')
    cache = app / "cache"
    cache.mkdir()
    (cache / "avtr_test.png").write_bytes(b"not really a png")
    return app


def main():
    print("xdg defaults")
    root = Path(tempfile.mkdtemp(prefix="infavis-paths-"))
    home = root / "home"
    home.mkdir()
    shutil.copy2(PATHS_PY, home / "paths.py")
    out, err = run_paths("print(paths.data_dir())", home,
                         {"PYTHONPATH": str(home)})
    check("data dir follows XDG", out == str(home / ".local/share/INF Avis"),
          f"got {out} err={err}")

    out, _ = run_paths("print(paths.config_dir())", home, {"PYTHONPATH": str(home)})
    check("config dir follows XDG", out == str(home / ".config/INF Avis"), f"got {out}")

    out, _ = run_paths("print(paths.cache_dir())", home, {"PYTHONPATH": str(home)})
    check("cache dir follows XDG", out == str(home / ".cache/INF Avis"), f"got {out}")

    print("xdg env vars are honoured")
    out, _ = run_paths("print(paths.data_dir())", home,
                       {"PYTHONPATH": str(home), "XDG_DATA_HOME": str(home / "xdgdata")})
    check("XDG_DATA_HOME wins",
          out == str(home / "xdgdata/INF Avis"), f"got {out}")

    print("relative XDG value is ignored")
    out, _ = run_paths("print(paths.data_dir())", home,
                       {"PYTHONPATH": str(home), "XDG_DATA_HOME": "relative/path"})
    check("relative XDG_DATA_HOME falls back",
          out == str(home / ".local/share/INF Avis"), f"got {out}")

    print("portable mode")
    out, _ = run_paths("print(paths.data_dir(), paths.cache_dir())", home,
                       {"PYTHONPATH": str(home), "INF_AVIS_PORTABLE": "1"})
    check("portable keeps data beside the app",
          out == f"{home} {home / 'cache'}", f"got {out}")

    print("legacy migration")
    root2 = Path(tempfile.mkdtemp(prefix="infavis-migrate-"))
    home2 = root2 / "home"
    home2.mkdir()
    app = make_legacy_tree(home2)

    out, err = run_paths("print(paths.migrate_legacy())", home2)
    check("migration reports what moved",
          out == f"[PosixPath('{home2}/.local/share/INF Avis/avatar_library.db'), "
                 f"PosixPath('{home2}/.config/INF Avis/session.json'), "
                 f"PosixPath('{home2}/.cache/INF Avis')]", f"got {out} err={err}")

    check("db moved to data dir",
          (home2 / ".local/share/INF Avis/avatar_library.db").is_file())
    check("session moved to config dir",
          (home2 / ".config/INF Avis/session.json").is_file())
    check("thumbnail cache moved",
          (home2 / ".cache/INF Avis/avtr_test.png").is_file())
    check("db removed from app dir", not (app / "avatar_library.db").exists())
    check("session removed from app dir", not (app / "session.json").exists())
    check("old cache dir removed", not (app / "cache").exists())

    print("migration is idempotent")
    out, err = run_paths(
        "paths.migrate_legacy(); print(paths.migrate_legacy())", home2)
    check("second run moves nothing", out == "[]", f"got {out} err={err}")

    print("migration does not clobber existing data")
    data_dir = home2 / ".local/share/INF Avis"
    (data_dir / "avatar_library.db").write_text("newer db")
    out, err = run_paths("print(paths.migrate_legacy())", home2)
    check("existing db is not overwritten",
          (data_dir / "avatar_library.db").read_text() == "newer db"
          and out == "[]", f"got {out} err={err}")

    print("portable mode does not migrate")
    root3 = Path(tempfile.mkdtemp(prefix="infavis-portable-"))
    home3 = root3 / "home"
    home3.mkdir()
    app3 = make_legacy_tree(home3)
    out, err = run_paths("print(paths.migrate_legacy())", home3,
                         {"INF_AVIS_PORTABLE": "1"})
    check("portable mode leaves files alone",
          (app3 / "avatar_library.db").is_file() and out == "[]",
          f"got {out} err={err}")

    for directory in (root, root2, root3):
        shutil.rmtree(directory, ignore_errors=True)

    print()
    if failures:
        print(f"{len(failures)} FAILURE(S): {', '.join(failures)}")
        return 1
    print("all checks passed")
    return 0


if __name__ == "__main__":
    sys.exit(main())