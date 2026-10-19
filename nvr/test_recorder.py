import os
import sqlite3
import time
from unittest.mock import patch
import tempfile
import unittest
from pathlib import Path

from nvr.recorder import NVRRecorderManager


class RecorderDeletionTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.manager = NVRRecorderManager(self.tmp.name)

    def tearDown(self):
        self.manager.stop_event.set()
        self.tmp.cleanup()

    def add_rtsp(self, camera_id="cam01"):
        self.manager.save_camera({
            "id": camera_id,
            "name": "Garage",
            "source_type": "rtsp",
            "rtsp_url": "rtsp://192.168.1.2/stream1",
            "enabled": False,
        })
        return camera_id

    def add_archived_file(self, camera_id):
        folder = Path(self.tmp.name) / "recordings" / camera_id
        folder.mkdir(parents=True, exist_ok=True)
        file = folder / "20261017_120000.mp4"
        file.write_bytes(b"test recording")
        with self.manager._connect() as db:
            db.execute(
                """INSERT INTO recordings
                   (camera_id, path, started_at, ended_at, size_bytes, created_at)
                   VALUES (?, ?, 1, 2, 14, 3)""",
                (camera_id, "recordings/" + camera_id + "/" + file.name),
            )
        return file

    def test_soft_delete_keeps_archive_and_frees_slot(self):
        self.manager.max_cameras = 1
        camera_id = self.add_rtsp()
        file = self.add_archived_file(camera_id)
        self.assertTrue(self.manager.delete_camera(camera_id, delete_recordings=False))
        self.assertEqual(self.manager.list_cameras(), [])
        self.assertEqual(self.manager.get_camera(camera_id), None)
        self.assertEqual(len(self.manager.list_recordings()), 1)
        self.assertTrue(file.exists())
        self.assertFalse(self.manager.delete_camera(camera_id))
        self.add_rtsp("cam02")
        self.assertEqual(len(self.manager.list_cameras()), 1)

    def test_permanent_delete_requires_explicit_flag(self):
        camera_id = self.add_rtsp()
        file = self.add_archived_file(camera_id)
        self.assertTrue(self.manager.delete_camera(camera_id, delete_recordings=True))
        self.assertFalse(file.exists())
        self.assertEqual(self.manager.list_recordings(), [])


    def test_archive_pruning_uses_free_space_and_keeps_recent_segments(self):
        camera_id = self.add_rtsp()
        old = self.add_archived_file(camera_id)
        recent = old.with_name("20261018_140000.mp4")
        recent.write_bytes(b"new recording")
        with self.manager._connect() as db:
            db.execute(
                "INSERT INTO recordings (camera_id, path, started_at, ended_at, size_bytes, created_at) "
                "VALUES (?, ?, ?, ?, ?, ?)",
                (camera_id, "recordings/" + camera_id + "/" + recent.name,
                 10, 12, recent.stat().st_size, 15),
            )
        os.utime(old, (time.time()-3600, time.time()-3600))
        self.manager.min_free_gb = 20
        self.manager.retention_days = 0
        self.manager.max_storage_gb = 0
        calls = [0]

        def fake_statvfs(path):
            calls[0] += 1
            return type("Stat", (), {
                "f_frsize": 4096,
                "f_bavail": 0 if calls[0] == 1 else 6_000_000,
            })()

        with patch("nvr.recorder.os.statvfs", side_effect=fake_statvfs):
            removed = self.manager.enforce_retention()
        self.assertEqual(removed, 1)
        self.assertFalse(old.exists())
        self.assertTrue(recent.exists())
        self.assertEqual(len(self.manager.list_recordings()), 1)

    def test_retention_disabled_preserves_old_archive(self):
        camera_id = self.add_rtsp()
        old = self.add_archived_file(camera_id)
        os.utime(old, (time.time()-3600, time.time()-3600))
        self.manager.min_free_gb = 0
        self.manager.retention_days = 0
        self.manager.max_storage_gb = 0
        self.assertEqual(self.manager.enforce_retention(), 0)
        self.assertTrue(old.exists())

    def test_retention_rejects_symlinks_and_unsafe_database_paths(self):
        camera_id = self.add_rtsp()
        victim = Path(self.tmp.name) / "keep.mp4"
        victim.write_bytes(b"must not be deleted")
        folder = Path(self.tmp.name) / "recordings" / camera_id
        folder.mkdir(parents=True, exist_ok=True)
        symlink = folder / "outside.mp4"
        symlink.symlink_to(victim)
        self.assertFalse(self.manager._delete_recording_row(
            {"id": 1, "path": "recordings/" + camera_id + "/outside.mp4"}))
        self.assertFalse(self.manager._delete_recording_row(
            {"id": 1, "path": "../keep.mp4"}))
        self.assertFalse(self.manager._delete_recording_row(
            {"id": 1, "path": "recordings/" + camera_id + "/../../keep.mp4"}))
        self.assertTrue(victim.exists())
        self.manager.scan_recordings(camera_id)
        self.assertEqual(self.manager.list_recordings(), [])

    def test_existing_database_schema_is_migrated(self):
        self.manager._connect().close()
        with self.manager._connect() as db:
            db.execute("ALTER TABLE cameras DROP COLUMN deleted")
        self.manager._init_db()
        with self.manager._connect() as db:
            columns = [row["name"] for row in db.execute("PRAGMA table_info(cameras)")]
        self.assertIn("deleted", columns)
        self.add_rtsp()
        self.assertTrue(self.manager.delete_camera("cam01"))
        self.assertEqual(self.manager.list_cameras(), [])


if __name__ == "__main__":
    unittest.main()
