#!/usr/bin/env bash
# Build Linux release tarball for INF Avis
# Usage: ./build_linux.sh [version]

set -euo pipefail

VERSION="${1:-$(git describe --tags --always --dirty 2>/dev/null || echo 'dev')}"
APP_NAME="inf-avis"
DIST_DIR="dist/${APP_NAME}-${VERSION}-linux-x86_64"

echo "Building ${APP_NAME} ${VERSION} for Linux..."

# Clean previous builds
rm -rf dist build *.spec

# Install PyInstaller if needed
if ! python3 -m PyInstaller --version >/dev/null 2>&1; then
    echo "Installing PyInstaller..."
    python3 -m pip install --quiet pyinstaller
fi

# Build with PyInstaller
python3 -m PyInstaller \
    --clean \
    --noconfirm \
    --name "${APP_NAME}" \
    --windowed \
    --add-data "gui:gui" \
    --add-data "api:api" \
    --add-data "database.py:." \
    --add-data "paths.py:." \
    --hidden-import=PyQt6.QtSvg \
    --hidden-import=certifi \
    --exclude-module=tkinter \
    --exclude-module=matplotlib \
    --exclude-module=numpy \
    --exclude-module=pytest \
    main.py

# Create release directory
mkdir -p "${DIST_DIR}"

# Copy the built executable and dependencies
cp -r "dist/${APP_NAME}"/* "${DIST_DIR}/"

# Create a launch script that sets up portable mode
cat > "${DIST_DIR}/inf-avis" << 'EOF'
#!/usr/bin/env bash
# INF Avis launcher - portable mode
set -euo pipefail
cd "$(dirname "$0")"
export INF_AVIS_PORTABLE=1
exec "./inf-avis" "$@"
EOF
chmod +x "${DIST_DIR}/inf-avis"

# Copy README and license
cp README.md "${DIST_DIR}/" 2>/dev/null || true

# Create tarball
TARBALL="dist/${APP_NAME}-${VERSION}-linux-x86_64.tar.gz"
tar -czf "${TARBALL}" -C dist "${APP_NAME}-${VERSION}-linux-x86_64"

echo "Done! Release tarball: ${TARBALL}"
echo "Size: $(du -h "${TARBALL}" | cut -f1)"

# Show contents
tar -tzf "${TARBALL}" | head -20