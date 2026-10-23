# INF Avis

A lightweight desktop avatar library for VRChat. Sort, categorize, and favorite avatars locally — no game client required.

## Download

Grab the latest release from the [Releases page](https://github.com/Hyperartss/Avatar-Storage/releases).

- **Linux (x86_64):** `inf-avis-<version>-linux-x86_64.tar.gz` — extract and run `./inf-avis`
- **Windows (x64):** `inf-avis-<version>-win64.zip` — extract and run `inf-avis.exe`

## Features

- **Import** avatars from VRChat by ID, profile URL, or your favorites list
- **Organize** with drag-and-drop categories in the sidebar, or the folder button on a card
- **Sync favorites** with vrchat.com (supports groups, 2FA, and rate limits)
- **Move favorites between VRChat groups** with a preview of every change
- **Search, sort & filter** by name, author, date, stats, or category
- **Local notes** that persist across re-imports
- **Dark mode**, compact density, and QoL options in Settings

All data is stored locally in a SQLite database. Nothing touches the VRChat client.

## Usage

### Importing from VRChat

`File → Import from VRChat Website…` — paste any of the following from vrchat.com:

- `https://vrchat.com/home/avatar/avtr_...`
- `https://vrchat.com/home/user/usr_...` (imports all public avatars)
- Bare `avtr_...` or `usr_...` IDs (one or more)

You'll need to log in first. Re-importing refreshes details, but keeps your notes, favorites, and categories intact.

### Favorites sync

`File → Import Favourites from VRChat…` to pull all favorites from your account. You can optionally create local categories per VRChat favorite group and mark them as favorites locally.

### Moving favorites between groups

`File → Move Favourites Between Groups…` or right-click a card → **Move to VRChat Favourite Group…**

This writes to your VRChat account. Since VRChat has no edit endpoint, each avatar is removed and re-added (a brief moment where it's missing from favorites). The dialog shows a full preview before applying changes.

## Data location

| Type | Linux | Windows | macOS |
|---|---|---|---|
| Database | `~/.local/share/INF Avis/` | `%LOCALAPPDATA%\INF Avis\` | `~/Library/Application Support/INF Avis/` |
| Session cookie | `~/.config/INF Avis/` | `%APPDATA%\INF Avis\` | `~/Library/Preferences/INF Avis/` |
| Thumbnails | `~/.cache/INF Avis/` | `%LOCALAPPDATA%\INF Avis\cache\` | `~/Library/Caches/INF Avis/` |

On Linux, `XDG_DATA_HOME`, `XDG_CONFIG_HOME`, and `XDG_CACHE_HOME` are respected. The session file is kept with restrictive permissions (`0600`).

**Portable mode:** run with `INF_AVIS_PORTABLE=1` to keep everything next to the app.

## Build from source

### Linux

```bash
./setup.sh
./run.sh
```

Dependencies (Debian/Ubuntu/Mint): `libxcb-cursor0 libxkbcommon-x11-0 libegl1 libgl1 libdbus-1-3 libfontconfig1`

### Windows

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
python main.py
```

### Create a release build

```bash
# Linux
./build_linux.sh [version]

# Windows
.\build_windows.ps1 [version]
```

## Notes

- Requires Python 3.10+ and depends on PyQt6, requests, and Pillow.
- **AI was used in the making of this project.**

## License

[MIT](LICENSE)
