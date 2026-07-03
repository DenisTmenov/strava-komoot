from __future__ import annotations

import hashlib
import logging
import threading
import uuid
from datetime import datetime, timezone
from typing import Any

logger = logging.getLogger(__name__)

from strava_komoot.db import SyncRepo
from strava_komoot.diff import activity_diff, make_snapshot
from strava_komoot.gpx import build_gpx, track_hash
from strava_komoot.komoot import KomootSink
from strava_komoot.strava import StravaSource


class SyncEngine:
    def __init__(self):
        self._strava: StravaSource | None = None
        self._komoot: KomootSink | None = None
        self._repo = SyncRepo()
        self._jobs: dict[str, dict[str, Any]] = {}

    @property
    def strava(self) -> StravaSource:
        if self._strava is None:
            self._strava = StravaSource()
        return self._strava

    @property
    def komoot(self) -> KomootSink:
        if self._komoot is None:
            self._komoot = KomootSink()
        return self._komoot

    def classify(self, after: datetime | None = None, limit: int | None = None, sport_type: str | None = None) -> dict[str, list[dict]]:
        activities = self.strava.list_activities(after=after, limit=limit, sport_type=sport_type)
        result = {"new": [], "modified": [], "synced": []}

        for a in activities:
            record = self._repo.get(a.id)
            if record is None:
                result["new"].append(self._activity_to_dict(a))
            elif record["status"] in ("synced", "already_present"):
                snapshot = self._repo.get_snapshot(a.id)
                if snapshot is None:
                    result["new"].append(self._activity_to_dict(a))
                    continue
                if "track_hash" in snapshot:
                    streams = self.strava.get_streams(a.id)
                    current_hash = track_hash(streams)
                    if current_hash != snapshot["track_hash"]:
                        diff = activity_diff(a, snapshot) or {}
                        diff["track"] = {"old_hash": snapshot["track_hash"], "new_hash": current_hash, "changed": True}
                        entry = self._activity_to_dict(a)
                        entry["changes"] = diff
                        entry["komoot_tour_id"] = record["komoot_tour_id"]
                        entry["sync_media"] = bool(record["sync_media"])
                        result["modified"].append(entry)
                        continue
                diff = activity_diff(a, snapshot)
                if diff:
                    entry = self._activity_to_dict(a)
                    entry["changes"] = diff
                    entry["komoot_tour_id"] = record["komoot_tour_id"]
                    entry["sync_media"] = bool(record["sync_media"])
                    result["modified"].append(entry)
                else:
                    entry = self._activity_to_dict(a)
                    entry["komoot_tour_id"] = record["komoot_tour_id"]
                    entry["synced_at"] = record["synced_at"]
                    entry["sync_media"] = bool(record["sync_media"])
                    result["synced"].append(entry)
            else:
                result["new"].append(self._activity_to_dict(a))

        return result

    def _build_cache_key(self, sport_type: str | None) -> str:
        return f"activities:{sport_type or 'all'}"

    def _build_sport_types_cache_key(self) -> str:
        return "sport_types"

    def list_activities_cached(self, sport_type: str | None = None, ttl: int = 300) -> dict:
        cache_key = self._build_cache_key(sport_type)
        cached = self._repo.get_cached_activities(cache_key, ttl_seconds=ttl)

        if cached is None:
            raw = self.strava.list_activities(sport_type=sport_type)
            cached = [self._activity_to_dict(a) for a in raw]
            self._repo.set_cached_activities(cache_key, cached)

        return {"activities": cached, "total": len(cached)}

    def get_sport_types_cached(self, ttl: int = 300) -> list[str]:
        cache_key = self._build_sport_types_cache_key()
        cached = self._repo.get_cached_sport_types(cache_key, ttl_seconds=ttl)
        if cached is not None:
            return cached
        types = self.strava.get_sport_types()
        self._repo.set_cached_activities(cache_key, [], sport_types=types)
        return types

    def _activity_to_dict(self, a) -> dict:
        return {
            "id": a.id,
            "name": a.name,
            "sport_type": a.sport_type,
            "start_date": a.start_date.isoformat(),
            "distance": a.distance,
            "moving_time": a.moving_time,
            "total_elevation_gain": a.total_elevation_gain,
            "visibility": a.visibility,
            "sync_media": False,
            "has_gps": bool(a.start_latlng),
        }

    def sync(self, activity_ids: list[int]) -> dict:
        activities = {a.id: a for a in self.strava.list_activities() if a.id in activity_ids}
        results = []

        for aid in activity_ids:
            activity = activities.get(aid)
            if activity is None:
                results.append({"id": aid, "status": "error", "error": "activity not found"})
                continue

            try:
                streams = self.strava.get_streams(aid)
            except Exception as e:
                results.append({"id": aid, "status": "error", "error": f"streams: {e}"})
                continue

            gpx_xml = build_gpx(activity, streams)
            h = track_hash(streams)
            sport = self.komoot.map_sport(activity.sport_type)
            vis = self.komoot.map_visibility(activity.visibility)

            try:
                result = self.komoot.upload(gpx_xml, sport, activity.name, vis)
            except Exception as e:
                results.append({"id": aid, "status": "error", "error": f"upload: {e}"})
                continue

            self._upload_activity_media(activity, result.tour_id)

            snapshot = make_snapshot(activity, h)
            self._repo.upsert(aid, result.tour_id, result.status, snapshot)
            results.append({"id": aid, "status": result.status, "komoot_tour_id": result.tour_id})

        return {"results": results}

    def _compute_media_hash(self, photos: list) -> str | None:
        if not photos:
            return None
        raw = ",".join(sorted(p.unique_id for p in photos))
        return hashlib.sha256(raw.encode()).hexdigest()

    def _upload_activity_media(self, activity, tour_id: int) -> dict:
        if not self._repo.get_sync_media(activity.id):
            return {"photo": 0, "video": 0, "skipped": True}

        media_results = {"photo": 0, "video": 0}
        try:
            photos = self.strava.get_photos(activity.id)
        except Exception as e:
            logger.warning("Failed to get photos for %s: %s", activity.id, e)
            return media_results

        current_hash = self._compute_media_hash(photos)
        stored_hash = self._repo.get_media_hash(activity.id)
        if current_hash and current_hash == stored_hash:
            return {"photo": 0, "video": 0, "unchanged": True}

        for photo in photos:
            try:
                data = self.strava.download_media(photo)
            except Exception as e:
                logger.warning("Failed to download %s for %s: %s", photo.media_type, activity.id, e)
                continue
            try:
                ok = self.komoot.upload_photo(
                    tour_id=tour_id,
                    image_path=data,
                    lat=photo.lat,
                    lng=photo.lng,
                    media_type=photo.media_type,
                )
                if ok:
                    media_results[photo.media_type] += 1
            except Exception as e:
                logger.warning("Failed to upload %s for %s: %s", photo.media_type, activity.id, e)

        if current_hash:
            self._repo.update_media_hash(activity.id, current_hash)
        return media_results

    def apply(self, activity_ids: list[int]) -> dict:
        activities = {a.id: a for a in self.strava.list_activities() if a.id in activity_ids}
        results = []

        for aid in activity_ids:
            activity = activities.get(aid)
            if activity is None:
                results.append({"id": aid, "status": "error", "error": "activity not found"})
                continue

            record = self._repo.get(aid)
            if record is None:
                results.append({"id": aid, "status": "error", "error": "not synced yet"})
                continue

            old_snapshot = self._repo.get_snapshot(aid)
            if old_snapshot is None:
                results.append({"id": aid, "status": "error", "error": "no snapshot"})
                continue

            diff = activity_diff(activity, old_snapshot)

            try:
                streams = self.strava.get_streams(aid)
            except Exception as e:
                results.append({"id": aid, "status": "error", "error": f"streams: {e}"})
                continue

            new_hash = track_hash(streams)
            track_changed = new_hash != old_snapshot.get("track_hash")

            if track_changed:
                self.komoot.delete(record["komoot_tour_id"])
                gpx_xml = build_gpx(activity, streams)
                sport = self.komoot.map_sport(activity.sport_type)
                vis = self.komoot.map_visibility(activity.visibility)
                upload_result = self.komoot.upload(gpx_xml, sport, activity.name, vis)
                self._upload_activity_media(activity, upload_result.tour_id)
                new_snapshot = make_snapshot(activity, new_hash)
                self._repo.upsert(aid, upload_result.tour_id, upload_result.status, new_snapshot)
                results.append({"id": aid, "status": "uploaded", "komoot_tour_id": upload_result.tour_id})
            elif diff:
                tour_id = record["komoot_tour_id"]
                self.komoot.update_meta(
                    tour_id,
                    name=diff.get("name", {}).get("new"),
                    sport=diff.get("sport_type", {}).get("new"),
                    status=self.komoot.map_visibility(activity.visibility),
                )
                new_snapshot = make_snapshot(activity, new_hash)
                self._repo.upsert(aid, tour_id, record["status"], new_snapshot)
                results.append({"id": aid, "status": "updated", "komoot_tour_id": tour_id})
            else:
                results.append({"id": aid, "status": "no_changes"})

        return {"results": results}

    def start_job(self, job_type: str, activity_ids: list[int]) -> str:
        job_id = str(uuid.uuid4())[:8]
        self._jobs[job_id] = {
            "status": "running",
            "type": job_type,
            "total": len(activity_ids),
            "current": 0,
            "current_name": "",
            "result": None,
        }
        t = threading.Thread(target=self._run_job, args=(job_id, job_type, activity_ids), daemon=True)
        t.start()
        return job_id

    def _run_job(self, job_id: str, job_type: str, activity_ids: list[int]) -> None:
        try:
            if job_type == "sync":
                result = self._sync_with_progress(job_id, activity_ids)
            elif job_type == "apply":
                result = self._apply_with_progress(job_id, activity_ids)
            elif job_type == "verify":
                result = self._verify_with_progress(job_id, activity_ids)
            else:
                result = {"results": [{"id": aid, "status": "error", "error": f"unknown job type: {job_type}"} for aid in activity_ids]}
            self._jobs[job_id]["result"] = result
            self._jobs[job_id]["status"] = "completed"
        except Exception as e:
            self._jobs[job_id]["status"] = "error"
            self._jobs[job_id]["error"] = str(e)

    def _sync_with_progress(self, job_id: str, activity_ids: list[int]) -> dict:
        activities = {a.id: a for a in self.strava.list_activities() if a.id in activity_ids}
        results = []

        for idx, aid in enumerate(activity_ids):
            activity = activities.get(aid)
            name = activity.name if activity else str(aid)
            self._jobs[job_id]["current"] = idx
            self._jobs[job_id]["current_name"] = name

            if activity is None:
                results.append({"id": aid, "status": "error", "error": "activity not found"})
                continue

            try:
                streams = self.strava.get_streams(aid)
            except Exception as e:
                results.append({"id": aid, "status": "error", "error": f"streams: {e}"})
                continue

            gpx_xml = build_gpx(activity, streams)
            h = track_hash(streams)
            sport = self.komoot.map_sport(activity.sport_type)
            vis = self.komoot.map_visibility(activity.visibility)

            try:
                result = self.komoot.upload(gpx_xml, sport, activity.name, vis)
            except Exception as e:
                results.append({"id": aid, "status": "error", "error": f"upload: {e}"})
                continue

            self._upload_activity_media(activity, result.tour_id)

            snapshot = make_snapshot(activity, h)
            self._repo.upsert(aid, result.tour_id, result.status, snapshot)
            results.append({"id": aid, "status": result.status, "komoot_tour_id": result.tour_id})

        self._jobs[job_id]["current"] = len(activity_ids)
        return {"results": results}

    def _apply_with_progress(self, job_id: str, activity_ids: list[int]) -> dict:
        activities = {a.id: a for a in self.strava.list_activities() if a.id in activity_ids}
        results = []

        for idx, aid in enumerate(activity_ids):
            activity = activities.get(aid)
            name = activity.name if activity else str(aid)
            self._jobs[job_id]["current"] = idx
            self._jobs[job_id]["current_name"] = name

            if activity is None:
                results.append({"id": aid, "status": "error", "error": "activity not found"})
                continue

            record = self._repo.get(aid)
            if record is None:
                results.append({"id": aid, "status": "error", "error": "not synced yet"})
                continue

            old_snapshot = self._repo.get_snapshot(aid)
            if old_snapshot is None:
                results.append({"id": aid, "status": "error", "error": "no snapshot"})
                continue

            diff = activity_diff(activity, old_snapshot)

            try:
                streams = self.strava.get_streams(aid)
            except Exception as e:
                results.append({"id": aid, "status": "error", "error": f"streams: {e}"})
                continue

            new_hash = track_hash(streams)
            track_changed = new_hash != old_snapshot.get("track_hash")

            if track_changed:
                self.komoot.delete(record["komoot_tour_id"])
                gpx_xml = build_gpx(activity, streams)
                sport = self.komoot.map_sport(activity.sport_type)
                vis = self.komoot.map_visibility(activity.visibility)
                upload_result = self.komoot.upload(gpx_xml, sport, activity.name, vis)
                self._upload_activity_media(activity, upload_result.tour_id)
                new_snapshot = make_snapshot(activity, new_hash)
                self._repo.upsert(aid, upload_result.tour_id, upload_result.status, new_snapshot)
                results.append({"id": aid, "status": "uploaded", "komoot_tour_id": upload_result.tour_id})
            elif diff:
                tour_id = record["komoot_tour_id"]
                self.komoot.update_meta(
                    tour_id,
                    name=diff.get("name", {}).get("new"),
                    sport=diff.get("sport_type", {}).get("new"),
                    status=self.komoot.map_visibility(activity.visibility),
                )
                new_snapshot = make_snapshot(activity, new_hash)
                self._repo.upsert(aid, tour_id, record["status"], new_snapshot)
                results.append({"id": aid, "status": "updated", "komoot_tour_id": tour_id})
            else:
                results.append({"id": aid, "status": "no_changes"})

        self._jobs[job_id]["current"] = len(activity_ids)
        return {"results": results}

    def list_synced_ids(self) -> list[int]:
        return [r["strava_id"] for r in self._repo.list_all()
                if r["status"] in ("synced", "already_present")]

    def verify(self, activity_ids: list[int]) -> dict:
        results = []
        for aid in activity_ids:
            record = self._repo.get(aid)
            if record is None:
                continue
            exists = self.komoot.tour_exists(record["komoot_tour_id"])
            if not exists:
                self._repo.delete(aid)
                results.append({"id": aid, "komoot_tour_id": record["komoot_tour_id"]})
        return {"results": results, "missing": results}

    def _verify_with_progress(self, job_id: str, activity_ids: list[int]) -> dict:
        results = []
        missing = []
        activities = {a.id: a for a in self.strava.list_activities() if a.id in activity_ids}

        for idx, aid in enumerate(activity_ids):
            record = self._repo.get(aid)
            activity = activities.get(aid)
            name = activity.name if activity else str(aid)
            self._jobs[job_id]["current"] = idx
            self._jobs[job_id]["current_name"] = name

            if record is None:
                continue

            exists = self.komoot.tour_exists(record["komoot_tour_id"])
            if not exists:
                self._repo.delete(aid)
                missing.append({"id": aid, "komoot_tour_id": record["komoot_tour_id"]})
                continue

            if activity and self._repo.get_sync_media(aid):
                media_result = self._upload_activity_media(activity, record["komoot_tour_id"])
                if media_result and not media_result.get("skipped") and not media_result.get("unchanged"):
                    results.append({"id": aid, "status": "media_uploaded", "media": media_result})

        self._jobs[job_id]["current"] = len(activity_ids)
        return {"results": results, "missing": missing}

    def _sync_media_with_progress(self, job_id: str, activity_ids: list[int]) -> dict:
        activities = {a.id: a for a in self.strava.list_activities() if a.id in activity_ids}
        results = []

        for idx, aid in enumerate(activity_ids):
            activity = activities.get(aid)
            name = activity.name if activity else str(aid)
            self._jobs[job_id]["current"] = idx
            self._jobs[job_id]["current_name"] = name

            record = self._repo.get(aid)
            if record is None:
                results.append({"id": aid, "status": "error", "error": "not synced yet"})
                continue

            if activity is None:
                results.append({"id": aid, "status": "error", "error": "activity not found"})
                continue

            media_result = self._upload_activity_media(activity, record["komoot_tour_id"])
            results.append({"id": aid, "status": "uploaded", "media": media_result})

        self._jobs[job_id]["current"] = len(activity_ids)
        return {"results": results, "missing": results}

    def get_job(self, job_id: str) -> dict[str, Any] | None:
        return self._jobs.get(job_id)
