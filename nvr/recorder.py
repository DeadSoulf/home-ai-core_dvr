#!/usr/bin/env python3
import json
import os
import re
import shutil
import sqlite3
import subprocess
import threading
import time
import uuid
from pathlib import Path


class ClosingSQLiteConnection(sqlite3.Connection):
    """Commit/rollback AND close when used in a with block.

    sqlite3.Connection.__exit__ does not close the file descriptor on its own.
    Long-running NVR operations must not accumulate idle SQLite handles.
    """

    def __exit__(self, exc_type, exc_value, traceback):
        try:
            return super().__exit__(exc_type, exc_value, traceback)
        finally:
            self.close()


class NVRRecorderManager:
    def __init__(self, output_root):
        self.output_root = Path(output_root)
        self.recordings_root = self.output_root / "recordings"
        self.logs_root = self.output_root / "logs"
        self.db_path = self.output_root / "nvr.db"
        self.segment_seconds = max(30, int(os.environ.get("NVR_SEGMENT_SECONDS", "300")))
        self.retention_days = max(0, int(os.environ.get("NVR_RETENTION_DAYS", "7")))
        self.max_storage_gb = max(0.0, float(os.environ.get("NVR_MAX_STORAGE_GB", "50")))
        self.max_cameras = max(1, min(32, int(os.environ.get("NVR_MAX_CAMERAS", "32"))))
        self.lock = threading.RLock()
        self.processes = {}
        self.stop_event = threading.Event()
        self.maintenance_thread = None

        self.recordings_root.mkdir(parents=True, exist_ok=True)
        self.logs_root.mkdir(parents=True, exist_ok=True)
        self._init_db()

    def _connect(self):
        db = sqlite3.connect(self.db_path, timeout=15, factory=ClosingSQLiteConnection)
        db.row_factory = sqlite3.Row
        db.execute("PRAGMA journal_mode=WAL")
        db.execute("PRAGMA foreign_keys=ON")
        return db

    def _init_db(self):
        with self._connect() as db:
            db.executescript(
                """
                CREATE TABLE IF NOT EXISTS cameras (
                    id TEXT PRIMARY KEY,
                    name TEXT NOT NULL,
                    source_type TEXT NOT NULL DEFAULT 'hikvision',
                    ip TEXT NOT NULL DEFAULT '',
                    port INTEGER NOT NULL DEFAULT 8000,
                    username TEXT NOT NULL DEFAULT '',
                    password TEXT NOT NULL DEFAULT '',
                    channel INTEGER NOT NULL DEFAULT 1,
                    rtsp_url TEXT NOT NULL DEFAULT '',
                    enabled INTEGER NOT NULL DEFAULT 1,
                    deleted INTEGER NOT NULL DEFAULT 0,
                    created_at INTEGER NOT NULL,
                    updated_at INTEGER NOT NULL
                );

                CREATE TABLE IF NOT EXISTS recordings (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    camera_id TEXT NOT NULL,
                    path TEXT NOT NULL UNIQUE,
                    started_at INTEGER NOT NULL,
                    ended_at INTEGER NOT NULL,
                    size_bytes INTEGER NOT NULL DEFAULT 0,
                    created_at INTEGER NOT NULL,
                    FOREIGN KEY(camera_id) REFERENCES cameras(id) ON DELETE CASCADE
                );

                CREATE INDEX IF NOT EXISTS idx_recordings_camera_time
                    ON recordings(camera_id, started_at DESC);
                """
            )
            # Preserve existing NVR databases. Older installations predate
            # the soft-delete column; add it without resetting credentials,
            # camera configuration, or recording indices.
            columns = {row["name"] for row in db.execute("PRAGMA table_info(cameras)")}
            if "deleted" not in columns:
                db.execute("ALTER TABLE cameras ADD COLUMN deleted INTEGER NOT NULL DEFAULT 0")

    @staticmethod
    def _safe_camera_id(value):
        value = re.sub(r"[^a-zA-Z0-9_.-]+", "-", str(value or "")).strip(".-")
        return value[:64]

    def _public_camera(self, row):
        item = dict(row)
        item.pop("password", None)
        item.pop("deleted", None)
        item["enabled"] = bool(item.get("enabled"))
        item["recording"] = self.is_recording(item["id"])
        return item

    def list_cameras(self):
        with self._connect() as db:
            rows = db.execute("SELECT * FROM cameras WHERE deleted = 0 ORDER BY name COLLATE NOCASE, id").fetchall()
        return [self._public_camera(r) for r in rows]

    def get_camera(self, camera_id, include_secret=False):
        camera_id = self._safe_camera_id(camera_id)
        with self._connect() as db:
            row = db.execute("SELECT * FROM cameras WHERE id = ? AND deleted = 0", (camera_id,)).fetchone()
        if not row:
            return None
        return dict(row) if include_secret else self._public_camera(row)

    def save_camera(self, data):
        name = str(data.get("name") or "").strip()
        source_type = str(data.get("source_type") or "hikvision").strip().lower()
        if source_type not in {"hikvision", "rtsp"}:
            raise ValueError("source_type должен быть hikvision или rtsp")
        if not name:
            raise ValueError("Укажите название камеры")

        camera_id = self._safe_camera_id(data.get("id")) or uuid.uuid4().hex[:12]
        existing = self.get_camera(camera_id, include_secret=True)

        if not existing:
            with self._connect() as db:
                camera_count = int(db.execute("SELECT COUNT(*) AS n FROM cameras").fetchone()["n"])
            if camera_count >= self.max_cameras:
                raise ValueError(f"Достигнут лимит NVR: максимум {self.max_cameras} камер")

        ip = str(data.get("ip", existing.get("ip", "") if existing else "")).strip()
        username = str(data.get("username", data.get("user", existing.get("username", "") if existing else ""))).strip()
        password = str(data.get("password", existing.get("password", "") if existing else ""))
        rtsp_url = str(data.get("rtsp_url", existing.get("rtsp_url", "") if existing else "")).strip()
        port = int(data.get("port", existing.get("port", 8000) if existing else 8000) or 8000)
        channel = int(data.get("channel", existing.get("channel", 1) if existing else 1) or 1)
        enabled = 1 if bool(data.get("enabled", existing.get("enabled", True) if existing else True)) else 0

        if not 1 <= port <= 65535:
            raise ValueError("Некорректный порт")
        if channel < 1:
            raise ValueError("Некорректный канал")

        if source_type == "hikvision":
            if not ip or not username or not password:
                raise ValueError("Для Hikvision нужны IP, пользователь и пароль")
        else:
            if not rtsp_url.lower().startswith(("rtsp://", "rtsps://")):
                raise ValueError("Для RTSP укажите rtsp:// адрес")

        now = int(time.time())
        created = existing.get("created_at", now) if existing else now
        with self._connect() as db:
            db.execute(
                """
                INSERT INTO cameras
                    (id, name, source_type, ip, port, username, password, channel, rtsp_url, enabled, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(id) DO UPDATE SET
                    name=excluded.name,
                    source_type=excluded.source_type,
                    ip=excluded.ip,
                    port=excluded.port,
                    username=excluded.username,
                    password=excluded.password,
                    channel=excluded.channel,
                    rtsp_url=excluded.rtsp_url,
                    enabled=excluded.enabled,
                    deleted=0,
                    updated_at=excluded.updated_at
                """,
                (camera_id, name, source_type, ip, port, username, password, channel, rtsp_url, enabled, created, now),
            )

        if enabled:
            self.restart_camera(camera_id)
        else:
            self.stop_camera(camera_id)

        return self.get_camera(camera_id)

    def delete_camera(self, camera_id, delete_recordings=False):
        camera_id = self._safe_camera_id(camera_id)
        if not camera_id or not self.get_camera(camera_id):
            return False
        self.stop_camera(camera_id)
        with self._connect() as db:
            if delete_recordings:
                # Explicit destructive request: remove recording files first,
                # but never discard their DB references if deletion failed.
                recordings = self.recordings_root / camera_id
                if recordings.exists():
                    shutil.rmtree(recordings)
                db.execute("DELETE FROM recordings WHERE camera_id = ?", (camera_id,))
                cur = db.execute("DELETE FROM cameras WHERE id = ?", (camera_id,))
            else:
                # Hidden from the active camera list while retaining its
                # metadata and archive history for playback and export.
                cur = db.execute(
                    "UPDATE cameras SET deleted = 1, enabled = 0, updated_at = ?"
                    " WHERE id = ? AND deleted = 0",
                    (int(time.time()), camera_id),
                )
        return cur.rowcount > 0

    def _recording_pattern(self, camera_id):
        target = self.recordings_root / camera_id
        target.mkdir(parents=True, exist_ok=True)
        return str(target / "%Y%m%d_%H%M%S.mp4")

    def _ffmpeg_segment_args(self, pattern):
        return [
            "-map", "0:v:0",
            "-map", "0:a:0?",
            "-c", "copy",
            "-f", "segment",
            "-segment_time", str(self.segment_seconds),
            "-reset_timestamps", "1",
            "-strftime", "1",
            "-segment_format", "mp4",
            pattern,
        ]

    def start_camera(self, camera_id):
        camera = self.get_camera(camera_id, include_secret=True)
        if not camera:
            raise ValueError("Камера не найдена")
        if not camera.get("enabled"):
            raise ValueError("Камера выключена")

        with self.lock:
            if self.is_recording(camera_id):
                return True
            self._stop_camera_locked(camera_id)

            pattern = self._recording_pattern(camera_id)
            log_path = self.logs_root / f"recorder_{camera_id}.log"
            log_handle = log_path.open("ab", buffering=0)

            sdk = None
            if camera["source_type"] == "hikvision":
                env = os.environ.copy()
                env.update({
                    "HCNET_IP": camera["ip"],
                    "HCNET_PORT": str(camera["port"]),
                    "HCNET_USER": camera["username"],
                    "HCNET_PASSWORD": camera["password"],
                    "HCNET_CHANNEL": str(camera["channel"]),
                    "HCNET_STREAM_TYPE": "0",
                })
                sdk = subprocess.Popen(
                    ["/usr/local/bin/sdk-stream"],
                    env=env,
                    stdout=subprocess.PIPE,
                    stderr=log_handle,
                    bufsize=0,
                )
                ffmpeg_args = [
                    "ffmpeg", "-hide_banner", "-loglevel", "warning",
                    "-fflags", "+genpts+nobuffer",
                    "-i", "pipe:0",
                    *self._ffmpeg_segment_args(pattern),
                ]
                ffmpeg = subprocess.Popen(
                    ffmpeg_args,
                    stdin=sdk.stdout,
                    stdout=subprocess.DEVNULL,
                    stderr=log_handle,
                )
                if sdk.stdout:
                    sdk.stdout.close()
            else:
                ffmpeg_args = [
                    "ffmpeg", "-hide_banner", "-loglevel", "warning",
                    "-rtsp_transport", "tcp",
                    "-i", camera["rtsp_url"],
                    *self._ffmpeg_segment_args(pattern),
                ]
                ffmpeg = subprocess.Popen(
                    ffmpeg_args,
                    stdout=subprocess.DEVNULL,
                    stderr=log_handle,
                )

            self.processes[camera_id] = {
                "sdk": sdk,
                "ffmpeg": ffmpeg,
                "log": log_handle,
                "started_at": int(time.time()),
            }
        return True

    def _stop_camera_locked(self, camera_id):
        proc = self.processes.pop(camera_id, None)
        if not proc:
            return False
        for key in ("ffmpeg", "sdk"):
            p = proc.get(key)
            if not p:
                continue
            try:
                if p.poll() is None:
                    p.terminate()
                    p.wait(timeout=5)
            except Exception:
                try:
                    p.kill()
                except Exception:
                    pass
        try:
            proc.get("log").close()
        except Exception:
            pass
        return True

    def stop_camera(self, camera_id):
        camera_id = self._safe_camera_id(camera_id)
        with self.lock:
            stopped = self._stop_camera_locked(camera_id)
        self.scan_recordings(camera_id)
        return stopped

    def restart_camera(self, camera_id):
        self.stop_camera(camera_id)
        return self.start_camera(camera_id)

    def is_recording(self, camera_id):
        with self.lock:
            proc = self.processes.get(camera_id)
            if not proc:
                return False
            ffmpeg = proc.get("ffmpeg")
            sdk = proc.get("sdk")
            if not ffmpeg or ffmpeg.poll() is not None:
                return False
            if sdk is not None and sdk.poll() is not None:
                return False
            return True

    def _probe_duration(self, path):
        try:
            p = subprocess.run(
                [
                    "ffprobe", "-v", "error",
                    "-show_entries", "format=duration",
                    "-of", "default=noprint_wrappers=1:nokey=1",
                    str(path),
                ],
                stdout=subprocess.PIPE,
                stderr=subprocess.DEVNULL,
                text=True,
                timeout=8,
                check=False,
            )
            return max(0.0, float((p.stdout or "0").strip() or 0))
        except Exception:
            return 0.0

    def scan_recordings(self, camera_id=None):
        now = time.time()
        roots = []
        if camera_id:
            roots = [self.recordings_root / self._safe_camera_id(camera_id)]
        else:
            roots = [p for p in self.recordings_root.iterdir() if p.is_dir()]

        added = 0
        with self._connect() as db:
            for root in roots:
                if not root.exists():
                    continue
                cid = root.name
                if not self.get_camera(cid):
                    continue
                for path in root.glob("*.mp4"):
                    try:
                        st = path.stat()
                    except FileNotFoundError:
                        continue
                    if now - st.st_mtime < 3:
                        continue
                    rel = str(path.relative_to(self.output_root))
                    exists = db.execute("SELECT 1 FROM recordings WHERE path = ?", (rel,)).fetchone()
                    if exists:
                        continue
                    try:
                        started = int(time.mktime(time.strptime(path.stem, "%Y%m%d_%H%M%S")))
                    except Exception:
                        started = int(st.st_mtime)
                    duration = self._probe_duration(path)
                    ended = max(started, int(started + duration)) if duration > 0 else int(st.st_mtime)
                    db.execute(
                        """
                        INSERT OR IGNORE INTO recordings
                            (camera_id, path, started_at, ended_at, size_bytes, created_at)
                        VALUES (?, ?, ?, ?, ?, ?)
                        """,
                        (cid, rel, started, ended, st.st_size, int(time.time())),
                    )
                    added += 1
        return added

    def list_recordings(self, camera_id=None, start=None, end=None, limit=500):
        self.scan_recordings(camera_id)
        limit = max(1, min(int(limit or 500), 5000))
        clauses = []
        args = []
        if camera_id:
            clauses.append("camera_id = ?")
            args.append(self._safe_camera_id(camera_id))
        if start is not None:
            clauses.append("ended_at >= ?")
            args.append(int(start))
        if end is not None:
            clauses.append("started_at <= ?")
            args.append(int(end))
        where = (" WHERE " + " AND ".join(clauses)) if clauses else ""
        with self._connect() as db:
            rows = db.execute(
                f"SELECT * FROM recordings{where} ORDER BY started_at DESC LIMIT ?",
                (*args, limit),
            ).fetchall()
        items = []
        for row in rows:
            item = dict(row)
            item["url"] = "/output/" + item["path"].replace(os.sep, "/")
            items.append(item)
        return items

    def _delete_recording_row(self, row):
        path = self.output_root / row["path"]
        try:
            path.unlink(missing_ok=True)
        except Exception:
            return False
        with self._connect() as db:
            db.execute("DELETE FROM recordings WHERE id = ?", (row["id"],))
        return True

    def enforce_retention(self):
        self.scan_recordings()
        removed = 0
        now = int(time.time())

        if self.retention_days > 0:
            cutoff = now - self.retention_days * 86400
            with self._connect() as db:
                rows = db.execute(
                    "SELECT * FROM recordings WHERE ended_at < ? ORDER BY ended_at ASC",
                    (cutoff,),
                ).fetchall()
            for row in rows:
                if self._delete_recording_row(row):
                    removed += 1

        if self.max_storage_gb > 0:
            max_bytes = int(self.max_storage_gb * 1024 * 1024 * 1024)
            with self._connect() as db:
                rows = db.execute("SELECT * FROM recordings ORDER BY started_at ASC").fetchall()
            total = sum(int(r["size_bytes"] or 0) for r in rows)
            for row in rows:
                if total <= max_bytes:
                    break
                size = int(row["size_bytes"] or 0)
                if self._delete_recording_row(row):
                    total -= size
                    removed += 1
        return removed

    def storage_bytes(self):
        total = 0
        for path in self.recordings_root.rglob("*.mp4"):
            try:
                total += path.stat().st_size
            except OSError:
                pass
        return total

    def status(self):
        cameras = self.list_cameras()
        with self._connect() as db:
            count = db.execute("SELECT COUNT(*) AS n FROM recordings").fetchone()["n"]
        active = sum(1 for camera in cameras if camera["recording"])
        return {
            "ok": True,
            "service": "h.a.c._nvr",
            "cameras": len(cameras),
            "max_cameras": self.max_cameras,
            "camera_slots_free": max(0, self.max_cameras - len(cameras)),
            "active_recorders": active,
            "recordings": int(count),
            "storage_bytes": self.storage_bytes(),
            "segment_seconds": self.segment_seconds,
            "retention_days": self.retention_days,
            "max_storage_gb": self.max_storage_gb,
            "database": str(self.db_path),
        }

    def _maintenance_loop(self):
        last_retention = 0
        while not self.stop_event.wait(10):
            try:
                self.scan_recordings()
                cameras = self.list_cameras()
                for camera in cameras:
                    if camera["enabled"] and not self.is_recording(camera["id"]):
                        try:
                            self.start_camera(camera["id"])
                        except Exception:
                            pass
                if time.time() - last_retention > 300:
                    self.enforce_retention()
                    last_retention = time.time()
            except Exception:
                pass

    def start(self):
        self.stop_event.clear()
        for camera in self.list_cameras():
            if camera["enabled"]:
                try:
                    self.start_camera(camera["id"])
                except Exception:
                    pass
        if not self.maintenance_thread or not self.maintenance_thread.is_alive():
            self.maintenance_thread = threading.Thread(
                target=self._maintenance_loop,
                name="nvr-maintenance",
                daemon=True,
            )
            self.maintenance_thread.start()

    def stop(self):
        self.stop_event.set()
        with self.lock:
            ids = list(self.processes.keys())
        for camera_id in ids:
            self.stop_camera(camera_id)
        if self.maintenance_thread and self.maintenance_thread.is_alive():
            self.maintenance_thread.join(timeout=3)
        self.scan_recordings()
