"""The suite must never touch MySQL, backend/.env or the real uploads/ folder (see conftest.py)."""
from pathlib import Path

import pytest

import database
from config import BASE_DIR, settings


def test_database_is_temp_sqlite(client, tmp_root):
    url = database.engine.url
    assert url.get_backend_name() == "sqlite"
    Path(url.database).resolve().relative_to(tmp_root)          # raises if the file is outside the temp dir
    with database.engine.connect() as conn:
        assert conn.exec_driver_sql("select sqlite_version()").scalar()


def test_dotenv_is_not_read():
    assert not settings.model_config.get("env_file")


@pytest.mark.parametrize("name", ["UPLOAD_DIR", "THUMBNAIL_DIR", "CV_OUTPUT_DIR", "CV_PIPELINE_PATH"])
def test_dirs_are_temp(name, tmp_root):
    p = Path(getattr(settings, name)).resolve()
    p.relative_to(tmp_root)
    assert BASE_DIR / "uploads" not in [p, *p.parents]


def test_mysql_drivers_are_blocked():
    pymysql = pytest.importorskip("pymysql")
    with pytest.raises(RuntimeError, match="never connect to MySQL"):
        pymysql.connect(host="127.0.0.1", port=3306, user="root", connect_timeout=1)
