"""Read-only HCNetSDK runtime health; never call vendor libraries in Web process."""
import ctypes
import functools
import json
import os
import subprocess
import sys
from pathlib import Path

SDK_PATH = Path(os.environ.get("HCNETSDK_PATH", "/opt/hikvision/lib"))
PROBE_TIMEOUT = 10


class _LocalSDKPath(ctypes.Structure):
    # NET_DVR_LOCAL_SDK_PATH in HCNetSDK 6.1.11.40 incEn/HCNetSDK.h.
    _fields_ = [("sPath", ctypes.c_char * 256),
                ("byRes", ctypes.c_ubyte * 128)]


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
    # Vendor guide §12.1.40 requires configuring the component directory
    # before NET_DVR_Init(). This is separate from LD_LIBRARY_PATH.
    encoded = os.fsencode(str(Path(root).resolve()))
    if not encoded or len(encoded) >= 256:
        raise ValueError("HCNetSDK component path is too long")
    sdk_path = _LocalSDKPath()
    sdk_path.sPath = encoded
    configure = handle.NET_DVR_SetSDKInitCfg
    configure.restype = ctypes.c_int
    configure.argtypes = [ctypes.c_int, ctypes.c_void_p]
    if configure(2, ctypes.byref(sdk_path)) != 1:
        raise OSError("HCNetSDK component directory configuration failed")
    init = handle.NET_DVR_Init
    init.restype = ctypes.c_int
    init.argtypes = []
    cleanup = handle.NET_DVR_Cleanup
    cleanup.restype = ctypes.c_int
    cleanup.argtypes = []
    fn = handle.NET_DVR_GetSDKBuildVersion
    fn.restype = ctypes.c_uint32
    fn.argtypes = []
    # HCNetSDK 6.1.11 returns 0 from GetSDKBuildVersion until Init.
    if init() != 1:
        raise OSError("HCNetSDK initialization failed")
    try:
        version_word = fn()
        if version_word == 0:
            raise ValueError("SDK returned no build version")
        return {"ok": True, "version": decode_sdk_version(version_word)}
    finally:
        cleanup()


class _RetryableSDKProbeFailure(Exception):
    """A failed probe must not be cached for the lifetime of the NVR process."""

    def __init__(self, result):
        super().__init__(result.get("error", "sdk_probe_failed"))
        self.result = result


@functools.lru_cache(maxsize=4)
def _cached_sdk_status(root):
    result = _probe_sdk_status(Path(root))
    if not result.get("ok"):
        raise _RetryableSDKProbeFailure(result)
    return result


def sdk_status(root=None):
    """Cache successful native probes but allow retry after a transient failure."""
    try:
        return _cached_sdk_status(str(Path(root) if root else SDK_PATH))
    except _RetryableSDKProbeFailure as exc:
        return exc.result


# Preserve the cache-clear interface used by isolated regression tests.
sdk_status.cache_clear = _cached_sdk_status.cache_clear


def _probe_sdk_status(root):
    """Keep vendor SDK Init/Cleanup in a bounded subprocess outside Web."""

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
