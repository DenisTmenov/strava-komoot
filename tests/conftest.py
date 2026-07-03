import pytest


@pytest.fixture(autouse=True)
def _cleanup_temp_db():
    yield
