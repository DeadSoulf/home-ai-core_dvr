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
        for setting in ("NVR_MAX_STORAGE_GB=0", "NVR_RETENTION_DAYS=0", "NVR_MIN_FREE_GB=20", "NVR_SDK_REQUIRED_VERSION=6.1.11.40"):
            self.assertIn(setting, dockerfile)

    def test_private_builder_verifies_exact_archive_and_never_publishes(self):
        script = (ROOT / "tools/build_sdk611_local.sh").read_text(encoding="utf-8")
        self.assertIn("2b8be43fd1cf0d4bd16d4a3b5860c214ee278fd851ea0c59ab0e0b4a9eceee29", script)
        self.assertIn("--build-context", script)
        self.assertIn("--sha256", script)
        self.assertIn("Dockerfile.sdk611", script)
        # Only the disposable container ID created by this script may be removed.
        self.assertIn('test_container=$(docker run -d --rm', script)
        self.assertIn('docker rm -f "$test_container"', script)
        for required in ("--network none", "--read-only", "--cap-drop ALL",
                         "--security-opt no-new-privileges",
                         "--mount \"type=bind,src=$test_data,dst=/data\"",
                         '/api/nvr/sdk', '"6.1.11.40"'):
            self.assertIn(required, script)
        for forbidden in ("docker push", "docker rm home-ai-module", "kubectl",
                          "systemctl stop", "/var/lib/home-ai-modules/nvr.module"):
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

    def test_ffmpeg_pipe_paths_preserve_h264_frames(self):
        # In FFmpeg, +genpts+nobuffer can discard packets when the HCNetSDK
        # MPEG-PS stream arrives through pipe:0; +genpts preserves the stream.
        recorder = (ROOT / "nvr/recorder.py").read_text(encoding="utf-8")
        web = (ROOT / "web/server.py").read_text(encoding="utf-8")
        for code in (recorder, web):
            self.assertNotIn("+genpts+nobuffer", code)
        self.assertEqual(recorder.count('"-fflags", "+genpts"'), 1)
        self.assertEqual(web.count('"-fflags", "+genpts"'), 2)

    def test_vendor_status_does_not_block_nvr_http_and_reports_capabilities(self):
        server = (ROOT / "web/server.py").read_text(encoding="utf-8")
        self.assertNotIn('run_cmd(["/usr/local/bin/sdk-smoke"]', server)
        self.assertIn('sdk_info = sdk_status_async()', server)
        self.assertIn('unsupported_sdk_post(SDK_PROFILE, clean)', server)
        self.assertIn('sdk_features', server)
        ui = (ROOT / "web/app.js").read_text(encoding="utf-8")
        self.assertIn('applySDKCapabilities(data.sdk_features)', ui)
        self.assertIn('min_free_gb', ui)

    def test_hardware_validation_is_opt_in_and_cannot_touch_nvr_state(self):
        script = (ROOT / "tools/test_sdk611_camera.sh").read_text(encoding="utf-8")
        check = subprocess.run(["sh", "-n", str(ROOT / "tools/test_sdk611_camera.sh")],
                               capture_output=True, text=True)
        self.assertEqual(check.returncode, 0, check.stderr)
        for required in ("--read-only", "--network host", "--cap-drop ALL",
                         "--entrypoint /usr/local/bin/sdk-login-test",
                         "--entrypoint /usr/local/bin/sdk-stream",
                         "--env HCNET_PASSWORD", "timeout --signal",
                         "ffprobe", "sample.mp4"):
            self.assertIn(required, script)
        for forbidden in ("docker push", "docker rm -f", "systemctl",
                          "/var/lib/home-ai-modules", "NET_DVR_PTZ"):
            self.assertNotIn(forbidden, script)

    def test_native_adapters_are_separately_version_guarded(self):
        stream = (ROOT / "native/sdk_stream_v40.cpp").read_text(encoding="utf-8")
        action = (ROOT / "native/sdk_action_v40.cpp").read_text(encoding="utf-8")
        for source in (stream, action):
            self.assertIn("NET_DVR_Login_V40", source)
            self.assertIn("NET_DVR_SetSDKInitCfg", source)
            self.assertIn("0x06010b28", source)
            self.assertIn("static_assert(sizeof(NET_DVR_USER_LOGIN_INFO) == 416", source)
        self.assertIn("Start digital channel:", stream)
        # Linux SDK defines HWND as an integer; nullptr fails compilation.
        self.assertIn("preview.hPlayWnd = 0;", stream)
        self.assertNotIn("preview.hPlayWnd = nullptr;", stream)
        for operation in ("NET_DVR_CaptureJPEGPicture", "NET_DVR_PTZControlWithSpeed_Other",
                          "NET_DVR_PTZPreset_Other"):
            self.assertIn(operation, action)
        script = ROOT / "tools/verify_hcnetsdk_abi.sh"
        result = subprocess.run(["sh", "-n", str(script)],
                                capture_output=True, text=True, check=False)
        self.assertEqual(result.returncode, 0, result.stderr)


if __name__ == "__main__":
    unittest.main()
