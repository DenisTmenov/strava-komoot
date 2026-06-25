# План: синхронизация тренировок Strava → Komoot

## Context

Denis хочет приложение, которое переносит велосипедные тренировки из Strava в Komoot. Папка `/Users/denis.tmenov/Denis/den_claude_code/strava_komoot/` создана и пуста — greenfield, кодовой базы нет.

**Главное ограничение:** у Komoot нет официального публичного API на запись. Используем приватный API через готовую библиотеку **[kompy](https://github.com/Tsadoq/kompy)** (Python, 20★, поддерживается). Это формально серая зона по ToS Komoot и может ломаться при изменениях на их стороне — Denis принял этот риск.

**Разведка GitHub (выполнена):**
- `Tsadoq/kompy` — Python, обёртка приватного Komoot API. Логин через HTTP Basic Auth, метод `upload_tour(gpx, activity_type, tour_name, status)` → реально работает. Документация: https://tsadoq.github.io/kompy/.
- `stefan-bergstein/strava-komoot-sync` — Python-проект ровно нашего сценария (Strava → Komoot через kompy, fallback GPX из streams, маппинг видов спорта, sync_log). Будем использовать как референс-архитектуру.
- `aexel90/strava_komoot_sync` — Go, сторонний.
- `Belenos-Toutatis/komoot-mcp` — MCP-сервер для Komoot, тоже использует kompy под капотом.

**Что снимает риск:** kompy уже решает обе сложные части — login (`USER_LOGIN_URL` + Basic Auth) и upload (`POST` с `params={sport, status, data_type, name}` + GPX в body). Дополнительный спайк по DevTools больше не нужен.

## Решения, согласованные с Denis

| Развилка | Выбор |
|---|---|
| Komoot API | Через библиотеку `kompy` (reverse-engineered private API, Basic Auth) |
| Масштаб | Single user (только Denis) |
| Запуск | Локально, по требованию (без webhooks/cron/VPS) |
| UI | Локальный веб-UI: список активностей с пометками статуса + множественный выбор + отдельный блок «изменены после синхронизации» |
| Объём | Историческая миграция всего прошлого + новые; только велосипед (Ride / MountainBikeRide / GravelRide / EBikeRide); дедупликация на стороне Komoot |
| Отслеживаемые правки | name, sport_type, visibility, GPS-трек (crop/trim) |
| Применение правок | Только по явному клику на кнопку «Apply to Komoot» (не автоматически) |
| Стек | Python |

## Архитектура

```
┌─────────────────────────────────────────────────────────────────┐
│  Local web app (FastAPI + Jinja + минимальный JS)               │
│  http://localhost:8000                                          │
│   ┌───────────────────────────────────────────────────────────┐ │
│   │ GET  /                   → 3 блока: changed/new/synced    │ │
│   │ POST /sync               → bulk: {ids: [...]} → job_id    │ │
│   │ POST /apply              → bulk: {ids: [...]} → job_id    │ │
│   │ GET  /jobs/{id}          → прогресс (для polling)         │ │
│   │ GET  /activities/{id}    → JSON с diff-снимком (для UI)   │ │
│   │ GET  /auth/strava        → OAuth-флоу Strava (1 раз)      │ │
│   └───────────────────────────────────────────────────────────┘ │
└────────────────────────┬────────────────────────────────────────┘
                         │
       ┌─────────────────┼──────────────────┐
       ▼                 ▼                  ▼
┌─────────────┐  ┌────────────────┐  ┌──────────────┐
│ Strava API  │  │ GPX builder    │  │ Komoot client│
│ (stravalib) │→ │ (gpxpy)        │→ │ (requests-   │
│             │  │ streams → GPX  │  │  session,    │
│             │  │                │  │  email/pwd)  │
└─────────────┘  └────────────────┘  └──────────────┘
                                            │
                          ┌─────────────────┴─────────────┐
                          ▼                               ▼
                  ┌──────────────┐               ┌────────────────┐
                  │ SQLite       │               │ Komoot tours   │
                  │ ~/.strava_   │               │ list (для      │
                  │  komoot.db   │               │ дедупликации)  │
                  └──────────────┘               └────────────────┘
```

### Слои (применяем паттерны из `patterns.md` без перебора)

- **Adapter**: `StravaSource` и `KomootSink` за общими интерфейсами `ActivitySource` / `ActivitySink`. Это позволит позже подменить Komoot-клиент (например, на Playwright-fallback), не трогая остальное. `KomootSink` имеет три метода: `upload(gpx, sport, name, status)`, `update_meta(tour_id, name, sport, status)`, `delete(tour_id)`.
- **Repository**: `SyncStateRepository` поверх SQLite — таблица `synced` хранит `strava_id`, `komoot_tour_id`, `synced_at`, `status`, плюс **снимок значимых полей на момент синхронизации** (`name`, `sport_type`, `visibility`, `track_hash`) — нужны для детекции изменений в Strava.
- **Strategy для маппинга**: `strava_sport_to_komoot(sport)` и `strava_visibility_to_komoot(vis)` — две dict-таблицы.
- Без Singleton/Factory/Observer — задача их не требует.

## Структура проекта

```
strava_komoot/
├── pyproject.toml          # uv / pip-совместимо, deps ниже
├── README.md
├── .env.example            # STRAVA_CLIENT_ID, STRAVA_CLIENT_SECRET, KOMOOT_EMAIL, KOMOOT_PASSWORD
├── src/strava_komoot/
│   ├── __init__.py
│   ├── config.py           # загрузка из .env через pydantic-settings
│   ├── db.py               # SQLite: schema + CRUD synced (с snapshot полей)
│   ├── strava.py           # OAuth + список + streams
│   ├── gpx.py              # streams → GPX, track_hash(streams)
│   ├── komoot.py           # KomootSink: upload / update_meta / delete + маппинги
│   ├── diff.py             # activity_diff(strava_activity, snapshot) → изменения
│   ├── sync.py             # оркестратор: classify (new/modified/synced), apply, jobs
│   ├── web.py              # FastAPI: 3 блока, bulk endpoints, polling
│   └── templates/
│       └── index.html      # 3-блочный UI с чекбоксами и diff-чипами
└── tests/
    ├── test_gpx.py         # streams → валидный GPX, стабильность track_hash
    ├── test_sport_map.py
    ├── test_visibility_map.py
    ├── test_diff.py        # 5 сценариев activity_diff
    ├── test_dedup.py
    ├── test_db.py          # CRUD + snapshot round-trip
    └── test_sync_classify.py  # активности правильно раскладываются по 3 блокам
```

### Зависимости
- `fastapi`, `uvicorn`, `jinja2` — локальный веб-UI
- `stravalib` — официальный Strava API
- `gpxpy` — сборка GPX из streams
- **`kompy`** — Komoot login + upload + list tours (через pip)
- `pydantic-settings` + `python-dotenv` — конфиг
- `pytest` + `responses` — тесты с моками HTTP

## Strava: что забираем

- OAuth2 (one-time): `read,activity:read_all` scopes, redirect на `localhost:8000/auth/strava/callback`. Refresh-токен сохраняем в `~/.strava_komoot/tokens.json` (chmod 600).
- `client.get_activities(after=...)` — список.
- Фильтр по типу: только `Ride`, `MountainBikeRide`, `GravelRide`, `EBikeRide`.
- Для каждой выбранной — `client.get_activity_streams(id, types=['latlng','time','altitude','heartrate','cadence'], resolution='high')`.

## GPX builder

`build_gpx(activity_meta, streams) -> str`:
- Один трек, один сегмент, точки = zip(latlng, time, altitude).
- Heartrate / cadence в `<extensions>` по схеме Garmin TrackPointExtension v1 — Komoot их игнорирует, но валидный GPX лучше.
- Имя трека = название активности из Strava + дата.

## Komoot client — через kompy

`komoot.py` — тонкая обёртка вокруг `kompy.KomootConnector` за нашим интерфейсом `ActivitySink`:

```python
class KomootSink:
    def __init__(self, email, password):
        self._c = KomootConnector(email=email, password=password)

    def upload(self, gpx: GPX, sport: str, name: str, status='private') -> UploadResult:
        ok = self._c.upload_tour(gpx, activity_type=sport, tour_name=name, status=status)
        # kompy возвращает True и для 201 (created), и для 202 (already exists).
        # Нам нужен сам tour_id и различие created/duplicate — патчим: вызываем
        # private requests.post тем же путём, что upload_tour, и читаем status_code сами.
        ...
```

**Важная находка:** Komoot сам делает дедупликацию:
- `201 Created` → новый Tour создан, ответ содержит `id`.
- `202 Accepted` → Tour с такими же датой/треком уже существует, ответ содержит `id` существующего.

Это **полностью заменяет** нашу самодельную дедупликацию по дате/расстоянию (см. секцию ниже — она удалена).

Маппинг видов (уточнено из `kompy.constants.activities.SupportedActivities` и [stefan-bergstein/strava-komoot-sync](https://github.com/stefan-bergstein/strava-komoot-sync/blob/main/README.md)):

```python
STRAVA_TO_KOMOOT_SPORT = {
    'Ride':              'touringbicycle',
    'GravelRide':        'mtb',                # gravel в Komoot мапится в mtb
    'MountainBikeRide':  'mtb',
    'EBikeRide':         'e_touringbicycle',
}
```

### Что патчим в kompy (минимально)

Метод `upload_tour` возвращает `bool` и теряет `tour_id` + не различает 201/202. Нам важно сохранять `komoot_tour_id` в БД и показывать в UI статус `synced` vs `already_present`.

Решение: в нашем `KomootSink` повторяем тело `upload_tour` напрямую через `requests` (URL и параметры берём из `kompy.constants.urls.KomootUrl` и реюзаем `self._c.authentication`). Это короткая копия (~15 строк), плюс мы не зависим от будущих изменений сигнатуры в kompy.

## Дедупликация

Двухуровневая:
1. **Локальная БД (быстро, без сети)**: если `synced(strava_id)` уже существует со статусом `synced` или `already_present` — пропускаем, не дёргаем Komoot.
2. **Komoot-side (надёжно)**: если активности нет в БД, всё равно загружаем — Komoot вернёт `202` с `id` существующего тура, если такой уже был. Записываем в БД со статусом `already_present`.

Никакого ручного matching по дате/расстоянию — Komoot делает это сам.

## Детекция изменений после синхронизации

**Проблема:** Strava API не возвращает `updated_at` для активностей — нельзя просто сравнить timestamps. Решаем через snapshot значимых полей.

**Что храним в БД при синхронизации (`synced_snapshot`):**
- `name` — название активности.
- `sport_type` — тип спорта в Strava.
- `visibility` — видимость в Strava (`everyone` / `followers_only` / `only_me`).
- `track_hash` — SHA-256 от concat всех `latlng` точек streams (не GPX-XML — он содержит метаданные, которые не должны влиять на хеш).

**Логика детекции при загрузке списка:**
```python
for activity in strava.list_activities():
    record = repo.get(activity.id)
    if record is None:
        bucket = "new"
    elif activity_diff(activity, record.snapshot):  # сравниваем 4 поля
        record.changes = compute_changes(...)        # diff: что именно изменилось
        bucket = "modified"
    else:
        bucket = "synced"
```

`activity_diff` возвращает структуру:
```python
{
  "name":       {"old": "Morning Ride",   "new": "Суббота gravel"},
  "sport_type": {"old": "Ride",           "new": "GravelRide"},
  "visibility": {"old": "followers_only", "new": "everyone"},
  "track":      {"old_hash": "abc...", "new_hash": "def...", "changed": True},
}
```
В UI показываем только реально изменённые поля.

**Применение изменений в Komoot (по клику «Apply»):**
- Если изменены только `name` / `sport_type` / `visibility` → **`kompy.change_tour(tour_id, ...)`** (один HTTP PATCH, без перезаливки трека).
- Если изменён трек → **`kompy.delete_tour(tour_id)` + `upload_tour(новый GPX)`**. После успеха обновляем `komoot_tour_id` в БД (новый id).
- В обоих случаях после успеха обновляем `synced_snapshot` в БД.

## UI (главная страница)

Один экран, **три блока сверху вниз**:

### Блок 1 — Изменены после синхронизации (если есть)
Выделяется визуально (например, янтарный фон). Каждая строка:
- Дата | Название | Вид | Дистанция | **Чипы изменений** (`name`, `sport`, `visibility`, `track`) — клик по чипу разворачивает diff `old → new`.
- Чекбокс выбора + кнопка `Apply to Komoot` на строку.
- В шапке блока: `[Apply selected] [Apply all]`, счётчик `N changed`.

### Блок 2 — Новые (не синхронизированные)
- Дата | Название | Вид | Дистанция | Статус (`new` / `error: …`).
- Чекбокс выбора + кнопка `Sync` на строку.
- В шапке: `[Sync selected] [Sync all new]`, счётчик `N new`.

### Блок 3 — Уже синхронизированы (свернут по умолчанию)
- Только для контроля. Дата | Название | Komoot Tour ID (ссылка на komoot.com/tour/{id}) | Когда синхронизировано.
- Без кнопок действий — здесь делать нечего, кроме просмотра.

**Множественный выбор:**
- Чекбоксы в блоках 1 и 2 независимы.
- Шапки блоков имеют чекбокс «выбрать все в этом блоке».
- Над кнопкой `Apply selected` / `Sync selected` показывается «N selected».

**Прогресс:**
- При нажатии bulk-кнопки — фоновая задача в FastAPI, frontend опрашивает `GET /jobs/{id}` раз в 2 секунды и обновляет статусы строк.
- Не используем SSE/WebSocket в первой итерации — polling проще и достаточно.

**Фильтры (минимальные):**
- Период (since / until).
- Вид спорта (Ride / MTB / Gravel / EBike — все включены по умолчанию).

## Verification

1. **Unit-тесты**:
   - `streams → GPX` валидируется через `gpxpy.parse()` и совпадение числа точек.
   - `track_hash` стабилен на одинаковых streams и меняется при изменении трека.
   - Маппинг видов спорта (Ride/MTB/Gravel/EBike → корректные Komoot-типы).
   - Маппинг видимости (everyone/followers_only/only_me → public/friends/private).
   - `activity_diff`: возвращает только реально изменённые поля; `name+sport`, `только track`, `всё сразу`, `без изменений`.
   - Локальная дедупликация: `synced(strava_id)` без изменений → upload не вызывается.
   - Парсинг ответа Komoot upload: 201 → `synced`, 202 → `already_present`, иной → `error` (мокаем через `responses`).
2. **Интеграция Strava (live, ручной)**: `smoke_strava` — авторизация + получение последних 5 активностей, печать json.
3. **Интеграция Komoot (live, ручной)**:
   - `smoke_komoot_login` (kompy.KomootConnector + печать username).
   - `smoke_komoot_upload` (одна тестовая GPX → 201/202 с tour_id).
   - `smoke_komoot_change` (PATCH name тестового тура → 200, потом обратно).
4. **E2E базовый**: веб-UI → выбрать 2 новые активности → `Sync selected` → обе появились в Komoot со статусами `synced`, повторное открытие страницы — обе в блоке «Уже синхронизированы».
5. **E2E детект изменений**:
   - Синхронизировать активность.
   - Переименовать её в Strava → перезагрузить нашу UI → активность в блоке «Изменены», чип `name` показывает diff.
   - Нажать `Apply to Komoot` → проверить в Komoot, что имя обновилось, в БД новый snapshot.
6. **E2E изменение трека**: trim активности в Strava → активность в «Изменены» с чипом `track` → `Apply` → старый Tour удалён в Komoot, новый загружен, `komoot_tour_id` в БД обновлён.
7. **Регресс дедупликации (Komoot-side)**: вручную залить тот же GPX через UI Komoot → запустить наш sync → `already_present` (HTTP 202).

## Что НЕ делаем в первой итерации

- Webhooks от Strava (Denis выбрал ручной запуск).
- Multi-user, фронт-онбординг.
- Playwright-фолбэк (готов интерфейс, но реализация — только если приватный API не заработает).
- Виды спорта кроме велосипеда.
- Шифрование БД (chmod 600 на токены и БД достаточно для локального single-user).

## Открытые риски

1. **kompy перестанет работать после изменений на стороне Komoot.** Mitigation: интерфейс `ActivitySink` оставляем — если kompy умрёт, можно переключиться на Playwright или fork библиотеки. Также kompy активно поддерживается (последний коммит — июнь 2026, 4 issues open).
2. **Маппинг GravelRide.** Сейчас мапим в `mtb` (как делает stefan-bergstein). Если Denis захочет `racebike` — это однострочное изменение в `STRAVA_TO_KOMOOT_SPORT`.
3. **Strava OAuth callback.** Локальный `localhost:8000` callback может не работать, если Strava-app настроен на другой домен. В первом запуске уточнится.
4. **Удаление+перезагрузка при изменении трека.** При обнаружении изменения трека мы удаляем старый Tour в Komoot и заливаем новый — это меняет `tour_id`, ломает прямые ссылки на старый tour, и теряет лайки/комменты в Komoot, если они есть. Альтернатив через приватный API нет (нет PATCH-эндпоинта на трек). Mitigation: в UI при `Apply` для track-изменений показываем явное предупреждение перед действием.
5. **Снимок видимости.** Strava различает `everyone` / `followers_only` / `only_me`, Komoot — `public` / `friends` / `private`. Маппим: `everyone→public`, `followers_only→friends`, `only_me→private`. Это сохранено в `STRAVA_VIS_TO_KOMOOT`.
