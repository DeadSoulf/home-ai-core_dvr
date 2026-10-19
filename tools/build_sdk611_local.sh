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
case "$(realpath "$1")" in
  "$root"/*) echo "Never place vendor SDK archives inside the Git repository" >&2; exit 2 ;;
esac
stage_root=$(mktemp -d)
trap 'rm -rf "$stage_root"' EXIT HUP INT TERM
python3 "$root/tools/stage_hcnetsdk.py" "$1" \
  --output "$stage_root/vendor_sdk" \
  --sha256 2b8be43fd1cf0d4bd16d4a3b5860c214ee278fd851ea0c59ab0e0b4a9eceee29
sh "$root/tools/verify_hcnetsdk_abi.sh" "$stage_root/vendor_sdk" "$stage_root/sdk-stream"
cd "$root"
docker buildx build --platform linux/amd64 --load \
  --build-context "vendor_sdk=$stage_root/vendor_sdk" \
  -f Dockerfile.sdk611 -t home-ai-core-nvr:1.1.6-sdk611-local .
echo "Validated local HCNetSDK image: home-ai-core-nvr:1.1.6-sdk611-local"
echo "No running NVR, host mount, camera configuration or archive was modified."
echo "Do not publish the proprietary image or replace production NVR without an authorized rollout."
