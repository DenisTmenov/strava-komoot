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


def _bw(args: list[str], session: str | None = None, timeout: int = 10) -> str | None:
    """Run a bw CLI command. Returns stdout or None on failure."""
    env = os.environ.copy()
    if session:
        env["BW_SESSION"] = session
    try:
        return subprocess.check_output(
            ["bw", *args],
            timeout=timeout,
            stderr=subprocess.DEVNULL,
            env=env,
        ).decode().strip()
    except Exception:
        return None


def _bw_unlock_interactive() -> str | None:
    """Prompt user for master password and return session token."""
    print("\n🔐 Bitwarden is locked. Enter master password to unlock:")
    try:
        session = subprocess.check_output(
            ["bw", "unlock", "--raw"],
            timeout=60,
            stderr=subprocess.DEVNULL,
        ).decode().strip()
        return session if session else None
    except Exception:
        return None


def _load_from_bitwarden(session: str | None = None) -> dict[str, str]:
    """Pull credentials from Bitwarden."""
    result: dict[str, str] = {}
    for field, (item, fname) in _BW_ITEMS.items():
        raw = _bw(["get", "item", item], session=session)
        if not raw:
            continue
        try:
            data = json.loads(raw)
            for f in data.get("fields", []):
                if f.get("name") == fname and f.get("value"):
                    result[field] = f["value"]
                    break
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

# Try to fill empty fields from Bitwarden.
if not all([settings.strava_client_id, settings.strava_client_secret,
            settings.komoot_email, settings.komoot_password]):

    bw_status_raw = _bw(["status"], timeout=5)
    bw_status = "unavailable"
    if bw_status_raw:
        try:
            bw_status = json.loads(bw_status_raw).get("status", "unknown")
        except Exception:
            pass

    session = None
    if bw_status == "locked":
        session = _bw_unlock_interactive()
        if session:
            bw_status = "unlocked"
    elif bw_status == "unlocked":
        # Already unlocked — BW_SESSION may be in env.
        session = os.environ.get("BW_SESSION")

    if bw_status in ("unlocked", "locked") and session:
        bw = _load_from_bitwarden(session)
        for key in ("strava_client_id", "strava_client_secret", "komoot_email", "komoot_password"):
            if not getattr(settings, key) and bw.get(key):
                setattr(settings, key, bw[key])

    # Final status.
    if not all([settings.strava_client_id, settings.strava_client_secret,
                settings.komoot_email, settings.komoot_password]):
        if bw_status == "locked":
            print("⚠  Bitwarden unlock failed or cancelled.")
        elif bw_status == "unauthenticated":
            print("⚠  Bitwarden not logged in. Run 'bw login' first.")
        elif bw_status == "unavailable":
            print("⚠  Bitwarden CLI not found. Create .env file with credentials.")
        else:
            print("⚠  Some credentials missing. Check .env or Bitwarden.")

# Propagate to os.environ so strava_sync.config.settings picks them up.
os.environ["STRAVA_CLIENT_ID"] = settings.strava_client_id
os.environ["STRAVA_CLIENT_SECRET"] = settings.strava_client_secret
os.environ["KOMOOT_EMAIL"] = settings.komoot_email
os.environ["KOMOOT_PASSWORD"] = settings.komoot_password
