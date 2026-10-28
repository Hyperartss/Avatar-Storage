# Avatar Storage

A small desktop app that keeps your VRChat avatars in one place, on your own computer. Browse, sort and search them without opening VRChat. Everything lives in a local database, so it works offline.

## Download

Grab the latest build from the [Releases page](https://github.com/Hyperartss/Avatar-Storage/releases), unpack it and run:

- **Linux:** `inf-avis-<version>-linux-x86_64.tar.gz` → `./inf-avis`
- **Windows:** `inf-avis-<version>-win64.zip` → `inf-avis.exe`

If the Linux build closes without a window, a system library is missing:

```bash
sudo apt install libxcb-cursor0 libxkbcommon-x11-0 libegl1 libgl1 libdbus-1-3 libfontconfig1
```

## Adding avatars

Sign in first with `VRChat API → Login…` (two-factor codes go in `VRChat API → Verify Two-Factor Code…`), then use `File → Import from VRChat Website…` and paste any of these:

- `https://vrchat.com/home/avatar/avtr_...`
- `https://vrchat.com/home/user/usr_...`, which brings in that person's public avatars
- a bare `avtr_...` or `usr_...` ID, several at once if you like

Importing an avatar again updates its details and keeps your notes, categories and favourites.

## Favourites

`File → Import Favourites from VRChat…` pulls your favourites in, and can make a local category for each VRChat group along the way. To move avatars, right-click one and choose **Move to VRChat Favourite Group…**, or use `File → Move Favourites Between Groups…` for a batch. You'll see every change before it's applied.

VRChat has no edit call for favourites, so a move removes and re-adds the avatar. For a moment it isn't favourited, which is expected.

## Organising

Categories live in the sidebar and can be dragged around. The star favourites an avatar, the folder button moves it, and any notes you write survive re-imports. Search covers names, authors, descriptions and notes; sort by name, author, date added, stats or category. Themes and a compact card layout are in `File → Settings…`.

## Your files

| | Linux | Windows |
|---|---|---|
| Database | `~/.local/share/INF Avis/` | `%LOCALAPPDATA%\INF Avis\` |
| Session | `~/.config/INF Avis/` | `%APPDATA%\INF Avis\` |
| Thumbnails | `~/.cache/INF Avis/` | `%LOCALAPPDATA%\INF Avis\cache\` |

The folder names still say `INF Avis` so existing libraries keep working. To keep everything next to the app instead, start it with `INF_AVIS_PORTABLE=1`.

## Build from source

Python 3.10+, only if you want to change something.

```bash
./setup.sh && ./run.sh        # Linux
```

On Windows, run `setup.bat` then `run.bat`. To make a release yourself, use `./build_linux.sh [version]` or `.\build_windows.ps1 [version]`.

## Licence

MIT. AI assistants were used along the way.
