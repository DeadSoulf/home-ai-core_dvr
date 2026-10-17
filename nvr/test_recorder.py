import sqlite3
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
