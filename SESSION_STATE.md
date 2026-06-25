# Сессия: синхронизация Strava → Komoot

**Дата:** 25 июня 2026
**Model:** `opencode/deepseek-v4-flash-free`

## Что сделано

- [x] Создан GitHub-репозиторий https://github.com/DenisTmenov/strava-komoot
- [x] `CONVENTIONS.md` вынесен в `.opencode/CONVENTIONS.md`, добавлен в `.gitignore`, история почищена
- [x] `PLAN.md` переписан как 6 вертикальных срезов

### Реализованные шаги

| Шаг | Описание | Статус |
|---|---|---|
| 0 | Scaffold: FastAPI + config + pyproject.toml | ✅ |
| 1 | Strava reader: OAuth, list activities, streams | ✅ |
| 2 | GPX builder: build_gpx, track_hash + тесты | ✅ |
| 3 | Komoot uploader: KomootSink + маппинг спорта + тесты | ✅ |
| 4 | DB + sync engine: SQLite, diff, classify/sync/apply + тесты | ✅ |
| 5 | Web UI: FastAPI endpoints + Jinja2 шаблон с 3 блоками | ✅ |

**Тесты:** 31/31 проходят

## Структура проекта

```
src/strava_komoot/
  __init__.py
  config.py       # pydantic-settings из .env
  strava.py       # OAuth + список + streams
  gpx.py          # build_gpx + track_hash
  komoot.py       # KomootSink (upload / update_meta / delete)
  diff.py         # activity_diff
  db.py           # SQLite: SyncRepo
  sync.py         # SyncEngine: classify, sync, apply, jobs
  web.py          # FastAPI: /, /sync, /apply, /jobs/{id}, /auth/strava
  templates/
    index.html    # 3-блочный UI (modified / new / synced)
tests/
  test_gpx.py         # 8 тестов
  test_sport_map.py   # 10 тестов
  test_diff.py        # 7 тестов
  test_db.py          # 6 тестов
```

## Зависимости

`fastapi`, `uvicorn`, `jinja2`, `stravalib`, `gpxpy`, `kompy`, `pydantic-settings`, `python-dotenv`, `python-multipart`

## Как запустить

```bash
cd ~/Denis/den_claude_code/strava_komoot
uv run uvicorn src.strava_komoot.web:app --reload
# открыть http://localhost:8000
```

## Безопасность

- `.env` не используется — ключи экспортируются скриптом в память процесса
- Bitwarden-записи: `strava-client-id` (field `CLAIENT_ID`), `strava-client-secret` (field `CLIENT_SECRET`), `komoot-email` (field `EMAIL`), `komoot-pass` (field `PASS`)
- Лаунчер: `scripts/opencode-strava.sh`

## Текущая сессия (25 июня 2026)

### Исправленные баги

1. **`sport_type` не парсился** (`strava.py:105`) — stravalib возвращает `SportType(root='Ride')`, `str()` давал `"root='Ride'"`, фильтр `BIKE_SPORTS` отбрасывал все. Исправлено на `.root if hasattr(raw, "root") else str(raw)`.

2. **`limit` считал сырые, а не отфильтрованные активности** (`strava.py:122`) — limit=50 показывал меньше 50, если среди них были не-вело. Исправлено: break после набора `limit` bike-активностей, без передачи `limit` в stravalib.

3. **`self._komoot` вместо `self.komoot`** (`sync.py:103,150,152,153,160,164`) — lazy-проперти не вызывалась, `_komoot` оставался None. Исправлено: `self.komoot` (через property).

4. **Добавлен фильтр по типу активности** (sport_type) в UI: Type: All / Ride / AlpineSki / ... + Load: 10/30/50/100/All. Фильтр и лимит сохраняют друг друга.

### Решённая проблема

~~**Komoot login возвращает 403.**~~ ✅ **Причина:** в конфигурации был сохранён email `kulek.adam@gmail` (без `.com`). После исправления на `kulek.adam@gmail.com` — login 200 OK, синхронизация работает.

Первая протестированная синхронизация: active #19053536132 → Komoot tour_id `3064442086`.

**Тесты:** 31/31 проходят

## Что дальше (не реализовано)

- Создать `.env` с реальными ключами (через Bitwarden-скрипт)
- Авторизоваться в Strava (первый запуск)
- ✅ Протестировать синхронизацию одной активности — заблокировано Komoot 403
- Webhooks от Strava
- Multi-user
- Playwright-фолбэк для Komoot
