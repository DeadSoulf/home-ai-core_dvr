#!/bin/sh
# Opt-in hardware smoke: non-destructive login and a short video sample.
# Never changes installed NVR, its mount, camera settings or recording archive.
set -eu

for name in HCNET_IP HCNET_USER HCNET_PASSWORD; do
    eval 'value=${'"$name"'-}'
    if [ -z "$value" ]; then
        echo "Missing $name (environment variable)" >&2
        exit 2
    fi
done
for binary in docker timeout ffmpeg ffprobe; do
    if ! command -v "$binary" >/dev/null 2>&1; then
        echo "Required program is missing: $binary" >&2
        exit 2
    fi
done

image="home-ai-core-nvr:1.1.6-sdk611-local"
docker image inspect "$image" >/dev/null
port=${HCNET_PORT:-8000}
channel=${HCNET_CHANNEL:-1}
duration=${HCNET_SAMPLE_SECONDS:-20}
case "$port" in ''|*[!0-9]*) echo "Invalid HCNET_PORT" >&2; exit 2;; esac
case "$channel" in ''|*[!0-9]*) echo "Invalid HCNET_CHANNEL" >&2; exit 2;; esac
case "$duration" in ''|*[!0-9]*) echo "Invalid HCNET_SAMPLE_SECONDS" >&2; exit 2;; esac
if [ "$port" -lt 1 ] || [ "$port" -gt 65535 ] ||
   [ "$channel" -lt 1 ] || [ "$channel" -gt 2048 ] ||
   [ "$duration" -lt 5 ] || [ "$duration" -gt 60 ]; then
    echo "Port, channel or duration outside supported bounds" >&2
    exit 2
fi
export HCNET_PORT="$port" HCNET_CHANNEL="$channel" HCNET_STREAM_TYPE=0
temp=$(mktemp -d)
trap 'rm -rf "$temp"' EXIT HUP INT TERM
mkdir "$temp/data"
chmod 0777 "$temp/data"

# No service ports exposed. Outgoing LAN connection only.
# Pass secret by name, never as a literal CLI value.
echo "Checking HCNetSDK login and camera channel inventory..."
docker run --rm --platform linux/amd64 --network host --user 1001:1001 \
    --read-only --cap-drop ALL --security-opt no-new-privileges \
    --tmpfs /tmp:rw,noexec,nosuid,size=64m \
    --mount "type=bind,src=$temp/data,dst=/data" \
    --env HCNET_IP --env HCNET_USER --env HCNET_PASSWORD \
    --env HCNET_PORT --env HCNET_CHANNEL \
    --entrypoint /usr/local/bin/sdk-login-test "$image"

echo "Capturing a $duration second read-only video sample..."
code=0
timeout --signal=INT --kill-after=8 "$duration" \
    docker run --rm --platform linux/amd64 --network host \
        --user 1001:1001 --read-only --cap-drop ALL \
        --security-opt no-new-privileges \
        --tmpfs /tmp:rw,noexec,nosuid,size=64m \
        --mount "type=bind,src=$temp/data,dst=/data" \
        --env HCNET_IP --env HCNET_USER --env HCNET_PASSWORD \
        --env HCNET_PORT --env HCNET_CHANNEL --env HCNET_STREAM_TYPE \
        --entrypoint /usr/local/bin/sdk-stream "$image" \
        >"$temp/stream.ps" 2>"$temp/sdk-error.log" || code=$?
# A timed capture is normal; any other nonzero status is a real failure.
if [ "$code" -ne 0 ] && [ "$code" -ne 124 ]; then
    echo "Camera stream process failed with status $code" >&2
    exit 1
fi
if [ ! -s "$temp/stream.ps" ]; then
    echo "No camera stream bytes received" >&2
    exit 1
fi
ffmpeg -nostdin -hide_banner -loglevel error -y -fflags +genpts \
    -i "$temp/stream.ps" -map 0:v:0 -map 0:a:0? -c copy \
    -movflags +faststart "$temp/sample.mp4"
codec=$(ffprobe -v error -select_streams v:0 \
    -show_entries stream=codec_name -of default=noprint_wrappers=1:nokey=1 \
    "$temp/sample.mp4")
case "$codec" in h264|hevc) ;; *)
    echo "Video stream could not be decoded as H.264/H.265: $codec" >&2
    exit 1 ;;
esac
if [ ! -s "$temp/sample.mp4" ]; then
    echo "Sample MP4 is empty" >&2
    exit 1
fi
echo "HCNetSDK login, stream, and video remux: PASS ($codec)"
echo "No PTZ commands were sent; the camera's pan/tilt position was not changed."
echo "Captured test data has been kept only in the disposable temporary directory."
