#!/usr/bin/env python3
import hashlib
import json
import mimetypes
import os
import shutil
import subprocess
import threading
import time
from collections import deque
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import unquote, parse_qs, urlparse
import sys

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from nvr.recorder import NVRRecorderManager
from nvr.storage import capacity_snapshot
from nvr.sdk_runtime import sdk_status
from nvr.validation import normalize_sdk_channel

WEB_ROOT = Path("/app/web")
OUTPUT_ROOT = Path(os.environ.get("NVR_DATA_ROOT", "/data"))
HLS_ROOT = OUTPUT_ROOT / "hls"
ARCHIVE_ROOT = OUTPUT_ROOT / "archive"
HOST = "0.0.0.0"
PORT = 8090

for p in (OUTPUT_ROOT, HLS_ROOT, ARCHIVE_ROOT):
    p.mkdir(parents=True, exist_ok=True)

NVR = NVRRecorderManager(OUTPUT_ROOT)

LIVE_LOCK = threading.RLock()
LIVE_SESSIONS = {}

ALARM_LOCK = threading.RLock()
ALARM_PROCESS = None
ALARM_THREAD = None
ALARM_EVENTS = deque(maxlen=250)


def run_cmd(args, env=None, timeout=15):
    full_env = os.environ.copy()
    if env:
        full_env.update(env)
    try:
        p = subprocess.run(
            args,
            env=full_env,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            timeout=timeout,
            check=False,
        )
        return {
            "ok": p.returncode == 0,
            "code": p.returncode,
            "stdout": p.stdout.strip(),
            "stderr": p.stderr.strip(),
        }
    except subprocess.TimeoutExpired:
        return {"ok": False, "code": -1, "stdout": "", "stderr": "TIMEOUT"}
    except OSError:
        return {"ok": False, "code": -2, "stdout": "", "stderr": "SDK_COMMAND_UNAVAILABLE"}


def device_env(data):
    ip = str(data.get("ip", "")).strip()
    user = str(data.get("user", "")).strip()
    password = str(data.get("password", ""))
    port = str(data.get("port", "8000")).strip()
    channel = normalize_sdk_channel(data.get("channel"))

    if not ip or not user or not password:
        raise ValueError("Укажите IP, имя пользователя и пароль")

    env = {
        "HCNET_IP": ip,
        "HCNET_USER": user,
        "HCNET_PASSWORD": password,
        "HCNET_PORT": port or "8000",
    }
    if channel:
        env["HCNET_CHANNEL"] = channel
    return env


def parse_login_output(result):
    info = {}
    text = "\n".join([result.get("stdout", ""), result.get("stderr", "")])
    for line in text.splitlines():
        if ":" in line:
            key, value = line.split(":", 1)
            info[key.strip()] = value.strip()
    return info


def int_info(info, key, default=0):
    try:
        return int(info.get(key, default))
    except Exception:
        return default


def channels_from_info(info):
    out = []
    analog = int_info(info, "Analog channels")
    start = int_info(info, "Start channel", 1) or 1
    digital = int_info(info, "Digital channels")
    dstart = int_info(info, "Start digital channel", 33) or 33

    for i in range(analog):
        ch = start + i
        out.append({"id": ch, "name": f"Аналоговый {ch}", "type": "analog"})
    for i in range(digital):
        ch = dstart + i
        out.append({"id": ch, "name": f"IP-камера {i + 1}", "type": "digital"})
    if not out:
        out.append({"id": 1, "name": "Канал 1", "type": "unknown"})
    return out[:128]


def parse_key_values(text):
    result = {}
    for line in (text or "").splitlines():
        if "=" in line:
            k, v = line.split("=", 1)
            result[k.strip()] = v.strip()
    return result


def parse_archive(text):
    files = []
    for line in (text or "").splitlines():
        if not line.startswith("file") or "=" not in line:
            continue
        _, value = line.split("=", 1)
        parts = value.split("|")
        if len(parts) >= 4:
            try:
                size = int(parts[3])
            except Exception:
                size = 0
            files.append({
                "filename": parts[0],
                "start": parts[1],
                "end": parts[2],
                "size": size,
            })
    return files


