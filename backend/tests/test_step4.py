"""Frontend requests (stage/progress, list shape, thumbnails, delete, profile, config, matches)
and CV pipeline v1.1.0 output handling."""
import json
import shutil
import subprocess
import textwrap
import threading
import time
from pathlib import Path

import pytest

import pipeline
from config import settings
from conftest import FAKE_MP4, login, register_and_login
from database import SessionLocal
from models import MatchVideo, Player, PlayerMatchStat, TrackingDetection

LIST_KEYS = {"id", "video_id", "match_id", "title", "file_name", "match_date", "home_team", "away_team",
             "status", "stage", "progress", "error_message", "error", "created_at", "uploaded_at", "processed_at",
             "fps", "video_type", "resolution", "duration_seconds", "thumbnail_url", "source_url", "match", "tags", "result"}
FORM = {"title": "Step4 clip", "match_date": "2026-11-01", "home_team": "Capstone FC", "away_team": "Rival United"}


def upload(client, headers, data=None, content=FAKE_MP4, name="clip.mp4"):
    return client.post("/api/videos", headers=headers, data=FORM if data is None else data,
                       files={"file": (name, content, "video/mp4")})


@pytest.fixture
def demo(client):
    return login(client, "faisal@example.com", "capstone123")


@pytest.fixture(scope="module")
def carol(client):
    return register_and_login(client, "carol@example.com", first="Carol", last="C")


@pytest.fixture(scope="module")
def real_mp4(tmp_root):
    if not shutil.which("ffmpeg"):
        pytest.skip("ffmpeg not installed")
    out = tmp_root / "real_small.mp4"
    subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-f", "lavfi", "-i",
                    "testsrc=duration=2:size=320x240:rate=10", "-pix_fmt", "yuv420p", str(out)], check=True)
    return out.read_bytes()


# ------------------------------------------------------------------ config / profile
def test_public_config(client):
    r = client.get("/api/config")
    assert r.status_code == 200
    assert r.json() == {"max_upload_mb": settings.MAX_UPLOAD_MB, "allowed_extensions": ["avi", "mkv", "mov", "mp4"]}


def test_register_with_name_and_me_has_name(client):
    r = client.post("/api/auth/register", json={"name": "Dana van Dyke", "email": "dana@example.com",
                                                "password": "password123"})
    assert r.status_code == 201, r.text
    u = r.json()
    assert (u["name"], u["first_name"], u["last_name"]) == ("Dana van Dyke", "Dana", "van Dyke")
    h = login(client, "dana@example.com", "password123")
    me = client.get("/api/auth/me", headers=h).json()
    assert set(me) == {"id", "user_id", "name", "first_name", "last_name", "email", "role", "created_at"}
    assert me["name"] == "Dana van Dyke"
    single = client.post("/api/auth/register", json={"name": "Madonna", "email": "m@example.com", "password": "password123"})
    assert single.status_code == 201 and single.json()["name"] == "Madonna" and single.json()["last_name"] == ""
    assert client.post("/api/auth/register", json={"email": "x@example.com", "password": "password123"}).status_code == 422


def test_patch_me(client):
    h = register_and_login(client, "erin@example.com", first="Erin", last="E")
    r = client.patch("/api/auth/me", headers=h, json={"name": "Erin Marie Stone"})
    assert r.status_code == 200 and r.json()["first_name"] == "Erin" and r.json()["last_name"] == "Marie Stone"
    r = client.patch("/api/auth/me", headers=h, json={"last_name": "Smith"})
    assert r.json()["name"] == "Erin Smith"
    r = client.patch("/api/auth/me", headers=h, json={"name": "Ignored Name", "first_name": "Eri"})
    assert r.json()["name"] == "Eri Name"  # explicit first_name overrides the split
    assert client.patch("/api/auth/me", headers=h, json={}).status_code == 422
    assert client.patch("/api/auth/me", headers=h, json={"name": "   "}).status_code == 422
    assert client.patch("/api/auth/me", json={"name": "No Auth"}).status_code == 401
    assert client.get("/api/auth/me", headers=h).json()["name"] == "Eri Name"


