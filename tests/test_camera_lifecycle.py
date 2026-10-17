"""Regression tests for durable NVR camera deletion (stdlib only)."""
import sqlite3
import tempfile
import time
import unittest
from contextlib import closing
from pathlib import Path

from nvr.recorder import NVRRecorderManager


class TestCameraDeletion(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.nvr = NVRRecorderManager(self.root)

    def tearDown(self):
        self.temp.cleanup()

    def camera(self, name="Front"):
        return self.nvr.save_camera({
            "name": name, "source_type": "rtsp",
            "rtsp_url": "rtsp://user:secret@192.168.44.5/live",
            "enabled": False,
        })

    def record(self, camera):
        file = self.root / "recordings" / camera["id"] / "clip.mp4"
        file.parent.mkdir(parents=True, exist_ok=True)
        file.write_bytes(b"test recording")
        with self.nvr._connect() as db:
            db.execute(
                "INSERT INTO recordings(camera_id,path,started_at,ended_at,size_bytes,created_at) VALUES (?,?,?,?,?,?)",
                (camera["id"], str(file.relative_to(self.root)), 1, 2, 14, int(time.time())),
            )
        return file

    def test_default_removal_preserves_history_but_removes_credentials(self):
        camera = self.camera()
        file = self.record(camera)
        self.assertTrue(self.nvr.delete_camera(camera["id"]))
        self.assertIsNone(self.nvr.get_camera(camera["id"]))
        self.assertEqual(self.nvr.list_cameras(), [])
        self.assertTrue(file.exists())
        recordings = self.nvr.list_recordings(camera["id"])
        self.assertEqual(len(recordings), 1)
        with self.nvr._connect() as db:
            row = db.execute("SELECT password,rtsp_url,enabled,deleted_at FROM cameras WHERE id=?",
                             (camera["id"],)).fetchone()
        self.assertEqual(row["password"], "")
        self.assertEqual(row["rtsp_url"], "")
        self.assertEqual(row["enabled"], 0)
        self.assertGreater(row["deleted_at"], 0)
        self.assertFalse(self.nvr.delete_camera(camera["id"]))

    def test_explicit_delete_recordings_removes_files_and_index(self):
        camera = self.camera()
        file = self.record(camera)
        self.assertTrue(self.nvr.delete_camera(camera["id"], delete_recordings=True))
        self.assertFalse(file.exists())
        self.assertEqual(self.nvr.list_recordings(camera["id"]), [])

    def test_existing_v111_database_migrates_without_losing_records(self):
        camera = self.camera()
        file = self.record(camera)
        self.nvr.stop()
        with closing(sqlite3.connect(self.root / "nvr.db")) as db, db:
            db.execute("CREATE TABLE cameras_old AS SELECT id,name,source_type,ip,port,username,password,channel,rtsp_url,enabled,created_at,updated_at FROM cameras")
            db.execute("DROP TABLE recordings")
            db.execute("DROP TABLE cameras")
            db.execute("ALTER TABLE cameras_old RENAME TO cameras")
            db.execute("""CREATE TABLE recordings (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                camera_id TEXT NOT NULL, path TEXT NOT NULL UNIQUE,
                started_at INTEGER NOT NULL, ended_at INTEGER NOT NULL,
                size_bytes INTEGER NOT NULL DEFAULT 0, created_at INTEGER NOT NULL,
                FOREIGN KEY(camera_id) REFERENCES cameras(id) ON DELETE CASCADE
            )""")
            db.execute("INSERT INTO recordings(camera_id,path,started_at,ended_at,size_bytes,created_at) VALUES (?,?,?,?,?,?)",
                       (camera["id"], str(file.relative_to(self.root)), 1, 2, 14, int(time.time())))
        fresh = NVRRecorderManager(self.root)
        self.assertTrue(fresh.get_camera(camera["id"]))
        self.assertEqual(len(fresh.list_recordings(camera["id"])), 1)
        self.assertTrue(fresh.delete_camera(camera["id"]))
        self.assertEqual(len(fresh.list_recordings(camera["id"])), 1)


if __name__ == "__main__":
    unittest.main()