def parse_device_status(text):
    raw = parse_key_values(text)
    disks = []
    channels = []
    for k, v in raw.items():
        if k.startswith("disk") and k[4:].isdigit():
            p = v.split("|")
            if len(p) >= 3:
                disks.append({
                    "index": int(k[4:]),
                    "capacity_mb": int(p[0] or 0),
                    "free_mb": int(p[1] or 0),
                    "state": int(p[2] or 0),
                })
        elif k.startswith("channel_state"):
            p = v.split("|")
            if len(p) >= 6:
                channels.append({
                    "channel": int(p[0] or 0),
                    "recording": int(p[1] or 0),
                    "signal_lost": int(p[2] or 0),
                    "hardware_error": int(p[3] or 0),
                    "bitrate": int(p[4] or 0),
                    "links": int(p[5] or 0),
                })
    return {
        "device_state": int(raw.get("device_state", 0) or 0),
        "disk_count": int(raw.get("disk_count", 0) or 0),
        "analog_count": int(raw.get("analog_count", 0) or 0),
        "digital_count": int(raw.get("digital_count", 0) or 0),
        "disks": disks,
        "channels": channels,
    }


def tail_file(path, limit=4000):
    try:
        data = Path(path).read_text(encoding="utf-8", errors="replace")
        return data[-limit:]
    except Exception:
        return ""


def stop_live(key):
    with LIVE_LOCK:
        sess = LIVE_SESSIONS.pop(key, None)
    if not sess:
        return False

    for proc_name in ("ffmpeg", "sdk"):
        proc = sess.get(proc_name)
        if not proc:
            continue
        try:
            if proc.poll() is None:
                proc.terminate()
                proc.wait(timeout=3)
        except Exception:
            try:
                proc.kill()
            except Exception:
                pass

    for f in ("sdk_log_handle", "ffmpeg_log_handle"):
        try:
            sess.get(f).close()
        except Exception:
            pass
    return True


def start_live(data):
    env = device_env(data)
    channel = str(data.get("channel") or env.get("HCNET_CHANNEL") or "1")
    stream_type = str(data.get("stream_type", 1))
    if stream_type not in {"0", "1", "2"}:
        stream_type = "1"

    env["HCNET_CHANNEL"] = channel
    env["HCNET_STREAM_TYPE"] = stream_type

    key = f"ch{channel}_s{stream_type}"
    stop_live(key)

    target = HLS_ROOT / key
    shutil.rmtree(target, ignore_errors=True)
    target.mkdir(parents=True, exist_ok=True)

    sdk_log_path = target / "sdk.log"
    ffmpeg_log_path = target / "ffmpeg.log"
    sdk_log = sdk_log_path.open("wb")
    ffmpeg_log = ffmpeg_log_path.open("wb")

    sdk = subprocess.Popen(
        ["/usr/local/bin/sdk-stream"],
        env={**os.environ, **env},
        stdout=subprocess.PIPE,
        stderr=sdk_log,
        bufsize=0,
    )

    playlist = target / "index.m3u8"
    ffmpeg_cmd = [
        "ffmpeg", "-hide_banner", "-loglevel", "warning",
        "-fflags", "+genpts",
        "-flags", "low_delay",
        "-probesize", "2000000",
        "-analyzeduration", "2000000",
        "-i", "pipe:0",
        "-map", "0:v:0",
        "-an",
        "-vf", "scale='min(1280,iw)':-2",
        "-c:v", "libx264",
        "-preset", "ultrafast",
        "-tune", "zerolatency",
        "-profile:v", "main",
        "-pix_fmt", "yuv420p",
        "-g", "25",
        "-keyint_min", "25",
        "-sc_threshold", "0",
        "-f", "hls",
        "-hls_time", "1",
        "-hls_list_size", "4",
        "-hls_flags", "delete_segments+append_list+omit_endlist+independent_segments",
        str(playlist),
    ]

    ffmpeg = subprocess.Popen(
        ffmpeg_cmd,
        stdin=sdk.stdout,
        stdout=subprocess.DEVNULL,
        stderr=ffmpeg_log,
    )
    if sdk.stdout:
        sdk.stdout.close()

    sess = {
        "key": key,
        "channel": channel,
        "stream_type": stream_type,
        "created": time.time(),
        "sdk": sdk,
        "ffmpeg": ffmpeg,
        "sdk_log_handle": sdk_log,
        "ffmpeg_log_handle": ffmpeg_log,
        "dir": target,
    }
    with LIVE_LOCK:
        LIVE_SESSIONS[key] = sess

    deadline = time.time() + 12
    while time.time() < deadline:
        if playlist.exists() and playlist.stat().st_size > 40:
            return {
                "ok": True,
                "key": key,
                "playlist_url": f"/output/hls/{key}/index.m3u8?t={int(time.time())}",
            }
        if sdk.poll() is not None or ffmpeg.poll() is not None:
            break
        time.sleep(0.25)

    sdk_log.flush()
    ffmpeg_log.flush()
    details = "\n".join(filter(None, [
        tail_file(sdk_log_path, 1600),
        tail_file(ffmpeg_log_path, 2400),
    ]))
    stop_live(key)
    return {"ok": False, "error": "Не удалось подготовить браузерный видеопоток", "details": details}


