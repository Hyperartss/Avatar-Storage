#!/usr/bin/env bash
# Create a local virtualenv and install the dependencies.
set -euo pipefail
cd "$(dirname "$0")"

PYTHON="${PYTHON:-python3}"
VENV="${VENV:-.venv}"

if ! command -v "$PYTHON" >/dev/null 2>&1; then
    echo "error: '$PYTHON' not found." >&2
    echo "       Install Python 3.10+ or point PYTHON at an interpreter:" >&2
    echo "         PYTHON=/usr/bin/python3.12 ./setup.sh" >&2
    exit 1
fi

if ! "$PYTHON" - <<'EOF'
import sys
if sys.version_info < (3, 10):
    sys.exit(f"error: Python 3.10+ required, found {sys.version.split()[0]}")
EOF
then
    exit 1
fi

missing_venv_help() {
    cat >&2 <<EOF

error: '$PYTHON' cannot create virtualenvs (the ensurepip module is missing),
       and 'virtualenv' is not installed either.

       This is normal on a fresh Linux install; the packaging is separate:

         Debian / Ubuntu / Mint   sudo apt install python3-venv
         Fedora                   sudo dnf install python3-virtualenv
         Arch                     sudo pacman -S python-virtualenv

       Or skip the virtualenv entirely and install into your user site:

         $PYTHON -m pip install --user -r requirements.txt
         ./run.sh

EOF
}

# A half-built venv from a previous failed attempt must not be reused.
if [ -d "$VENV" ] && ! "$VENV/bin/python" -c "import pip" >/dev/null 2>&1; then
    echo "Removing incomplete virtualenv in $VENV..."
    rm -rf "$VENV"
fi

if [ ! -d "$VENV" ]; then
    echo "Creating virtualenv in $VENV..."
    created=no
    # virtualenv does not need ensurepip, so try it first when it is installed.
    if command -v virtualenv >/dev/null 2>&1; then
        if virtualenv "$VENV"; then
            created=yes
        fi
    fi
    if [ "$created" = no ]; then
        if ! "$PYTHON" -c "import ensurepip" >/dev/null 2>&1; then
            missing_venv_help
            exit 1
        fi
        if ! "$PYTHON" -m venv "$VENV"; then
            missing_venv_help
            exit 1
        fi
    fi
fi

if ! "$VENV/bin/python" -c "import pip" >/dev/null 2>&1; then
    missing_venv_help
    exit 1
fi

"$VENV/bin/python" -m pip install --upgrade pip
"$VENV/bin/python" -m pip install -r requirements.txt

# Fail here rather than at first launch if something is unsatisfiable.
if ! "$VENV/bin/python" -c "import PyQt6, requests, PIL" >/dev/null 2>&1; then
    echo "error: dependencies still missing after install." >&2
    exit 1
fi

echo
echo "Done. Start the app with: ./run.sh"