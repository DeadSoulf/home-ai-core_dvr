# HOME AI Cameras / NVR module

Отдельный Docker-модуль **Cameras / NVR** для HOME AI на базе Hikvision HCNetSDK V6.1.9.48 Linux64.

Этот репозиторий больше не является частью бинарника HOME AI Core. Core управляет установкой, версиями, разрешениями и lifecycle модуля, а NVR работает в собственном контейнере.

## Module contract

Manifest: `module.json`

- module ID: `nvr`
- module version: `0.1.0`
- runtime: Docker
- architecture: `amd64`
- internal port: `8090`
- health endpoint: `/health`
- image target: `ghcr.io/deadsoulf/home-ai-core-dvr:0.1.0`

HCNetSDK runtime пока доступен только для Linux amd64/x86_64, поэтому manifest не объявляет arm64.

## Что входит в контейнер

- HCNetSDK runtime-библиотеки;
- Web/API service модуля;
- runtime-утилиты `sdk-smoke`, `sdk-login-test`, `sdk-stream`, `sdk-action`, `sdk-alarm-monitor`, `sdk-extended`;
- FFmpeg для Live View/HLS и обработки видео.

## Локальная разработка

Сборка:

```bash
docker build -t home-ai-core-dvr:0.1.0 .
```

или:

```bash
docker compose build
```

Запуск:

```bash
docker compose up -d
```

Standalone compose публикует Web/API **только на localhost**:

```text
http://127.0.0.1:8090
```

Проверка module health:

```text
http://127.0.0.1:8090/health
```

Расширенный статус SDK:

```text
http://127.0.0.1:8090/api/status
```

## Работа под HOME AI Core

В штатной установке Core не должен публиковать порт 8090 напрямую в LAN/Internet. Контейнер подключается к управляемой HOME AI module network, а доступ пользователя к API/UI модуля проходит через Core с его identity/RBAC/audit boundary.

Контейнеру не передаётся `/var/run/docker.sock` и он не запускается в privileged mode.

Persistent runtime-данные должны храниться в отдельном volume/data directory модуля.

## Данные

Текущий development compose сохраняет runtime-выходы в:

```text
./data/output
```

Каталог не коммитится в Git.

## Текущий функционал прототипа

- подключение к Hikvision DVR/NVR через HCNetSDK;
- чтение каналов и состояния устройства;
- Live View/HLS;
- snapshots;
- PTZ/presets;
- alarms/events;
- поиск и подготовка архива;
- FFmpeg media processing.

Следующий этап — убрать standalone-ориентированную авторизацию/конфигурацию из UI и подключить модуль к namespaced Core API contract.

## Third-party SDK

Файлы в `sdk/lib` являются сторонними бинарными компонентами Hikvision. Их использование и распространение регулируются условиями производителя. Перед публичной публикацией контейнерного образа необходимо отдельно подтвердить право на распространение этих бинарных файлов.
