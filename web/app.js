const $ = (id) => document.getElementById(id);
const $$ = (sel) => [...document.querySelectorAll(sel)];

const pageTitles = {
  monitor: "Живой просмотр",
  archive: "Архив",
  events: "События",
  device: "Устройство",
  system: "Система",
  logs: "Журнал"
};

const state = {
  connected: false,
  info: {},
  channels: [],
  selectedChannel: null,
  selectedSlot: 0,
  layout: 4,
  tiles: Array.from({ length: 9 }, () => null),
  hls: Array.from({ length: 9 }, () => null),
  events: [],
  eventActive: false,
  nvrCameras: [],
  busy: false
};

function nowText() {
  return new Date().toLocaleTimeString("ru-RU");
}

function log(message, kind = "info") {
  const box = $("log");
  const prefix = kind === "error" ? "ОШИБКА" : kind === "ok" ? "OK" : "INFO";
  if (!box) return;
  box.textContent += "[" + nowText() + "] " + prefix + ": " + message + "\n";
  box.scrollTop = box.scrollHeight;
}

function toast(message, kind = "info") {
  const host = $("toastHost");
  const item = document.createElement("div");
  item.className = "toast " + (kind === "error" ? "bad" : kind === "ok" ? "ok" : "");
  item.textContent = message;
  host.appendChild(item);
  setTimeout(() => item.remove(), 4200);
}

async function api(url, options = {}) {
  const res = await fetch(url, {
    cache: "no-store",
    headers: { "Content-Type": "application/json" },
    ...options
  });

  let body = {};
  try {
    body = await res.json();
  } catch {
    body = { ok: false, error: "Сервер вернул некорректный ответ" };
  }

  if (!res.ok || body.ok === false) {
    const err = new Error(body.error || body.message || body.details || ("HTTP " + res.status));
    err.details = body.details || "";
    throw err;
  }
  return body;
}

function credentials(channel = null) {
  const data = {
    ip: $("ip").value.trim(),
    port: Number($("port").value || 8000),
    user: $("user").value.trim(),
    password: $("password").value
  };
  const ch = channel !== null ? channel : state.selectedChannel;
  if (ch !== null && ch !== undefined) data.channel = Number(ch);
  return data;
}

function requireConnection() {
  if (!state.connected) {
    toast("Сначала подключитесь к камере или NVR", "error");
    navigate("device");
    return false;
  }
  return true;
}

function navigate(page) {
  $$(".page").forEach((el) => el.classList.toggle("active", el.id === "page-" + page));
  $$(".nav-item").forEach((el) => el.classList.toggle("active", el.dataset.page === page));
  $("pageTitle").textContent = pageTitles[page] || page;
}

$$(".nav-item").forEach((button) => {
  button.addEventListener("click", () => navigate(button.dataset.page));
});

$$("[data-page-link]").forEach((button) => {
  button.addEventListener("click", () => navigate(button.dataset.pageLink));
});

function createVideoTiles() {
  const grid = $("videoGrid");
  grid.textContent = "";

  for (let i = 0; i < 9; i++) {
    const tile = document.createElement("div");
    tile.className = "video-tile";
    tile.dataset.slot = String(i);

    const video = document.createElement("video");
    video.playsInline = true;
    video.autoplay = true;
    video.muted = true;
    video.classList.add("hidden");

    const placeholder = document.createElement("div");
    placeholder.className = "tile-placeholder";
    placeholder.innerHTML = '<div><span class="placeholder-icon">◉</span><strong>Окно ' + (i + 1) + '</strong><small>Дважды нажмите камеру для запуска</small></div>';

    const top = document.createElement("div");
    top.className = "tile-top";
    top.innerHTML = '<strong>Окно ' + (i + 1) + '</strong><span class="tile-live hidden">LIVE</span>';

    const actions = document.createElement("div");
    actions.className = "tile-actions";

    const stop = document.createElement("button");
    stop.textContent = "■";
    stop.title = "Остановить";
    stop.addEventListener("click", (e) => {
      e.stopPropagation();
      stopTile(i);
    });

    const full = document.createElement("button");
    full.textContent = "⛶";
    full.title = "На весь экран";
    full.addEventListener("click", (e) => {
      e.stopPropagation();
      if (tile.requestFullscreen) tile.requestFullscreen();
    });

    actions.append(stop, full);
    tile.append(video, placeholder, top, actions);
    tile.addEventListener("click", () => selectSlot(i));
    grid.appendChild(tile);
  }

  selectSlot(0);
  applyLayout(4);
}

