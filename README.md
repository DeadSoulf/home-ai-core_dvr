> Продолжение разработки и рабочие принципы: [docs/PROJECT_CONTEXT_RU.md](docs/PROJECT_CONTEXT_RU.md)

# HOME AI Core DVR

Минимальный Docker-проект DVR/NVR с существующим runtime Hikvision HCNetSDK V6.1.9.48 Linux64. Для официального **HCNetSDK 6.1.11.40** добавлен отдельный **локально собираемый** Docker-образ с адаптерами V40 для записи/просмотра, авторизации камер, снимков, PTZ и пресетов. Публичный образ и репозиторий не включают новый проприетарный SDK.

## Что оставлено

- HCNetSDK runtime-библиотеки, необходимые для функций NVR/DVR.
- Веб-консоль HCNetSDK NVR Console.
- Вспомогательные runtime-утилиты, которые вызываются веб-сервером:
  - `sdk-smoke`
  - `sdk-login-test`
  - `sdk-stream`
  - `sdk-action`
  - `sdk-alarm-monitor`
  - `sdk-extended`
- FFmpeg для Live View/HLS и работы с видео.

## Что удалено из исходного Docker-образа

- большой экспорт `.tar`;
- официальный интерактивный demo-бинарник `sdkTest`;
- C/C++ headers SDK, не нужные для runtime;
- Python `__pycache__`;
- временные HLS/архивные файлы и логи;
- отладочные подсказки старого entrypoint.

## Сборка

```bash
docker build -t home-ai-core-dvr:6.1.9.48 .
```

или:

```bash
docker compose build
```

## Запуск

```bash
docker compose up -d
```

Веб-интерфейс:

```text
http://localhost:8090
```

Проверка состояния:

```bash
docker inspect --format '{{.State.Health.Status}}' home-ai-core-dvr
```

API status:

```text
http://localhost:8090/api/status
```

## Данные

Runtime-выходы сохраняются в:

```text
./data/output
```

Каталог не коммитится в Git.

## Архитектура

Текущие HCNetSDK и вспомогательные бинарники собраны для Linux amd64/x86_64.

## Важно

Файлы в `sdk/lib` являются сторонними бинарными компонентами Hikvision. Их использование и распространение регулируются условиями производителя.

Текущая веб-консоль слушает порт 8090 и изначально не имеет отдельной HTTP-аутентификации. Не публикуйте этот порт напрямую в Интернет без reverse proxy, авторизации и TLS.

## Интеграция HCNetSDK 6.1.11.40 (Linux amd64)

Предоставленный производителем архив `EN-HCNetSDKV6.1.11.40_build20260922_linux64.zip`
содержит полный набор `lib/`, включая `HCNetSDKCom/`, OpenSSL 3,
заголовки `incEn/` и примеры. При переходе с 6.1.9.48 **нельзя**
заменять только `libhcnetsdk.so`, перемешивать библиотеки OpenSSL 1.1
и 3 или использовать старые `sdk-*` исполняемые файлы без повторной
проверки ABI.

Подготовить SDK **локально**, не добавляя бинарные файлы производителя в Git:

```bash
python3 tools/stage_hcnetsdk.py /path/to/EN-HCNetSDKV6.1.11.40_build20260922_linux64.zip \
  --output /tmp/hcnetsdk-6.1.11.40 \
  --sha256 2b8be43fd1cf0d4bd16d4a3b5860c214ee278fd851ea0c59ab0e0b4a9eceee29
sh tools/verify_hcnetsdk_abi.sh /tmp/hcnetsdk-6.1.11.40 /tmp/hcnetsdk-v40-stream
```

ABI-проверка использует оригинальный `HCNetSDK.h`: для Linux64
`NET_DVR_USER_LOGIN_INFO` занимает 416 байт,
`cbLoginResultV40` имеет смещение 296, `NET_DVR_DEVICEINFO_V40` — 344,
`NET_DVR_PREVIEWINFO` — 280. Новый адаптер использует синхронный
`NET_DVR_Login_V40`, `NET_DVR_RealPlay_V40`, callback потоковых данных,
TCP и автоматическое переподключение; его `--version` проверяет запуск
в изолированном процессе **без логина на камеру**.

Проверка и сборка нативных утилит теперь включают `sdk-stream`,
`sdk-smoke`, `sdk-login-test` и пересобранный из исходников
`sdk-action` (snapshot, PTZ, пресеты). Библиотеки нового SDK не
подмешиваются к старому образу.

**Сборка только на своём компьютере, из переданного архива вне Git:**

```bash
sh tools/build_sdk611_local.sh /secure/vendor/EN-HCNetSDKV6.1.11.40_build20260922_linux64.zip
```

Скрипт создаст `home-ai-core-nvr:1.1.6-sdk611-local`, не трогая работающий
NVR. Функции `sdk-alarm-monitor` и `sdk-extended` в этом варианте
явно недоступны (код 78): их старые бинарники несовместимы с новым
ABI и OpenSSL 3. Требуется отдельная разработка и тестирование этих функций.
Подробнее: [docs/SDK_6_1_11_40_RU.md](docs/SDK_6_1_11_40_RU.md).

**Этот образ — локальная кандидатная сборка, не опубликованный релиз для
автообновления через Core.** Для реального выпуска нужны лицензирование
распространения, проверка с камерами, резервное копирование и безопасное
обновление уже установленного контейнера. Не удаляйте `/data`, `nvr.db`
и видеоархив. Исходный SDK ZIP не публикуется в GitHub.

`GET /api/nvr/sdk` и `GET /api/status` определяют **фактически
загруженную** версию, а не предполагаемую по метке Docker.
