#!/usr/bin/env bash
# Build a Linux release of INF Avis.
# Usage: ./build_linux.sh [version]
#
# Output:
#   release/linux/inf-avis-<version>-linux-x86_64/   (portable folder)
#   release/inf-avis-<version>-linux-x86_64.tar.gz   (distributable tarball)

set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "${ROOT_DIR}"

VERSION="${1:-$(git describe --tags --always --dirty 2>/dev/null || echo 'dev')}"
VERSION="${VERSION#v}"
APP_NAME="inf-avis"

# Prefer the project virtualenv, fall back to a pyinstaller on PATH.
if [[ -x "${ROOT_DIR}/.venv/bin/pyinstaller" ]]; then
    PYINSTALLER="${ROOT_DIR}/.venv/bin/pyinstaller"
elif command -v pyinstaller >/dev/null 2>&1; then
    PYINSTALLER="$(command -v pyinstaller)"
else
    echo "error: PyInstaller not found. Run ./setup.sh first." >&2
    exit 1
fi

echo "Building ${APP_NAME} ${VERSION} for Linux..."

rm -rf build/inf-avis dist/inf-avis
"${PYINSTALLER}" --clean --noconfirm inf-avis.spec

RELEASE_DIR="release/linux/${APP_NAME}-${VERSION}-linux-x86_64"
rm -rf "${RELEASE_DIR}"
mkdir -p "${RELEASE_DIR}"
cp -a "dist/${APP_NAME}/." "${RELEASE_DIR}/"
cp README.md "${RELEASE_DIR}/" 2>/dev/null || true
cp LICENSE "${RELEASE_DIR}/" 2>/dev/null || true
chmod +x "${RELEASE_DIR}/${APP_NAME}"

TARBALL="release/${APP_NAME}-${VERSION}-linux-x86_64.tar.gz"
rm -f "${TARBALL}"
tar -czf "${TARBALL}" -C release/linux "${APP_NAME}-${VERSION}-linux-x86_64"

echo ""
echo "============================================"
echo "Done! Release ready at:"
echo "  Folder:  ${RELEASE_DIR}/"
echo "  Tarball: ${TARBALL}"
echo "============================================"
