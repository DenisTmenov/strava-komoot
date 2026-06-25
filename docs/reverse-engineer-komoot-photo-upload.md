# Reverse-engineer Komoot photo/video upload endpoint

**Цель:** перехватить трафик мобильного приложения Komoot при загрузке фото/видео, чтобы добавить синхронизацию медиа из Strava.

## Инструмент

Используем **mitmproxy** — MITM-прокси с Web UI.

## Настройка

### 1. Установить mitmproxy на Mac

```bash
brew install mitmproxy
```

### 2. Запустить mitmweb (Web UI)

```bash
mitmweb --listen-port 8888
```

Откроется `http://127.0.0.1:8081` — Web UI для просмотра запросов в реальном времени.

Прокси слушает на порту `8888` (HTTP/HTTPS).

### 3. Настроить телефон на прокси

- **Android:** Settings → WiFi → длинное нажатие на сети → Modify network → Advanced → Proxy → Manual → ввести IP твоего Mac и порт `8888`
- **iOS:** Settings → WiFi → значок ⓘ у сети → HTTP Proxy → Configure Proxy → Manual → ввести IP и порт `8888`

### 4. Установить SSL-сертификат (для HTTPS)

- Открыть в браузере на телефоне: `http://mitm.it`
- Выбрать свою платформу (Android / iOS)
- Установить сертификат
- На **iOS** дополнительно: Settings → General → About → Certificate Trust Settings → включить mitmproxy

### 5. Поймать запросы

1. Открыть Komoot на телефоне
2. Зайти в любой тур (желательно тот, у которого ещё нет фото)
3. Нажать "Upload photos" / "Add photo"
4. Выбрать фото/видео, загрузить
5. В **mitmweb** отсортировать по домену `api.komoot.de` или искать:

- `POST` / `PUT` с `Content-Type: multipart/form-data`
- Эндпоинты с `upload`, `media`, `image`, `photo`, `picture`
- Ответы с `201 Created`

## Что ищем

Нужно найти:

| Что | Пример |
|---|---|
| URL эндпоинта | `POST /v007/tours/{id}/images/upload` |
| Формат данных | multipart, raw binary, JSON с URL, etc. |
| Query/body параметры | caption, is_cover, order, etc. |
| Auth | тот же Basic Auth `userId:token` или Bearer |

## Предполагаемые эндпоинты для проверки (начни с них)

| Endpoint | Метод | Зачем |
|---|---|---|
| `/v007/tours/{id}/images/` | POST | если есть — upload |
| `/v007/tours/{id}/cover_images/` | POST | если есть — upload |
| `/v007/tours/{id}/media/` | POST | медиа upload |
| `/v007/media/` | POST | общий медиа upload |
| `/v007/upload/image` | POST | generic upload |

## После того как найдёшь эндпоинт

- Сохрани полный запрос (URL + headers + body)
- Скопируй ответ (формат JSON)
- Открой issue или напиши — добавим поддержку в `komoot.py`
