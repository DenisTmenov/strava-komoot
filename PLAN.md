# План: синхронизация тренировок Strava → Komoot

## Context

Denis хочет приложение, которое переносит велосипедные тренировки из Strava в Komoot.

**Главное ограничение:** у Komoot нет официального публичного API на запись. Используем приватный API через готовую библиотеку **[kompy](https://github.com/Tsadoq/kompy)** (Python, 20★, поддерживается). Это формально серая зона по ToS Komoot и может ломаться при изменениях на их стороне — Denis принял этот риск.

**Референсы:**
- `Tsadoq/kompy` — Python обёртка приватного Komoot API
- `stefan-bergstein/strava-komoot-sync` — Python-проект того же сценария (используем как референс-архитектуру)

## Решения

| Развилка | Выбор |
|---|---|
| Komoot API | Через `kompy` (reverse-engineered private API, Basic Auth) |
| Масштаб | Single user (только Denis) |
| Запуск | Локально, по требованию (без webhooks/cron/VPS) |
| UI | Локальный веб-UI: 3 блока (changed / new / synced) |
| Объём | Историческая миграция + новые; только велосипед; дедупликация на стороне Komoot |
| Отслеживаемые правки | name, sport_type, visibility, GPS-трек |
| Применение правок | Только по клику (не автоматически) |
| Стек | Python |

## Конечная архитектура

```
┌──────────────────────────────────────────────────────┐
│  FastAPI + Jinja (localhost:8000)                     │
│  GET /, POST /sync, POST /apply, GET /jobs/{id}      │
│  GET /activities/{id}, GET /auth/strava               │
├───────────────┬──────────────────┬────────────────────┤
│  StravaSource │  GPX builder     │  KomootSink        │
│  (stravalib)  │  (gpxpy)         │  (kompy + raw req) │
│  OAuth, list  │  streams → GPX   │  upload/update/    │
│  streams      │  + track_hash    │  delete            │
└───────────────┴──────────────────┴────────────────────┘
                         │
                 ┌───────┴───────┐
                 │  SQLite       │
                 │  SyncStateRepo│
                 │  (snapshots)  │
                 └───────────────┘
```

## Зависимости

- `fastapi`, `uvicorn`, `jinja2` — веб-UI
- `stravalib` — Strava API
- `gpxpy` — сборка GPX
- `kompy` — Komoot login + upload
- `pydantic-settings` + `python-dotenv` — конфиг
- `pytest` + `responses` — тесты

## Структура (финальная)

```
src/strava_komoot/
  __init__.py
  config.py          # .env → pydantic-settings
  strava.py          # OAuth + список + streams
  gpx.py             # streams → GPX, track_hash
  komoot.py          # KomootSink (upload / update_meta / delete + маппинги)
  diff.py            # activity_diff → изменения
  db.py              # SQLite: CRUD synced (со snapshot)
  sync.py            # оркестратор: classify, apply, jobs
  web.py             # FastAPI эндпоинты
  templates/
    index.html       # 3-блочный UI
```

---

# Реализация: пошаговые вертикальные срезы

Каждый шаг — работающий промежуточный продукт. Можно остановиться на любом шаге.
DeepSeek Flash Free на каждом шаге нужно читать только файлы из **этого шага**, остальное — чёрный ящик.

---

## Step 0 — Scaffold

**Цель:** пустое FastAPI-приложение, которое запускается и отвечает 200.

**Что создаём:**

| Файл | Что делает |
|---|---|
| `pyproject.toml` | uv-проект со всеми зависимостями |
| `src/strava_komoot/__init__.py` | пустой |
| `src/strava_komoot/config.py` | загрузка `.env` через pydantic-settings |
| `src/strava_komoot/web.py` | FastAPI app, GET / → {"ok": true} |
| `.env.example` | шаблон с STRAVA_*, KOMOOT_* |

**Проверка:**
```bash
uv sync && uv run uvicorn src.strava_komoot.web:app --reload
curl http://localhost:8000  # → {"ok": true}
```

---

## Step 1 — Strava reader (CLI)

**Цель:** CLI-скрипт, который авторизуется в Strava (OAuth, сохранение токена) и выводит список велосипедных активностей.

**Что создаём:**

| Файл | Что делает |
|---|---|
| `src/strava_komoot/strava.py` | OAuth-флоу (save/load/refresh token), `list_activities()`, `get_streams()` |

**Важно:** токены сохраняются `chmod 600` в `~/.strava_komoot/tokens.json`.

**Проверка:**
```bash
uv run python -c "from strava_komoot.strava import StravaSource; s = StravaSource(); print(len(s.list_activities()))"
# → вывод последних активностей (Ride/MTB/Gravel/EBike) с id, name, type
```

**Что НЕ делаем:** пока никакой БД, никакого Komoot, никакого веба.

---

## Step 2 — GPX builder

**Цель:** утилита, которая превращает streams-данные активности в валидный GPX и вычисляет track_hash.

**Что создаём:**

| Файл | Что делает |
|---|---|
| `src/strava_komoot/gpx.py` | `build_gpx(activity_meta, streams) → str`, `track_hash(streams) → str` |
| `tests/test_gpx.py` | проверка: валидный GPX, стабильность хеша |

**Проверка:**
```bash
uv run python -c "
from strava_komoot.strava import StravaSource
from strava_komoot.gpx import build_gpx, track_hash
s = StravaSource()
acts = s.list_activities(limit=1)
streams = s.get_streams(acts[0].id)
print(track_hash(streams))
print(build_gpx(acts[0], streams)[:200])
"
# → хеш + начало GPX-файла
uv run pytest tests/test_gpx.py -v
```

**Что НЕ делаем:** Komoot, БД, веб.

---

## Step 3 — Komoot uploader (CLI)

**Цель:** CLI-скрипт, который логинится в Komoot через kompy и загружает GPX.

**Что создаём:**

| Файл | Что делает |
|---|---|
| `src/strava_komoot/komoot.py` | `KomootSink`: `upload(gpx, sport, name, status)`, различает 201/202, возвращает `(tour_id, status)` |
| `tests/test_sport_map.py` | маппинг Ride→touringbicycle, GravelRide→mtb и т.д. |
| `tests/test_visibility_map.py` | маппинг everyone→public и т.д. |

**Проверка (ручная, live):**
```bash
uv run python -c "
from strava_komoot.strava import StravaSource
from strava_komoot.gpx import build_gpx
from strava_komoot.komoot import KomootSink
s = StravaSource()
acts = s.list_activities(limit=1)
streams = s.get_streams(acts[0].id)
gpx = build_gpx(acts[0], streams)
k = KomootSink()
tour_id, status = k.upload(gpx, 'touringbicycle', acts[0].name, 'private')
print(tour_id, status)
"  # → tour_id, 'synced' или 'already_present'
```

**Что НЕ делаем:** БД, веб, diff.

---

## Step 4 — DB + синхронизация (CLI)

**Цель:** SQLite-хранилище состояния синхронизации + CLI-оркестратор, который:
1. Получает список активностей из Strava
2. Сверяется с БД
3. Раскладывает по трём корзинам (new / modified / synced)
4. По команде sync — загружает новые в Komoot
5. По команде apply — применяет изменения

**Что создаём:**

| Файл | Что делает |
|---|---|
| `src/strava_komoot/db.py` | SQLite: schema + CRUD synced (strava_id, komoot_tour_id, snapshot JSON, status, synced_at) |
| `src/strava_komoot/diff.py` | `activity_diff(activity, snapshot) → dict` — сравнивает 4 поля |
| `src/strava_komoot/sync.py` | оркестратор: `classify()`, `sync(ids)`, `apply(ids)`, фоновые job'ы |
| `tests/test_diff.py` | 5 сценариев diff |
| `tests/test_db.py` | CRUD + snapshot round-trip |
| `tests/test_sync_classify.py` | активности по трём корзинам |

**Проверка:**
```bash
uv run python -c "
from strava_komoot.sync import SyncEngine
e = SyncEngine()
result = e.classify()
print(f'new: {len(result[\"new\"])}, modified: {len(result[\"modified\"])}, synced: {len(result[\"synced\"])}')
"
uv run pytest tests/ -v
```

**Что НЕ делаем:** веб-UI.

---

## Step 5 — Web UI

**Цель:** FastAPI + Jinja2-шаблон с тремя блоками, чекбоксами, bulk-действиями, polling прогресса.

**Что создаём:**

| Файл | Что делает |
|---|---|
| `src/strava_komoot/web.py` | обновляем: GET / (рендер 3 блоков), POST /sync, POST /apply, GET /jobs/{id}, GET /auth/strava |
| `src/strava_komoot/templates/index.html` | три блока с чекбоксами, diff-чипами, polling |

**Проверка:**
```bash
uv run uvicorn src.strava_komoot.web:app --reload
# открыть http://localhost:8000 — три блока, можно тыкать чекбоксы
```

**Это финальный шаг.** На нём всё готово.

---

## Что НЕ делаем (первая итерация)

- Webhooks от Strava (ручной запуск)
- Multi-user
- Playwright-фолбэк
- Виды спорта кроме велосипедных
- Шифрование БД (chmod 600 достаточно)

## Риски

1. **kompy сломается после изменений Komoot.** Mitigation: интерфейс `ActivitySink` позволяет переключиться на Playwright или fork.
2. **GravelRide мапится в `mtb`.** Если нужно `racebike` — однострочное изменение.
3. **Strava OAuth callback требует localhost.** Если Strava App настроен на другой URL — поправим.
4. **Изменение трека = удаление+перезагрузка.** Теряются лайки/комменты в Komoot. В UI будет предупреждение.
5. **Маппинг видимости:** everyone→public, followers_only→friends, only_me→private.
