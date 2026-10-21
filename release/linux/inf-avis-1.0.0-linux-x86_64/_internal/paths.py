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

# In a PyInstaller bundle, __file__ points to the temp extraction dir.
# Use sys.executable to find the real app location when frozen.
if getattr(sys, 'frozen', False):
    APP_DIR = Path(sys.executable).resolve().parent
else:
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


# VRCX discovery removed in favor of direct VRChat imports

# --------------------------------------------------------------------------
# End
# --------------------------------------------------------------------------