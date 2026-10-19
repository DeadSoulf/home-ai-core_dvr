"""Read-only HCNetSDK runtime health; never call vendor libraries in Web process."""
import ctypes
import functools
import json
import os
import subprocess
import sys
from pathlib import Path

SDK_PATH = Path(os.environ.get("HCNETSDK_PATH", "/opt/hikvision/lib"))
PROBE_TIMEOUT = 4


def decode_sdk_version(build):
    build = int(build)
    if build < 0 or build > 0xFFFFFFFF:
        raise ValueError("invalid HCNetSDK version word")
    return ".".join(str((build >> shift) & 0xFF) for shift in (24, 16, 8, 0))


def _worker(root):
    lib = Path(root) / "libhcnetsdk.so"
    if not lib.is_file():
        raise OSError("missing libhcnetsdk.so")
    handle = ctypes.CDLL(str(lib), mode=ctypes.RTLD_LOCAL)
    fn = handle.NET_DVR_GetSDKBuildVersion
    fn.restype = ctypes.c_uint32
    fn.argtypes = []
    return {"ok": True, "version": decode_sdk_version(fn())}


@functools.lru_cache(maxsize=4)
def sdk_status(root=None):
    """Isolate native crashes and timeouts away from NVR API and recordings."""
    root = Path(root) if root else SDK_PATH
    base = {"ok": False, "version": None, "architecture": "linux/amd64"}
    if not (root / "libhcnetsdk.so").is_file():
        return {**base, "error": "sdk_library_missing"}
    environment = os.environ.copy()
    environment["LD_LIBRARY_PATH"] = (
        str(root) + ":" + str(root / "HCNetSDKCom") +
        (":" + environment["LD_LIBRARY_PATH"] if environment.get("LD_LIBRARY_PATH") else "")
    )
    try:
        process = subprocess.run(
            [sys.executable, str(Path(__file__).resolve()), "--probe", str(root)],
            stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, text=True,
            env=environment, timeout=PROBE_TIMEOUT, check=False
        )
    except (OSError, subprocess.TimeoutExpired):
        return {**base, "error": "sdk_probe_unavailable"}
    if process.returncode != 0:
        return {**base, "error": "sdk_probe_failed"}
    try:
        result = json.loads(process.stdout)
        if result.get("ok") is True and isinstance(result.get("version"), str):
            return {**base, "ok": True, "version": result["version"],
                    "openssl": ("3" if (root / "libcrypto.so.3").exists() else
                                "1.1" if (root / "libcrypto.so.1.1").exists() else
                                "unknown")}
    except (ValueError, TypeError):
        pass
    return {**base, "error": "sdk_probe_invalid_response"}


def main():
    if len(sys.argv) != 3 or sys.argv[1] != "--probe":
        return 2
    try:
        print(json.dumps(_worker(sys.argv[2]), separators=(",", ":")))
        return 0
    except (OSError, AttributeError, ValueError):
        return 1


if __name__ == "__main__":
    sys.exit(main())
