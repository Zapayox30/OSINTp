"""Shared pytest fixtures."""

from __future__ import annotations

import os
import tempfile
from pathlib import Path

# Isolate the cases DB to an ephemeral file *before* the app (and its cached
# settings) are imported, so tests never touch a real dossier database.
_TEST_DB = Path(tempfile.gettempdir()) / "osintp_test.db"
for _leftover in _TEST_DB.parent.glob("osintp_test.db*"):
    try:
        _leftover.unlink()
    except OSError:
        pass
os.environ["DATABASE_PATH"] = str(_TEST_DB)

import pytest  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from app.main import app  # noqa: E402


@pytest.fixture
def client():
    """A TestClient that runs the application lifespan (startup/shutdown)."""
    with TestClient(app) as test_client:
        yield test_client
