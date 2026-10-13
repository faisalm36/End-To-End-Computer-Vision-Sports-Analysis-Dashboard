"""Step 5: frontend API contract alignment (auth responses, match_id coercion, {detail} errors, UTC timestamps)."""
import re
from datetime import datetime, timedelta, timezone

import pytest

from config import settings
from conftest import FAKE_MP4, login, register_and_login
from timeutil import iso_utc, utcnow

FORM = {"title": "Step5 clip", "match_date": "2026-12-05", "home_team": "Erin FC", "away_team": "Erin Rivals"}
ISO_Z = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(\.\d+)?Z$")


def upload(client, headers, data=None, content=FAKE_MP4, name="clip.mp4"):
    return client.post("/api/videos", headers=headers, data=FORM if data is None else data,
                       files={"file": (name, content, "video/mp4")})


def assert_recent_utc(value: str):
    assert ISO_Z.match(value), value
    t = datetime.fromisoformat(value.replace("Z", "+00:00"))
    assert abs(datetime.now(timezone.utc) - t) < timedelta(minutes=5), value


@pytest.fixture(scope="module")
def erin(client):
    return register_and_login(client, "erin@example.com", first="Erin", last="E")


# ------------------------------------------------------------------ auth responses
def test_register_returns_token_and_user(client):
    r = client.post("/api/auth/register", json={"name": "Frank Ocean", "email": "frank.s5@example.com",
                                                "password": "password123"})
    assert r.status_code == 201, r.text
    body = r.json()
    # unchanged top-level user fields (backward compatible) ...
    assert body["user_id"] == body["id"] and body["name"] == "Frank Ocean" and body["email"] == "frank.s5@example.com"
    # ... plus token + nested user
    assert body["token_type"] == "bearer" and body["expires_in"] > 0 and body["access_token"]
    assert body["user"]["id"] == body["id"] and body["user"]["name"] == "Frank Ocean"
    me = client.get("/api/auth/me", headers={"Authorization": f"Bearer {body['access_token']}"})
    assert me.status_code == 200 and me.json()["id"] == body["id"]
    assert_recent_utc(me.json()["created_at"])


def test_login_json_and_form_return_user(client):
    r = client.post("/api/auth/login", json={"email": "frank.s5@example.com", "password": "password123"})
    assert r.status_code == 200, r.text
    assert set(r.json()) == {"access_token", "token_type", "expires_in", "user"}
    assert r.json()["user"]["email"] == "frank.s5@example.com" and r.json()["user"]["id"]
    # frontend retries as an OAuth2 form on the SAME path
    f = client.post("/api/auth/login", data={"username": "frank.s5@example.com", "password": "password123"})
    assert f.status_code == 200, f.text
    assert f.json()["user"]["name"] == "Frank Ocean"
    t = client.post("/api/auth/token", data={"username": "frank.s5@example.com", "password": "password123"})
    assert t.status_code == 200 and t.json()["user"]["id"] == r.json()["user"]["id"]


def test_login_errors_are_detail_bodies(client):
    bad = client.post("/api/auth/login", json={"email": "frank.s5@example.com", "password": "nope-nope"})
    assert bad.status_code == 401 and bad.json() == {"detail": "Incorrect email or password"}
    bad_form = client.post("/api/auth/login", data={"username": "frank.s5@example.com", "password": "nope-nope"})
    assert bad_form.status_code == 401 and bad_form.json() == {"detail": "Incorrect email or password"}
    for kwargs in ({"json": {"email": "not-an-email", "password": "x"}}, {"json": {"password": "x"}},
                   {"content": b"{broken", "headers": {"Content-Type": "application/json"}},
                   {"data": {"password": "x"}}):
        r = client.post("/api/auth/login", **kwargs)
        assert r.status_code == 422, (kwargs, r.text)
        d = r.json()["detail"]
        assert isinstance(d, list) and d and all("msg" in e for e in d)


def test_change_password_400_body_is_exactly_detail(client):
    h = register_and_login(client, "gina@example.com", password="password123")
    r = client.post("/api/auth/change-password", headers=h,
                    json={"current_password": "WRONG-pass", "new_password": "newpassword1"})
    assert r.status_code == 400 and r.json() == {"detail": "Current password is incorrect"}
    r = client.post("/api/auth/change-password", headers=h,
                    json={"current_password": "password123", "new_password": "password123"})
    assert r.status_code == 400 and r.json() == {"detail": "New password must be different from the current one"}


# ------------------------------------------------------------------ upload match_id coercion
def test_upload_match_id_string_is_coerced(client, erin):
    first = upload(client, erin)
    assert first.status_code == 202, first.text
    mid = first.json()["match_id"]
    r = upload(client, erin, data={"title": "by id", "match_id": str(mid)})
    assert r.status_code == 202, r.text
    assert r.json()["match_id"] == mid and r.json()["match_date"] == "2026-12-05"
    r = upload(client, erin, data={"title": "by id, padded", "match_id": f" {mid} "})
    assert r.status_code == 202 and r.json()["match_id"] == mid


@pytest.mark.parametrize("empty", ["", "null", "undefined"])
def test_upload_empty_match_id_falls_back_to_teams(client, erin, empty):
    r = upload(client, erin, data={**FORM, "match_id": empty})
    assert r.status_code == 202, r.text
    assert r.json()["home_team"] == "Erin FC"