function applyLayout(count) {
  state.layout = Number(count);
  $("videoGrid").className = "video-grid grid-" + state.layout;
  $$(".video-tile").forEach((tile, idx) => tile.classList.toggle("hidden", idx >= state.layout));
  $$("#layoutButtons button").forEach((b) => b.classList.toggle("active", Number(b.dataset.layout) === state.layout));

  for (let i = state.layout; i < 9; i++) {
    if (state.tiles[i]) stopTile(i, true);
  }
  if (state.selectedSlot >= state.layout) selectSlot(0);
}

$$("#layoutButtons button").forEach((b) => {
  b.addEventListener("click", () => applyLayout(Number(b.dataset.layout)));
});

function selectSlot(slot) {
  state.selectedSlot = slot;
  $$(".video-tile").forEach((tile, idx) => tile.classList.toggle("selected", idx === slot));
  const session = state.tiles[slot];
  if (session) {
    state.selectedChannel = Number(session.channel);
    updateSelectedCamera();
    renderCameraList();
  }
}

function channelById(id) {
  return state.channels.find((c) => Number(c.id) === Number(id));
}

function updateSelectedCamera() {
  const ch = channelById(state.selectedChannel);
  $("selectedCameraName").textContent = ch ? ch.name : (state.selectedChannel ? "Канал " + state.selectedChannel : "Канал не выбран");
}


function renderCameraList() {
  const root = $("cameraList");
  root.textContent = "";
  $("cameraCount").textContent = state.channels.length + " каналов";

  if (!state.channels.length) {
    const empty = document.createElement("div");
    empty.className = "empty-note";
    empty.textContent = "Подключите камеру или NVR";
    root.appendChild(empty);
    return;
  }

  state.channels.forEach((ch) => {
    const button = document.createElement("button");
    button.className = "camera-item online";
    if (Number(ch.id) === Number(state.selectedChannel)) button.classList.add("active");

    const dot = document.createElement("span");
    dot.className = "cam-dot";

    const name = document.createElement("span");
    name.className = "cam-name";
    const strong = document.createElement("strong");
    strong.textContent = ch.name;
    const small = document.createElement("small");
    small.textContent = "Канал " + ch.id + " · " + (ch.type === "digital" ? "IP" : ch.type === "analog" ? "Analog" : "Video");
    name.append(strong, small);

    const play = document.createElement("span");
    play.className = "play-mini";
    play.textContent = "▶";

    button.append(dot, name, play);
    button.addEventListener("click", () => {
      state.selectedChannel = Number(ch.id);
      updateSelectedCamera();
      renderCameraList();
    });
    button.addEventListener("dblclick", () => {
      state.selectedChannel = Number(ch.id);
      startLive(Number(ch.id), state.selectedSlot);
    });
    root.appendChild(button);
  });
}

function tileElements(slot) {
  const tile = document.querySelector('.video-tile[data-slot="' + slot + '"]');
  return {
    tile: tile,
    video: tile ? tile.querySelector("video") : null,
    placeholder: tile ? tile.querySelector(".tile-placeholder") : null,
    title: tile ? tile.querySelector(".tile-top strong") : null,
    live: tile ? tile.querySelector(".tile-live") : null
  };
}

function destroyPlayer(slot) {
  if (state.hls[slot]) {
    try { state.hls[slot].destroy(); } catch {}
    state.hls[slot] = null;
  }
  const video = tileElements(slot).video;
  if (video) {
    try {
      video.pause();
      video.removeAttribute("src");
      video.load();
    } catch {}
  }
}

