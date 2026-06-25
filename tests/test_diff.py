from datetime import datetime

from strava_komoot.diff import activity_diff, make_snapshot
from strava_komoot.strava import StravaActivity


def _activity(**kwargs) -> StravaActivity:
    defaults = dict(
        id=1, name="Morning Ride", sport_type="Ride",
        start_date=datetime(2024, 6, 1, 10, 0, 0),
        distance=10000.0, moving_time=1800,
        total_elevation_gain=100.0, visibility="everyone",
    )
    defaults.update(kwargs)
    return StravaActivity(**defaults)


class TestActivityDiff:
    def test_no_changes(self):
        a = _activity()
        snap = make_snapshot(a, "abc")
        assert activity_diff(a, snap) is None

    def test_name_change(self):
        a = _activity(name="Evening Ride")
        snap = make_snapshot(_activity(name="Morning Ride"), "abc")
        diff = activity_diff(a, snap)
        assert diff is not None
        assert diff["name"] == {"old": "Morning Ride", "new": "Evening Ride"}

    def test_sport_type_change(self):
        a = _activity(sport_type="GravelRide")
        snap = make_snapshot(_activity(sport_type="Ride"), "abc")
        diff = activity_diff(a, snap)
        assert diff is not None
        assert diff["sport_type"] == {"old": "Ride", "new": "GravelRide"}

    def test_visibility_change(self):
        a = _activity(visibility="only_me")
        snap = make_snapshot(_activity(visibility="everyone"), "abc")
        diff = activity_diff(a, snap)
        assert diff is not None
        assert diff["visibility"] == {"old": "everyone", "new": "only_me"}

    def test_all_fields_change(self):
        a = _activity(name="Evening", sport_type="GravelRide", visibility="only_me")
        snap = make_snapshot(_activity(name="Morning", sport_type="Ride", visibility="everyone"), "abc")
        diff = activity_diff(a, snap)
        assert diff is not None
        assert len(diff) == 3

    def test_track_hash_not_in_diff(self):
        a = _activity()
        snap = make_snapshot(a, "hash1")
        diff = activity_diff(a, snap)
        assert diff is None

    def test_name_none_to_string(self):
        a = _activity(name="Named")
        snap = make_snapshot(_activity(name=""), "abc")
        diff = activity_diff(a, snap)
        assert diff is not None
        assert diff["name"]["old"] == ""
