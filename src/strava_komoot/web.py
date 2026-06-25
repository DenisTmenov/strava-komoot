from fastapi import FastAPI
from strava_komoot.config import settings

app = FastAPI(title="Strava → Komoot Sync")


@app.get("/")
def root():
    return {"ok": True, "strava_configured": bool(settings.strava_client_id), "komoot_configured": bool(settings.komoot_email)}