async function stopTile(slot, quiet = false) {
  const sess = state.tiles[slot];
  destroyPlayer(slot);

  if (sess) {
    try {
      await api("/api/live/stop", {
        method: "POST",
        body: JSON.stringify({ key: sess.key })
      });
    } catch (e) {
      if (!quiet) log(e.message, "error");
    }
  }

  state.tiles[slot] = null;
  const el = tileElements(slot);
  if (el.video) el.video.classList.add("hidden");
  if (el.placeholder) {
    el.placeholder.classList.remove("hidden");
    el.placeholder.innerHTML = '<div><span class="placeholder-icon">◉</span><strong>Окно ' + (slot + 1) + '</strong><small>Дважды нажмите камеру для запуска</small></div>';
  }
  if (el.title) el.title.textContent = "Окно " + (slot + 1);
  if (el.live) el.live.classList.add("hidden");
  updateLiveCount();
}

function attachHls(slot, url) {
  const el = tileElements(slot);
  const video = el.video;
  if (!video) return;

  video.classList.remove("hidden");
  if (el.placeholder) el.placeholder.classList.add("hidden");

  if (window.Hls && Hls.isSupported()) {
    const hls = new Hls({
      lowLatencyMode: true,
      liveSyncDurationCount: 2,
      liveMaxLatencyDurationCount: 6,
      maxBufferLength: 8,
      backBufferLength: 0
    });
    state.hls[slot] = hls;
    hls.loadSource(url);
    hls.attachMedia(video);
    hls.on(Hls.Events.MANIFEST_PARSED, () => video.play().catch(() => {}));
    hls.on(Hls.Events.ERROR, (_evt, data) => {
      if (!data.fatal) return;
      log("HLS ошибка: " + (data.details || data.type), "error");
      if (data.type === Hls.ErrorTypes.NETWORK_ERROR) hls.startLoad();
      else if (data.type === Hls.ErrorTypes.MEDIA_ERROR) hls.recoverMediaError();
    });
  } else if (video.canPlayType("application/vnd.apple.mpegurl")) {
    video.src = url;
    video.play().catch(() => {});
  } else {
    throw new Error("Этот браузер не поддерживает HLS/MSE");
  }
}

async function startLive(channel, slot = state.selectedSlot) {
  if (!requireConnection()) return;

  state.selectedChannel = Number(channel);
  selectSlot(slot);
  renderCameraList();
  await stopTile(slot, true);

  const el = tileElements(slot);
  const ch = channelById(channel);
  if (el.placeholder) {
    el.placeholder.classList.remove("hidden");
    el.placeholder.innerHTML = '<div><span class="placeholder-icon">◌</span><strong>Подключение…</strong><small>' + (ch ? ch.name : "Канал " + channel) + '</small></div>';
  }

  try {
    const data = await api("/api/live/start", {
      method: "POST",
      body: JSON.stringify({
        ...credentials(channel),
        stream_type: Number($("streamType").value)
      })
    });

    state.tiles[slot] = {
      key: data.key,
      channel: Number(channel),
      streamType: Number($("streamType").value),
      playlist: data.playlist_url
    };

    if (el.title) el.title.textContent = ch ? ch.name : "Канал " + channel;
    if (el.live) el.live.classList.remove("hidden");
    attachHls(slot, data.playlist_url);
    updateLiveCount();
    toast("Поток канала " + channel + " запущен", "ok");
    log("Live View: канал " + channel + ", слот " + (slot + 1), "ok");
  } catch (e) {
    if (el.placeholder) {
      el.placeholder.classList.remove("hidden");
      el.placeholder.innerHTML = '<div><span class="placeholder-icon">!</span><strong>Ошибка потока</strong><small>' + e.message + '</small></div>';
    }
    log(e.details || e.message, "error");
    toast(e.message, "error");
  }
}

async function stopAllLive() {
  for (let i = 0; i < 9; i++) destroyPlayer(i);
  try {
    await api("/api/live/stop-all", { method: "POST", body: "{}" });
  } catch {}

  for (let i = 0; i < 9; i++) {
    state.tiles[i] = null;
    const el = tileElements(i);
    if (el.video) el.video.classList.add("hidden");
    if (el.placeholder) {
      el.placeholder.classList.remove("hidden");
      el.placeholder.innerHTML = '<div><span class="placeholder-icon">◉</span><strong>Окно ' + (i + 1) + '</strong><small>Дважды нажмите камеру для запуска</small></div>';
    }
    if (el.title) el.title.textContent = "Окно " + (i + 1);
    if (el.live) el.live.classList.add("hidden");
  }
  updateLiveCount();
}

function updateLiveCount() {
  const count = state.tiles.filter(Boolean).length;
  $("liveSessionCount").textContent = count + (count === 1 ? " поток" : " потоков");
}


