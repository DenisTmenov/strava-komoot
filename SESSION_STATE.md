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

## Что дальше (не реализовано)

- Создать `.env` с реальными ключами (через Bitwarden-скрипт)
- Авторизоваться в Strava (первый запуск)
- Протестировать синхронизацию одной активности
- Webhooks от Strava
- Multi-user
- Playwright-фолбэк для Komoot