def start_saved_camera_live(camera_id):
    """Open a browser-ready HLS preview using credentials already held by NVR.

    No camera passwords or RTSP URLs are returned to the Core UI.
    Recording and live preview are independent processes.
    """
    camera = NVR.get_camera(camera_id, include_secret=True)
    if not camera or not camera.get("enabled"):
        raise ValueError("Камера не найдена или выключена")

    key = "saved_" + NVR._safe_camera_id(camera_id)
    stop_live(key)
    target = HLS_ROOT / key
    shutil.rmtree(target, ignore_errors=True)
    target.mkdir(parents=True, exist_ok=True)
    sdk_log = (target / "sdk.log").open("wb")
    ffmpeg_log = (target / "ffmpeg.log").open("wb")
    sdk = None
    ffmpeg = None
    try:
        command = [
            "ffmpeg", "-hide_banner", "-loglevel", "warning",
            "-fflags", "+genpts",
        ]
        if camera["source_type"] == "hikvision":
            env = {
                **os.environ,
                "HCNET_IP": camera["ip"],
                "HCNET_USER": camera["username"],
                "HCNET_PASSWORD": camera["password"],
                "HCNET_PORT": str(camera["port"]),
                "HCNET_CHANNEL": str(camera["channel"]),
                "HCNET_STREAM_TYPE": "1",
            }
            sdk = subprocess.Popen(
                ["/usr/local/bin/sdk-stream"],
                env=env,
                stdout=subprocess.PIPE,
                stderr=sdk_log,
                bufsize=0,
            )
            command += ["-i", "pipe:0"]
        else:
            if not camera["rtsp_url"].lower().startswith(("rtsp://", "rtsps://")):
                raise ValueError("Не настроен RTSP-адрес камеры")
            command += ["-rtsp_transport", "tcp", "-i", camera["rtsp_url"]]
        playlist = target / "index.m3u8"
        command += [
            "-map", "0:v:0", "-an",
            "-vf", "scale='min(1280,iw)':-2",
            "-c:v", "libx264", "-preset", "ultrafast", "-tune", "zerolatency",
            "-pix_fmt", "yuv420p", "-g", "25",
            "-f", "hls", "-hls_time", "1", "-hls_list_size", "5",
            "-hls_flags", "delete_segments+append_list+omit_endlist+independent_segments",
            str(playlist),
        ]
        ffmpeg = subprocess.Popen(
            command,
            stdin=sdk.stdout if sdk else subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=ffmpeg_log,
        )
        if sdk and sdk.stdout:
            sdk.stdout.close()
        sess = {
            "key": key, "camera_id": camera_id, "channel": camera["channel"],
            "stream_type": 1, "created": time.time(), "sdk": sdk,
            "ffmpeg": ffmpeg, "sdk_log_handle": sdk_log,
            "ffmpeg_log_handle": ffmpeg_log, "dir": target,
        }
        with LIVE_LOCK:
            LIVE_SESSIONS[key] = sess
        deadline = time.monotonic() + 12
        while time.monotonic() < deadline:
            if playlist.exists() and playlist.stat().st_size > 40:
                return {
                    "ok": True, "key": key, "camera_id": camera_id,
                    "playlist_url": f"/output/hls/{key}/index.m3u8",
                }
            if (sdk and sdk.poll() is not None) or ffmpeg.poll() is not None:
                break
            time.sleep(0.25)
        stop_live(key)
        return {"ok": False, "error": "Камера не предоставила видеопоток"}
    except Exception:
        stop_live(key)
        if ffmpeg and ffmpeg.poll() is None:
            ffmpeg.terminate()
        if sdk and sdk.poll() is None:
            sdk.terminate()
        sdk_log.close()
        ffmpeg_log.close()
        raise


