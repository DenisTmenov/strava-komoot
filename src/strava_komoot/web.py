from __future__ import annotations

from fastapi import FastAPI, Form, Query, Request
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from pathlib import Path
from starlette.responses import RedirectResponse

from strava_komoot.config import settings
from strava_komoot.sync import SyncEngine
from strava_komoot.strava import StravaSource

app = FastAPI(title="Strava → Komoot Sync")
templates = Jinja2Templates(directory=str(Path(__file__).parent / "templates"))
app.mount("/static", StaticFiles(directory=str(Path(__file__).parent / "static")), name="static")
_engine: SyncEngine | None = None


def get_engine() -> SyncEngine:
    global _engine
    if _engine is None:
        _engine = SyncEngine()
    return _engine


@app.get("/")
def index(request: Request, limit: int = Query(default=10, ge=0), sport_type: str = Query(default="all")) -> HTMLResponse:
    try:
        sport_types = get_engine().get_sport_types_cached()
    except Exception:
        sport_types = []
    return templates.TemplateResponse(
        request,
        "index.html",
        {
            "sport_types": sport_types,
            "current_sport": sport_type,
            "strava_ok": bool(settings.strava_client_id and settings.strava_client_secret),
            "komoot_ok": bool(settings.komoot_email and settings.komoot_password),
            "limit": limit,
        },
    )


@app.post("/sync")
def sync(ids: list[int] = Form(...)) -> JSONResponse:
    job_id = get_engine().start_job("sync", ids)
    return JSONResponse({"job_id": job_id})


@app.post("/apply")
def apply(ids: list[int] = Form(...)) -> JSONResponse:
    job_id = get_engine().start_job("apply", ids)
    return JSONResponse({"job_id": job_id})


@app.post("/verify")
def verify() -> JSONResponse:
    ids = get_engine().list_synced_ids()
    if not ids:
        return JSONResponse({"job_id": None, "message": "No synced activities to verify"})
    job_id = get_engine().start_job("verify", ids)
    return JSONResponse({"job_id": job_id})


@app.get("/jobs/{job_id}")
def get_job(job_id: str) -> JSONResponse:
    job = get_engine().get_job(job_id)
    if job is None:
        return JSONResponse({"error": "not found"}, status_code=404)
    return JSONResponse(job)


@app.post("/activities/{id}/sync-media")
def set_sync_media(id: int, sync_media: str = Form("0")):
    get_engine()._repo.set_sync_media(id, sync_media == "1")
    return JSONResponse({"ok": True, "sync_media": sync_media == "1"})


@app.get("/api/activities")
def api_activities(
    sport_type: str = Query(default="all"),
) -> JSONResponse:
    st = sport_type if sport_type != "all" else None
    engine = get_engine()
    cached = engine.list_activities_cached(sport_type=st)

    result = {"new": [], "modified": [], "synced": [], "unsyncable": []}
    for act in cached["activities"]:
        record = engine._repo.get(act["id"])

        is_private = act.get("visibility") == "only_me"
        has_gps = act.get("has_gps")

        if record and record["status"] not in ("synced", "already_present"):
            record = None

        if record is None:
            if is_private and not has_gps:
                act["unsyncable_reason"] = "Private + no GPS coordinates"
                act["can_force_sync"] = False
                result["unsyncable"].append(act)
            elif is_private:
                act["unsyncable_reason"] = "Private (only_me)"
                act["can_force_sync"] = True
                result["unsyncable"].append(act)
            elif not has_gps:
                act["unsyncable_reason"] = "No GPS coordinates"
                act["can_force_sync"] = False
                result["unsyncable"].append(act)
            else:
                result["new"].append(act)
        elif record["status"] in ("synced", "already_present"):
            act["komoot_tour_id"] = record["komoot_tour_id"]
            act["synced_at"] = record["synced_at"]
            act["sync_media"] = bool(record["sync_media"])
            snapshot = engine._repo.get_snapshot(act["id"])
            if snapshot:
                changes = {}
                for field in ("name", "sport_type", "visibility"):
                    if act.get(field) != snapshot.get(field):
                        changes[field] = {"old": snapshot.get(field), "new": act.get(field)}
                if changes:
                    act["changes"] = changes
                    result["modified"].append(act)
                    continue
            result["synced"].append(act)
        else:
            result["new"].append(act)

    return JSONResponse({
        "new": result["new"],
        "modified": result["modified"],
        "synced": result["synced"],
        "unsyncable": result["unsyncable"],
    })


@app.get("/auth/strava")
def auth_strava():
    s = StravaSource(auto_login=False)
    url = s.get_authorization_url()
    return RedirectResponse(url)


@app.get("/auth/strava/callback")
def auth_strava_callback(code: str):
    s = StravaSource(auto_login=False)
    s.handle_callback(code)
    return RedirectResponse("/")