async function refreshSdkStatus() {
  try {
    const [data, nvr] = await Promise.all([
      api("/api/status"),
      api("/api/nvr/status")
    ]);
    const storage = await api("/api/nvr/storage").catch(() => ({ok: false}));
    $("sdkDot").className = "status-dot ok";
    $("sdkStateText").textContent = "NVR работает";
    $("sdkSubText").textContent = nvr.active_recorders + " REC · " + formatSize(nvr.storage_bytes);
    $("systemStatus").textContent = [
      "NVR: h.a.c._nvr",
      "Камер: " + nvr.cameras + " / " + nvr.max_cameras,
      "Активных записей: " + nvr.active_recorders,
      "Файлов архива: " + nvr.recordings,
      "Архив занимает: " + formatSize(nvr.storage_bytes),
      "Диск записей: " + (storage.ok ? storage.path : "недоступен"),
      "Всего на диске: " + (storage.ok ? formatSize(storage.total_bytes) : "—"),
      "Занято на диске: " + (storage.ok ? formatSize(storage.used_bytes) : "—"),
      "Свободно для записи: " + (storage.ok ? formatSize(storage.available_bytes) : "—"),
      "Использовано: " + (storage.ok ? storage.used_percent + "%" : "—"),
      "Хранение: " + nvr.retention_days + " дн. / " + nvr.max_storage_gb + " GB",
      "Сегмент: " + nvr.segment_seconds + " сек.",
      "",
      data.sdk,
      "OpenSSL SDK: " + (data.sdk_info?.openssl || "не определён"),
      data.ffmpeg,
      "",
      data.details,
      "",
      "Активных live-сессий: " + ((data.live && data.live.length) || 0)
    ].join("\n");
  } catch (e) {
    $("sdkDot").className = "status-dot bad";
    $("sdkStateText").textContent = "Ошибка NVR";
    $("sdkSubText").textContent = e.message;
    $("systemStatus").textContent = e.message;
  }
}

async function connectDevice() {
  const btn = $("connectBtn");
  btn.disabled = true;
  btn.textContent = "Подключение…";

  try {
    const data = await api("/api/login", {
      method: "POST",
      body: JSON.stringify(credentials(null))
    });

    state.connected = true;
    state.info = data.info || {};
    state.channels = data.channels || [];
    state.selectedChannel = state.channels.length ? state.channels[0].id : 1;

    $("deviceDot").className = "status-dot ok";
    $("deviceStateText").textContent = "Подключено";
    $("deviceAddressText").textContent = $("ip").value.trim() + ":" + $("port").value;
    $("connectionBadge").className = "badge ok";
    $("connectionBadge").textContent = "Подключено";
    $("quickConnect").textContent = "Подключено";

    renderCameraList();
    fillChannelSelects();
    updateSelectedCamera();
    renderDeviceSummary();
    await refreshDeviceStatus();
    toast("Устройство подключено", "ok");
    log(data.details || "Подключение выполнено", "ok");
    navigate("monitor");
  } catch (e) {
    state.connected = false;
    $("deviceDot").className = "status-dot bad";
    $("deviceStateText").textContent = "Ошибка подключения";
    $("connectionBadge").className = "badge bad";
    $("connectionBadge").textContent = "Ошибка";
    toast(e.message, "error");
    log(e.details || e.message, "error");
  } finally {
    btn.disabled = false;
    btn.textContent = "Подключиться";
  }
}

async function disconnectUi() {
  await stopAllLive();
  if (state.eventActive) await stopEvents();

  state.connected = false;
  state.channels = [];
  state.info = {};
  state.selectedChannel = null;

  $("deviceDot").className = "status-dot offline";
  $("deviceStateText").textContent = "Не подключено";
  $("deviceAddressText").textContent = "—";
  $("connectionBadge").className = "badge neutral";
  $("connectionBadge").textContent = "Не подключено";
  $("quickConnect").textContent = "Подключить";

  renderCameraList();
  fillChannelSelects();
  renderDeviceSummary();
}

