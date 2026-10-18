import unittest
from types import SimpleNamespace
from unittest.mock import patch

from nvr.storage import capacity_snapshot


class NVRStorageCapacityTests(unittest.TestCase):
    def test_capacity_and_non_root_available_blocks(self):
        fake = SimpleNamespace(f_frsize=4096, f_bsize=4096,
                               f_blocks=100, f_bfree=30, f_bavail=20)
        with patch("nvr.storage.os.statvfs", return_value=fake):
            result = capacity_snapshot("/data")
        self.assertEqual(result["total_bytes"], 409600)
        self.assertEqual(result["used_bytes"], 286720)
        self.assertEqual(result["free_bytes"], 122880)
        self.assertEqual(result["available_bytes"], 81920)
        self.assertEqual(result["used_percent"], 70)

    def test_statvfs_failure_propagates(self):
        with patch("nvr.storage.os.statvfs", side_effect=OSError("missing")):
            with self.assertRaises(OSError):
                capacity_snapshot("/data")

    def test_rejects_inconsistent_filesystem_values(self):
        fake = SimpleNamespace(f_frsize=4096, f_bsize=4096,
                               f_blocks=10, f_bfree=20, f_bavail=20)
        with patch("nvr.storage.os.statvfs", return_value=fake):
            with self.assertRaises(OSError):
                capacity_snapshot("/data")


if __name__ == "__main__":
    unittest.main()
