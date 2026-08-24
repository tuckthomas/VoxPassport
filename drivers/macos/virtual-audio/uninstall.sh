#!/usr/bin/env bash
set -euo pipefail
DEST="/Library/Audio/Plug-Ins/HAL/VoxPassportVirtualAudio.driver"
sudo rm -rf "$DEST"
sudo killall coreaudiod 2>/dev/null || true
echo "Removed $DEST"
