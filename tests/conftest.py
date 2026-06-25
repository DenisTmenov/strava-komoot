from datetime import datetime

import pytest

from strava_komoot.db import DB_DIR, DB_PATH


@pytest.fixture(autouse=True)
def _clean_db():
    DB_DIR.mkdir(parents=True, exist_ok=True)
    DB_PATH.unlink(missing_ok=True)
    yield
    DB_PATH.unlink(missing_ok=True)
