from __future__ import annotations

import logging
from dataclasses import dataclass

import requests
from kompy import KomootConnector
from kompy.constants.activities import SupportedActivities
from kompy.constants.urls import KomootUrl
from kompy.constants.privacy_status import PrivacyStatus

from strava_komoot.config import settings

logger = logging.getLogger(__name__)

STRAVA_TO_KOMOOT_SPORT: dict[str, str] = {
    "Ride": SupportedActivities.BIKE_TOURING,
    "GravelRide": SupportedActivities.GRAVEL_RIDING,
    "MountainBikeRide": SupportedActivities.MOUNTAIN_BIKING,
    "EBikeRide": SupportedActivities.E_BIKE_TOURING,
}

STRAVA_VIS_TO_KOMOOT: dict[str, str] = {
    "everyone": PrivacyStatus.PUBLIC,
    "followers_only": PrivacyStatus.FRIENDS,
    "only_me": PrivacyStatus.PRIVATE,
}


@dataclass
class UploadResult:
    tour_id: int
    status: str  # "synced" | "already_present" | "error"


class KomootSink:
    def __init__(self):
        self._connector = KomootConnector(
            email=settings.komoot_email,
            password=settings.komoot_password,
        )
        self._auth = self._connector.authentication

    @staticmethod
    def map_sport(strava_sport: str) -> str:
        return STRAVA_TO_KOMOOT_SPORT.get(strava_sport, SupportedActivities.BIKE_TOURING)

    @staticmethod
    def map_visibility(strava_visibility: str | None) -> str:
        if strava_visibility is None:
            return PrivacyStatus.PRIVATE
        return STRAVA_VIS_TO_KOMOOT.get(strava_visibility, PrivacyStatus.PRIVATE)

    def upload(self, gpx_xml: str, sport: str, name: str, status: str = "private") -> UploadResult:
        headers = {"User-Agent": "StravaKomootSync"}
        params = {
            "sport": sport,
            "data_type": "gpx",
            "name": name,
        }
        url = KomootUrl.UPLOAD_TOUR_URL.format(object_type="gpx")
        resp = requests.post(
            url=url,
            auth=(self._auth.get_email_address(), self._auth.get_password()),
            headers=headers,
            params=params,
            data=gpx_xml.encode("utf-8"),
        )
        if resp.status_code in (201, 202):
            tour_id = resp.json()["id"]
            kind = "synced" if resp.status_code == 201 else "already_present"
            logger.info("Tour %s %s: %s", tour_id, kind, name)
            if status != "private":
                self.update_meta(tour_id, status=status)
            return UploadResult(tour_id=tour_id, status=kind)
        else:
            logger.error("Upload failed: %s %s", resp.status_code, resp.text)
            return UploadResult(tour_id=0, status="error")

    def update_meta(self, tour_id: int, name: str | None = None, sport: str | None = None, status: str | None = None) -> bool:
        body = {}
        if name is not None:
            body["name"] = name
        if sport is not None:
            body["sport"] = sport
        if status is not None:
            body["status"] = status
        if not body:
            return True
        url = KomootUrl.TOUR_URL.format(tour_identifier=tour_id)
        resp = requests.patch(
            url=url,
            auth=(self._auth.get_email_address(), self._auth.get_password()),
            headers={"User-Agent": "StravaKomootSync"},
            json=body,
        )
        return resp.status_code == 200

    def delete(self, tour_id: int) -> bool:
        url = KomootUrl.TOUR_URL.format(tour_identifier=tour_id)
        resp = requests.delete(
            url=url,
            auth=(self._auth.get_email_address(), self._auth.get_password()),
            headers={"User-Agent": "StravaKomootSync"},
        )
        return resp.status_code == 200
