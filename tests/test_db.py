import json
from pathlib import Path

from strava_komoot.db import SyncRepo


class TestSyncRepo:
    @staticmethod
    def _make_repo():
        return SyncRepo(db_path=Path("/tmp/test_strava_komoot.db"))

    def test_get_missing(self):
        repo = self._make_repo()
        assert repo.get(999) is None

    def test_upsert_and_get(self):
        repo = self._make_repo()
        snapshot = {"name": "Test", "sport_type": "Ride", "visibility": "everyone", "track_hash": "abc"}
        repo.upsert(strava_id=1, komoot_tour_id=100, status="synced", snapshot=snapshot)
        record = repo.get(1)
        assert record is not None
        assert record["strava_id"] == 1
        assert record["komoot_tour_id"] == 100
        assert record["status"] == "synced"

    def test_get_snapshot(self):
        repo = self._make_repo()
        snapshot = {"name": "Test", "sport_type": "Ride", "visibility": "everyone", "track_hash": "abc"}
        repo.upsert(1, 100, "synced", snapshot)
        loaded = repo.get_snapshot(1)
        assert loaded == snapshot

    def test_upsert_overwrites(self):
        repo = self._make_repo()
        repo.upsert(1, 100, "synced", {"name": "Old"})
        repo.upsert(1, 200, "already_present", {"name": "New"})
        record = repo.get(1)
        assert record["komoot_tour_id"] == 200
        assert record["status"] == "already_present"
        assert json.loads(record["snapshot"])["name"] == "New"

    def test_delete(self):
        repo = self._make_repo()
        repo.upsert(1, 100, "synced", {"name": "Test"})
        repo.delete(1)
        assert repo.get(1) is None

    def test_list_all(self):
        repo = self._make_repo()
        repo.upsert(1, 100, "synced", {})
        repo.upsert(2, 200, "synced", {})
        items = repo.list_all()
        assert len(items) == 2
