#!/bin/sh
set -eu

mkdir -p /app/output/hls /app/output/archive /app/sdkLog

/usr/local/bin/sdk-smoke

exec "$@"
