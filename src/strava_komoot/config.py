from __future__ import annotations

import json
import os
import subprocess

from pydantic_settings import BaseSettings, SettingsConfigDict

_BW_ITEMS = {
    "strava_client_id": ("strava-client-id", "CLIENT_ID"),
    "strava_client_secret": ("strava-client-secret", "CLIENT_SECRET"),
    "komoot_email": ("komoot-email", "EMAIL"),
    "komoot_password": ("komoot-pass", "PASS"),
}


def _bw_status() -> str:
    try:
        raw = subprocess.check_output(["bw", "status"], timeout=5, stderr=subprocess.DEVNULL)
        return json.loads(raw).get("status", "unknown")
    except Exception:
        return "unavailable"


def _load_from_bitwarden() -> dict[str, str]:
    """Try to pull missing credentials from Bitwarden."""
    result: dict[str, str] = {}
    for field, (item, fname) in _BW_ITEMS.items():
        try:
            raw = subprocess.check_output(
                ["bw", "get", "item", item],
                timeout=10,
                stderr=subprocess.DEVNULL,
            )
            data = json.loads(raw)
            value = ""
            for f in data.get("fields", []):
                if f.get("name") == fname:
                    value = f.get("value", "")
                    break
            if value:
                result[field] = value
        except Exception:
            pass
    return result


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8")

    strava_client_id: str = ""
    strava_client_secret: str = ""
    komoot_email: str = ""
    komoot_password: str = ""


settings = Settings()

# Fill empty fields from Bitwarden (best-effort, no error if bw is locked/missing).
if not all([settings.strava_client_id, settings.strava_client_secret,
            settings.komoot_email, settings.komoot_password]):
    bw = _load_from_bitwarden()
    if not settings.strava_client_id and bw.get("strava_client_id"):
        settings.strava_client_id = bw["strava_client_id"]
    if not settings.strava_client_secret and bw.get("strava_client_secret"):
        settings.strava_client_secret = bw["strava_client_secret"]
    if not settings.komoot_email and bw.get("komoot_email"):
        settings.komoot_email = bw["komoot_email"]
    if not settings.komoot_password and bw.get("komoot_password"):
        settings.komoot_password = bw["komoot_password"]

    if not all([settings.strava_client_id, settings.strava_client_secret,
                settings.komoot_email, settings.komoot_password]):
        bw_st = _bw_status()
        if bw_st == "locked":
            print("⚠  Bitwarden is locked. Run 'bw unlock' to load credentials automatically.")
        elif bw_st == "unauthenticated":
            print("⚠  Bitwarden is not logged in. Run 'bw login' first.")
        elif bw_st == "unavailable":
            print("⚠  Bitwarden CLI (bw) not found. Create .env file with credentials.")
        else:
            print("⚠  Some credentials missing. Check .env or Bitwarden.")

# Propagate to os.environ so strava_sync.config.settings picks them up.
os.environ["STRAVA_CLIENT_ID"] = settings.strava_client_id
os.environ["STRAVA_CLIENT_SECRET"] = settings.strava_client_secret
os.environ["KOMOOT_EMAIL"] = settings.komoot_email
os.environ["KOMOOT_PASSWORD"] = settings.komoot_password
