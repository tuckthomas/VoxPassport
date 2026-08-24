#!/usr/bin/env bash
set -euo pipefail

CONFIG_DIR="${XDG_CONFIG_HOME:-$HOME/.config}/pipewire/pipewire-pulse.conf.d"
CONFIG_PATH="$CONFIG_DIR/90-voxpassport-virtual-audio.conf"
rm -f "$CONFIG_PATH"
echo "Removed persistent config: $CONFIG_PATH"

if ! command -v pactl >/dev/null 2>&1 || ! pactl info >/dev/null 2>&1; then
  exit 0
fi

# Unload remap-source before the sink it depends on. Module IDs are session-local.
while read -r module_id module_name module_args _; do
  if [[ "$module_name" == "module-remap-source" && "$module_args" == *"voxpassport_virtual_microphone"* ]]; then
    pactl unload-module "$module_id" || true
  fi
done < <(pactl list short modules)

while read -r module_id module_name module_args _; do
  if [[ "$module_name" == "module-null-sink" && "$module_args" == *"voxpassport_translation_sink"* ]]; then
    pactl unload-module "$module_id" || true
  fi
done < <(pactl list short modules)

echo "Unloaded active VoxPassport virtual-audio modules where present."
