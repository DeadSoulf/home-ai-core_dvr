#!/bin/sh
# ABI-check and build SDK stream adapter from the locally staged vendor package.
set -eu
if [ "$#" -ne 2 ]; then
  echo "Usage: sh tools/verify_hcnetsdk_abi.sh SDK_STAGE_DIR OUTPUT_BINARY" >&2
  exit 2
fi
sdk=$(realpath "$1")
source_root=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)
output="$2"
test -f "$sdk/manifest.json"
test -f "$sdk/include/HCNetSDK.h"
test -f "$sdk/lib/libhcnetsdk.so"
mkdir -p "$(dirname "$output")"
g++ -std=c++17 -O2 -Wall -Wextra -pthread \
  -I"$sdk/include" "$source_root/native/sdk_stream_v40.cpp" \
  -L"$sdk/lib" -Wl,-rpath,"$sdk/lib" \
  -lhcnetsdk -o "$output"
LD_LIBRARY_PATH="$sdk/lib:$sdk/lib/HCNetSDKCom" \
  HCNETSDK_PATH="$sdk/lib" "$output" --version

# Recompile control operations with exactly the same vendor headers and libs.
# Never reuse the old sdk-action binary linked against OpenSSL 1.1.
g++ -std=c++17 -O2 -Wall -Wextra -Werror -pthread \
  -I"$sdk/include" "$source_root/native/sdk_action_v40.cpp" \
  -L"$sdk/lib" -Wl,-rpath,"$sdk/lib" \
  -lhcnetsdk -o "${output}-action"
# A missing command must be rejected before attempting camera login.
status=0
LD_LIBRARY_PATH="$sdk/lib:$sdk/lib/HCNetSDKCom" \
  HCNETSDK_PATH="$sdk/lib" "${output}-action" >/dev/null 2>&1 || status=$?
if [ "$status" -ne 64 ]; then
    echo "sdk-action must reject missing camera action arguments" >&2
    exit 1
fi
echo "V40 stream and action adapters compiled with HCNetSDK 6.1.11.40 headers"