@pytest.mark.parametrize("bad", ["abc", "1.5", "-3", "0", "12abc", "١٢"])
def test_upload_non_numeric_match_id_is_422(client, erin, bad):
    r = upload(client, erin, data={"title": "x", "match_id": bad})
    assert r.status_code == 422, r.text
    d = r.json()["detail"]
    assert isinstance(d, list) and d[0]["loc"] == ["body", "match_id"] and "integer" in d[0]["msg"]


def test_upload_foreign_match_id_is_404(client, erin):
    other = register_and_login(client, "hank@example.com")
    mid = upload(client, other, data={**FORM, "home_team": "Hank A", "away_team": "Hank B"}).json()["match_id"]
    r = upload(client, erin, data={"title": "x", "match_id": str(mid)})
    assert r.status_code == 404 and r.json() == {"detail": "Match not found"}


def test_upload_without_match_id_or_teams_is_422_detail(client, erin):
    r = upload(client, erin, data={"title": "x"})
    assert r.status_code == 422 and r.json() == {"detail": "Provide match_id, or match_date + home_team + away_team"}


# ------------------------------------------------------------------ video object / 409
def test_video_timestamps_are_utc_z_and_error_alias(client, erin):
    v = upload(client, erin).json()
    assert_recent_utc(v["created_at"])
    assert v["created_at"] == v["uploaded_at"]
    assert v["error"] is None and v["error_message"] is None
    d = client.get(f"/api/videos/{v['id']}", headers=erin).json()
    assert d["status"] == "done"
    assert_recent_utc(d["processed_at"])
    assert d["match_date"] == "2026-12-05" and d["match"]["match_date"] == "2026-12-05"  # plain dates
    for item in client.get("/api/videos", headers=erin).json():
        assert ISO_Z.match(item["created_at"]) and ISO_Z.match(item["uploaded_at"])


def test_stats_409_failed_includes_error_message(client, erin, monkeypatch):
    monkeypatch.setattr(settings, "CV_PIPELINE_STUB", False)  # no pipeline -> failed
    v = upload(client, erin).json()
    d = client.get(f"/api/videos/{v['id']}", headers=erin).json()
    assert d["status"] == "failed" and d["error"] == d["error_message"] and d["error_message"]
    r = client.get(f"/api/videos/{v['id']}/stats", headers=erin)
    assert r.status_code == 409
    body = r.json()
    assert body["detail"] == "Video processing failed" and body["status"] == "failed" and body["stage"] == "failed"
    assert body["error_message"] == d["error_message"]
    assert_recent_utc(d["processed_at"])


# ------------------------------------------------------------------ error body consistency
def test_error_bodies_are_detail(client, erin):
    cases = [
        client.get("/api/auth/me"),                                              # 401
        client.get("/api/auth/me", headers={"Authorization": "Bearer junk"}),     # 401
        client.get("/api/videos/999999", headers=erin),                          # 404
        client.delete("/api/videos/999999", headers=erin),                       # 404
        client.get("/api/players/999999"),                                       # 404
        client.get("/api/no-such-route"),                                        # 404 (router)
        client.put("/api/config"),                                               # 405
        upload(client, erin, name="clip.txt"),                                   # 415
        upload(client, erin, content=b"not a video at all" * 10),               # 415 (sniff)
        upload(client, erin, content=b""),                                       # 422 empty
        client.post("/api/auth/register", json={"name": "Dup", "email": "erin@example.com",
                                                "password": "password123"}),    # 409
    ]
    for r in cases:
        assert r.status_code >= 400
        assert r.headers["content-type"].startswith("application/json"), (r.request.url, r.text)
        assert "detail" in r.json(), (r.request.url, r.text)
        assert isinstance(r.json()["detail"], (str, list))


def test_upload_413_is_detail(client, erin, monkeypatch):
    monkeypatch.setattr(settings, "MAX_UPLOAD_MB", 1)
    r = upload(client, erin, content=FAKE_MP4 + b"\x00" * (2 * 1024 * 1024))
    assert r.status_code == 413 and r.json() == {"detail": "File too large (max 1 MB)"}


def test_unhandled_error_is_json_500_with_cors(client):
    from main import app

    def boom():
        raise RuntimeError("kaboom")

    app.add_api_route("/api/__test_boom", boom, methods=["GET"])
    r = client.get("/api/__test_boom", headers={"Origin": "http://localhost:5173"})
    assert r.status_code == 500 and r.json() == {"detail": "Internal server error"}
    assert r.headers.get("access-control-allow-origin") == "http://localhost:5173"
    assert "kaboom" not in r.text


# ------------------------------------------------------------------ timeutil
def test_iso_utc():
    assert iso_utc(None) is None
    assert iso_utc(datetime(2026, 9, 30, 21, 20, 19)) == "2026-09-30T21:20:19Z"  # naive = UTC
    est = timezone(timedelta(hours=-4))
    assert iso_utc(datetime(2026, 9, 30, 17, 20, 19, tzinfo=est)) == "2026-09-30T21:20:19Z"
    n = utcnow()
    assert n.tzinfo is None and abs(datetime.now(timezone.utc).replace(tzinfo=None) - n) < timedelta(seconds=5)
