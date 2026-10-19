#!/bin/sh
# Reproducible, private local build. The vendor archive is not uploaded to GitHub.
set -eu
if [ "$#" -ne 1 ]; then
    echo "Usage: sh tools/build_sdk611_local.sh /path/to/EN-HCNetSDKV6.1.11.40_build20260922_linux64.zip" >&2
    exit 2
fi
case "$(uname -m)" in
  x86_64|amd64) ;;
  *) echo "HCNetSDK 6.1.11.40 build supports Linux amd64 only" >&2; exit 2 ;;
esac
if ! command -v docker >/dev/null 2>&1 || ! docker buildx version >/dev/null 2>&1; then
    echo "Docker with buildx and BuildKit is required" >&2
    exit 2
fi
if ! command -v python3 >/dev/null 2>&1 || ! command -v g++ >/dev/null 2>&1; then
    echo "Python 3 and g++ are required for SDK verification" >&2
    exit 2
fi
root=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)
archive=$(realpath "$1")
case "$archive" in
  "$root"/*) echo "Never place vendor SDK archives inside the Git repository" >&2; exit 2 ;;
esac
cd "$root"
stage_root=$(mktemp -d)
trap 'rm -rf "$stage_root"' EXIT HUP INT TERM
python3 "$root/tools/stage_hcnetsdk.py" "$archive" \
  --output "$stage_root/vendor_sdk" \
  --sha256 2b8be43fd1cf0d4bd16d4a3b5860c214ee278fd851ea0c59ab0e0b4a9eceee29
sh "$root/tools/verify_hcnetsdk_abi.sh" "$stage_root/vendor_sdk" "$stage_root/sdk-stream"
cd "$root"
docker buildx build --platform linux/amd64 --load \
  --build-context "vendor_sdk=$stage_root/vendor_sdk" \
  -f Dockerfile.sdk611 -t home-ai-core-nvr:1.1.6-sdk611-local .

# Integration-check ONLY the freshly built image, never an installed NVR.
# No host ports, no external network, no production recording paths.
test_data="$stage_root/disposable-nvr-data"
mkdir "$test_data"
chmod 0777 "$test_data"
test_container=""
cleanup() {
    if [ -n "$test_container" ]; then
        docker rm -f "$test_container" >/dev/null 2>&1 || true
    fi
    rm -rf "$stage_root"
}
trap cleanup EXIT HUP INT TERM

test_container=$(docker run -d --rm --platform linux/amd64 \
  --network none --user 1001:1001 --read-only \
  --cap-drop ALL --security-opt no-new-privileges --pids-limit 256 \
  --tmpfs /tmp:rw,noexec,nosuid,size=64m \
  --mount "type=bind,src=$test_data,dst=/data" \
  home-ai-core-nvr:1.1.6-sdk611-local)

verified=0
n=0
while [ "$n" -lt 100 ]; do
    n=$((n+1))
    if ! docker inspect --format '{{.State.Running}}' "$test_container" 2>/dev/null | grep -qx true; then
        echo "SDK611 smoke-test container exited unexpectedly" >&2
        break
    fi
    if docker exec "$test_container" python3 -c '
import json, urllib.request
def get(path):
    return json.load(urllib.request.urlopen("http://127.0.0.1:8090"+path, timeout=2))
status = get("/api/nvr/status")
sdk = get("/api/nvr/sdk")
assert status.get("ok") is True and sdk.get("ok") is True
assert sdk.get("version") == "6.1.11.40", sdk.get("error")
' >/dev/null 2>&1; then
        verified=1
        break
    fi
    sleep 2
done
if [ "$verified" -ne 1 ]; then
    echo "SDK611 local image failed read-only container runtime/API smoke test" >&2
    docker logs --tail 100 "$test_container" >&2 || true
    exit 1
fi
echo "SDK611 container passed isolated health, API and actual loaded library-version checks"
echo "Locally validated: home-ai-core-nvr:1.1.6-sdk611-local"
echo "No production NVR, camera configuration, host mount or archive was modified."
echo "Do not publish the proprietary image or replace production NVR without an authorized rollout."
