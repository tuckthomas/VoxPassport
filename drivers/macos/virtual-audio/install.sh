#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
BUILD_DIR="$ROOT/build"
DRIVER="$BUILD_DIR/VoxPassportVirtualAudio.driver"
DEST="/Library/Audio/Plug-Ins/HAL/VoxPassportVirtualAudio.driver"

if [[ ! -d "$DRIVER" ]]; then
  cmake -S "$ROOT" -B "$BUILD_DIR" -DCMAKE_BUILD_TYPE=Release
  cmake --build "$BUILD_DIR" --config Release
fi

if [[ ! -d "$DRIVER" ]]; then
  echo "Built driver bundle not found at $DRIVER" >&2
  exit 1
fi

sudo mkdir -p /Library/Audio/Plug-Ins/HAL
sudo rm -rf "$DEST"
sudo cp -R "$DRIVER" "$DEST"
sudo chown -R root:wheel "$DEST"
sudo chmod -R a+rX "$DEST"

# CoreAudio reloads HAL plug-ins on daemon restart. macOS relaunches coreaudiod.
sudo killall coreaudiod 2>/dev/null || true

echo "Installed $DEST"
echo "No signing/security policy was changed by this script."
