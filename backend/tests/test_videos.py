import json
import textwrap

import pytest

from config import settings
from conftest import FAKE_MP4, register_and_login

FORM = {"title": "Derby clip", "match_date": "2026-09-27", "home_team": "Lions FC", "away_team": "Tigers FC"}

BASE_KEYS = {"player_id", "name", "top_speed_mph", "distance_km", "injury_risk"}


def base(row: dict) -> dict:
    return {k: row[k] for k in BASE_KEYS}


def upload(client, headers, data=None, content=FAKE_MP4, name="clip.mp4", ctype="video/mp4"):
    return client.post("/api/videos", headers=headers, data=FORM if data is None else data,
                       files={"file": (name, content, ctype)})


@pytest.fixture(scope="module")
def alice(client):
    return register_and_login(client, "alice@example.com", first="Alice", last="A")


@pytest.fixture(scope="module")
def bob(client):
    return register_and_login(client, "bob@example.com", first="Bob", last="B")


def test_requires_auth(client):
    assert upload(client, {}).status_code == 401
    assert client.get("/api/videos").status_code == 401


def test_upload_stub_flow(client, alice, tmp_root):
    r = upload(client, alice)
    assert r.status_code == 202, r.text
    v = r.json()
    assert v["status"] == "queued" and v["title"] == "Derby clip" and v["file_name"] == "clip.mp4"
    assert v["match"]["home_team"] == "Lions FC" and v["match"]["match_date"] == "2026-09-27"
    stored = list((tmp_root / "uploads").glob("*.mp4"))
    assert stored and all(len(p.stem) == 32 for p in stored)  # uuid4 hex names

    # TestClient runs BackgroundTasks before returning, so processing already finished
    s = client.get(f"/api/videos/{v['video_id']}", headers=alice).json()
    assert s["status"] == "done" and s["error_message"] is None and s["processed_at"]

    stats = client.get(f"/api/videos/{v['video_id']}/stats", headers=alice).json()
    assert isinstance(stats, list) and len(stats) == 8  # no roster -> 8 placeholder players
    for p in stats:
        assert BASE_KEYS <= set(p)  # video stats add flat metric extras (step 6)
        assert isinstance(p["top_speed_mph"], float) and p["injury_risk"] in {"Low", "Medium", "High"}
        assert p["name"].startswith("Unknown #")

    # same teams + date -> same match reused, list is newest first
    r2 = upload(client, alice, data={**FORM, "title": "Second half"})
    assert r2.json()["match_id"] == v["match_id"]
    titles = [x["title"] for x in client.get("/api/videos", headers=alice).json()]
    assert titles[:2] == ["Second half", "Derby clip"]


def test_stub_maps_roster_jerseys_to_real_players(client):
    demo = {"Authorization": "Bearer " + client.post(
        "/api/auth/login", json={"email": "faisal@example.com", "password": "capstone123"}).json()["access_token"]}
    r = upload(client, demo, data={"title": "Match 1 upload", "match_id": "1"})
    assert r.status_code == 202, r.text
    stats = client.get(f"/api/videos/{r.json()['video_id']}/stats", headers=demo).json()
    names = {p["name"] for p in stats}
    assert "Faisal Musa" in names and not any(n.startswith("Unknown") for n in names)


def test_user_isolation(client, alice, bob):
    vid = client.get("/api/videos", headers=alice).json()[0]["video_id"]
    assert client.get(f"/api/videos/{vid}", headers=bob).status_code == 404
    assert client.get(f"/api/videos/{vid}/stats", headers=bob).status_code == 404
    assert client.get("/api/videos", headers=bob).json() == []
    # bob cannot attach to alice's match either
    mid = client.get(f"/api/videos/{vid}", headers=alice).json()["match_id"]
    assert upload(client, bob, data={"match_id": str(mid)}).status_code == 404
    # and bob's "Lions FC" is his own team, not alice's
    r = upload(client, bob)
    assert r.status_code == 202 and r.json()["match_id"] != mid


