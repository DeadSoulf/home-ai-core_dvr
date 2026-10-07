#!/bin/sh
set -eu

DATA_ROOT="${NVR_DATA_ROOT:-/data}"
mkdir -p "$DATA_ROOT/hls" "$DATA_ROOT/archive" "$DATA_ROOT/recordings" "$DATA_ROOT/logs" "$DATA_ROOT/SDKLOG"
cd "$DATA_ROOT"

/usr/local/bin/sdk-smoke

exec "$@"