def live_status():
    items = []
    dead = []
    with LIVE_LOCK:
        for key, s in LIVE_SESSIONS.items():
            alive = (s["sdk"] is None or s["sdk"].poll() is None) and s["ffmpeg"].poll() is None
            items.append({
                "key": key,
                "channel": s["channel"],
                "stream_type": s["stream_type"],
                "alive": alive,
                "uptime": int(time.time() - s["created"]),
            })
            if not alive:
                dead.append(key)
    for key in dead:
        stop_live(key)
    return items


def _alarm_reader(proc):
    global ALARM_PROCESS
    try:
        while True:
            line = proc.stdout.readline() if proc.stdout else ""
            if not line:
                break
            line = line.strip()
            if not line:
                continue
            try:
                event = json.loads(line)
            except Exception:
                event = {
                    "ts": int(time.time()),
                    "kind": "event",
                    "channel": 0,
                    "raw": line,
                }
            event["received"] = int(time.time())
            with ALARM_LOCK:
                ALARM_EVENTS.appendleft(event)
    finally:
        with ALARM_LOCK:
            if ALARM_PROCESS is proc:
                ALARM_PROCESS = None


def stop_alarm_monitor():
    global ALARM_PROCESS, ALARM_THREAD
    with ALARM_LOCK:
        proc = ALARM_PROCESS
        ALARM_PROCESS = None
        ALARM_THREAD = None
    if proc:
        try:
            if proc.poll() is None:
                proc.terminate()
                proc.wait(timeout=3)
        except Exception:
            try:
                proc.kill()
            except Exception:
                pass
        return True
    return False


def start_alarm_monitor(data):
    global ALARM_PROCESS, ALARM_THREAD
    env = device_env(data)
    stop_alarm_monitor()

    proc = subprocess.Popen(
        ["/usr/local/bin/sdk-alarm-monitor"],
        env={**os.environ, **env},
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        bufsize=1,
    )

    deadline = time.time() + 4
    while time.time() < deadline:
        if proc.poll() is not None:
            err = proc.stderr.read() if proc.stderr else ""
            return {"ok": False, "error": "Не удалось включить мониторинг событий", "details": err}
        time.sleep(0.1)
        if time.time() - (deadline - 4) > 0.5:
            break

    thread = threading.Thread(target=_alarm_reader, args=(proc,), daemon=True)
    with ALARM_LOCK:
        ALARM_PROCESS = proc
        ALARM_THREAD = thread
    thread.start()
    return {"ok": True, "message": "Мониторинг событий включён"}


def alarm_state():
    with ALARM_LOCK:
        proc = ALARM_PROCESS
        active = proc is not None and proc.poll() is None
        events = list(ALARM_EVENTS)
    return {"active": active, "events": events}