def test_change_password(client):
    h = register_and_login(client, "frank@example.com", password="oldpassword1")
    url = "/api/auth/change-password"
    assert client.post(url, json={"current_password": "oldpassword1", "new_password": "x"}).status_code == 401
    r = client.post(url, headers=h, json={"current_password": "WRONG-pass", "new_password": "newpassword1"})
    assert r.status_code == 400 and r.json()["detail"] == "Current password is incorrect"
    assert client.post(url, headers=h, json={"current_password": "oldpassword1", "new_password": "short"}).status_code == 422
    assert client.post(url, headers=h, json={"current_password": "oldpassword1", "new_password": "y" * 73}).status_code == 422
    assert client.post(url, headers=h, json={"current_password": "oldpassword1", "new_password": "oldpassword1"}).status_code == 400
    r = client.post(url, headers=h, json={"current_password": "oldpassword1", "new_password": "newpassword1"})
    assert r.status_code == 204 and r.content == b""
    assert client.post("/api/auth/login", json={"email": "frank@example.com", "password": "oldpassword1"}).status_code == 401
    assert client.post("/api/auth/login", json={"email": "frank@example.com", "password": "newpassword1"}).status_code == 200


# ------------------------------------------------------------------ video object shapes
def test_list_is_bare_array_with_frontend_fields(client, carol):
    r = upload(client, carol, data={**FORM, "home_team": "Carol A", "away_team": "Carol B"})
    assert r.status_code == 202
    created = r.json()
    assert created["id"] == created["video_id"] and created["stage"] == "queued" and created["progress"] == 0
    assert "pipeline_meta" in created  # upload response = detail object
    lst = client.get("/api/videos", headers=carol).json()
    assert isinstance(lst, list) and lst
    item = lst[0]
    assert set(item) == LIST_KEYS  # no pipeline_meta in the list
    assert item["status"] == "done" and item["stage"] == "done" and item["progress"] == 100
    assert item["home_team"] == "Carol A" and item["match_date"] == "2026-11-01"
    assert item["created_at"] == item["uploaded_at"]
    assert item["duration_seconds"] == 1.0  # stub meta.json duration_s
    assert item["thumbnail_url"] is None     # fake mp4 bytes -> no thumbnail, processing still done
    detail = client.get(f"/api/videos/{item['id']}", headers=carol).json()
    assert set(detail) == LIST_KEYS | {"pipeline_meta"}
    assert detail["pipeline_meta"]["adapter_source"] == "stub" and detail["pipeline_meta"]["duration_s"] == 1.0


def test_stats_409_until_done(client, carol, monkeypatch):
    vid = client.get("/api/videos", headers=carol).json()[0]["id"]
    with SessionLocal() as db:
        v = db.get(MatchVideo, vid)
        v.processing_status, v.stage, v.progress = "processing", "detect", 40
        db.commit()
    r = client.get(f"/api/videos/{vid}/stats", headers=carol)
    assert r.status_code == 409
    assert r.json() == {"detail": "Video not processed yet", "status": "processing", "stage": "detect", "progress": 40,
                        "error_message": None}
    with SessionLocal() as db:
        v = db.get(MatchVideo, vid)
        v.processing_status, v.stage, v.progress = "done", "done", 100
        db.commit()
    assert client.get(f"/api/videos/{vid}/stats", headers=carol).status_code == 200

    monkeypatch.setattr(settings, "CV_PIPELINE_STUB", False)  # pipeline missing -> failed
    failed = upload(client, carol, data={**FORM, "home_team": "Carol A", "away_team": "Carol B"}).json()
    r = client.get(f"/api/videos/{failed['id']}/stats", headers=carol)
    assert r.status_code == 409 and r.json()["status"] == "failed" and r.json()["detail"] == "Video processing failed"
    assert r.json()["error_message"] and "pipeline" in r.json()["error_message"].lower()
    assert client.get(f"/api/videos/{failed['id']}", headers=carol).json()["stage"] == "failed"


