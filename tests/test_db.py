import json
import os
from pathlib import Path

from strava_komoot.db import SyncRepo

_TEST_DB = Path("/tmp/test_strava_komoot.db")


class TestSyncRepo:
    @staticmethod
    def _make_repo():
        if _TEST_DB.exists():
            os.unlink(_TEST_DB)
        return SyncRepo(db_path=_TEST_DB)

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

    def test_set_sync_media_pending_for_new_activity(self):
        repo = self._make_repo()
        repo.set_sync_media(999, True)
        assert repo.get_sync_media(999) is True

    def test_set_sync_media_pending_false(self):
        repo = self._make_repo()
        repo.set_sync_media(999, False)
        assert repo.get_sync_media(999) is False

    def test_set_sync_media_existing_row(self):
        repo = self._make_repo()
        repo.upsert(1, 100, "synced", {"name": "Test"})
        repo.set_sync_media(1, True)
        assert repo.get_sync_media(1) is True
        record = repo.get(1)
        assert record["sync_media"] == 1

    def test_upsert_preserves_pending_media(self):
        repo = self._make_repo()
        repo.set_sync_media(42, True)
        repo.upsert(42, 200, "synced", {"name": "Test"})
        assert repo.get_sync_media(42) is True
        record = repo.get(42)
        assert record["sync_media"] == 1

    def test_pop_pending_media(self):
        repo = self._make_repo()
        repo.set_sync_media(777, True)
        val = repo.pop_pending_media(777)
        assert val is True
        assert repo.pop_pending_media(777) is None

    def test_get_sync_media_defaults_false(self):
        repo = self._make_repo()
        assert repo.get_sync_media(999) is False
