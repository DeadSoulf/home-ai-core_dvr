> Продолжение разработки и рабочие принципы: [docs/PROJECT_CONTEXT_RU.md](docs/PROJECT_CONTEXT_RU.md)

# HOME AI Core DVR

Минимальный Docker-проект DVR/NVR на базе Hikvision HCNetSDK V6.1.9.48 Linux64.

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