# ------------------------------------------------------------------ thumbnails
def test_thumbnail_flow(client, demo, carol, real_mp4):
    v = upload(client, demo, content=real_mp4).json()
    item = client.get(f"/api/videos/{v['id']}", headers=demo).json()
    assert item["status"] == "done"
    url = item["thumbnail_url"]
    assert url and url.startswith(f"/api/videos/{v['id']}/thumbnail?token=")
    r = client.get(url)  # what <img src> does: no headers
    assert r.status_code == 200 and r.headers["content-type"] == "image/jpeg" and r.content[:2] == b"\xff\xd8"
    assert client.get(f"/api/videos/{v['id']}/thumbnail", headers=demo).status_code == 200  # bearer works too
    assert client.get(f"/api/videos/{v['id']}/thumbnail").status_code == 401
    assert client.get(f"/api/videos/{v['id']}/thumbnail", headers=carol).status_code == 404  # not carol's
    token = url.split("token=")[1]
    other = client.get("/api/videos", headers=demo).json()[-1]["id"]
    assert other != v["id"]
    assert client.get(f"/api/videos/{other}/thumbnail?token={token}").status_code == 401  # scoped to one video
    assert client.get("/api/auth/me", headers={"Authorization": f"Bearer {token}"}).status_code == 401
    access = demo["Authorization"].split()[1]
    assert client.get(f"/api/videos/{v['id']}/thumbnail?token={access}").status_code == 401  # no access tokens in URLs


# ------------------------------------------------------------------ delete
def test_delete_video_removes_everything(client, demo, carol, real_mp4, tmp_root):
    v = upload(client, demo, content=real_mp4).json()
    vid = v["id"]
    with SessionLocal() as db:
        row = db.get(MatchVideo, vid)
        files = [Path(row.file_path), Path(row.thumbnail_path)]
        files = [f if f.is_absolute() else Path(settings.UPLOAD_DIR).parent / f for f in files]
        assert db.query(PlayerMatchStat).filter_by(video_id=vid).count() > 0
        assert db.query(TrackingDetection).filter_by(video_id=vid).count() > 0
        db.add(Player(team_id=1, first_name="Unknown", last_name=f"Track 9 (video {vid})"))
        db.commit()
    out_dir = Path(settings.CV_OUTPUT_DIR) / f"video_{vid}"
    assert out_dir.is_dir() and all(f.is_file() for f in files)

    assert client.delete(f"/api/videos/{vid}", headers=carol).status_code == 404
    assert client.delete(f"/api/videos/{vid}").status_code == 401
    r = client.delete(f"/api/videos/{vid}", headers=demo)
    assert r.status_code == 204 and r.content == b""
    assert client.get(f"/api/videos/{vid}", headers=demo).status_code == 404
    assert client.delete(f"/api/videos/{vid}", headers=demo).status_code == 404
    assert not out_dir.exists() and not any(f.exists() for f in files)
    with SessionLocal() as db:
        assert db.query(PlayerMatchStat).filter_by(video_id=vid).count() == 0
        assert db.query(TrackingDetection).filter_by(video_id=vid).count() == 0
        assert db.query(Player).filter(Player.last_name.like(f"% (video {vid})")).count() == 0


def test_background_task_tolerates_row_deleted_after_pipeline(client, carol, monkeypatch):
    v = upload(client, carol, data={**FORM, "home_team": "Carol A", "away_team": "Carol B"}).json()
    real_run = pipeline.run_pipeline

    def run_then_delete(video):
        out = real_run(video)
        with SessionLocal() as db:
            db.delete(db.get(MatchVideo, video.video_id))
            db.commit()
        return out
    monkeypatch.setattr(pipeline, "run_pipeline", run_then_delete)
    pipeline.process_video(v["id"])  # must not raise
    assert client.get(f"/api/videos/{v['id']}", headers=carol).status_code == 404
    assert not (Path(settings.CV_OUTPUT_DIR) / f"video_{v['id']}").exists()


# ------------------------------------------------------------------ matches
def test_matches_list(client, demo, carol):
    ms = client.get("/api/matches", headers=demo).json()
    assert isinstance(ms, list) and ms
    assert {"match_id", "match_date", "home_team", "away_team", "video_count"} <= set(ms[0])  # + step-6 fields
    dates = [m["match_date"] for m in ms]
    assert dates == sorted(dates, reverse=True)
    m1 = next(m for m in ms if m["match_id"] == 1)
    assert m1["home_team"] == "Capstone FC" and m1["video_count"] >= 1
    carol_ms = client.get("/api/matches", headers=carol).json()
    assert {m["home_team"] for m in carol_ms} == {"Carol A"} and carol_ms[0]["video_count"] >= 1
    assert client.get("/api/matches").status_code == 401


