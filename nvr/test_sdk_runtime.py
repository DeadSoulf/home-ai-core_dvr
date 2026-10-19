import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from nvr.sdk_runtime import decode_sdk_version, sdk_status


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

    def test_probe_timeout_does_not_block_server(self):
        (self.root / "libhcnetsdk.so").write_bytes(b"ELF")
        with patch("nvr.sdk_runtime.subprocess.run", side_effect=subprocess.TimeoutExpired(["probe"], 4)):
            self.assertEqual(sdk_status(self.root)["error"], "sdk_probe_unavailable")


if __name__ == "__main__":
    unittest.main()