def test_upload_validation(client, alice, monkeypatch):
    assert upload(client, alice, name="notes.txt", ctype="text/plain").status_code == 415
    assert upload(client, alice, name="clip.mp4", ctype="image/png").status_code == 415
    assert upload(client, alice, content=b"hello, not a video" * 10).status_code == 415  # sniff fails
    assert upload(client, alice, content=b"").status_code == 422
    assert upload(client, alice, data={"title": "no match info"}).status_code == 422
    # curl's default content type is accepted when the bytes look right
    assert upload(client, alice, ctype="application/octet-stream").status_code == 202
    avi = b"RIFF\x00\x00\x00\x00AVI LIST" + b"\x00" * 64
    assert upload(client, alice, content=avi, name="x.AVI", ctype="video/x-msvideo").status_code == 202
    monkeypatch.setattr(settings, "MAX_UPLOAD_MB", 0)
    assert upload(client, alice).status_code == 413


def test_missing_pipeline_without_stub_fails_gracefully(client, alice, monkeypatch):
    monkeypatch.setattr(settings, "CV_PIPELINE_STUB", False)
    v = upload(client, alice).json()
    s = client.get(f"/api/videos/{v['video_id']}", headers=alice).json()
    assert s["status"] == "failed" and "CV pipeline not found" in s["error_message"]


FAKE_RUN_PIPELINE = textwrap.dedent("""
    \"\"\"Stand-in for PR #1 cv/run_pipeline.py: same CLI, same output files. Output comes from cv/scenario.json.\"\"\"
    import argparse, json, os, sys
    from pathlib import Path
    from cv.marker import OK  # proves the adapter put the repo root on PYTHONPATH
    p = argparse.ArgumentParser()
    p.add_argument("--video", required=True); p.add_argument("--out", required=True)
    p.add_argument("--calibration"); p.add_argument("--device", default="auto")
    p.add_argument("--model"); p.add_argument("--annotate", action="store_true")
    p.add_argument("--no-ocr", action="store_true"); p.add_argument("--ocr-sample-rate", type=int, default=10)
    a = p.parse_args()
    print("module", __name__, "spec", __spec__.name if __spec__ else None)
    print("cwd", os.getcwd())
    print("device", a.device, "calibration", a.calibration)
    if "FAIL" in Path(a.video).read_bytes().decode("latin-1"):
        print("Error during processing: boom", file=sys.stderr); sys.exit(1)
    sc = json.loads((Path(__file__).parent / "scenario.json").read_text())
    out = Path(a.out); out.mkdir(parents=True, exist_ok=True)
    (out / "tracking_detections.json").write_text(json.dumps(sc["detections"]))
    (out / "player_match_stats.json").write_text(json.dumps(sc["stats"]))
    if sc.get("meta") is not None:
        (out / "meta.json").write_text(json.dumps(sc["meta"]))
""")


def det(frame, tid, jersey=None, cls="player", **extra):
    return {"frame": frame, "timestamp": round(frame / 25, 3), "track_id": tid, "class": cls,
            "bbox_x1": 1.0, "bbox_y1": 2.0, "bbox_x2": 30.0, "bbox_y2": 80.0, "confidence": 0.9,
            "pitch_x": 10.0, "pitch_y": 5.0, "jersey_number": jersey, **extra}


def stat(tid, jersey, speed, dist, risk="Low", **extra):
    return {"track_id": tid, "jersey_number": jersey, "top_speed_mph": speed, "distance_km": dist,
            "injury_risk": risk, "high_speed_distance_km": 0.0, "sprint_distance_km": 0.0, "sprint_count": 0,
            **extra}


# Today's output format (no team/role/meta): jersey 21 -> seeded Faisal Musa, track 9 -> placeholder
BASIC = {
    "detections": [det(0, 3, 21), det(25, 3, 21), det(25, 9), det(25, -1, cls="ball")],
    "stats": [stat(3, 21, 20.55, 1.23, "Medium"), stat(9, None, 11.0, 0.4)],
    "meta": None,
}