# ------------------------------------------------------------------ CV v1.1.0 contract (fake subprocess)
FAKE_V11 = textwrap.dedent('''
    import argparse, json, sys, time
    from pathlib import Path
    p = argparse.ArgumentParser()
    for a in ("--video", "--out", "--calibration", "--device", "--model"):
        p.add_argument(a)
    p.add_argument("--ocr-sample-rate"); p.add_argument("--no-ocr", action="store_true")
    a = p.parse_args()
    sc = json.loads((Path(__file__).parent / "scenario.json").read_text())
    for line, pause in sc.get("print", []):
        sys.stderr.write(line); sys.stderr.flush(); time.sleep(pause)
    out = Path(a.out); out.mkdir(parents=True, exist_ok=True)
    (out / "tracking_detections.json").write_text(json.dumps(sc["detections"]))
    (out / "player_match_stats.json").write_text(json.dumps(sc["stats"]))
    (out / "meta.json").write_text(json.dumps(sc["meta"]))
''')


def d(frame, tid, jersey=None, team=None, role="player", cls="player", px=10.0):
    return {"frame": frame, "timestamp": round(frame / 30, 3), "track_id": tid, "class": cls,
            "bbox_x1": 1.0, "bbox_y1": 2.0, "bbox_x2": 3.0, "bbox_y2": 4.0, "confidence": 0.8,
            "pitch_x": px, "pitch_y": px, "jersey_number": jersey, "team": team, "role": role}


def st(tid, jersey, team, role, speed, dist, risk="Low"):
    return {"track_id": tid, "jersey_number": jersey, "top_speed_mph": speed, "distance_km": dist,
            "injury_risk": risk, "high_speed_distance_km": 0.0, "sprint_distance_km": 0.0, "sprint_count": 0,
            "team": team, "role": role}


META_V11 = {"pipeline_version": "1.1.0", "video_path": "x.mp4", "fps": 30.0, "frame_count": 90, "duration_s": 3.0,
            "resolution": "1920x1080", "model_path": "yolov8x.pt", "device": "cpu",
            "calibration": "/repo/cv/config/default_calibration.json",
            "start_timestamp": "2026-09-30T20:53:00.123456", "end_timestamp": "2026-09-30T20:53:03.000000",
            "runtime_s": 2.88, "unique_tracks": 4, "player_count": 3, "warnings": []}


@pytest.fixture
def fake_v11(tmp_root, monkeypatch):
    cv = tmp_root / "fake_v11" / "cv"
    cv.mkdir(parents=True, exist_ok=True)
    (cv / "__init__.py").write_text("")
    (cv / "run_pipeline.py").write_text(FAKE_V11)
    monkeypatch.setattr(settings, "CV_PIPELINE_PATH", cv / "run_pipeline.py")
    monkeypatch.setattr(settings, "CV_PIPELINE_STUB", False)

    def scenario(**kw):
        sc = {"detections": [], "stats": [], "meta": META_V11, **kw}
        (cv / "scenario.json").write_text(json.dumps(sc))
    scenario()
    return scenario


def test_v11_output_handling(client, demo, fake_v11):
    fake_v11(
        detections=[d(0, 1, 21, 0), d(30, 1, 21, 0), d(0, 2, 1, 1), d(0, 3, None, None, "referee"),
                    d(0, 4, None, None, "unknown"), d(0, -1, None, None, "ball", "ball")],
        stats=[st(1, 21, 0, "player", 19.1, 1.5), st(2, 1, 1, "goalkeeper", 12.0, 0.8, "Medium"),
               st(4, None, None, "unknown", None, None)],   # classifier not fitted -> role "unknown", nulls
    )
    v = upload(client, demo, data={**FORM, "match_date": "2026-11-02"}).json()
    item = client.get(f"/api/videos/{v['id']}", headers=demo).json()
    assert item["status"] == "done", item["error_message"]
    assert item["fps"] == 30.0 and item["duration_seconds"] == 3.0
    meta = item["pipeline_meta"]
    assert meta["pipeline_version"] == "1.1.0" and meta["resolution"] == "1920x1080" and meta["player_count"] == 3
    assert any("default_calibration.json" in w for w in meta["warnings"])
    stats = {p["name"]: p for p in client.get(f"/api/videos/{v['id']}/stats", headers=demo).json()}
    assert stats["Faisal Musa"]["top_speed_mph"] == 19.1           # team 0 -> home roster
    assert stats["Ivan Horvat"]["injury_risk"] == "Medium"         # team 1 goalkeeper -> away roster
    unknown = stats[f"Unknown Track 4 (video {v['id']})"]
    assert unknown["top_speed_mph"] is None and unknown["distance_km"] is None
    with SessionLocal() as db:
        classes = {r.track_id: r.object_class for r in db.query(TrackingDetection).filter_by(video_id=v["id"])}
    assert classes == {1: "player", 2: "player", 3: "referee", 4: "unknown", -1: "ball"}


