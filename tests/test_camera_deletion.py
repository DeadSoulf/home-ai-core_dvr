import tempfile
import unittest
from pathlib import Path
from unittest import mock

from nvr.recorder import NVRRecorderManager


class CameraDeletionTests(unittest.TestCase):
    def test_delete_preserves_archived_video_and_clears_credentials(self):
        with tempfile.TemporaryDirectory() as directory:
            nvr = NVRRecorderManager(directory)
            with mock.patch.object(nvr, "restart_camera"), mock.patch.object(nvr, "stop_camera"):
                camera = nvr.save_camera({
                    "id": "front", "name": "Front door", "source_type": "rtsp",
                    "rtsp_url": "rtsp://admin:secret@192.168.2.5/main",
                })
                self.assertEqual(camera["id"], "front")
                video = Path(directory) / "recordings/front/20261017_190000.mp4"
                video.parent.mkdir(parents=True, exist_ok=True)
                video.write_bytes(b"video")
                with nvr._connect() as db:
                    db.execute(
                        "INSERT INTO recordings (camera_id,path,started_at,ended_at,size_bytes,created_at) "
                        "VALUES (?,?,?,?,?,?)",
                        ("front", "recordings/front/20261017_190000.mp4", 10, 20, 5, 30),
                    )
                self.assertTrue(nvr.delete_camera("front", delete_recordings=False))
                self.assertEqual(nvr.list_cameras(), [])
                self.assertIsNone(nvr.get_camera("front"))
                self.assertTrue(video.is_file())
                archived = nvr.list_recordings()
                self.assertEqual(len(archived), 1)
                self.assertEqual(archived[0]["camera_id"], "front")
                with nvr._connect() as db:
                    values = db.execute(
                        "SELECT password,rtsp_url,deleted_at FROM cameras WHERE id = ?", ("front",)
                    ).fetchone()
                    self.assertEqual(values["password"], "")
                    self.assertEqual(values["rtsp_url"], "")
                    self.assertGreater(values["deleted_at"], 0)

    def test_reopen_old_database_schema_without_losing_records(self):
        import sqlite3
        with tempfile.TemporaryDirectory() as directory:
            db = sqlite3.connect(str(Path(directory) / "nvr.db"))
            db.executescript("""
                CREATE TABLE cameras (
                    id TEXT PRIMARY KEY, name TEXT NOT NULL,
                    source_type TEXT NOT NULL DEFAULT 'hikvision',
                    ip TEXT NOT NULL DEFAULT '', port INTEGER NOT NULL DEFAULT 8000,
                    username TEXT NOT NULL DEFAULT '', password TEXT NOT NULL DEFAULT '',
                    channel INTEGER NOT NULL DEFAULT 1, rtsp_url TEXT NOT NULL DEFAULT '',
                    enabled INTEGER NOT NULL DEFAULT 1, created_at INTEGER NOT NULL,
                    updated_at INTEGER NOT NULL
                );
                INSERT INTO cameras (id,name,created_at,updated_at)
                VALUES ('legacy','Existing',1,1);
            """)
            db.close()
            nvr = NVRRecorderManager(directory)
            self.assertEqual(len(nvr.list_cameras()), 1)
            self.assertEqual(nvr.list_cameras()[0]["id"], "legacy")


if __name__ == "__main__":
    unittest.main()
