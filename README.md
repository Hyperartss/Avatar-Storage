# INF Avis

A desktop avatar library for VRChat. Built to let you sort, categorize, and favorite avatars locally — same idea as VRCX, but cross-platform and without the game attached.

## What it does

- **Import avatars** from VRChat (by ID, profile URL, or your favorites list) or from a VRCX database
- **Organize with categories** — drag avatars onto category names in the sidebar, or use the folder button on a card
- **Favorite on VRChat** — the star button syncs your favorites to vrchat.com (handles groups, 2FA, rate limits)
- **Move favorites between VRChat groups** — bulk reassign with a clear preview of what changes
- **Search, sort, filter** — by name, author, date, stats, or category
- **Local notes** per avatar that survive re-imports
- **Dark mode**, compact density, and a handful of QoL toggles in Settings

Everything lives in a local SQLite database. Nothing touches the game client.

## Install & run (Linux)

```bash
./setup.sh     # creates .venv, installs deps
./run.sh
```

Requires Python 3.10+ and a few system libs (Qt's X11 backend):
```bash
# Debian / Ubuntu / Mint
sudo apt install libxcb-cursor0 libxkbcommon-x11-0 libegl1 libgl1 libdbus-1-3 libfontconfig1
```

On Wayland it works natively; force X11 with `QT_QPA_PLATFORM=xcb ./run.sh` if your compositor misbehaves.

### Portable mode
```bash
INF_AVIS_PORTABLE=1 ./run.sh
```
Keeps database, cache, and session inside the source tree.

## Where your data lives

| Thing | Linux | Windows | macOS |
|-------|-------|---------|-------|
| Database | `~/.local/share/INF Avis/` | `%LOCALAPPDATA%\INF Avis\` | `~/Library/Application Support/INF Avis/` |
| Session cookie | `~/.config/INF Avis/` | `%APPDATA%\INF Avis\` | `~/Library/Preferences/INF Avis/` |
| Thumbnails | `~/.cache/INF Avis/` | `%LOCALAPPDATA%\INF Avis\cache\` | `~/Library/Caches/INF Avis/` |

`XDG_DATA_HOME` / `XDG_CONFIG_HOME` / `XDG_CACHE_HOME` are respected. Config dir is `0700`, session file `0600` (it holds a live auth cookie).

## Importing from VRChat

`File → Import from VRChat Website…`

Paste anything you copied from vrchat.com:
- `https://vrchat.com/home/avatar/avtr_…`
- `https://vrchat.com/home/user/usr_…` (grabs all their public avatars)
- Bare `avtr_…` or `usr_…` IDs
- A whole selection at once; one per line not required

Pick a category to file them into (or create one inline). Re-importing refreshes name, author, thumbnail, tags, stats — **your notes, favorites, and categories stay untouched**.

You need to log in first. VRChat returns 401 even for public avatars.

## Importing from VRCX

`File → Import from VRCX…`

Searches the usual Wine/Proton/Bottles/flatpak Steam locations for `VRCX.sqlite3` and offers a file picker if not found. Imports avatars only; your local categories and notes are left alone.

## Favorites sync

`File → Import Favourites from VRChat…`

Pulls every avatar you've favorited on the website into the library. Options:
- Create a local category for each VRChat favorite group (synced on repeat runs)
- Mark imported avatars as favorites locally
- Refresh details for avatars already in the library (off by default, faster)

## Moving favorites between VRChat groups

`File → Move Favourites Between Groups…` or right-click a card → **Move to VRChat Favourite Group…**

This **writes to your VRChat account**. VRChat has no "edit favorite" endpoint — every change is remove-then-add, so each avatar is briefly absent from your favorites. The dialog spells out what it will do, logs per-avatar, and puts the favorite back if the re-add fails.

Group names matter: VRChat returns both a `name` (internal slug like `avatars1`) and a `displayName` (what you see, like `Mains`). The slug is what the API expects.

## Keyboard / mouse

- **Click** a card to select; **Shift/Ctrl+click** for ranges / additive selection
- **Drag a card** onto a sidebar category to file it; onto the ★ zone to favorite/unfavorite
- **Drag categories** in the sidebar to reorder (persisted)
- **Star button** = favorite on vrchat.com | **Folder button** = local categories

## Tests

```bash
QT_QPA_PLATFORM=offscreen python3 tests/smoke_test.py       # builds the real window
python3 tests/test_paths.py                                  # paths and VRCX discovery
QT_QPA_PLATFORM=offscreen python3 tests/test_import.py       # importer, stub API
QT_QPA_PLATFORM=offscreen python3 tests/test_favorites.py    # favorites sync, stub API
QT_QPA_PLATFORM=offscreen python3 tests/test_sorting.py      # sorting and filter state
```

All tests copy the app to a temp dir first (path migration relocates files relative to `paths.py`). None touch the network or a real VRChat session.

## Requirements

- Python 3.10+
- PyQt6 ≥ 6.6
- requests ≥ 2.31
- Pillow ≥ 10.0

## License

MIT — do whatever, but keep the license notice.