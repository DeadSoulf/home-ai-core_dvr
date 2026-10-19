"""Security contract for the opt-in vendor SDK image; no proprietary ZIP in CI."""
import subprocess
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


class SDK611LocalBuildContract(unittest.TestCase):
    def test_local_image_is_constructed_only_from_explicit_vendor_context(self):
        dockerfile = (ROOT / "Dockerfile.sdk611").read_text(encoding="utf-8")
        self.assertIn("COPY --from=vendor_sdk /lib/", dockerfile)
        self.assertIn("COPY --from=vendor_sdk /include/", dockerfile)
        self.assertIn('org.opencontainers.image.version="1.1.6-sdk611-local"', dockerfile)
        self.assertNotIn("COPY sdk/lib/", dockerfile)
        self.assertNotIn("COPY bin/", dockerfile)
        self.assertIn("COPY --from=native-builder /out/sdk-action", dockerfile)
        self.assertIn("COPY --from=native-builder /out/sdk-stream", dockerfile)
        self.assertIn("sdk611_unsupported.sh", dockerfile)

    def test_private_builder_verifies_exact_archive_and_never_publishes(self):
        script = (ROOT / "tools/build_sdk611_local.sh").read_text(encoding="utf-8")
        self.assertIn("2b8be43fd1cf0d4bd16d4a3b5860c214ee278fd851ea0c59ab0e0b4a9eceee29", script)
        self.assertIn("--build-context", script)
        self.assertIn("--sha256", script)
        self.assertIn("Dockerfile.sdk611", script)
        for forbidden in ("docker push", "docker rm", "kubectl", "systemctl stop"):
            self.assertNotIn(forbidden, script)
        result = subprocess.run(["sh", "-n", str(ROOT / "tools/build_sdk611_local.sh")],
                                capture_output=True, text=True, check=False)
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_unsupported_old_abi_operations_fail_explicitly(self):
        script = ROOT / "tools/sdk611_unsupported.sh"
        result = subprocess.run(["sh", str(script), "status"],
                                capture_output=True, text=True, check=False)
        self.assertEqual(result.returncode, 78)
        self.assertIn("needs a separately validated native adapter", result.stderr)
        self.assertEqual(result.stdout, "")

    def test_native_adapters_are_separately_version_guarded(self):
        stream = (ROOT / "native/sdk_stream_v40.cpp").read_text(encoding="utf-8")
        action = (ROOT / "native/sdk_action_v40.cpp").read_text(encoding="utf-8")
        for source in (stream, action):
            self.assertIn("NET_DVR_Login_V40", source)
            self.assertIn("NET_DVR_SetSDKInitCfg", source)
            self.assertIn("0x06010b28", source)
            self.assertIn("static_assert(sizeof(NET_DVR_USER_LOGIN_INFO) == 416", source)
        self.assertIn("Start digital channel:", stream)
        for operation in ("NET_DVR_CaptureJPEGPicture", "NET_DVR_PTZControlWithSpeed_Other",
                          "NET_DVR_PTZPreset_Other"):
            self.assertIn(operation, action)
        script = ROOT / "tools/verify_hcnetsdk_abi.sh"
        result = subprocess.run(["sh", "-n", str(script)],
                                capture_output=True, text=True, check=False)
        self.assertEqual(result.returncode, 0, result.stderr)


if __name__ == "__main__":
    unittest.main()
