import sqlite3
import tempfile
import unittest
from pathlib import Path

from nvr.recorder import NVRRecorderManager


class CameraArchiveTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.manager = NVRRecorderManager(self.root)

    def create_camera(self):
        return self.manager.save_camera({
            "id": "gate", "name": "Front gate", "source_type": "rtsp",
            "rtsp_url": "rtsp://127.0.0.1:8554/live",
            "enabled": False,
        })

    def test_remove_camera_keeps_recordings_visible(self):
        camera = self.create_camera()
        self.assertEqual(camera["name"], "Front gate")
        with self.manager._connect() as db:
            db.execute(
                "INSERT INTO recordings (camera_id, path, started_at, ended_at, size_bytes, created_at)"
                " VALUES (?, ?, ?, ?, ?, ?)",
                ("gate", "recordings/gate/20261017_220000.mp4", 12, 30, 1024, 35),
            )
        self.assertTrue(self.manager.delete_camera("gate"))
        self.assertEqual(self.manager.list_cameras(), [])
        self.assertIsNone(self.manager.get_camera("gate"))
        recordings = self.manager.list_recordings()
        self.assertEqual(len(recordings), 1)
        self.assertEqual(recordings[0]["camera_id"], "gate")
        self.assertEqual(recordings[0]["size_bytes"], 1024)
        restarted = NVRRecorderManager(self.root)
        self.assertEqual(len(restarted.list_recordings()), 1)

    def test_destructive_delete_is_explicit(self):
        self.create_camera()
        record_dir = self.root / "recordings" / "gate"
        record_dir.mkdir(parents=True, exist_ok=True)
        (record_dir / "movie.mp4").write_bytes(b"clip")
        self.assertTrue(self.manager.delete_camera("gate", delete_recordings=True))
        self.assertFalse(record_dir.exists())
        self.assertEqual(self.manager.list_recordings(), [])
        self.assertFalse(self.manager.delete_camera("gate"))

    def test_existing_pre_deleted_schema_migrates_without_reset(self):
        other = self.root / "legacy"
        other.mkdir(parents=True, exist_ok=True)
        db = sqlite3.connect(other / "nvr.db")
        db.execute(
            "CREATE TABLE cameras (id TEXT PRIMARY KEY, name TEXT NOT NULL,"
            " source_type TEXT NOT NULL, ip TEXT NOT NULL DEFAULT '',"
            " port INTEGER NOT NULL DEFAULT 8000, username TEXT NOT NULL DEFAULT '',"
            " password TEXT NOT NULL DEFAULT '', channel INTEGER NOT NULL DEFAULT 1,"
            " rtsp_url TEXT NOT NULL DEFAULT '', enabled INTEGER NOT NULL DEFAULT 1,"
            " created_at INTEGER NOT NULL, updated_at INTEGER NOT NULL)"
        )
        db.execute("INSERT INTO cameras VALUES "
                   "('original','Old Camera','rtsp','',554,'','','1',"
                   "'rtsp://127.0.0.1/old',0,1,1)")
        db.commit()
        db.close()
        old = NVRRecorderManager(other)
        self.assertEqual(old.list_cameras()[0]["name"], "Old Camera")
        self.assertTrue(old.delete_camera("original"))
        self.assertEqual(old.list_cameras(), [])


if __name__ == "__main__":
    unittest.main()