function renderDeviceSummary() {
  const metrics = $("deviceSummary").querySelectorAll(".metric strong");
  if (!state.connected) {
    metrics.forEach((m) => m.textContent = "—");
    return;
  }

  metrics[0].textContent = state.info["Analog channels"] || "0";
  metrics[1].textContent = state.info["Digital channels"] || "0";
  metrics[2].textContent = state.info["Disks"] || "0";
  metrics[3].textContent = state.info["Device type"] || "—";
}

function fillChannelSelects() {
  const select = $("archiveChannel");
  select.textContent = "";

  state.nvrCameras.forEach((camera) => {
    const opt = document.createElement("option");
    opt.value = camera.id;
    opt.textContent = camera.name + (camera.recording ? " · REC" : "");
    select.appendChild(opt);
  });

  if (!state.nvrCameras.length) {
    const opt = document.createElement("option");
    opt.value = "";
    opt.textContent = "Нет камер в NVR";
    select.appendChild(opt);
  }
}

async function loadNvrCameras() {
  try {
    const data = await api("/api/nvr/cameras");
    state.nvrCameras = data.cameras || [];
    fillChannelSelects();
  } catch (e) {
    state.nvrCameras = [];
    fillChannelSelects();
    log("NVR: " + e.message, "error");
  }
}

async function addSelectedToNvr() {
  if (!requireConnection()) return;
  const channel = Number(state.selectedChannel || 1);
  const ch = channelById(channel);
  const ip = $("ip").value.trim();
  const btn = $("addToNvrBtn");
  btn.disabled = true;
  btn.textContent = "Добавление…";

  try {
    const data = await api("/api/nvr/cameras", {
      method: "POST",
      body: JSON.stringify({
        name: (ch ? ch.name : "Канал " + channel) + " · " + ip,
        source_type: "hikvision",
        ip: ip,
        port: Number($("port").value || 8000),
        username: $("user").value.trim(),
        password: $("password").value,
        channel: channel,
        enabled: true
      })
    });
    await loadNvrCameras();
    toast("Канал добавлен в NVR и запись запущена", "ok");
    log("NVR: запись " + data.camera.name + " включена", "ok");
  } catch (e) {
    toast(e.message, "error");
    log("NVR: " + e.message, "error");
  } finally {
    btn.disabled = false;
    btn.textContent = "Добавить канал в NVR";
  }
}

async function refreshDeviceStatus() {
  if (!requireConnection()) return;

  try {
    const data = await api("/api/device-status", {
      method: "POST",
      body: JSON.stringify(credentials())
    });
    renderHealth(data.status || {});
    log(data.message, "ok");
  } catch (e) {
    $("deviceHealth").textContent = e.message;
    log(e.details || e.message, "error");
  }
}

function renderHealth(status) {
  const root = $("deviceHealth");
  root.textContent = "";

  const head = document.createElement("div");
  head.className = "health-head";
  const dot = document.createElement("span");
  dot.className = "status-dot " + (Number(status.device_state) === 0 ? "ok" : "bad");
  const text = document.createElement("strong");
  text.textContent = Number(status.device_state) === 0 ? "Устройство работает нормально" : "Состояние устройства: " + status.device_state;
  head.append(dot, text);
  root.appendChild(head);

  const grid = document.createElement("div");
  grid.className = "disk-grid";

  (status.disks || []).forEach((disk) => {
    const card = document.createElement("div");
    card.className = "disk-card";
    const used = disk.capacity_mb > 0 ? Math.max(0, Math.min(100, 100 - disk.free_mb * 100 / disk.capacity_mb)) : 0;
    const stateText = disk.state === 0 ? "Активен" : disk.state === 1 ? "Сон" : disk.state === 4 ? "Не форматирован" : "Статус " + disk.state;
    card.innerHTML =
      "<strong>Диск " + disk.index + "</strong>" +
      "<span>" + stateText + " · свободно " + formatSize(disk.free_mb * 1024 * 1024) + "</span>" +
      '<div class="disk-bar"><i style="width:' + used + '%"></i></div>';
    grid.appendChild(card);
  });

  if (!(status.disks || []).length) {
    const empty = document.createElement("div");
    empty.className = "empty-note";
    empty.textContent = "Диски не обнаружены или устройство не вернуло их состояние";
    grid.appendChild(empty);
  }

  root.appendChild(grid);
}