class Handler(BaseHTTPRequestHandler):
    server_version = "HCNetSDK-NVR-Web/2.0"

    def log_message(self, fmt, *args):
        print("[WEB]", fmt % args, flush=True)

    def send_json(self, obj, status=200):
        payload = json.dumps(obj, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(payload)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(payload)

    def read_json(self):
        length = int(self.headers.get("Content-Length", "0") or "0")
        if length <= 0:
            return {}
        raw = self.rfile.read(length)
        return json.loads(raw.decode("utf-8"))

    def serve_file(self, path):
        if not path.exists() or not path.is_file():
            self.send_error(404)
            return

        ext = path.suffix.lower()
        if ext == ".m3u8":
            ctype = "application/vnd.apple.mpegurl"
        elif ext == ".ts":
            ctype = "video/mp2t"
        elif ext == ".mp4":
            ctype = "video/mp4"
        else:
            ctype = mimetypes.guess_type(str(path))[0] or "application/octet-stream"

        data = path.read_bytes()
        self.send_response(200)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("Access-Control-Allow-Origin", "*")
        self.end_headers()
        self.wfile.write(data)

    def do_GET(self):
        parsed = urlparse(self.path)
        clean = unquote(parsed.path)
        query = parse_qs(parsed.query)

        if clean == "/api/nvr/storage":
            try:
                self.send_json(capacity_snapshot(OUTPUT_ROOT))
            except OSError:
                self.send_json({"ok": False, "error": "storage_unavailable"})
            return

        if clean == "/api/nvr/sdk":
            self.send_json(sdk_status())
            return

        if clean == "/api/nvr/status":
            self.send_json(NVR.status())
            return

        if clean == "/api/nvr/cameras":
            self.send_json({"ok": True, "cameras": NVR.list_cameras()})
            return

        if clean == "/api/nvr/recordings":
            camera_id = (query.get("camera_id") or [None])[0]
            start = (query.get("start") or [None])[0]
            end = (query.get("end") or [None])[0]
            limit = (query.get("limit") or ["500"])[0]
            self.send_json({
                "ok": True,
                "recordings": NVR.list_recordings(
                    camera_id=camera_id,
                    start=int(start) if start else None,
                    end=int(end) if end else None,
                    limit=int(limit),
                ),
            })
            return

        if clean == "/api/status":
            result = run_cmd(["/usr/local/bin/sdk-smoke"], timeout=10)
            ff = run_cmd(["ffmpeg", "-version"], timeout=5)
            self.send_json({
                "ok": result["ok"],
                "container": "hikvision-hcnetsdk",
                "sdk": (
                    "HCNetSDK " + sdk_status()["version"] + " Linux64"
                    if sdk_status().get("version")
                    else "HCNetSDK: не удалось определить версию"
                ),
                "sdk_info": sdk_status(),
                "ffmpeg": (ff["stdout"].splitlines()[0] if ff["ok"] and ff["stdout"] else "недоступен"),
                "details": result["stdout"] or result["stderr"],
                "live": live_status(),
            }, 200 if result["ok"] else 500)
            return

        if clean == "/api/live/status":
            self.send_json({"ok": True, "sessions": live_status()})
            return

        if clean == "/api/events":
            state = alarm_state()
            self.send_json({"ok": True, **state})
            return

        if clean.startswith("/output/"):
            rel = clean[len("/output/"):]
            target = (OUTPUT_ROOT / rel).resolve()
            if OUTPUT_ROOT.resolve() not in target.parents:
                self.send_error(403)
                return
            self.serve_file(target)
            return

        if clean == "/":
            clean = "/index.html"

        target = (WEB_ROOT / clean.lstrip("/")).resolve()
        if WEB_ROOT.resolve() not in target.parents:
            self.send_error(403)
            return
        self.serve_file(target)

    def do_POST(self):
        try:
            data = self.read_json()
        except Exception:
            self.send_json({"ok": False, "error": "Некорректный JSON"}, 400)
            return

        try:
            clean = urlparse(self.path).path

            if clean == "/api/nvr/cameras":
                camera = NVR.save_camera(data)
                self.send_json({"ok": True, "camera": camera}, 201)
                return

            if clean == "/api/nvr/retention":
                removed = NVR.enforce_retention()
                self.send_json({"ok": True, "removed": removed, "status": NVR.status()})
                return

            if clean.startswith("/api/nvr/cameras/"):
                parts = clean.strip("/").split("/")
                if len(parts) == 5 and parts[:3] == ["api", "nvr", "cameras"]:
                    camera_id = parts[3]
                    action = parts[4]
                    if action == "start":
                        NVR.start_camera(camera_id)
                        self.send_json({"ok": True, "camera": NVR.get_camera(camera_id)})
                        return
                    if action == "stop":
                        stopped = NVR.stop_camera(camera_id)
                        self.send_json({"ok": True, "stopped": stopped, "camera": NVR.get_camera(camera_id)})
                        return
                    if action == "restart":
                        NVR.restart_camera(camera_id)
                        self.send_json({"ok": True, "camera": NVR.get_camera(camera_id)})
                        return
                if len(parts) == 6 and parts[:3] == ["api", "nvr", "cameras"] and parts[4] == "live":
                    camera_id = parts[3]
                    action = parts[5]
                    if action == "start":
                        result = start_saved_camera_live(camera_id)
                        self.send_json(result, 200 if result.get("ok") else 502)
                        return
                    if action == "stop":
                        key = "saved_" + NVR._safe_camera_id(camera_id)
                        self.send_json({"ok": True, "stopped": stop_live(key)})
                        return

            if self.path == "/api/login":
                env = device_env(data)
                result = run_cmd(["/usr/local/bin/sdk-login-test"], env=env, timeout=12)
                info = parse_login_output(result)
                self.send_json({
                    "ok": result["ok"],
                    "message": "Подключение успешно" if result["ok"] else "Ошибка подключения",
                    "info": info,
                    "channels": channels_from_info(info) if result["ok"] else [],
                    "details": result["stdout"] or result["stderr"],
                }, 200 if result["ok"] else 502)
                return

            if self.path == "/api/device-status":
                env = device_env(data)
                result = run_cmd(["/usr/local/bin/sdk-extended", "status"], env=env, timeout=12)
                self.send_json({
                    "ok": result["ok"],
                    "message": "Состояние устройства получено" if result["ok"] else "Ошибка чтения состояния",
                    "status": parse_device_status(result["stdout"]) if result["ok"] else {},
                    "details": result["stdout"] or result["stderr"],
                }, 200 if result["ok"] else 502)
                return

            if self.path == "/api/live/start":
                result = start_live(data)
                self.send_json(result, 200 if result.get("ok") else 502)
                return

            if self.path == "/api/live/stop":
                channel = str(data.get("channel", "1"))
                stream_type = str(data.get("stream_type", 1))
                key = str(data.get("key") or f"ch{channel}_s{stream_type}")
                stopped = stop_live(key)
                self.send_json({"ok": True, "stopped": stopped, "key": key})
                return

            if self.path == "/api/live/stop-all":
                with LIVE_LOCK:
                    keys = list(LIVE_SESSIONS.keys())
                for key in keys:
                    stop_live(key)
                self.send_json({"ok": True, "stopped": len(keys)})
                return

            if self.path == "/api/events/start":
                result = start_alarm_monitor(data)
                self.send_json(result, 200 if result.get("ok") else 502)
                return

            if self.path == "/api/events/stop":
                stopped = stop_alarm_monitor()
                self.send_json({"ok": True, "stopped": stopped})
                return

            if self.path == "/api/snapshot":
                env = device_env(data)
                ch = str(data.get("channel") or env.get("HCNET_CHANNEL") or "1")
                filename = f"snapshot_ch{ch}.jpg"
                target = OUTPUT_ROOT / filename
                target.unlink(missing_ok=True)
                result = run_cmd(
                    ["/usr/local/bin/sdk-action", "snapshot", str(target)],
                    env=env,
                    timeout=20,
                )
                ok = result["ok"] and target.exists()
                self.send_json({
                    "ok": ok,
                    "message": "Снимок получен" if ok else "Не удалось получить снимок",
                    "image_url": f"/output/{filename}?t={int(time.time())}" if ok else None,
                    "details": result["stdout"] or result["stderr"],
                }, 200 if ok else 502)
                return

            if self.path == "/api/ptz":
                env = device_env(data)
                action = str(data.get("action", "")).strip()
                speed = str(data.get("speed", 4))
                duration = str(data.get("duration", 350))
                allowed = {
                    "up", "down", "left", "right",
                    "up_left", "up_right", "down_left", "down_right",
                    "zoom_in", "zoom_out", "focus_near", "focus_far",
                    "iris_open", "iris_close",
                }
                if action not in allowed:
                    self.send_json({"ok": False, "error": "Неизвестная PTZ-команда"}, 400)
                    return
                result = run_cmd(
                    ["/usr/local/bin/sdk-action", "ptz", action, speed, duration],
                    env=env,
                    timeout=12,
                )
                self.send_json({
                    "ok": result["ok"],
                    "message": "Команда PTZ выполнена" if result["ok"] else "Ошибка PTZ",
                    "details": result["stdout"] or result["stderr"],
                }, 200 if result["ok"] else 502)
                return

            if self.path == "/api/preset":
                env = device_env(data)
                action = str(data.get("action", "")).strip()
                preset = str(data.get("preset", "1")).strip()
                if action not in {"set", "goto"}:
                    self.send_json({"ok": False, "error": "Неизвестная команда пресета"}, 400)
                    return
                result = run_cmd(
                    ["/usr/local/bin/sdk-action", "preset", action, preset],
                    env=env,
                    timeout=12,
                )
                self.send_json({
                    "ok": result["ok"],
                    "message": "Пресет выполнен" if result["ok"] else "Ошибка пресета",
                    "details": result["stdout"] or result["stderr"],
                }, 200 if result["ok"] else 502)
                return

            if self.path == "/api/ability":
                result = run_cmd(["/usr/local/bin/sdk-extended", "ability"], timeout=10)
                self.send_json({
                    "ok": result["ok"],
                    "message": "Возможности SDK получены" if result["ok"] else "Ошибка чтения возможностей SDK",
                    "data": parse_key_values(result["stdout"]),
                    "details": result["stdout"] or result["stderr"],
                }, 200 if result["ok"] else 502)
                return

            if self.path == "/api/net-usage":
                env = device_env(data)
                result = run_cmd(["/usr/local/bin/sdk-extended", "net_usage"], env=env, timeout=12)
                self.send_json({
                    "ok": result["ok"],
                    "message": "Сетевая нагрузка получена" if result["ok"] else "Не удалось получить сетевую нагрузку",
                    "data": parse_key_values(result["stdout"]),
                    "details": result["stdout"] or result["stderr"],
                }, 200 if result["ok"] else 502)
                return

            if self.path == "/api/alarm-test":
                env = device_env(data)
                result = run_cmd(["/usr/local/bin/sdk-extended", "alarm_test"], env=env, timeout=12)
                self.send_json({
                    "ok": result["ok"],
                    "message": "Тревожный канал работает" if result["ok"] else "Ошибка тревожного канала",
                    "details": result["stdout"] or result["stderr"],
                }, 200 if result["ok"] else 502)
                return

            if self.path == "/api/voice-test":
                env = device_env(data)
                result = run_cmd(["/usr/local/bin/sdk-extended", "voice_test"], env=env, timeout=12)
                self.send_json({
                    "ok": result["ok"],
                    "message": "Голосовой канал работает" if result["ok"] else "Ошибка голосового канала",
                    "details": result["stdout"] or result["stderr"],
                }, 200 if result["ok"] else 502)
                return

            if self.path == "/api/archive-search":
                env = device_env(data)
                start = str(data.get("start", "")).strip()
                end = str(data.get("end", "")).strip()
                if len(start) == 16:
                    start += ":00"
                if len(end) == 16:
                    end += ":00"
                if not start or not end:
                    self.send_json({"ok": False, "error": "Укажите время начала и окончания"}, 400)
                    return
                result = run_cmd(
                    ["/usr/local/bin/sdk-extended", "archive_search", start, end],
                    env=env,
                    timeout=30,
                )
                self.send_json({
                    "ok": result["ok"],
                    "message": "Поиск архива завершён" if result["ok"] else "Ошибка поиска архива",
                    "files": parse_archive(result["stdout"]) if result["ok"] else [],
                    "details": result["stdout"] or result["stderr"],
                }, 200 if result["ok"] else 502)
                return

            if self.path == "/api/archive-prepare":
                env = device_env(data)
                filename = str(data.get("filename", "")).strip()
                if not filename or len(filename) > 240:
                    self.send_json({"ok": False, "error": "Некорректное имя записи"}, 400)
                    return

                ident = hashlib.sha1(
                    (env["HCNET_IP"] + "|" + env.get("HCNET_CHANNEL", "1") + "|" + filename).encode("utf-8")
                ).hexdigest()[:16]
                raw = ARCHIVE_ROOT / f"{ident}.raw"
                mp4 = ARCHIVE_ROOT / f"{ident}.mp4"
                raw.unlink(missing_ok=True)
                mp4.unlink(missing_ok=True)

                result = run_cmd(
                    ["/usr/local/bin/sdk-extended", "archive_download", filename, str(raw)],
                    env=env,
                    timeout=190,
                )
                if not result["ok"] or not raw.exists():
                    self.send_json({
                        "ok": False,
                        "error": "Не удалось скачать запись с устройства",
                        "details": result["stdout"] or result["stderr"],
                    }, 502)
                    return

                conv = run_cmd([
                    "ffmpeg", "-y", "-hide_banner", "-loglevel", "warning",
                    "-i", str(raw),
                    "-map", "0:v:0", "-map", "0:a:0?",
                    "-c:v", "libx264", "-preset", "veryfast", "-pix_fmt", "yuv420p",
                    "-c:a", "aac", "-movflags", "+faststart",
                    str(mp4),
                ], timeout=180)
                if not conv["ok"] or not mp4.exists():
                    self.send_json({
                        "ok": False,
                        "error": "Запись скачана, но не удалось подготовить её для браузера",
                        "details": conv["stderr"] or conv["stdout"],
                    }, 502)
                    return

                self.send_json({
                    "ok": True,
                    "message": "Запись подготовлена",
                    "playback_url": f"/output/archive/{mp4.name}?t={int(time.time())}",
                    "download_url": f"/output/archive/{mp4.name}",
                })
                return

            self.send_json({"ok": False, "error": "Неизвестный API-метод"}, 404)

        except ValueError as e:
            self.send_json({"ok": False, "error": str(e)}, 400)
        except Exception as e:
            self.send_json({"ok": False, "error": f"Внутренняя ошибка: {e}"}, 500)



    def do_DELETE(self):
        clean = urlparse(self.path).path
        if not clean.startswith("/api/nvr/cameras/"):
            self.send_json({"ok": False, "error": "Неизвестный API-метод"}, 404)
            return
        parts = clean.strip("/").split("/")
        if len(parts) != 4 or parts[:3] != ["api", "nvr", "cameras"]:
            self.send_json({"ok": False, "error": "Некорректный путь"}, 400)
            return
        camera_id = parts[3]
        query = parse_qs(urlparse(self.path).query)
        delete_recordings = (query.get("delete_recordings") or ["0"])[0].lower() in {"1", "true", "yes", "on"}
        stop_live("saved_" + NVR._safe_camera_id(camera_id))
        deleted = NVR.delete_camera(camera_id, delete_recordings=delete_recordings)
        self.send_json({"ok": True, "deleted": deleted})


if __name__ == "__main__":
    NVR.start()
    print(f"NVR Web UI: http://{HOST}:{PORT}", flush=True)
    print(f"NVR recorder: {json.dumps(NVR.status(), ensure_ascii=False)}", flush=True)
    try:
        ThreadingHTTPServer((HOST, PORT), Handler).serve_forever()
    finally:
        with LIVE_LOCK:
            keys = list(LIVE_SESSIONS.keys())
        for key in keys:
            stop_live(key)
        stop_alarm_monitor()
        NVR.stop()
