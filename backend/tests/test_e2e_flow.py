"""End-to-end through the HTTP API: upload -> background processing (stub CV pipeline) -> status/progress ->
stats -> heatmap -> tags -> match result -> insights -> delete. Runs entirely on the temp SQLite DB/dirs from
conftest.py (TestClient executes BackgroundTasks right after the upload response, like uvicorn would)."""
import json

import pytest

import pipeline
from conftest import FAKE_MP4, register_and_login
from database import SessionLocal
from models import MatchVideo


@pytest.fixture(scope="module")
def coach(client):
    return register_and_login(client, "e2e.coach@example.com", first="Eve", last="Coach")


@pytest.fixture()
def progress_log(monkeypatch):
    """Record every status/stage/progress the worker goes through (DB view + set_progress calls)."""
    seen = []
    real_set, real_run = pipeline.set_progress, pipeline.run_pipeline

    def snap(video_id, where):
        with SessionLocal() as db:
            v = db.get(MatchVideo, video_id)
            seen.append((where, v.processing_status, v.stage, v.progress))

    def set_progress(video_id, stage, progress):
        ok = real_set(video_id, stage, progress)
        snap(video_id, f"set_progress:{stage}")
        return ok

    def run_pipeline(video):
        snap(video.video_id, "run_pipeline")
        return real_run(video)

    monkeypatch.setattr(pipeline, "set_progress", set_progress)
    monkeypatch.setattr(pipeline, "run_pipeline", run_pipeline)
    return seen


def upload(client, headers, **form):
    data = {"title": "E2E derby", "match_date": "2026-09-20", "home_team": "E2E Hawks", "away_team": "E2E Owls",
            "our_side": "home", "tags": json.dumps([{"key": "weather", "value": "Windy"}])}
    data.update(form)
    return client.post("/api/videos", headers=headers, data=data,
                       files={"file": ("e2e.mp4", FAKE_MP4, "video/mp4")})


def test_full_flow(client, coach, progress_log, tmp_root):
    # ---- upload: 202 + queued, file lands in the TEMP upload dir
    r = upload(client, coach)
    assert r.status_code == 202, r.text
    v = r.json()
    vid, mid = v["id"], v["match_id"]
    assert (v["status"], v["stage"], v["progress"]) == ("queued", "queued", 0)
    assert v["match"]["home_team"] == "E2E Hawks" and v["tags"] == [{"key": "weather", "value": "Windy"}]
    assert list((tmp_root / "uploads").glob("*.mp4"))

    # ---- background processing went queued -> processing/detect -> metrics -> ingest -> done
    assert progress_log[0] == ("run_pipeline", "processing", "detect", 10), progress_log
    stages = [s[2] for s in progress_log]
    assert stages.index("detect") < stages.index("metrics") < stages.index("ingest")
    progresses = [s[3] for s in progress_log]
    assert progresses == sorted(progresses)                      # never moves backwards

    # ---- status endpoint
    s = client.get(f"/api/videos/{vid}", headers=coach).json()
    assert (s["status"], s["stage"], s["progress"]) == ("done", "done", 100)
    assert s["error_message"] is None and s["processed_at"] and s["fps"] == 30.0
    assert s["pipeline_meta"]["model"] == "stub"
    listed = {x["id"]: x for x in client.get("/api/videos", headers=coach).json()}
    assert listed[vid]["status"] == "done"

    # ---- stats (plain + extended metrics)
    stats = client.get(f"/api/videos/{vid}/stats", headers=coach)
    assert stats.status_code == 200
    rows = stats.json()
    assert rows and all({"player_id", "name", "top_speed_mph", "distance_km", "injury_risk"} <= set(x) for x in rows)
    with_metrics = client.get(f"/api/videos/{vid}/stats?include=metrics", headers=coach).json()
    assert all("metrics" in x for x in with_metrics)
    pid = rows[0]["player_id"]

    # ---- heatmaps (video, single player, player history)
    hm = client.get(f"/api/videos/{vid}/heatmap", headers=coach).json()
    assert hm["video_id"] == vid and hm["grid"]["cols"] > 0 and hm["players"]
    one = client.get(f"/api/videos/{vid}/heatmap?player_id={pid}", headers=coach).json()
    assert [p["player_id"] for p in one["players"]] == [pid]
    ph = client.get(f"/api/players/{pid}/heatmap", headers=coach)
    assert ph.status_code == 200 and ph.json()["player_id"] == pid
    pm = client.get(f"/api/players/{pid}/metrics", headers=coach)
    assert pm.status_code == 200 and pm.json()["series"][0]["video_id"] == vid

    # ---- tags: add one on the match, read back through video/match/catalog
    r = client.post(f"/api/matches/{mid}/tags", headers=coach, json={"tags": [{"key": "pitch", "value": "Turf"}]})
    assert r.status_code == 200, r.text
    assert {"key": "pitch", "value": "Turf"} in client.get(f"/api/videos/{vid}/tags", headers=coach).json()
    catalog = {t["key"]: t for t in client.get("/api/tags", headers=coach).json()}
    assert {"weather", "pitch"} <= set(catalog)

    # ---- match result: scores -> W for our side (home)
    r = client.patch(f"/api/matches/{mid}", headers=coach, json={"home_score": 3, "away_score": 1})
    assert r.status_code == 200 and r.json()["result"] == "W"
    assert client.get(f"/api/videos/{vid}", headers=coach).json()["result"] == "W"

    # ---- a second match, lost and in the rain -> insights split by weather
    r2 = upload(client, coach, title="E2E away day", match_date="2026-09-27", home_team="E2E Foxes",
                away_team="E2E Hawks", our_side="away", tags=json.dumps([{"key": "weather", "value": "Rainy"}]))
    assert r2.status_code == 202
    mid2 = r2.json()["match_id"]
    assert client.get(f"/api/videos/{r2.json()['id']}", headers=coach).json()["status"] == "done"
    assert client.patch(f"/api/matches/{mid2}", headers=coach,
                        json={"home_score": 2, "away_score": 0}).json()["result"] == "L"

    ins = client.get("/api/insights?tag_key=weather", headers=coach)
    assert ins.status_code == 200, ins.text
    body = ins.json()
    groups = {g["value"]: g for g in body["groups"]}
    assert set(groups) == {"Windy", "Rainy"}
    assert body["baseline"]["wdl"] == {"w": 1, "d": 0, "l": 1, "unknown": 0}
    assert all(g["matches"] == 1 and g["low_sample"] for g in groups.values())
    assert client.get("/api/insights/tags?key=weather", headers=coach).status_code == 200
    assert client.get("/api/insights?tag_key=weather").status_code == 401

    # ---- delete removes the video and its stats (DB cascade); the other video is untouched
    assert client.delete(f"/api/videos/{vid}", headers=coach).status_code == 204
    assert client.get(f"/api/videos/{vid}", headers=coach).status_code == 404
    assert client.get(f"/api/videos/{vid}/stats", headers=coach).status_code == 404
    assert client.get(f"/api/videos/{r2.json()['id']}", headers=coach).status_code == 200


def test_other_users_cannot_see_the_flow(client, coach):
    v = upload(client, coach, title="private").json()
    other = register_and_login(client, "e2e.other@example.com")
    for url in (f"/api/videos/{v['id']}", f"/api/videos/{v['id']}/stats", f"/api/videos/{v['id']}/heatmap",
                f"/api/videos/{v['id']}/tags", f"/api/matches/{v['match_id']}"):
        assert client.get(url, headers=other).status_code == 404, url
    assert client.get(f"/api/videos/{v['id']}").status_code == 401
