#!/bin/sh
set -eu

DATA_ROOT="${NVR_DATA_ROOT:-/data}"
mkdir -p "$DATA_ROOT/hls" "$DATA_ROOT/archive" "$DATA_ROOT/recordings" "$DATA_ROOT/logs" "$DATA_ROOT/SDKLOG"
# A Core-managed external recording mount is permitted only if its marker
# matches the expected filesystem. If the disk disappears after a reboot,
# fail closed rather than writing recordings to the system partition.
if [ -n "${NVR_STORAGE_MARKER:-}" ]; then
    MARKER="$DATA_ROOT/recordings/.home-ai-core-nvr-storage"
    [ -f "$MARKER" ] || { echo "NVR recording volume is not mounted: marker missing" >&2; exit 41; }
    STORED="$(cat "$MARKER")"
    [ "$STORED" = "$NVR_STORAGE_MARKER" ] || { echo "NVR recording volume marker mismatch" >&2; exit 42; }
fi
cd "$DATA_ROOT"

/usr/local/bin/sdk-smoke

exec "$@"