@pytest.fixture
def fake_cv_repo(tmp_root, monkeypatch):
    cv = tmp_root / "fake_repo" / "cv"
    cv.mkdir(parents=True, exist_ok=True)
    (cv / "__init__.py").write_text("")
    (cv / "marker.py").write_text("OK = True\n")
    (cv / "run_pipeline.py").write_text(FAKE_RUN_PIPELINE)
    monkeypatch.setattr(settings, "CV_PIPELINE_PATH", cv / "run_pipeline.py")
    monkeypatch.setattr(settings, "CV_PIPELINE_STUB", False)
    monkeypatch.setattr(settings, "CV_DEVICE", "cpu")

    def set_scenario(sc):
        (cv / "scenario.json").write_text(json.dumps(sc))
    set_scenario(BASIC)
    return set_scenario


@pytest.fixture
def demo(client):
    tok = client.post("/api/auth/login", json={"email": "faisal@example.com", "password": "capstone123"})
    return {"Authorization": f"Bearer {tok.json()['access_token']}"}


def capstone_upload(client, headers, title, date="2026-10-01"):
    r = upload(client, headers, data={"title": title, "match_date": date,
                                      "home_team": "Capstone FC", "away_team": "Rival United"})
    assert r.status_code == 202, r.text
    return r.json()["video_id"]


def test_real_pipeline_subprocess_contract(client, fake_cv_repo, demo, tmp_root):
    from pipeline import resolve_mode
    assert resolve_mode() == "real"
    vid = capstone_upload(client, demo, "real pipeline")
    s = client.get(f"/api/videos/{vid}", headers=demo).json()
    assert s["status"] == "done", s["error_message"]
    assert s["fps"] == 25.0  # no meta.json -> estimated from frame/timestamp
    assert s["pipeline_meta"]["adapter_source"] == "real" and s["pipeline_meta"]["warnings"] == []
    stats = {p["name"]: p for p in client.get(f"/api/videos/{vid}/stats", headers=demo).json()}
    assert base(stats["Faisal Musa"]) == {"player_id": 21, "name": "Faisal Musa", "top_speed_mph": 20.55,
                                          "distance_km": 1.23, "injury_risk": "Medium"}
    assert f"Unknown Track 9 (video {vid})" in stats
    log = (tmp_root / "cv_outputs" / f"video_{vid}" / "pipeline.log").read_text()
    root = str(tmp_root / "fake_repo")
    assert "-m cv.run_pipeline" in log and "spec cv.run_pipeline" in log   # invoked as a module
    assert f"cwd {root}" in log                                             # cwd = repo root
    assert "device cpu calibration None" in log


def test_stats_are_per_video(client, fake_cv_repo, demo):
    fake_cv_repo({"detections": [], "stats": [stat(1, 21, 18.0, 2.0, "Low")], "meta": None})
    v1 = capstone_upload(client, demo, "per-video A", date="2026-10-05")
    fake_cv_repo({"detections": [], "stats": [stat(4, 21, 19.5, 3.0, "High")], "meta": None})
    v2 = capstone_upload(client, demo, "per-video B", date="2026-10-05")
    s1 = client.get(f"/api/videos/{v1}", headers=demo).json()
    s2 = client.get(f"/api/videos/{v2}", headers=demo).json()
    assert s1["match_id"] == s2["match_id"]  # same match, separate stats
    a = client.get(f"/api/videos/{v1}/stats", headers=demo).json()
    b = client.get(f"/api/videos/{v2}/stats", headers=demo).json()
    assert [base(x) for x in a] == [{"player_id": 21, "name": "Faisal Musa", "top_speed_mph": 18.0, "distance_km": 2.0, "injury_risk": "Low"}]
    assert [base(x) for x in b] == [{"player_id": 21, "name": "Faisal Musa", "top_speed_mph": 19.5, "distance_km": 3.0, "injury_risk": "High"}]
    both = client.get(f"/api/players/stats?match_id={s1['match_id']}").json()
    assert both == [{"player_id": 21, "name": "Faisal Musa", "top_speed_mph": 19.5, "distance_km": 5.0, "injury_risk": "High"}]