async function loadNetworkUsage() {
  if (!requireConnection()) return;

  try {
    const data = await api("/api/net-usage", {
      method: "POST",
      body: JSON.stringify(credentials())
    });
    const d = data.data || {};
    const values = ["preview_bps", "playback_bps", "ipc_bps", "disk_bps"];
    $("networkMetrics").querySelectorAll(".metric strong").forEach((el, i) => {
      el.textContent = formatBitrate(Number(d[values[i]] || 0));
    });
    log(data.details || data.message, "ok");
  } catch (e) {
    toast(e.message, "error");
    log(e.details || e.message, "error");
  }
}

async function takeSnapshot() {
  if (!requireConnection() || !state.selectedChannel) return;

  try {
    const data = await api("/api/snapshot", {
      method: "POST",
      body: JSON.stringify(credentials(state.selectedChannel))
    });
    window.open(data.image_url, "_blank", "noopener");
    toast("Снимок получен", "ok");
    log(data.details || data.message, "ok");
  } catch (e) {
    toast(e.message, "error");
    log(e.details || e.message, "error");
  }
}

async function sendPtz(action) {
  if (!requireConnection() || !state.selectedChannel || state.busy) return;
  state.busy = true;

  try {
    const data = await api("/api/ptz", {
      method: "POST",
      body: JSON.stringify({
        ...credentials(state.selectedChannel),
        action: action,
        speed: Number($("ptzSpeed").value),
        duration: 280
      })
    });
    log(data.details || data.message, "ok");
  } catch (e) {
    toast(e.message, "error");
    log(e.details || e.message, "error");
  } finally {
    state.busy = false;
  }
}

async function preset(action) {
  if (!requireConnection() || !state.selectedChannel) return;

  try {
    const data = await api("/api/preset", {
      method: "POST",
      body: JSON.stringify({
        ...credentials(state.selectedChannel),
        action: action,
        preset: Number($("presetNumber").value || 1)
      })
    });
    toast(data.message, "ok");
    log(data.details || data.message, "ok");
  } catch (e) {
    toast(e.message, "error");
    log(e.details || e.message, "error");
  }
}


function setupArchiveDefaults() {
  const end = new Date();
  const start = new Date(end.getTime() - 24 * 60 * 60 * 1000);
  $("archiveStart").value = localDateValue(start);
  $("archiveEnd").value = localDateValue(end);
}

async function searchArchive() {
  const cameraId = $("archiveChannel").value;
  if (!cameraId) {
    toast("Сначала добавьте камеру в NVR", "error");
    return;
  }

  const btn = $("archiveSearchBtn");
  btn.disabled = true;
  btn.textContent = "Поиск…";

  try {
    const start = Math.floor(new Date($("archiveStart").value).getTime() / 1000);
    const end = Math.floor(new Date($("archiveEnd").value).getTime() / 1000);
    const data = await api(
      "/api/nvr/recordings?camera_id=" + encodeURIComponent(cameraId) +
      "&start=" + encodeURIComponent(start) +
      "&end=" + encodeURIComponent(end) +
      "&limit=2000"
    );
    renderArchiveResults(data.recordings || []);
  } catch (e) {
    renderArchiveResults([]);
    toast(e.message, "error");
    log("NVR archive: " + e.message, "error");
  } finally {
    btn.disabled = false;
    btn.textContent = "Найти";
  }
}

function formatArchiveTime(ts) {
  return new Date(Number(ts || 0) * 1000).toLocaleString("ru-RU");
}

function renderArchiveResults(files) {
  $("archiveResultCount").textContent = files.length + " записей";
  const body = $("archiveTableBody");
  body.textContent = "";

  if (!files.length) {
    const tr = document.createElement("tr");
    tr.innerHTML = '<td colspan="5" class="table-empty">Записи не найдены</td>';
    body.appendChild(tr);
    return;
  }

  files.forEach((file) => {
    const tr = document.createElement("tr");
    const filename = (file.path || "").split("/").pop() || file.path || "recording.mp4";

    [
      formatArchiveTime(file.started_at),
      formatArchiveTime(file.ended_at),
      formatSize(file.size_bytes),
      filename
    ].forEach((value) => {
      const td = document.createElement("td");
      td.textContent = value;
      tr.appendChild(td);
    });

    const actions = document.createElement("td");
    const play = document.createElement("button");
    play.className = "btn";
    play.textContent = "Воспроизвести";
    play.addEventListener("click", () => prepareArchive(file));
    actions.appendChild(play);
    tr.appendChild(actions);
    body.appendChild(tr);
  });
}

