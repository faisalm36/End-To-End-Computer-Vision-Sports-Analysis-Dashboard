"""Test setup: throwaway SQLite DB + temp upload/output dirs. No MySQL, no CV deps needed.
Run from backend/:  pip install -r requirements-dev.txt && pytest -q

Isolation guarantees (checked below; the run aborts before anything is seeded if one fails):
  * backend/.env is NOT read (BACKEND_ENV_FILE=""), and DATABASE_URL is forced to a SQLite file in a fresh temp dir,
    so a DATABASE_URL in .env or in your shell is ignored.
  * MySQL drivers are disabled: any pymysql / MySQLdb connect attempt raises immediately.
  * UPLOAD_DIR, THUMBNAIL_DIR, CV_OUTPUT_DIR and CV_PIPELINE_PATH all point inside that temp dir.
  * backend/uploads/ is fingerprinted at start and compared at the end; any change fails the run.
"""
import os
import sys
import tempfile
from pathlib import Path

BACKEND = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BACKEND))
TMP = Path(tempfile.mkdtemp(prefix="soccer-backend-tests-")).resolve()
REAL_UPLOADS = BACKEND / "uploads"

# Must be set before config.py is imported (env vars beat backend/.env; BACKEND_ENV_FILE="" skips .env entirely).
os.environ.update({
    "BACKEND_ENV_FILE": "",
    "DATABASE_URL": f"sqlite:///{TMP / 'test.db'}",
    "UPLOAD_DIR": str(TMP / "uploads"),
    "THUMBNAIL_DIR": str(TMP / "uploads" / "thumbnails"),
    "THUMBNAILS_ENABLED": "true",
    "CV_OUTPUT_DIR": str(TMP / "cv_outputs"),
    "CV_PIPELINE_MODE": "auto",
    "TRACK_PIPELINE_MODE": "stub",
    "CV_PIPELINE_STUB": "true",
    "CV_PIPELINE_PATH": str(TMP / "no-such-cv" / "run_pipeline.py"),
    "CV_PYTHON": "",
    "CV_CALIBRATION_PATH": "",
    "CV_EXTRA_ARGS": "",
    "CV_MODEL": "",
    "CV_CREATE_UNKNOWN_PLAYERS": "true",
    "SQL_ECHO": "false",
    "MAX_UPLOAD_MB": "5",
    "JWT_SECRET": "test-secret-that-is-at-least-32-bytes-long!!",
    "CORS_ORIGINS": "http://localhost:5173,http://127.0.0.1:5173",
    # Test-only AES-256-GCM key (32 bytes of 0x11, base64). Never a real key.
    "HEALTH_DATA_KEY": "ERERERERERERERERERERERERERERERERERERERERERE=",
    "CSV_MAX_MB": "5",
})


def _no_mysql(*_a, **_k):
    raise RuntimeError("tests must never connect to MySQL (see tests/conftest.py)")


try:  # block the MySQL drivers before the app can import them
    import pymysql
    pymysql.connect = pymysql.Connect = pymysql.connections.Connection.__init__ = _no_mysql
except ImportError:
    pass
try:
    import MySQLdb
    MySQLdb.connect = MySQLdb.Connect = _no_mysql
except ImportError:
    pass


def _fingerprint(root: Path) -> dict:
    if not root.exists():
        return {}
    return {str(p.relative_to(root)): (p.stat().st_size, p.stat().st_mtime_ns)
            for p in root.rglob("*") if p.is_file()}


UPLOADS_BEFORE = _fingerprint(REAL_UPLOADS)

import pytest  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

import database  # noqa: E402
from config import settings  # noqa: E402


def _inside_tmp(p) -> bool:
    try:
        Path(p).resolve().relative_to(TMP)
        return True
    except ValueError:
        return False


_problems = []
if database.engine.url.get_backend_name() != "sqlite" or not _inside_tmp(database.engine.url.database or "/"):
    _problems.append(f"engine is {database.engine.url!r}, expected sqlite under {TMP}")
for _name in ("UPLOAD_DIR", "THUMBNAIL_DIR", "CV_OUTPUT_DIR", "CV_PIPELINE_PATH"):
    if not _inside_tmp(getattr(settings, _name)):
        _problems.append(f"{_name}={getattr(settings, _name)} is outside {TMP}")
if settings.model_config.get("env_file"):
    _problems.append(f"backend/.env would be read: {settings.model_config.get('env_file')}")
if _problems:  # abort before seed.seed() (which wipes every table) can run anywhere real
    raise pytest.UsageError("test isolation check failed:\n  " + "\n  ".join(_problems))

import seed  # noqa: E402
from main import app  # noqa: E402


def pytest_sessionfinish(session, exitstatus):
    after = _fingerprint(REAL_UPLOADS)
    if after != UPLOADS_BEFORE:
        changed = sorted(set(after.items()) ^ set(UPLOADS_BEFORE.items()))
        print(f"\nERROR: the test run changed the real {REAL_UPLOADS}: {changed[:10]}", file=sys.stderr)
        session.exitstatus = 1

FAKE_MP4 = b"\x00\x00\x00\x18ftypisom\x00\x00\x02\x00isomiso2" + b"\x00" * 256


@pytest.fixture(scope="session")
def client():
    seed.seed()
    with TestClient(app) as c:
        yield c
    import shutil
    shutil.rmtree(TMP, ignore_errors=True)


@pytest.fixture(scope="session")
def tmp_root() -> Path:
    return TMP


def login(client, email, password):
    r = client.post("/api/auth/login", json={"email": email, "password": password})
    assert r.status_code == 200, r.text
    return {"Authorization": f"Bearer {r.json()['access_token']}"}


def register_and_login(client, email, password="supersecret1", first="Test", last="User"):
    r = client.post("/api/auth/register", json={"first_name": first, "last_name": last,
                                                "email": email, "password": password})
    assert r.status_code in (201, 409), r.text
    r = client.post("/api/auth/login", json={"email": email, "password": password})
    assert r.status_code == 200, r.text
    return {"Authorization": f"Bearer {r.json()['access_token']}"}
