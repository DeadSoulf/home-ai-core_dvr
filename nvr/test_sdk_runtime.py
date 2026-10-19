import subprocess
import threading
import time
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

from nvr.sdk_runtime import SDKStatusMonitor, _worker, decode_sdk_version, sdk_status


class SDKRuntimeTests(unittest.TestCase):
    def setUp(self):
        sdk_status.cache_clear()
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)

    def test_sdk_version_word(self):
        self.assertEqual(decode_sdk_version(0x06010B28), "6.1.11.40")
        self.assertEqual(decode_sdk_version(0x06010930), "6.1.9.48")
        with self.assertRaises(ValueError):
            decode_sdk_version(-1)

    def test_native_build_word_requires_initialization_and_cleanup(self):
        (self.root / "libhcnetsdk.so").write_bytes(b"ELF")

        class FakeFunction:
            restype = None
            argtypes = None

            def __init__(self, callback):
                self.callback = callback

            def __call__(self, *args):
                return self.callback(*args)

        state = {"configured": False, "initialized": False, "cleaned": False}

        def configure(kind, location):
            if kind != 2 or str(self.root).encode() != location._obj.sPath:
                return 0
            state["configured"] = True
            return 1

        class FakeLibrary:
            NET_DVR_SetSDKInitCfg = FakeFunction(configure)
            NET_DVR_Init = FakeFunction(lambda: state.__setitem__("initialized", True) or 1 if state["configured"] else 0)
            NET_DVR_GetSDKBuildVersion = FakeFunction(
                lambda: 0x06010B28 if state["initialized"] else 0
            )
            NET_DVR_Cleanup = FakeFunction(lambda: state.__setitem__("cleaned", True) or 1)

        with patch("nvr.sdk_runtime.ctypes.CDLL", return_value=FakeLibrary()):
            result = _worker(self.root)
        self.assertEqual(result["version"], "6.1.11.40")
        self.assertTrue(state["configured"])
        self.assertTrue(state["cleaned"])

    def test_missing_native_component_path_is_rejected_before_initialization(self):
        (self.root / "libhcnetsdk.so").write_bytes(b"ELF")

        class RejectLibrary:
            def __init__(self):
                self.initialized = False
                self.NET_DVR_SetSDKInitCfg = Mock(side_effect=self.reject)

            def reject(self, kind, location):
                self.kind = kind
                return 0

            def NET_DVR_Init(self):
                self.initialized = True
                return 1

        library = RejectLibrary()
        with patch("nvr.sdk_runtime.ctypes.CDLL", return_value=library):
            with self.assertRaisesRegex(OSError, "component directory"):
                _worker(self.root)
        self.assertFalse(library.initialized)
        self.assertEqual(library.kind, 2)

    def test_missing_library_is_reported_without_loading_native_code(self):
        self.assertEqual(sdk_status(self.root)["error"], "sdk_library_missing")

    def test_subprocess_isolation_prevents_native_failure(self):
        (self.root / "libhcnetsdk.so").write_bytes(b"ELF")
        with patch("nvr.sdk_runtime.subprocess.run", return_value=subprocess.CompletedProcess([], -11)):
            result = sdk_status(self.root)
        self.assertFalse(result["ok"])
        self.assertEqual(result["error"], "sdk_probe_failed")

    def test_validated_runtime_version_and_openssl_generation(self):
        (self.root / "libhcnetsdk.so").write_bytes(b"ELF")
        (self.root / "libcrypto.so.3").write_bytes(b"ELF")
        with patch("nvr.sdk_runtime.subprocess.run",
                   return_value=subprocess.CompletedProcess([], 0, '{"ok":true,"version":"6.1.11.40"}')):
            result = sdk_status(self.root)
        self.assertTrue(result["ok"])
        self.assertEqual(result["version"], "6.1.11.40")
        self.assertEqual(result["openssl"], "3")

    def test_timeout_is_retryable_in_same_process(self):
        (self.root / "libhcnetsdk.so").write_bytes(b"ELF")
        (self.root / "libcrypto.so.3").write_bytes(b"ELF")
        success = subprocess.CompletedProcess(
            [], 0, '{"ok":true,"version":"6.1.11.40"}'
        )
        with patch("nvr.sdk_runtime.subprocess.run", side_effect=[
            subprocess.TimeoutExpired(["sdk-probe"], 10), success
        ]) as run:
            first = sdk_status(self.root)
            second = sdk_status(self.root)
            third = sdk_status(self.root)
        self.assertFalse(first["ok"])
        self.assertEqual(first["error"], "sdk_probe_unavailable")
        self.assertTrue(second["ok"])
        self.assertEqual(third, second)
        self.assertEqual(run.call_count, 2, "only successful probe must be cached")

    def test_real_hcnetsdk_probe_has_a_realistic_timeout(self):
        from nvr.sdk_runtime import PROBE_TIMEOUT
        self.assertGreaterEqual(PROBE_TIMEOUT, 10)
        self.assertLessEqual(PROBE_TIMEOUT, 45)


    def test_web_probe_never_blocks_or_runs_concurrently(self):
        entered = threading.Event()
        release = threading.Event()
        done = threading.Event()
        runs = []

        def probe(root):
            runs.append(root)
            entered.set()
            release.wait(2)
            done.set()
            return {"ok": True, "version": "6.1.11.40",
                    "architecture": "linux/amd64"}

        monitor = SDKStatusMonitor(probe=probe)
        try:
            beginning = time.monotonic()
            self.assertEqual(monitor.status(self.root)["error"], "sdk_probe_in_progress")
            self.assertTrue(entered.wait(1))
            for _ in range(12):
                self.assertEqual(monitor.status(self.root)["error"], "sdk_probe_in_progress")
            self.assertLess(time.monotonic() - beginning, 0.5)
            self.assertEqual(len(runs), 1)
        finally:
            release.set()
        self.assertTrue(done.wait(2))
        for _ in range(200):
            result = monitor.status(self.root)
            if result.get("ok"):
                break
            time.sleep(0.005)
        self.assertTrue(result["ok"])
        self.assertEqual(len(runs), 1)

    def test_web_probe_errors_are_throttled_before_retry(self):
        attempts = []
        clock = [100.0]
        entered = threading.Event()

        def failure(root):
            attempts.append(root)
            entered.set()
            return {"ok": False, "version": None, "architecture": "linux/amd64",
                    "error": "sdk_probe_unavailable"}

        monitor = SDKStatusMonitor(probe=failure, retry_seconds=10,
                                   clock=lambda: clock[0])
        self.assertEqual(monitor.status(self.root)["error"], "sdk_probe_in_progress")
        self.assertTrue(entered.wait(1))
        for _ in range(200):
            status = monitor.status(self.root)
            if status.get("error") == "sdk_probe_unavailable":
                break
            time.sleep(0.005)
        self.assertEqual(status["error"], "sdk_probe_unavailable")
        for _ in range(10):
            self.assertEqual(monitor.status(self.root)["error"], "sdk_probe_unavailable")
        self.assertEqual(len(attempts), 1)
        clock[0] += 11
        self.assertEqual(monitor.status(self.root)["error"], "sdk_probe_in_progress")

    def test_probe_timeout_does_not_block_server(self):
        (self.root / "libhcnetsdk.so").write_bytes(b"ELF")
        with patch("nvr.sdk_runtime.subprocess.run", side_effect=subprocess.TimeoutExpired(["probe"], 4)):
            self.assertEqual(sdk_status(self.root)["error"], "sdk_probe_unavailable")


if __name__ == "__main__":
    unittest.main()
