from datetime import datetime

import gpxpy
import pytest

from strava_komoot.gpx import build_gpx, track_hash
from strava_komoot.strava import StravaActivity


def _make_mock_stream(type_name: str, data: list):
    class MockStream:
        def __init__(self, type_, data_):
            self.type = type_
            self.data = data_
    return MockStream(type_name, data)


def _make_activity(**kwargs) -> StravaActivity:
    defaults = dict(
        id=1,
        name="Test Ride",
        sport_type="Ride",
        start_date=datetime(2024, 6, 1, 10, 0, 0),
        distance=10000.0,
        moving_time=1800,
        total_elevation_gain=100.0,
        visibility="everyone",
    )
    defaults.update(kwargs)
    return StravaActivity(**defaults)


class TestBuildGpx:
    def test_gpx_is_valid_xml(self):
        activity = _make_activity()
        streams = {
            "latlng": _make_mock_stream("latlng", [[48.85, 2.35], [48.86, 2.36]]),
            "time": _make_mock_stream("time", [0, 60]),
            "altitude": _make_mock_stream("altitude", [100, 105]),
        }
        xml = build_gpx(activity, streams)
        parsed = gpxpy.parse(xml)
        assert len(parsed.tracks) == 1
        assert len(parsed.tracks[0].segments) == 1
        points = parsed.tracks[0].segments[0].points
        assert len(points) == 2
        assert points[0].latitude == 48.85
        assert points[1].longitude == 2.36

    def test_gpx_extra_streams_ignored(self):
        activity = _make_activity()
        streams = {
            "latlng": _make_mock_stream("latlng", [[48.85, 2.35]]),
            "time": _make_mock_stream("time", [0]),
            "altitude": _make_mock_stream("altitude", [100]),
            "heartrate": _make_mock_stream("heartrate", [150]),
            "cadence": _make_mock_stream("cadence", [85]),
        }
        xml = build_gpx(activity, streams)
        parsed = gpxpy.parse(xml)
        assert len(parsed.tracks[0].segments[0].points) == 1

    def test_gpx_empty_latlng(self):
        activity = _make_activity()
        streams = {}
        xml = build_gpx(activity, streams)
        parsed = gpxpy.parse(xml)
        assert len(parsed.tracks) == 1
        assert len(parsed.tracks[0].segments[0].points) == 0

    def test_gpx_partial_extra_streams(self):
        activity = _make_activity()
        streams = {
            "latlng": _make_mock_stream("latlng", [[48.85, 2.35]]),
            "time": _make_mock_stream("time", [0]),
            "heartrate": _make_mock_stream("heartrate", [150]),
        }
        xml = build_gpx(activity, streams)
        assert "<trkpt" in xml
        assert len(xml) > 100


class TestTrackHash:
    def test_hash_stable_for_same_streams(self):
        streams = {
            "latlng": _make_mock_stream("latlng", [[48.85, 2.35], [48.86, 2.36]]),
        }
        h1 = track_hash(streams)
        h2 = track_hash(streams)
        assert h1 == h2

    def test_hash_changes_with_different_track(self):
        streams_a = {"latlng": _make_mock_stream("latlng", [[48.85, 2.35]])}
        streams_b = {"latlng": _make_mock_stream("latlng", [[48.86, 2.36]])}
        assert track_hash(streams_a) != track_hash(streams_b)

    def test_hash_empty_latlng(self):
        streams = {}
        h = track_hash(streams)
        assert isinstance(h, str)
        assert len(h) == 64

    def test_hash_ignores_non_latlng_streams(self):
        streams_a = {"latlng": _make_mock_stream("latlng", [[48.85, 2.35]])}
        streams_b = {
            "latlng": _make_mock_stream("latlng", [[48.85, 2.35]]),
            "heartrate": _make_mock_stream("heartrate", [150]),
        }
        assert track_hash(streams_a) == track_hash(streams_b)
