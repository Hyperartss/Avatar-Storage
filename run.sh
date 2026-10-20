#!/usr/bin/env bash
# Launch INF Avis, preferring the local virtualenv created by setup.sh.
set -euo pipefail
cd "$(dirname "$0")"

VENV="${VENV:-.venv}"

if [ -x "$VENV/bin/python" ]; then
    PYTHON="$VENV/bin/python"
elif command -v python3 >/dev/null 2>&1; then
    PYTHON="python3"
else
    echo "error: no python3 found. Install Python 3.10+ first." >&2
    exit 1
fi

if ! "$PYTHON" -c "import PyQt6, requests, PIL" >/dev/null 2>&1; then
    echo "error: missing dependencies for $PYTHON" >&2
    echo "       run ./setup.sh to create a virtualenv with everything installed," >&2
    echo "       or: $PYTHON -m pip install -r requirements.txt" >&2
    exit 1
fi

# PyQt6 loads its X11 backend through a plugin that links against a handful of
# system libraries. Missing any of them aborts the process inside Qt with a
# "dumped core" and no useful message, so check for them before launching.
QT_XCB_PLUGIN="$("$PYTHON" - <<'EOF' 2>/dev/null || true
import os
try:
    import PyQt6
except ImportError:
    raise SystemExit
base = os.path.join(os.path.dirname(PyQt6.__file__), "Qt6", "plugins", "platforms")
for name in ("libqxcb.so", "libqxcb.so.6"):
    candidate = os.path.join(base, name)
    if os.path.exists(candidate):
        print(candidate)
        break
EOF
)"

if [ -n "$QT_XCB_PLUGIN" ] && command -v ldd >/dev/null 2>&1; then
    MISSING="$(ldd "$QT_XCB_PLUGIN" 2>/dev/null | awk '/not found/ {print $1}' | sort -u)"
    if [ -n "$MISSING" ]; then
        echo "error: Qt's X11 support is incomplete. Missing system libraries:" >&2
        echo "$MISSING" | sed 's/^/         /' >&2
        echo >&2
        echo "       On Debian / Ubuntu / Mint:" >&2
        echo "         sudo apt install libxcb-cursor0 libxkbcommon-x11-0 libegl1 \\" >&2
        echo "           libgl1 libdbus-1-3 libfontconfig1" >&2
        echo >&2
        echo "       On Fedora:" >&2
        echo "         sudo dnf install libxkbcommon-x11 libXcursor" >&2
        echo >&2
        echo "       On Arch:" >&2
        echo "         sudo pacman -S libxcursor libxkbcommon-x11" >&2
        echo >&2
        echo "       Then run ./run.sh again." >&2
        exit 1
    fi
fi

exec "$PYTHON" main.py "$@"