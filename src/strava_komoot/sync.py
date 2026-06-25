from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Any

from strava_komoot.db import SyncRepo
from strava_komoot.diff import activity_diff, make_snapshot
from strava_komoot.gpx import build_gpx, track_hash
from strava_komoot.komoot import KomootSink
from strava_komoot.strava import StravaSource


class SyncEngine:
    def __init__(self):
        self._strava = StravaSource()
        self._komoot = KomootSink()
        self._repo = SyncRepo()
        self._jobs: dict[str, dict[str, Any]] = {}

    def classify(self, after: datetime | None = None) -> dict[str, list[dict]]:
        activities = self._strava.list_activities(after=after)
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
                    streams = self._strava.get_streams(a.id)
                    current_hash = track_hash(streams)
                    if current_hash != snapshot["track_hash"]:
                        diff = activity_diff(a, snapshot) or {}
                        diff["track"] = {"old_hash": snapshot["track_hash"], "new_hash": current_hash, "changed": True}
                        entry = self._activity_to_dict(a)
                        entry["changes"] = diff
                        entry["komoot_tour_id"] = record["komoot_tour_id"]
                        result["modified"].append(entry)
                        continue
                diff = activity_diff(a, snapshot)
                if diff:
                    entry = self._activity_to_dict(a)
                    entry["changes"] = diff
                    entry["komoot_tour_id"] = record["komoot_tour_id"]
                    result["modified"].append(entry)
                else:
                    entry = self._activity_to_dict(a)
                    entry["komoot_tour_id"] = record["komoot_tour_id"]
                    entry["synced_at"] = record["synced_at"]
                    result["synced"].append(entry)
            else:
                result["new"].append(self._activity_to_dict(a))

        return result

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
        }

    def sync(self, activity_ids: list[int]) -> dict:
        activities = {a.id: a for a in self._strava.list_activities() if a.id in activity_ids}
        results = []

        for aid in activity_ids:
            activity = activities.get(aid)
            if activity is None:
                results.append({"id": aid, "status": "error", "error": "activity not found"})
                continue

            try:
                streams = self._strava.get_streams(aid)
            except Exception as e:
                results.append({"id": aid, "status": "error", "error": f"streams: {e}"})
                continue

            gpx_xml = build_gpx(activity, streams)
            h = track_hash(streams)
            sport = self._komoot.map_sport(activity.sport_type)
            vis = self._komoot.map_visibility(activity.visibility)

            try:
                result = self._komoot.upload(gpx_xml, sport, activity.name, vis)
            except Exception as e:
                results.append({"id": aid, "status": "error", "error": f"upload: {e}"})
                continue

            snapshot = make_snapshot(activity, h)
            self._repo.upsert(aid, result.tour_id, result.status, snapshot)
            results.append({"id": aid, "status": result.status, "komoot_tour_id": result.tour_id})

        return {"results": results}

    def apply(self, activity_ids: list[int]) -> dict:
        activities = {a.id: a for a in self._strava.list_activities() if a.id in activity_ids}
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
                streams = self._strava.get_streams(aid)
            except Exception as e:
                results.append({"id": aid, "status": "error", "error": f"streams: {e}"})
                continue

            new_hash = track_hash(streams)
            track_changed = new_hash != old_snapshot.get("track_hash")

            if track_changed:
                self._komoot.delete(record["komoot_tour_id"])
                gpx_xml = build_gpx(activity, streams)
                sport = self._komoot.map_sport(activity.sport_type)
                vis = self._komoot.map_visibility(activity.visibility)
                upload_result = self._komoot.upload(gpx_xml, sport, activity.name, vis)
                new_snapshot = make_snapshot(activity, new_hash)
                self._repo.upsert(aid, upload_result.tour_id, upload_result.status, new_snapshot)
                results.append({"id": aid, "status": "uploaded", "komoot_tour_id": upload_result.tour_id})
            elif diff:
                tour_id = record["komoot_tour_id"]
                self._komoot.update_meta(
                    tour_id,
                    name=diff.get("name", {}).get("new"),
                    sport=diff.get("sport_type", {}).get("new"),
                    status=self._komoot.map_visibility(activity.visibility),
                )
                new_snapshot = make_snapshot(activity, new_hash)
                self._repo.upsert(aid, tour_id, record["status"], new_snapshot)
                results.append({"id": aid, "status": "updated", "komoot_tour_id": tour_id})
            else:
                results.append({"id": aid, "status": "no_changes"})

        return {"results": results}

    def start_job(self, job_type: str, activity_ids: list[int]) -> str:
        job_id = str(uuid.uuid4())[:8]
        if job_type == "sync":
            result = self.sync(activity_ids)
        elif job_type == "apply":
            result = self.apply(activity_ids)
        else:
            result = {"results": [{"id": aid, "status": "error", "error": f"unknown job type: {job_type}"} for aid in activity_ids]}

        self._jobs[job_id] = {
            "status": "completed",
            "type": job_type,
            "result": result,
        }
        return job_id

    def get_job(self, job_id: str) -> dict[str, Any] | None:
        return self._jobs.get(job_id)
