#!/usr/bin/env bash
set -euo pipefail

SINK_ID="voxpassport_translation_sink"
SOURCE_ID="voxpassport_virtual_microphone"
CONFIG_DIR="${XDG_CONFIG_HOME:-$HOME/.config}/pipewire/pipewire-pulse.conf.d"
CONFIG_PATH="$CONFIG_DIR/90-voxpassport-virtual-audio.conf"

for command in pactl pw-record pw-play; do
  if ! command -v "$command" >/dev/null 2>&1; then
    echo "Required command '$command' was not found on PATH." >&2
    exit 1
  fi
done

mkdir -p "$CONFIG_DIR"
cat >"$CONFIG_PATH" <<'EOF'
# VoxPassport persistent PipeWire-Pulse virtual audio pair.
pulse.cmd = [
    { cmd = "load-module" args = "module-null-sink sink_name=voxpassport_translation_sink rate=48000 channels=2 channel_map=front-left,front-right sink_properties=device.description='VoxPassport Translation Sink'" flags = [ ] }
    { cmd = "load-module" args = "module-remap-source master=voxpassport_translation_sink.monitor source_name=voxpassport_virtual_microphone rate=48000 channels=2 channel_map=front-left,front-right source_properties=device.description='VoxPassport Virtual Microphone'" flags = [ ] }
]
EOF

echo "Installed persistent PipeWire-Pulse config: $CONFIG_PATH"

if ! pactl info >/dev/null 2>&1; then
  echo "PipeWire-Pulse is not reachable in this session. The endpoints will be created when it next starts." >&2
  exit 0
fi

if ! pactl list short sinks | awk '{print $2}' | grep -Fxq "$SINK_ID"; then
  pactl load-module module-null-sink \
    sink_name="$SINK_ID" \
    rate=48000 channels=2 channel_map=front-left,front-right \
    "sink_properties=device.description='VoxPassport Translation Sink'" >/dev/null
fi

if ! pactl list short sources | awk '{print $2}' | grep -Fxq "$SOURCE_ID"; then
  pactl load-module module-remap-source \
    master="$SINK_ID.monitor" \
    source_name="$SOURCE_ID" \
    rate=48000 channels=2 channel_map=front-left,front-right \
    "source_properties=device.description='VoxPassport Virtual Microphone'" >/dev/null
fi

echo "VoxPassport Translation Sink and VoxPassport Virtual Microphone are active."
