import hashlib
import os
import struct
import tempfile
import unittest
import zipfile
from pathlib import Path

from tools.stage_hcnetsdk import REQUIRED, stage_archive


ROOT = "EN-HCNetSDKV6.1.11.40_build20260922_linux64"


def fake_elf(marker=b""):
    header = bytearray(64)
    header[0:6] = b"\x7fELF\x02\x01"
    header[16:18] = struct.pack("<H", 3)
    header[18:20] = struct.pack("<H", 62)
    return bytes(header) + marker


class VendorSDKArchiveTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.archive = Path(self.temp.name) / "sdk.zip"
        self.out = Path(self.temp.name) / "staged"

    def create_archive(self, extras=None, omit=None):
        with zipfile.ZipFile(self.archive, "w", zipfile.ZIP_DEFLATED) as z:
            for filename in REQUIRED:
                if filename == omit:
                    continue
                relative = "incEn/" + filename.split("/")[-1] if filename.startswith("include/") else filename
                data = (b"NET_DVR_Login_V40 cbLoginResultV40" if filename.endswith(".h")
                        else fake_elf(b"The HCNetSDK version is 6.1.11.40"
                                      if filename == "lib/libhcnetsdk.so" else b""))
                z.writestr(ROOT + "/" + relative, data)
            for filename, data in (extras or {}).items():
                z.writestr(filename, data)

    def test_valid_archive_and_checksum(self):
        self.create_archive()
        digest = hashlib.sha256(self.archive.read_bytes()).hexdigest()
        result = stage_archive(self.archive, self.out, digest)
        self.assertEqual(result["sdk_version"], "6.1.11.40")
        self.assertEqual(len(result["files"]), len(REQUIRED))
        self.assertTrue((self.out / "manifest.json").exists())
        with self.assertRaisesRegex(ValueError, "refusing to replace"):
            stage_archive(self.archive, self.out)

    def test_rejects_missing_component_and_does_not_create_destination(self):
        self.create_archive(omit="lib/libssl.so.3")
        with self.assertRaisesRegex(ValueError, "missing components"):
            stage_archive(self.archive, self.out)
        self.assertFalse(self.out.exists())

    def test_rejects_archive_checksum_mismatch(self):
        self.create_archive()
        with self.assertRaisesRegex(ValueError, "SHA-256 mismatch"):
            stage_archive(self.archive, self.out, "0" * 64)

    def test_rejects_duplicate_library(self):
        self.create_archive({"other_root/lib/libhcnetsdk.so": fake_elf()})
        with self.assertRaisesRegex(ValueError, "unexpected SDK archive root"):
            stage_archive(self.archive, self.out)

    def test_rejects_unsafe_member(self):
        self.create_archive({ROOT + "/lib/../../escape.so": fake_elf()})
        with self.assertRaisesRegex(ValueError, "unsafe|duplicate|unexpected"):
            stage_archive(self.archive, self.out)
        self.assertFalse((Path(self.temp.name) / "escape.so").exists())

    def test_rejects_non_elf_binary(self):
        self.create_archive({ROOT + "/lib/libtampered.so": b"not an ELF"})
        with self.assertRaisesRegex(ValueError, "non-ELF"):
            stage_archive(self.archive, self.out)


if __name__ == "__main__":
    unittest.main()
