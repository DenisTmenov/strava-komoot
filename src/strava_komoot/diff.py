from __future__ import annotations

from strava_komoot.strava import StravaActivity


def activity_diff(activity: StravaActivity, snapshot: dict) -> dict | None:
    changes = {}

    if activity.name != snapshot.get("name"):
        changes["name"] = {"old": snapshot.get("name"), "new": activity.name}

    if activity.sport_type != snapshot.get("sport_type"):
        changes["sport_type"] = {"old": snapshot.get("sport_type"), "new": activity.sport_type}

    if activity.visibility != snapshot.get("visibility"):
        changes["visibility"] = {"old": snapshot.get("visibility"), "new": activity.visibility}

    return changes if changes else None


def make_snapshot(activity: StravaActivity, track_hash: str) -> dict:
    return {
        "name": activity.name,
        "sport_type": activity.sport_type,
        "visibility": activity.visibility,
        "track_hash": track_hash,
    }
