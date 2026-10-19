> Продолжение разработки и рабочие принципы: [docs/PROJECT_CONTEXT_RU.md](docs/PROJECT_CONTEXT_RU.md)

# HOME AI Core DVR

Минимальный Docker-проект DVR/NVR с существующим runtime Hikvision HCNetSDK V6.1.9.48 Linux64. Поддержка анализа и подготовки **6.1.11.40** добавлена отдельно; публичный Docker-образ пока не содержит новую проприетарную библиотеку автоматически.

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

Результат проверки **не устанавливает** SDK в NVR. Перед выпуском
образа с 6.1.11.40 нужно пересобрать и проверить остальные `sdk-action`,
`sdk-alarm-monitor` и `sdk-extended`, поскольку их исходников в
текущем репозитории нет. До этого не меняйте рабочий контейнер и архив.
Полный комплект SDK распространяется на условиях Hikvision — исходный ZIP
в данном репозитории не публикуется.

`GET /api/nvr/sdk` и `GET /api/status` определяют **фактически
загруженную** версию, а не предполагаемую по метке Docker.
