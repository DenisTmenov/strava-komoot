from __future__ import annotations

import json
import os
import webbrowser
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from stravalib.client import Client

from strava_komoot.config import settings

TOKEN_DIR = Path.home() / ".strava_komoot"
TOKEN_FILE = TOKEN_DIR / "tokens.json"

BIKE_SPORTS = {"Ride", "MountainBikeRide", "GravelRide", "EBikeRide"}


@dataclass
class StravaActivity:
    id: int
    name: str
    sport_type: str
    start_date: datetime
    distance: float
    moving_time: int
    total_elevation_gain: float
    visibility: str | None


class StravaSource:
    def __init__(self, auto_login: bool = True):
        self._client = Client()
        if auto_login:
            self._ensure_token()

    def _ensure_token(self) -> None:
        token_data = self._load_token()
        if token_data:
            self._client.access_token = token_data["access_token"]
            self._client.refresh_token = token_data["refresh_token"]
            self._client.token_expires = token_data["expires_at"]
            if self._client.token_expires and datetime.now().timestamp() >= self._client.token_expires:
                self._refresh_token()
        elif settings.strava_client_id and settings.strava_client_secret:
            self._authorize()

    def is_authenticated(self) -> bool:
        return bool(self._client.access_token)

    def get_authorization_url(self) -> str:
        return self._client.authorization_url(
            client_id=int(settings.strava_client_id),
            redirect_uri="http://localhost:8000/auth/strava/callback",
            scope=["read", "activity:read_all"],
        )

    def handle_callback(self, code: str) -> None:
        token = self._client.exchange_code_for_token(
            client_id=int(settings.strava_client_id),
            client_secret=settings.strava_client_secret,
            code=code,
        )
        self._save_token(token)

    def _authorize(self) -> None:
        url = self.get_authorization_url()
        print(f"Open this URL in browser:\n{url}")
        webbrowser.open(url)
        code = input("Paste the code from the redirect URL: ").strip()
        self.handle_callback(code)

    def _refresh_token(self) -> None:
        token = self._client.refresh_access_token(
            client_id=int(settings.strava_client_id),
            client_secret=settings.strava_client_secret,
            refresh_token=self._client.refresh_token,
        )
        self._save_token(token)

    def _load_token(self) -> dict | None:
        if TOKEN_FILE.exists():
            return json.loads(TOKEN_FILE.read_text())
        return None

    def _save_token(self, token) -> None:
        TOKEN_DIR.mkdir(parents=True, exist_ok=True)
        TOKEN_FILE.write_text(
            json.dumps({
                "access_token": token["access_token"],
                "refresh_token": token["refresh_token"],
                "expires_at": token["expires_at"],
            })
        )
        TOKEN_FILE.chmod(0o600)
        self._client.access_token = token["access_token"]
        self._client.refresh_token = token["refresh_token"]
        self._client.token_expires = token["expires_at"]

    def list_activities(self, after: datetime | None = None, limit: int | None = None, sport_type: str | None = None) -> list[StravaActivity]:
        activities = []
        for a in self._client.get_activities(after=after):
            raw = a.sport_type or a.type or ""
            sport = raw.root if hasattr(raw, "root") else str(raw)
            if sport_type:
                if sport != sport_type:
                    continue
            elif sport not in BIKE_SPORTS:
                continue
            distance = float(a.distance) if a.distance else 0.0
            elev = float(a.total_elevation_gain) if a.total_elevation_gain else 0.0
            activities.append(
                StravaActivity(
                    id=a.id,
                    name=a.name or "",
                    sport_type=sport,
                    start_date=a.start_date,
                    distance=distance,
                    moving_time=int(a.moving_time) if a.moving_time else 0,
                    total_elevation_gain=elev,
                    visibility=a.visibility,
                )
            )
            if limit and len(activities) >= limit:
                break
        return activities

    def get_sport_types(self) -> list[str]:
        types: set[str] = set()
        for a in self._client.get_activities(limit=200):
            raw = a.sport_type or a.type or ""
            sport = raw.root if hasattr(raw, "root") else str(raw)
            types.add(sport)
        return sorted(types)

    def get_streams(self, activity_id: int) -> dict:
        return self._client.get_activity_streams(
            activity_id,
            types=["latlng", "time", "altitude", "heartrate", "cadence"],
            resolution="high",
        )
