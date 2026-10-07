# h.a.c._nvr — инструкция

Дата: 7 октября 2026 г.

## Назначение

`h.a.c._nvr` — отдельный Docker-модуль NVR для HOME AI Core. Он поддерживает Hikvision через HCNetSDK и прямые RTSP-источники, ведёт локальную постоянную запись, индексирует архив в SQLite и автоматически очищает старые записи.

## Текущая конфигурация

- контейнер: `h.a.c._nvr`
- образ: `home-ai-core-nvr:1.0.0`
- Web/API: `8090`
- максимум камер: `32`
- сегмент записи: `300` секунд
- срок хранения: `7` дней
- лимит архива: `50` ГБ
- база: `/app/output/nvr.db`
- записи: `/app/output/recordings`
- recorder-логи: `/app/output/logs`

## Установка и обновление на Windows

```powershell
cd D:\AI\NVR\home-ai-core_dvr
git fetch origin
git reset --hard origin/main
docker compose build
docker compose up -d --force-recreate
```

Проверка:

```powershell
docker ps --filter "name=h.a.c._nvr"
docker logs --tail 100 h.a.c._nvr
Invoke-RestMethod http://localhost:8090/api/nvr/status
```

Ожидаемые поля статуса:

```text
ok                : True
service           : h.a.c._nvr
cameras           : 0
max_cameras       : 32
camera_slots_free : 32
active_recorders  : 0
recordings        : 0
segment_seconds   : 300
retention_days    : 7
max_storage_gb    : 50,0
```

В русской локали PowerShell `50,0` означает `50.0` ГБ.

## Веб-интерфейс

Открыть `http://localhost:8090`.

Для Hikvision:

1. Указать IP, SDK-порт (обычно 8000), логин и пароль.
2. Нажать «Подключиться».
3. Выбрать канал.
4. Нажать «Добавить канал в NVR».
5. Канал сохраняется в SQLite и автоматически запускается на запись.

После перезапуска контейнера включённые камеры запускаются снова автоматически.

## Локальный архив

Записи сохраняются как MP4-сегменты в `/app/output/recordings/<camera_id>/`. Закрытые сегменты индексируются в SQLite. При сегменте 300 секунд первая запись может появиться в индексе примерно через 5 минут.

## Настройки compose.yaml

```yaml
environment:
  NVR_SEGMENT_SECONDS: "300"
  NVR_RETENTION_DAYS: "7"
  NVR_MAX_STORAGE_GB: "50"
  NVR_MAX_CAMERAS: "32"
```

`NVR_RETENTION_DAYS=0` отключает очистку по возрасту. `NVR_MAX_STORAGE_GB=0` отключает лимит по объёму. Максимально поддерживаемое число камер текущей версии — 32.

## Основные API

```text
GET    /api/nvr/status
GET    /api/nvr/cameras
POST   /api/nvr/cameras
POST   /api/nvr/cameras/{id}/start
POST   /api/nvr/cameras/{id}/stop
POST   /api/nvr/cameras/{id}/restart
DELETE /api/nvr/cameras/{id}
GET    /api/nvr/recordings
POST   /api/nvr/retention
```

Для удаления камеры вместе с архивом:

```text
DELETE /api/nvr/cameras/{id}?delete_recordings=1
```

## Диагностика

```powershell
docker logs --tail 200 h.a.c._nvr
docker exec h.a.c._nvr ps -ef
docker exec h.a.c._nvr grep -n "/api/nvr/status" /app/web/server.py
Invoke-RestMethod http://localhost:8090/api/nvr/status
```

## Резервное копирование

Сохранять каталог `data/output/`. Файл `data/output/nvr.db` содержит конфигурацию камер и индекс локального архива.

## Безопасность

Текущая самостоятельная версия хранит учётные данные камер в локальной SQLite-базе. Перед промышленным развёртыванием пароли следует перенести в защищённое хранилище HOME AI Core и выдавать recorder только при установлении соединения.