async function prepareArchive(file) {
  const player = $("archivePlayer");
  $("archivePlayerEmpty").classList.add("hidden");
  player.src = file.url;
  player.load();
  player.play().catch(() => {});
  $("archiveNowTitle").textContent =
    formatArchiveTime(file.started_at) + " — " + formatArchiveTime(file.ended_at);
  $("archiveDownload").href = file.url;
  $("archiveDownload").classList.remove("hidden");
  toast("Запись открыта из локального архива NVR", "ok");
}

async function startEvents() {
  if (!requireConnection()) return;

  try {
    const data = await api("/api/events/start", {
      method: "POST",
      body: JSON.stringify(credentials())
    });
    state.eventActive = true;
    renderEventState();
    toast(data.message, "ok");
    await pollEvents();
  } catch (e) {
    toast(e.message, "error");
    log(e.details || e.message, "error");
  }
}

async function stopEvents() {
  try {
    await api("/api/events/stop", { method: "POST", body: "{}" });
  } catch {}
  state.eventActive = false;
  renderEventState();
}

async function pollEvents() {
  try {
    const data = await api("/api/events");
    state.eventActive = Boolean(data.active);
    state.events = data.events || [];
    renderEventState();
    renderEvents();
  } catch {}
}

function renderEventState() {
  $("eventMonitorStatus").textContent = state.eventActive ? "мониторинг включён" : "мониторинг выключен";
  $("eventsStateBadge").textContent = state.eventActive ? "Активен" : "Выключено";
  $("eventsStateBadge").className = "badge " + (state.eventActive ? "ok" : "neutral");
  $("toggleEventMonitor").style.color = state.eventActive ? "#49df87" : "";
}

function eventTitle(ev) {
  const map = {
    motion: "Движение",
    video_lost: "Потеря видеосигнала",
    disk_full: "Диск заполнен",
    disk_error: "Ошибка диска",
    tamper: "Саботаж камеры",
    illegal_access: "Ошибка авторизации",
    sensor: "Тревожный вход",
    event: "Событие устройства"
  };
  return map[ev.kind] || ev.kind || "Событие";
}

function renderEvents() {
  const mini = $("eventMiniList");
  mini.textContent = "";
  const items = state.events.slice(0, 12);

  if (!items.length) {
    mini.innerHTML = '<div class="empty-note">Нет событий</div>';
  } else {
    items.forEach((ev) => {
      const card = document.createElement("div");
      card.className = "event-card";
      const t = new Date((ev.ts || ev.received || 0) * 1000);
      const time = document.createElement("span");
      time.className = "event-time";
      time.textContent = t.toLocaleString("ru-RU");
      const strong = document.createElement("strong");
      strong.textContent = eventTitle(ev);
      const small = document.createElement("small");
      small.textContent = ev.channel ? "Канал " + ev.channel : "Устройство";
      card.append(time, strong, small);
      mini.appendChild(card);
    });
  }

  const body = $("eventTableBody");
  body.textContent = "";

  if (!state.events.length) {
    body.innerHTML = '<tr><td colspan="4" class="table-empty">Событий пока нет</td></tr>';
    return;
  }

  state.events.forEach((ev) => {
    const tr = document.createElement("tr");
    const values = [
      new Date((ev.ts || ev.received || 0) * 1000).toLocaleString("ru-RU"),
      eventTitle(ev),
      ev.channel || "—",
      ev.command || "—"
    ];

    values.forEach((value) => {
      const td = document.createElement("td");
      td.textContent = value;
      tr.appendChild(td);
    });
    body.appendChild(tr);
  });
}

async function testAlarmChannel() {
  if (!requireConnection()) return;

  try {
    const data = await api("/api/alarm-test", {
      method: "POST",
      body: JSON.stringify(credentials())
    });
    toast(data.message, "ok");
    log(data.details || data.message, "ok");
  } catch (e) {
    toast(e.message, "error");
    log(e.details || e.message, "error");
  }
}

