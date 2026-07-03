from __future__ import annotations

import hashlib
import logging
import warnings
from dataclasses import dataclass
from pathlib import Path

import requests
from kompy import KomootConnector
from kompy.constants.activities import SupportedActivities
from kompy.constants.urls import KomootUrl
from kompy.constants.privacy_status import PrivacyStatus
from PIL import Image
from PIL.ExifTags import GPSTAGS, IFD
from urllib3.exceptions import InsecureRequestWarning

from strava_komoot.config import settings

warnings.filterwarnings("ignore", category=InsecureRequestWarning)

logger = logging.getLogger(__name__)

STRAVA_TO_KOMOOT_SPORT: dict[str, str] = {
    "Ride": SupportedActivities.BIKE_TOURING,
    "GravelRide": SupportedActivities.GRAVEL_RIDING,
    "MountainBikeRide": SupportedActivities.MOUNTAIN_BIKING,
    "EBikeRide": SupportedActivities.E_BIKE_TOURING,
}

STRAVA_VIS_TO_KOMOOT: dict[str, str] = {
    "everyone": PrivacyStatus.FRIENDS,
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

    def tour_exists(self, tour_id: int) -> bool:
        url = KomootUrl.TOUR_URL.format(tour_identifier=tour_id)
        resp = requests.get(
            url=url,
            auth=(self._auth.get_email_address(), self._auth.get_password()),
            headers={"User-Agent": "StravaKomootSync"},
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

    @staticmethod
    def _gps_from_exif(image_path: str | Path) -> tuple[float, float] | None:
        try:
            img = Image.open(image_path)
            exif = img.getexif()
            if ifd := exif.get_ifd(IFD.GPSInfo):
                def _to_decimal(values, ref):
                    d, m, s = values
                    dec = d + m / 60.0 + s / 3600.0
                    if ref in ("S", "W"):
                        dec = -dec
                    return dec
                lat = _to_decimal(ifd[2], ifd[1])
                lng = _to_decimal(ifd[4], ifd[3])
                return lat, lng
        except Exception:
            pass
        return None

    def upload_photo(
        self,
        tour_id: int,
        image_path: str | Path | bytes,
        lat: float | None = None,
        lng: float | None = None,
        media_type: str = "photo",
        content_type: str | None = None,
        unique_id: str | None = None,
    ) -> bool:
        auth = (self._auth.get_email_address(), self._auth.get_password())
        headers = {"User-Agent": "StravaKomootSync"}

        if lat is None or lng is None:
            if isinstance(image_path, (str, Path)):
                coords = self._gps_from_exif(image_path)
                if coords:
                    lat, lng = coords
            if lat is None or lng is None:
                logger.warning("No GPS coords for media, using (0, 0)")
                lat, lng = 0.0, 0.0

        poi_url = f"https://www.komoot.com/api/v006/tours/{tour_id}/pois/?srid=4326"
        poi_body = {
            "name": "",
            "coordinateIndex": 0,
            "clientHash": hashlib.sha256(self._auth.get_username().encode()).hexdigest(),
            "point": {"x": lng, "y": lat},
            "creator": self._auth.get_username(),
            "content": {"hasImage": False, "text": "", "imageUrl": None},
        }
        resp = requests.post(poi_url, auth=auth, headers=headers, json=poi_body, verify=False)
        if resp.status_code not in (200, 201):
            logger.error("POI creation failed: %s %s", resp.status_code, resp.text)
            return False
        poi_id = resp.headers.get("Location", "").rstrip("/").split("/")[-1]
        if not poi_id:
            logger.error("No POI ID in response")
            return False

        if isinstance(image_path, (str, Path)):
            data = Path(image_path).read_bytes()
        else:
            data = image_path

        if content_type is None:
            if media_type == "video":
                content_type = "video/mp4"
            elif isinstance(image_path, (str, Path)):
                ext = Path(image_path).suffix.lower()
                content_type = {
                    ".png": "image/png",
                    ".jpg": "image/jpeg",
                    ".jpeg": "image/jpeg",
                    ".webp": "image/webp",
                    ".heic": "image/heic",
                    ".heif": "image/heif",
                    ".gif": "image/gif",
                    ".mp4": "video/mp4",
                    ".mov": "video/quicktime",
                }.get(ext, "image/jpeg")
            else:
                content_type = "image/jpeg"

        content_path = "video" if media_type == "video" else "image"
        upload_url = f"https://www.komoot.com/api/v006/pois/{poi_id}/content/{content_path}"
        upload_headers = {
            "User-Agent": "StravaKomootSync",
            "Content-Type": content_type,
            "Accept": "application/hal+json,application/json",
        }
        resp = requests.post(upload_url, auth=auth, headers=upload_headers, data=data, verify=False)
        if resp.status_code in (200, 201):
            logger.info("%s uploaded to tour %s (POI %s)", media_type, tour_id, poi_id)
            return True
        else:
            logger.error("%s upload failed: %s %s", media_type, resp.status_code, resp.text)
            return False
