"""Platform-correct filesystem locations for INF Avis.

Data no longer lives next to main.py. The app has to keep working when it is
installed somewhere read-only (distro package, Flatpak, Nix store) and when the
repository is cloned by someone other than the person who ran it first.

Every location can be overridden, which is what the tests and the portable
build use:

    INF_AVIS_DATA_DIR    database
    INF_AVIS_CONFIG_DIR  session cookie
    INF_AVIS_CACHE_DIR   thumbnail cache
    INF_AVIS_PORTABLE=1  keep everything inside the source tree (old layout)
"""

import os
import shutil
import sys
from pathlib import Path

APP_NAME = "INF Avis"
APP_DIR = Path(__file__).resolve().parent

_TRUTHY = {"1", "true", "yes", "on"}
_migration_attempted = False


# --------------------------------------------------------------------------
# location helpers
# --------------------------------------------------------------------------

def _override(var):
    raw = os.environ.get(var, "").strip()
    return Path(raw).expanduser() if raw else None


def _xdg(var, fallback):
    """XDG base directory. The spec says to ignore a non-absolute value."""
    raw = os.environ.get(var, "").strip()
    if raw:
        base = Path(raw).expanduser()
        if base.is_absolute():
            return base
    return Path.home() / fallback


def _portable():
    return os.environ.get("INF_AVIS_PORTABLE", "").strip().lower() in _TRUTHY


def data_dir():
    override = _override("INF_AVIS_DATA_DIR")
    if override is not None:
        return override
    if _portable():
        return APP_DIR
    if sys.platform == "darwin":
        return Path.home() / "Library" / "Application Support" / APP_NAME
    if os.name == "nt":
        base = os.environ.get("LOCALAPPDATA", "").strip() or str(Path.home() / "AppData" / "Local")
        return Path(base) / APP_NAME
    return _xdg("XDG_DATA_HOME", ".local/share") / APP_NAME


def config_dir():
    override = _override("INF_AVIS_CONFIG_DIR")
    if override is not None:
        return override
    if _portable():
        return APP_DIR
    if sys.platform == "darwin":
        return Path.home() / "Library" / "Preferences" / APP_NAME
    if os.name == "nt":
        base = os.environ.get("APPDATA", "").strip() or str(Path.home() / "AppData" / "Roaming")
        return Path(base) / APP_NAME
    return _xdg("XDG_CONFIG_HOME", ".config") / APP_NAME


def cache_dir():
    override = _override("INF_AVIS_CACHE_DIR")
    if override is not None:
        return override
    if _portable():
        return APP_DIR / "cache"
    if sys.platform == "darwin":
        return Path.home() / "Library" / "Caches" / APP_NAME
    if os.name == "nt":
        base = os.environ.get("LOCALAPPDATA", "").strip() or str(Path.home() / "AppData" / "Local")
        return Path(base) / APP_NAME / "cache"
    return _xdg("XDG_CACHE_HOME", ".cache") / APP_NAME


def db_path():
    return data_dir() / "avatar_library.db"


def session_path():
    return config_dir() / "session.json"


# --------------------------------------------------------------------------
# creation and one-time migration
# --------------------------------------------------------------------------

def _makedirs(path, mode):
    path.mkdir(parents=True, exist_ok=True)
    # mkdir()'s mode is masked by umask, and a directory left behind by an older
    # build may have looser permissions than we want, so set it every time.
    if os.name != "nt":
        try:
            path.chmod(mode)
        except OSError:
            pass


def migrate_legacy():
    """Move pre-1.0 files out of the source tree into the platform locations.

    Returns the destination of everything that was moved. Does nothing if the
    new location already holds data, so it is safe to call on every start.
    """
    global _migration_attempted
    if _migration_attempted or _portable():
        return []
    if APP_DIR in (data_dir(), config_dir(), cache_dir()):
        return []
    _migration_attempted = True

    moved = []

    for legacy_name, destination in (
        ("avatar_library.db", db_path()),
        ("session.json", session_path()),
    ):
        source = APP_DIR / legacy_name
        if source.is_file() and not destination.exists():
            destination.parent.mkdir(parents=True, exist_ok=True)
            shutil.move(str(source), str(destination))
            moved.append(destination)

    legacy_cache = APP_DIR / "cache"
    if legacy_cache.is_dir() and not legacy_cache.is_symlink():
        destination = cache_dir()
        destination_empty = not destination.is_dir() or not any(destination.iterdir())
        if destination_empty:
            destination.parent.mkdir(parents=True, exist_ok=True)
            shutil.copytree(legacy_cache, destination, dirs_exist_ok=True)
            shutil.rmtree(legacy_cache, ignore_errors=True)
            moved.append(destination)

    return moved