async function loadAbility() {
  try {
    const data = await api("/api/ability", {
      method: "POST",
      body: "{}"
    });
    const d = data.data || {};
    const values = ["max_realplay", "max_playback", "max_alarm", "max_voice"];

    $("abilityMetrics").querySelectorAll(".metric strong").forEach((el, i) => {
      el.textContent = d[values[i]] || "—";
    });
    log(data.details || data.message, "ok");
  } catch (e) {
    toast(e.message, "error");
  }
}

function formatSize(bytes) {
  const n = Number(bytes || 0);
  if (n <= 0) return "0 B";
  const units = ["B", "KB", "MB", "GB", "TB"];
  const i = Math.min(units.length - 1, Math.floor(Math.log(n) / Math.log(1024)));
  return (n / Math.pow(1024, i)).toFixed(i === 0 ? 0 : 1) + " " + units[i];
}

function formatBitrate(value) {
  const n = Number(value || 0);
  if (n >= 1000000) return (n / 1000000).toFixed(1) + " Mb/s";
  if (n >= 1000) return (n / 1000).toFixed(1) + " Kb/s";
  return n + " b/s";
}

function localDateValue(d) {
  const pad = (n) => String(n).padStart(2, "0");
  return (
    d.getFullYear() + "-" +
    pad(d.getMonth() + 1) + "-" +
    pad(d.getDate()) + "T" +
    pad(d.getHours()) + ":" +
    pad(d.getMinutes()) + ":" +
    pad(d.getSeconds())
  );
}


$("quickConnect").addEventListener("click", () => navigate("device"));
$("connectBtn").addEventListener("click", connectDevice);
$("disconnectBtn").addEventListener("click", disconnectUi);
$("addToNvrBtn").addEventListener("click", addSelectedToNvr);
$("refreshDeviceState").addEventListener("click", refreshDeviceStatus);
$("deviceStatusBtn").addEventListener("click", refreshDeviceStatus);
$("networkUsageBtn").addEventListener("click", loadNetworkUsage);
$("systemRefresh").addEventListener("click", refreshSdkStatus);
$("abilityBtn").addEventListener("click", loadAbility);
$("snapshotSelected").addEventListener("click", takeSnapshot);
$("fullscreenSelected").addEventListener("click", () => {
  const tile = document.querySelector('.video-tile[data-slot="' + state.selectedSlot + '"]');
  if (tile && tile.requestFullscreen) tile.requestFullscreen();
});
$("stopAllLive").addEventListener("click", stopAllLive);
$("archiveSearchBtn").addEventListener("click", searchArchive);
$("eventsStart").addEventListener("click", startEvents);
$("eventsStop").addEventListener("click", stopEvents);
$("alarmTest").addEventListener("click", testAlarmChannel);
$("toggleEventMonitor").addEventListener("click", () => {
  if (state.eventActive) stopEvents();
  else startEvents();
});
$("clearLog").addEventListener("click", () => {
  $("log").textContent = "";
});

$("togglePassword").addEventListener("click", () => {
  const input = $("password");
  const show = input.type === "password";
  input.type = show ? "text" : "password";
  $("togglePassword").textContent = show ? "Скрыть" : "Показать";
});

$("ptzSpeed").addEventListener("input", () => {
  $("ptzSpeedValue").textContent = $("ptzSpeed").value;
});

$$("[data-ptz]").forEach((button) => {
  button.addEventListener("click", () => sendPtz(button.dataset.ptz));
});

$("presetGoto").addEventListener("click", () => preset("goto"));
$("presetSet").addEventListener("click", () => preset("set"));

["ip", "port", "user"].forEach((id) => {
  const saved = localStorage.getItem("hcnvr_" + id);
  if (saved !== null) $(id).value = saved;
  $(id).addEventListener("change", () => {
    localStorage.setItem("hcnvr_" + id, $(id).value);
  });
});

createVideoTiles();
setupArchiveDefaults();
renderCameraList();
fillChannelSelects();
renderEventState();
refreshSdkStatus();
loadNvrCameras();
loadAbility();
pollEvents();

setInterval(() => {
  $("liveClock").textContent = new Date().toLocaleTimeString("ru-RU");
}, 1000);

setInterval(pollEvents, 2500);
setInterval(refreshSdkStatus, 15000);

log("NVR запущен. Готов к подключению и записи.");
