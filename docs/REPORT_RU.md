# Отчёт о проделанной работе — h.a.c._nvr

Дата: 7 октября 2026 г.

## Цель

Исходный проект на Hikvision HCNetSDK был веб-консолью для существующего регистратора: login, Live View, PTZ, события и работа с архивом внешнего устройства. Задача этапа — превратить его в самостоятельный NVR-модуль HOME AI Core с собственным локальным архивом.

## Выполнено

### Идентификация
- `HCNetSDK NVR Console` заменено на `NVR`.
- статус `SDK работает` заменён на `NVR работает`.
- имя контейнера: `h.a.c._nvr`.
- image: `home-ai-core-nvr:1.0.0`.
- healthcheck проверяет `/api/nvr/status`.

### Recorder
Добавлен `nvr/recorder.py`:
- постоянная запись;
- Hikvision/HCNetSDK и RTSP;
- автоматический запуск после рестарта;
- восстановление recorder при завершении процесса;
- MP4-сегментация;
- отдельные каталоги камер;
- отдельные recorder-логи.

### SQLite
Добавлена `/app/output/nvr.db` с таблицами `cameras` и `recordings`.

### Архив
Записи сохраняются в `/app/output/recordings/<camera_id>/`, завершённые сегменты индексируются, длительность определяется через `ffprobe`.

### Retention
Реализована очистка:
- по возрасту;
- по максимальному объёму архива.

По умолчанию: 7 дней, 50 ГБ, сегмент 300 секунд.

### 32 камеры
Добавлен `NVR_MAX_CAMERAS=32`. API публикует `max_cameras` и `camera_slots_free`; 33-я камера не принимается.

### API
Добавлены:
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

### Интерфейс
- добавлена кнопка «Добавить канал в NVR»;
- вкладка «Архив» переключена на локальные записи NVR;
- системный статус показывает число recorder и объём архива;
- количество камер отображается как текущее/максимум.

### Docker
Dockerfile включает recorder-модуль, каталоги archive/recordings/logs и NVR healthcheck. Compose содержит параметры сегмента, retention, объёма и 32 камер.

## Проверено

На рабочей машине API успешно вернул:

```text
ok               : True
service          : h.a.c._nvr
cameras          : 0
active_recorders : 0
recordings       : 0
storage_bytes    : 0
segment_seconds  : 300
retention_days   : 7
max_storage_gb   : 50,0
database         : /app/output/nvr.db
```

Это подтверждает запуск новой серверной части NVR и инициализацию SQLite/recorder.

## Следующие этапы

- защищённое хранение паролей в HOME AI Core;
- управление сохранёнными камерами в UI;
- включение/выключение recorder;
- удаление камеры с сохранением/удалением архива;
- настройки retention в UI;
- раскладки Live 16/25/32;
- расписания записи;
- запись по событиям;
- timeline;
- экспорт фрагментов;
- управление физическими дисками;
- нагрузочное тестирование 32 камер;
- тесты восстановления после сетевых обрывов и рестартов Docker.

## Итог

Проект переведён от HCNetSDK-веб-консоли к первой рабочей версии самостоятельного Docker NVR для HOME AI Core. HCNetSDK остаётся внутренним драйвером Hikvision, FFmpeg выполняет потоковую обработку/запись, SQLite хранит камеры и индекс локального архива.
