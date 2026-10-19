#!/bin/sh
# ABI-check and build SDK stream adapter from the locally staged vendor package.
set -eu
if [ "$#" -ne 2 ]; then
  echo "Usage: sh tools/verify_hcnetsdk_abi.sh SDK_STAGE_DIR OUTPUT_BINARY" >&2
  exit 2
fi
sdk=$(realpath "$1")
output="$2"
test -f "$sdk/manifest.json"
test -f "$sdk/include/HCNetSDK.h"
test -f "$sdk/lib/libhcnetsdk.so"
mkdir -p "$(dirname "$output")"
g++ -std=c++17 -O2 -Wall -Wextra -pthread \
  -I"$sdk/include" native/sdk_stream_v40.cpp \
  -L"$sdk/lib" -Wl,-rpath,"$sdk/lib" \
  -lhcnetsdk -o "$output"
LD_LIBRARY_PATH="$sdk/lib:$sdk/lib/HCNetSDKCom" \
  HCNETSDK_PATH="$sdk/lib" "$output" --version