def ensure_dirs():
    migrate_legacy()
    _makedirs(data_dir(), 0o755)
    _makedirs(cache_dir(), 0o755)
    # Holds the VRChat session cookie, so keep it owner-only.
    _makedirs(config_dir(), 0o700)


def protect_session_file():
    """Drop group/other bits from the session cookie (no-op on Windows)."""
    if os.name == "nt":
        return
    try:
        session_path().chmod(0o600)
    except OSError:
        pass


# --------------------------------------------------------------------------
# VRCX discovery
# --------------------------------------------------------------------------

VRCX_DB_NAME = "VRCX.sqlite3"


def _windows_vrcx_dirs(root):
    """VRCX locations under a Wine or Proton prefix rooted at `root`.

    Proton puts the prefix under compatdata/<appid>/pfx while Bottles uses
    drive_c directly, and both have an optional extra level in front, so the
    obvious patterns are all tried. Depth stays bounded on purpose: a full
    recursive walk of a Proton prefix is slow.
    """
    directories = []
    for appdata in ("Local", "Roaming"):
        for pattern in (
            f"drive_c/users/*/AppData/{appdata}/VRCX",
            f"pfx/drive_c/users/*/AppData/{appdata}/VRCX",
            f"*/drive_c/users/*/AppData/{appdata}/VRCX",
            f"*/pfx/drive_c/users/*/AppData/{appdata}/VRCX",
        ):
            directories.extend(root.glob(pattern))
    return directories


def _vrcx_search_dirs():
    home = Path.home()
    directories = []

    if sys.platform == "darwin":
        directories.append(home / "Library" / "Application Support" / "VRCX")
    elif os.name == "nt":
        for var in ("APPDATA", "LOCALAPPDATA"):
            base = os.environ.get(var, "").strip()
            if base:
                directories.append(Path(base) / "VRCX")
    else:
        directories += [
            _xdg("XDG_DATA_HOME", ".local/share") / "VRCX",
            _xdg("XDG_CONFIG_HOME", ".config") / "VRCX",
            home / ".config" / "VRCX",
            home / ".local" / "share" / "VRCX",
        ]

    # VRCX ships as a Windows binary, so on Linux and macOS it lives inside a
    # Wine or Proton prefix. Several Steam roots are checked because the
    # default install path is not always ~/.steam.
    if os.name != "nt":
        prefixes = [
            home / ".wine",
            home / ".steam" / "steam" / "steamapps" / "compatdata",
            home / ".local" / "share" / "Steam" / "steamapps" / "compatdata",
            home / ".var" / "app" / "com.valvesoftware.Steam"
                 / "data" / "Steam" / "steamapps" / "compatdata",
            home / ".var" / "app" / "com.usebottles.bottles" / "data" / "bottles" / "bottles",
        ]
        for root in prefixes:
            if not root.is_dir():
                continue
            if root.name in ("compatdata", "bottles"):
                # One directory per installed game or bottle.
                for child in sorted(p for p in root.iterdir() if p.is_dir()):
                    directories.extend(_windows_vrcx_dirs(child))
            else:
                directories.extend(_windows_vrcx_dirs(root))

    return directories


def find_vrcx_databases():
    """Every VRCX.sqlite3 we can find, most recently modified first."""
    found = []
    seen = set()

    for directory in _vrcx_search_dirs():
        for name in (VRCX_DB_NAME, VRCX_DB_NAME.lower()):
            candidate = directory / name
            if not candidate.is_file():
                continue
            resolved = candidate.resolve()
            if resolved in seen:
                continue
            seen.add(resolved)
            found.append(resolved)

    found.sort(key=lambda p: p.stat().st_mtime, reverse=True)
    return found