def test_null_speed_distance_without_calibration(client, fake_cv_repo, demo):
    before = next(p for p in client.get("/api/players/stats?team_id=1").json() if p["player_id"] == 7)
    fake_cv_repo({"detections": [det(0, 1, 7)], "stats": [stat(1, 7, None, None, "Low"), stat(2, 4, None, None)],
                  "meta": {"fps": 30, "calibration": None, "warnings": ["no calibration: pitch coords disabled"]}})
    vid = capstone_upload(client, demo, "uncalibrated", date="2026-10-07")
    v = client.get(f"/api/videos/{vid}", headers=demo).json()
    assert v["status"] == "done"
    assert "no calibration: pitch coords disabled" in v["pipeline_meta"]["warnings"]
    assert any("No speed/distance" in w for w in v["pipeline_meta"]["warnings"])
    stats = client.get(f"/api/videos/{vid}/stats", headers=demo).json()
    assert {p["player_id"] for p in stats} == {7, 4}
    for p in stats:  # keys always present, values null
        assert BASE_KEYS <= set(p)  # video stats add flat metric extras (step 6)
        assert p["top_speed_mph"] is None and p["distance_km"] is None
    # across all rows: NULLs are ignored by MAX/SUM -> Luka's aggregate is unchanged by the null row
    after = next(p for p in client.get("/api/players/stats?team_id=1").json() if p["player_id"] == 7)
    assert after == before and after["top_speed_mph"] is not None


def test_team_role_and_meta_forward_compat(client, fake_cv_repo, demo):
    fake_cv_repo({
        "detections": [det(0, 1, 14, team=0), det(0, 2, 8), det(0, 3, None, role="referee"),
                       det(0, 4, 1, team=1, role="goalkeeper"), det(0, -1, cls="ball", role="ball")],
        "stats": [
            stat(1, 14, 17.0, 1.0, team=0),                    # home has no #14 -> placeholder on HOME (not Jan Dvorak, away)
            stat(2, 8, 16.0, 1.1),                             # no team -> home first, then away -> Mateo Rossi
            stat(3, None, 12.0, 0.5, role="referee"),          # skipped
            stat(4, 1, 9.0, 0.3, "Medium", team=1, role="goalkeeper"),  # away #1 -> Ivan Horvat
            {"track_id": 5, "jersey_number": 10, "unexpected_new_field": [1, 2]},  # sparse row tolerated
        ],
        "meta": {"fps": 29.97, "frame_count": 300, "duration_s": 10.01, "resolution": [1920, 1080],
                 "model": "yolov8x.pt", "device": "mps", "calibration": "calib.json",
                 "pipeline_version": "0.2.0", "runtime_s": 12.3, "warnings": ["ball lost for 40 frames"]},
    })
    vid = capstone_upload(client, demo, "forward compat", date="2026-10-09")
    v = client.get(f"/api/videos/{vid}", headers=demo).json()
    assert v["status"] == "done", v["error_message"]
    assert v["fps"] == 29.97  # from meta.json
    assert v["pipeline_meta"]["pipeline_version"] == "0.2.0"
    assert v["pipeline_meta"]["warnings"] == ["ball lost for 40 frames"]
    names = {p["name"]: p for p in client.get(f"/api/videos/{vid}/stats", headers=demo).json()}
    assert set(names) == {"Unknown #14", "Mateo Rossi", "Ivan Horvat", "Marco Silva"}
    assert names["Ivan Horvat"]["injury_risk"] == "Medium"
    assert names["Marco Silva"]["top_speed_mph"] is None  # row without numbers -> null, no crash
    home_placeholder = client.get(f"/api/players/{names['Unknown #14']['player_id']}", headers=demo).json()
    assert home_placeholder["team_id"] == 1


def test_team_side_mapping():
    from pipeline import team_side
    assert team_side(0) == "home" and team_side(1) == "away" and team_side("1") == "away"
    assert team_side(None) is None and team_side(2) is None and team_side("x") is None


def test_seed_video_stats(client, demo):
    s = client.get("/api/videos/1/stats", headers=demo).json()
    faisal = next(p for p in s if p["player_id"] == 21)
    assert faisal["top_speed_mph"] == 19.2 and faisal["distance_km"] == 2.1  # match-1 row only


def test_real_pipeline_failure_recorded(client, alice, fake_cv_repo):
    v = upload(client, alice, content=FAKE_MP4 + b"FAIL").json()
    s = client.get(f"/api/videos/{v['video_id']}", headers=alice).json()
    assert s["status"] == "failed" and "exited with code 1" in s["error_message"] and "boom" in s["error_message"]
