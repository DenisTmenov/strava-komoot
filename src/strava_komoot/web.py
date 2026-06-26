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
        st = sport_type if sport_type != "all" else None
        classified = get_engine().classify(limit=limit or None, sport_type=st)
        sport_types = get_engine().strava.get_sport_types()
    except Exception:
        classified = {"new": [], "modified": [], "synced": []}
        sport_types = []
    return templates.TemplateResponse(
        request,
        "index.html",
        {
            "new": classified["new"],
            "modified": classified["modified"],
            "synced": classified["synced"],
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
