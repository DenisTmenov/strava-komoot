from __future__ import annotations

import hashlib
from datetime import datetime

import gpxpy
import gpxpy.gpx

from strava_komoot.strava import StravaActivity


def build_gpx(activity: StravaActivity, streams: dict) -> str:
    gpx = gpxpy.gpx.GPX()
    track = gpxpy.gpx.GPXTrack()
    gpx.tracks.append(track)
    seg = gpxpy.gpx.GPXTrackSegment()
    track.segments.append(seg)

    latlng = streams.get("latlng")
    times = streams.get("time")
    altitude = streams.get("altitude")

    if latlng is None:
        return gpx.to_xml()

    for i, (lat, lon) in enumerate(latlng.data):
        t = None
        if times and i < len(times.data):
            t = datetime.fromtimestamp(activity.start_date.timestamp() + times.data[i])
        alt = None
        if altitude and i < len(altitude.data):
            alt = altitude.data[i]
        seg.points.append(gpxpy.gpx.GPXTrackPoint(lat, lon, time=t, elevation=alt))

    return gpx.to_xml()


def track_hash(streams: dict) -> str:
    latlng = streams.get("latlng")
    if latlng is None or not latlng.data:
        return hashlib.sha256(b"").hexdigest()
    raw = "".join(f"{lat},{lon}" for lat, lon in latlng.data)
    return hashlib.sha256(raw.encode()).hexdigest()