def test_v11_no_calibration_warning_and_empty_stats(client, demo, fake_v11):
    fake_v11(meta={**META_V11, "calibration": "none",
                   "warnings": ["No calibration - pitch coordinates and speed/distance metrics will be null"]},
             detections=[d(0, 1, 21, 0, px=None)], stats=[])
    v = upload(client, demo, data={**FORM, "match_date": "2026-11-03"}).json()
    item = client.get(f"/api/videos/{v['id']}", headers=demo).json()
    assert item["status"] == "done"
    assert item["pipeline_meta"]["warnings"] == ["No calibration - pitch coordinates and speed/distance metrics will be null"]
    r = client.get(f"/api/videos/{v['id']}/stats", headers=demo)
    assert r.status_code == 200 and r.json() == []  # done with zero rows


def test_stage_hints_from_log():
    assert pipeline.stage_from_log("") is None
    assert pipeline.stage_from_log("Processing frames:   0%|") == ("detect", 10)
    assert pipeline.stage_from_log("Processing frames:  50%|#####") == ("detect", 40)
    assert pipeline.stage_from_log("\rProcessing frames: 100%|##########|") == ("detect", 70)
    assert pipeline.stage_from_log("...Finalizing team and role assignments...") == ("track", 72)
    assert pipeline.stage_from_log("Finalizing jersey numbers with majority voting...") == ("ocr", 75)
    assert pipeline.stage_from_log("Calculating player statistics...") == ("metrics", 78)


def test_progress_updates_during_real_run(client, demo, fake_v11, monkeypatch):
    fake_v11(print=[["Processing frames:  50%|#####\r", 2.6], ["Calculating player statistics...\n", 2.6]],
             stats=[st(1, 21, 0, "player", 18.0, 1.0)])
    seen = []
    orig = pipeline.set_progress
    monkeypatch.setattr(pipeline, "set_progress", lambda vid, stage, pr: seen.append((stage, pr)) or orig(vid, stage, pr))
    v = upload(client, demo, data={**FORM, "match_date": "2026-11-04"}).json()
    assert client.get(f"/api/videos/{v['id']}", headers=demo).json()["stage"] == "done"
    stages = [s for s, _ in seen]
    assert ("detect", 40) in seen and ("metrics", 78) in seen
    assert stages[-2:] == ["metrics", "ingest"]  # then done is written by process_video itself


def test_delete_while_real_pipeline_running_kills_it(client, demo, fake_v11, tmp_root):
    fake_v11(print=[["Processing frames:  10%|\r", 30]])  # would run 30s if not killed
    with SessionLocal() as db:
        f = tmp_root / "uploads" / "slow.mp4"
        f.parent.mkdir(parents=True, exist_ok=True)
        f.write_bytes(FAKE_MP4)
        v = MatchVideo(match_id=1, user_id=1, title="slow", file_name="slow.mp4", file_path=str(f))
        db.add(v)
        db.commit()
        vid = v.video_id
    t = threading.Thread(target=pipeline.process_video, args=(vid,))
    started = time.monotonic()
    t.start()
    time.sleep(1.0)
    assert client.get(f"/api/videos/{vid}", headers=demo).json()["status"] == "processing"
    assert client.delete(f"/api/videos/{vid}", headers=demo).status_code == 204
    t.join(timeout=15)
    assert not t.is_alive() and time.monotonic() - started < 10
    assert not (Path(settings.CV_OUTPUT_DIR) / f"video_{vid}").exists()
