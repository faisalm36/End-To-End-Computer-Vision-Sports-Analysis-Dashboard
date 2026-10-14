"""Step 6 (tag filters: same key = OR, different keys = AND): extended metrics (004), heatmaps, match tags + results (005), insights, CV v1.1.1 handling."""
import json
import re
from pathlib import Path

import pytest
from sqlalchemy import func

import metrics_catalog as mc
import pipeline
import seed
from conftest import FAKE_MP4, login, register_and_login
from database import SessionLocal
from models import PlayerHeatmap, PlayerMatchMetric, PlayerMatchStat, TagKey, TagValue

BACKEND = Path(__file__).resolve().parents[1]
FRONTEND_KEYS = {"distance_per_min", "hsr_distance_km", "sprint_count", "sprint_distance_km", "accels", "decels"}
FORM = {"title": "S6", "match_date": "2026-12-20", "home_team": "Zed FC", "away_team": "Zed Rivals"}


@pytest.fixture(autouse=True, scope="module")
def _fresh_seed(client):
    seed.seed()
    yield
    seed.seed()


@pytest.fixture(scope="module")
def demo(client):
    return login(client, "faisal@example.com", "capstone123")


@pytest.fixture(scope="module")
def zed(client):
    return register_and_login(client, "zed@example.com", first="Zed", last="Z")


def upload(client, headers, data=None, content=FAKE_MP4, name="clip.mp4"):
    return client.post("/api/videos", headers=headers, data=FORM if data is None else data,
                       files={"file": (name, content, "video/mp4")})


# ============================================================== metric registry
def test_metrics_registry_public(client):
    r = client.get("/api/metrics")
    assert r.status_code == 200
    defs = {d["key"]: d for d in r.json()}
    assert FRONTEND_KEYS <= set(defs) and {"distance_km", "top_speed_mph", "avg_pitch_x", "avg_pitch_y",
                                          "minutes_played", "high_intensity_efforts"} <= set(defs)
    assert {f"zone{i}_distance_km" for i in range(1, 6)} <= set(defs)
    assert {"top_speed_kmh", "visible_minutes", "coverage_pct", "hsr_count"} <= set(defs)       # v1.2.0 additions
    assert all(d["availability"] == "ready" for d in defs.values())                          # all emitted by v1.2.0
    assert defs["accels"]["is_estimate"] and defs["distance_per_min"]["unit"] == "m/min"
    assert defs["top_speed_mph"]["aggregation"] == "max" and defs["distance_per_min"]["aggregation"] == "ratio"
    assert set(defs["sprint_count"]) == {"key", "label", "unit", "category", "value_type", "aggregation", "decimals",
                                         "higher_is_better", "requires_calibration", "is_estimate", "availability",
                                         "storage", "description", "sort_order"}
    assert "high_speed_distance_km" not in defs  # pipeline key is aliased to hsr_distance_km


@pytest.mark.parametrize("path", ["migrations/004_player_metrics.sql", "migrations/006_pipeline_v120.sql",
                                  "migrations/007_video_player_overrides.sql", "schema.sql"])
def test_sql_definitions_match_catalog(path):
    sql = (BACKEND / path).read_text()
    assert mc.definitions_insert_sql() in sql                      # exact generated block
    for d in mc.DEFINITIONS:
        m = re.search(r"\('" + re.escape(d["metric_key"]) + r"', '((?:[^']|'')*)', ('[^']*'|NULL), '([a-z_]+)', "
                      r"'(\w+)', '(\w+)'", sql)
        assert m, d["metric_key"]
        assert m.group(1).replace("''", "'") == d["label"] and m.group(5) == d["aggregation"]


def test_aggregate_rules():
    rows = [{"distance_km": 2.0, "minutes_played": 40.0, "top_speed_mph": 18.0, "sprint_count": 3.0},
            {"distance_km": 1.0, "minutes_played": 20.0, "top_speed_mph": 20.0, "sprint_count": None},
            {"distance_km": None, "minutes_played": 30.0, "top_speed_mph": None}]
    a = mc.aggregate(rows)
    assert a["distance_km"] == 3.0 and a["top_speed_mph"] == 20.0 and a["sprint_count"] == 3
    assert isinstance(a["sprint_count"], int)
    assert a["distance_per_min"] == 50  # (2+1) km * 1000 / (40+20) min; the row without distance is skipped
    assert a["accels"] is None and a["minutes_played"] == 90.0
    cells, n, mean = mc.heatmap([(0, 0), (104.9, 67.9), (52.5, 34), (200, 10)], 105, 68)
    assert n == 3 and cells[0][0] == 1 and cells[7][11] == 1 and cells[4][6] == 1 and mean is not None


# ============================================================== stats ?include=metrics
def test_players_stats_unchanged_without_include(client):
    for row in client.get("/api/players/stats").json():
        assert set(row) == {"player_id", "name", "top_speed_mph", "distance_km", "injury_risk"}


def test_players_stats_include_metrics(client):
    rows = client.get("/api/players/stats?include=metrics").json()
    faisal = next(r for r in rows if r["player_id"] == 21)
    assert faisal["top_speed_mph"] == 19.2 and faisal["distance_km"] == 4.5          # unchanged numbers
    assert set(faisal["metrics"]) == {d["metric_key"] for d in mc.DEFINITIONS}
    assert faisal["metrics"]["distance_km"] == 4.5 and isinstance(faisal["metrics"]["accels"], int)
    assert faisal["metrics"]["minutes_played"] == 120.0                              # 2 x 60 seeded
    vis = faisal["metrics"]["visible_minutes"]
    assert vis < 120 and abs(faisal["metrics"]["distance_per_min"] - 4.5 * 1000 / vis) <= 1   # per tracked minute
    assert faisal["visible_minutes"] == vis and faisal["speed_zones"]["walk"] is not None      # flat extras
    assert isinstance(faisal["metrics"]["sprint_count"], int)
    assert set(faisal["avg_position"]) == {"x", "y"}
    only = client.get("/api/players/stats?include=metrics&metrics=sprint_count,hsr_distance_km,nope").json()
    assert set(only[0]["metrics"]) == {"sprint_count", "hsr_distance_km"}


def test_video_stats_include_metrics_and_heatmap(client, demo):
    s = client.get("/api/videos/1/stats?include=metrics", headers=demo).json()
    assert s and all("metrics" in r and "avg_position" in r for r in s)
    plain = client.get("/api/videos/1/stats", headers=demo).json()
    assert all("metrics" not in r for r in plain)
    flat = {"jersey_number", "minutes_played", "distance_per_min", "hsr_distance_km", "sprint_distance_km",
            "sprint_count", "high_intensity_efforts", "accels", "decels", "speed_zones", "avg_position", "heatmap"}
    for r in plain:                              # flat extras are always on video stats (frontend contract)
        assert flat <= set(r) and isinstance(r["accels"], int) and set(r["speed_zones"]) == set(mc.ZONE_NAMES)
        assert r["heatmap"]["cols"] == 12 and len(r["heatmap"]["cells"]) == 96 and max(r["heatmap"]["cells"]) == 1.0
        assert r["heatmap"]["source"] == "backend"                                    # video 1 = older pipeline
        assert r["speed_thresholds"] == {**mc.DEFAULT_SPEED_THRESHOLDS, "source": "pipeline"}  # seed meta (v0.4.1)
        assert isinstance(r["sprint_count"], int)
    assert client.get("/api/videos/1", headers=demo).json()["result"] == "W"
    h = client.get("/api/videos/2/heatmap", headers=demo)
    assert h.status_code == 200
    body = h.json()
    assert body["grid"]["cols"] == 21 and body["grid"]["rows"] == 14 and body["grid"]["pitch_length_m"] == 105.0
    assert body["grid"]["source"] == "pipeline" and body["grid"]["cell_unit"] == "seconds"
    p = body["players"][0]
    assert len(p["counts"]) == 14 and all(len(r) == 21 for r in p["counts"]) and p["samples"] > 0
    assert p["source"] == "pipeline"
    s2 = client.get("/api/videos/2/stats", headers=demo).json()
    assert s2[0]["speed_thresholds"] == {"preset": "gps_standard", "hsr_kmh": 19.8, "sprint_kmh": 25.3,
                                         "zone_edges_kmh": {"walk": 7.0, "jog": 15.0, "run": 19.8, "hsr": 25.3},
                                         "source": "pipeline"}
    assert s2[0]["heatmap"]["cols"] == 21 and len(s2[0]["heatmap"]["cells"]) == 21 * 14
    v1 = client.get("/api/videos/1/heatmap", headers=demo).json()
    assert v1["grid"]["cols"] == 12 and v1["grid"]["source"] == "backend" and v1["grid"]["cell_unit"] == "samples"
    assert max(v for r in p["intensity"] for v in r) == 1.0
    one = client.get("/api/videos/2/heatmap?player_id=7", headers=demo).json()
    assert [x["player_id"] for x in one["players"]] == [7]


# ============================================================== pipeline v1.1.1 ingestion
V111_META = {"pipeline_version": "1.1.1", "fps": 30.0, "frame_count": 5400, "duration_s": 180.0,
             "resolution": "1920x1080", "width": 1920, "height": 1080, "model_path": "yolov8n.pt", "device": "cpu",
             "calibration": "cv/config/default_calibration.json", "runtime_s": 1.0, "unique_tracks": 4,
             "player_count": 3, "warnings": ["Using default calibration from default_calibration.json - "
                                             "create custom calibration for accurate results"]}


def _v111_output():
    dets = []
    for tid, team, role, (x, y) in [(1, 0, "player", (20, 10)), (2, 0, "player", (60, 30)),
                                    (3, 1, "player", (90, 60)), (4, None, "referee", (50, 34))]:
        for f in range(0, 30, 3):
            dets.append({"frame": f, "timestamp": f / 30, "track_id": tid, "class": "player", "team": team,
                         "role": role, "jersey_number": None, "bbox_x1": 1, "bbox_y1": 1, "bbox_x2": 2, "bbox_y2": 2,
                         "confidence": 0.9, "pitch_x": x + f / 10, "pitch_y": y})
    dets.append({"frame": 0, "timestamp": 0, "track_id": -1, "class": "ball", "role": "ball", "team": None,
                 "bbox_x1": 1, "bbox_y1": 1, "bbox_x2": 2, "bbox_y2": 2, "confidence": 0.4, "pitch_x": None,
                 "pitch_y": None})
    stats = [
        {"track_id": 1, "top_speed_mph": 17.3, "distance_km": 0.6, "injury_risk": "Low", "team": 0, "role": "player",
         "high_speed_distance_km": 0.05, "sprint_distance_km": 0.02, "sprint_count": 3, "jersey_number": None,
         "brand_new_metric": 1.5},
        {"track_id": 2, "top_speed_mph": None, "distance_km": None, "injury_risk": "Low", "team": 0,
         "role": "player", "high_speed_distance_km": None, "sprint_distance_km": None, "sprint_count": None},
        {"track_id": 3, "top_speed_mph": 19.0, "distance_km": 0.9, "injury_risk": "Medium", "team": 1,
         "role": "player", "high_speed_distance_km": 0.1, "sprint_distance_km": 0.04, "sprint_count": 5,
         "hsr_count": 4},
    ]
    return pipeline.PipelineOutput(detections=dets, player_stats=stats, source="real", meta=dict(V111_META))


def test_v111_output_ingest(client, zed, monkeypatch):
    monkeypatch.setattr(pipeline, "run_pipeline", lambda video: _v111_output())
    v = upload(client, zed).json()
    d = client.get(f"/api/videos/{v['id']}", headers=zed).json()
    assert d["status"] == "done", d["error_message"]
    warns = d["pipeline_meta"]["warnings"]
    assert sum("default calibration" in w.lower() or "default_calibration" in w.lower() for w in warns) == 1
    assert any("brand_new_metric" in w for w in warns)
    assert d["pipeline_meta"]["width"] == 1920 and d["duration_seconds"] == 180.0
    stats = client.get(f"/api/videos/{v['id']}/stats?include=metrics", headers=zed).json()
    assert len(stats) == 3  # referee skipped
    by_speed = {r["top_speed_mph"]: r for r in stats}
    t1, t2, t3 = by_speed[17.3], by_speed[None], by_speed[19.0]
    assert t1["metrics"]["hsr_distance_km"] == 0.05 and t1["metrics"]["sprint_count"] == 3
    # v0.7.0: no minutes from the CV -> null (never the clip length), so no rate either
    assert t1["metrics"]["minutes_played"] is None and t1["metrics"]["distance_per_min"] is None
    assert t1["metrics"]["high_intensity_efforts"] is None
    assert t3["metrics"]["high_intensity_efforts"] == 9                                     # hsr_count + sprints
    assert t2["metrics"]["hsr_distance_km"] is None and t2["metrics"]["distance_per_min"] is None
    assert t2["distance_km"] is None and t2["avg_position"] == {"x": 61.4, "y": 30.0}
    with SessionLocal() as db:
        ids = [s.stat_id for s in db.query(PlayerMatchStat).filter_by(video_id=v["id"])]
        assert db.query(PlayerHeatmap).filter(PlayerHeatmap.stat_id.in_(ids)).count() == 3
        assert db.query(PlayerMatchMetric).filter(PlayerMatchMetric.stat_id.in_(ids),
                                                  PlayerMatchMetric.metric_key == "hsr_distance_km").count() == 3
    # re-processing replaces (no duplicate metric rows), delete cascades
    pipeline.process_video(v["id"])
    with SessionLocal() as db:
        ids = [s.stat_id for s in db.query(PlayerMatchStat).filter_by(video_id=v["id"])]
        assert db.query(PlayerMatchMetric).filter(PlayerMatchMetric.stat_id.in_(ids)).count() == \
            len({(m.stat_id, m.metric_key) for m in db.query(PlayerMatchMetric).filter(
                PlayerMatchMetric.stat_id.in_(ids))})
    assert client.delete(f"/api/videos/{v['id']}", headers=zed).status_code == 204
    with SessionLocal() as db:
        assert db.query(PlayerMatchMetric).filter(PlayerMatchMetric.stat_id.in_(ids)).count() == 0
        assert db.query(PlayerHeatmap).filter(PlayerHeatmap.stat_id.in_(ids)).count() == 0


def test_v110_meta_still_gets_adapter_warning():
    out = pipeline.PipelineOutput(detections=[], player_stats=[], source="real",
                                  meta={"calibration": "/x/cv/config/default_calibration.json", "warnings": []})
    w = pipeline._meta_summary(out, 1.0)["warnings"]
    assert len(w) == 1 and "default_calibration.json" in w[0]


def test_heatmap_409_until_done(client, zed, monkeypatch):
    monkeypatch.setattr(pipeline, "process_video", lambda vid: None)
    import routers.videos as rv
    monkeypatch.setattr(rv, "process_video", lambda vid: None)
    v = upload(client, zed).json()
    r = client.get(f"/api/videos/{v['id']}/heatmap", headers=zed)
    assert r.status_code == 409 and r.json()["status"] == "queued"


# ============================================================== player history / heatmap
def test_player_metrics_history(client, demo, zed):
    r = client.get("/api/players/7/metrics", headers=demo)
    assert r.status_code == 200
    b = r.json()
    dates = [s["match_date"] for s in b["series"]]
    assert dates == sorted(dates) and len(b["series"]) == 6          # m3, m4, m5, m1, m6, m2 (legacy row)
    assert b["series"][0]["video_id"] == 2 and b["series"][0]["result"] == "W"
    assert b["series"][-1]["video_id"] is None                         # legacy (no video) row of match 2
    assert set(b["series"][0]["metrics"]) == {d["metric_key"] for d in mc.DEFINITIONS}
    assert b["totals"]["appearances"] == 6 and b["totals"]["distance_km"] == round(
        sum(s["distance_km"] for s in b["series"]), 2)
    lim = client.get("/api/players/7/metrics?metrics=sprint_count", headers=demo).json()
    assert set(lim["series"][0]["metrics"]) == {"sprint_count"}
    assert client.get("/api/players/7/metrics", headers=zed).status_code == 404   # not your player
    assert client.get("/api/players/7/metrics").status_code == 401
    hm = client.get("/api/players/7/heatmap", headers=demo).json()
    # videos 2-5 have 21x14 pipeline grids, video 1 a 12x8 backend grid: they can't be added -> the bigger group wins
    assert hm["videos"] == 4 and hm["videos_skipped"] == 1 and hm["samples"] == 1200 and hm["avg_position"]["y"] < 20
    assert hm["grid"]["cols"] == 21 and hm["grid"]["source"] == "pipeline"
    only1 = client.get("/api/players/7/heatmap?video_id=1", headers=demo).json()
    assert only1["grid"]["cols"] == 12 and only1["videos"] == 1 and only1["videos_skipped"] == 0
    one = client.get("/api/players/7/heatmap?video_id=2", headers=demo).json()
    assert one["videos"] == 1 and one["samples"] == 300
    assert client.get("/api/players/7/heatmap", headers=zed).status_code == 404


# ============================================================== tags
def test_video_tags_crud_and_reuse(client, demo):
    vid = 2  # seeded, match 3: weather Rainy + pitch Grass
    assert client.get(f"/api/videos/{vid}/tags", headers=demo).json() == [
        {"key": "Pitch", "value": "Grass"}, {"key": "Weather", "value": "Rainy"}]
    r = client.post(f"/api/videos/{vid}/tags", headers=demo,
                    json={"tags": [{"key": " Referee ", "value": "Strict"}, {"key": "weather", "value": "rainy"}]})
    assert r.status_code == 200 and r.json()["id"] == vid          # POST/PUT on a video return the video object
    tags = r.json()["tags"]
    assert {"key": "Referee", "value": "Strict"} in tags and len(tags) == 3   # 'weather'/'rainy' reused 'Weather'/'Rainy'
    bare = client.post(f"/api/videos/{vid}/tags", headers=demo, json=[{"key": "Home/Away", "value": "Home"}])
    assert bare.status_code == 200 and len(bare.json()["tags"]) == 4
    video = client.get(f"/api/videos/{vid}", headers=demo).json()
    assert {"key": "Home/Away", "value": "Home"} in video["tags"]
    lst = next(v for v in client.get("/api/videos", headers=demo).json() if v["id"] == vid)
    assert lst["tags"] == video["tags"]
    assert client.delete(f"/api/videos/{vid}/tags?key=referee&value=STRICT", headers=demo).status_code == 204
    assert client.delete(f"/api/videos/{vid}/tags?key=referee&value=STRICT", headers=demo).status_code == 204
    assert client.delete(f"/api/videos/{vid}/tags?key=home%2Faway", headers=demo).status_code == 204
    assert len(client.get(f"/api/videos/{vid}/tags", headers=demo).json()) == 2
    with SessionLocal() as db:  # values stay reusable for autocomplete
        assert db.query(TagValue).filter(TagValue.value == "Strict").count() == 1


def test_put_replaces_full_set(client, demo):
    r = client.put("/api/videos/3/tags", headers=demo, json={"tags": [{"key": "weather", "value": "Windy"}]})
    assert r.status_code == 200 and r.json()["tags"] == [{"key": "Weather", "value": "Windy"}]
    assert client.get("/api/matches/4/tags", headers=demo).json() == [{"key": "Weather", "value": "Windy"}]
    assert client.put("/api/videos/3/tags", headers=demo, json={"tags": []}).json()["tags"] == []
    back = client.put("/api/matches/4/tags", headers=demo,
                      json={"tags": [{"key": "weather", "value": "Sunny"}, {"key": "pitch", "value": "Turf"}]})
    assert len(back.json()) == 2


@pytest.mark.parametrize("bad", [{"tags": [{"key": "a:b", "value": "x"}]}, {"tags": [{"key": "k", "value": ""}]},
                                 {"tags": [{"key": "", "value": "x"}]}, {"tags": [{"key": "k"}]}, {"nope": 1}])
def test_bad_tags_422(client, demo, bad):
    r = client.post("/api/videos/2/tags", headers=demo, json=bad)
    assert r.status_code == 422 and "detail" in r.json()


def test_tag_catalog_endpoints(client, demo):
    tags = client.get("/api/tags", headers=demo).json()
    names = [t["key"] for t in tags]
    assert names == sorted(names, key=str.lower) and {"Pitch", "Weather", "Home/Away"} <= set(names)  # display case
    weather = next(t for t in tags if t["key"] == "Weather")
    counts = {v["value"]: v["count"] for v in weather["values"]}
    assert counts["Rainy"] == 3 and counts["Sunny"] == 3
    keys = {k["key"]: k for k in client.get("/api/tags/keys", headers=demo).json()}
    assert keys["Weather"]["match_count"] == 6 and keys["Weather"]["value_count"] >= 2
    vals = client.get("/api/tags/values?key=weather", headers=demo).json()
    assert {v["value"] for v in vals} >= {"Rainy", "Sunny"} and all(v["key"] == "Weather" for v in vals)
    assert client.get("/api/tags/values?key=weather&q=ra", headers=demo).json()[0]["value"] == "Rainy"
    assert client.get("/api/tags/values?key=nosuch", headers=demo).json() == []
    assert client.get("/api/tags").status_code == 401


def test_tags_are_user_isolated(client, demo, zed):
    assert client.get("/api/videos/2/tags", headers=zed).status_code == 404
    assert client.post("/api/videos/2/tags", headers=zed, json={"tags": [{"key": "x", "value": "y"}]}).status_code == 404
    assert client.put("/api/matches/3/tags", headers=zed, json={"tags": []}).status_code == 404
    v = upload(client, zed, data={**FORM, "tags": json.dumps([{"key": "weather", "value": "Rainy"}])}).json()
    assert v["tags"] == [{"key": "weather", "value": "Rainy"}]
    zed_tags = client.get("/api/tags", headers=zed).json()
    assert zed_tags == [{"key": "weather", "values": [{"value": "Rainy", "count": 1}]}]
    with SessionLocal() as db:  # separate key rows per user
        assert db.query(TagKey).filter(func.lower(TagKey.name) == "weather").count() == 2
    assert all(v["id"] != 2 for v in client.get("/api/videos?tag=weather:Rainy", headers=zed).json())


def test_upload_tags_field_and_our_side(client, zed):
    r = upload(client, zed, data={**FORM, "match_date": "2026-12-21", "our_side": "away",
                                  "tags": '{"tags": [{"key": "pitch", "value": "Turf"}]}'})
    assert r.status_code == 202 and r.json()["tags"] == [{"key": "pitch", "value": "Turf"}]
    m = client.get(f"/api/matches/{r.json()['match_id']}", headers=zed).json()
    assert m["our_side"] == "away" and m["our_team"] == "Zed Rivals"
    for bad in ("not json", '[{"key": "k"}]', '{"tags": 5}'):
        assert upload(client, zed, data={**FORM, "tags": bad}).status_code == 422
    assert upload(client, zed, data={**FORM, "our_side": "left"}).status_code == 422
    assert upload(client, zed, data={**FORM, "tags": ""}).status_code == 202


def test_video_tag_filter_and(client, demo):
    ids = lambda q: {v["id"] for v in client.get(f"/api/videos?{q}", headers=demo).json()}  # noqa: E731
    assert ids("tag=weather:Rainy") == {2, 4}                  # matches 3, 5 (match 2 has no video)
    assert ids("tag=weather:rainy&tag=pitch:Turf") == {4}       # AND
    assert ids("tag=weather:Snow") == set()
    assert ids("tag=weather:Rainy&tag=Weather:sunny") == {1, 2, 3, 4, 5}   # same key (any case) = OR
    assert ids("tag=weather:Rainy&tag=weather:Sunny&tag=pitch:Turf") == {3, 4}
    assert client.get("/api/videos?tag=weather", headers=demo).status_code == 422
    ms = {m["match_id"] for m in client.get("/api/matches?tag=weather:Rainy", headers=demo).json()}
    assert ms == {2, 3, 5}


# ============================================================== matches / results
def test_match_objects_and_patch(client, demo, zed):
    ms = {m["match_id"]: m for m in client.get("/api/matches", headers=demo).json()}
    assert ms[2]["result"] == "W" and ms[2]["our_side"] == "away" and ms[2]["our_team"] == "Capstone FC"
    assert ms[5]["result"] == "L" and ms[4]["result"] == "D" and ms[7]["result"] is None
    assert set(ms[1]) == {"match_id", "match_date", "home_team", "away_team", "home_team_id", "away_team_id",
                          "video_count", "home_score", "away_score", "our_side", "our_team", "opponent", "result",
                          "created_at", "tags"}
    v1 = client.get("/api/videos/1", headers=demo).json()
    assert v1["match"]["home_score"] == 3 and v1["match"]["result"] == "W"

    p = lambda body: client.patch("/api/matches/7", headers=demo, json=body)  # noqa: E731
    r = p({"home_score": 1, "away_score": 3})
    assert r.status_code == 200 and r.json()["result"] == "L"
    assert p({"our_side": "away"}).json()["result"] == "W"                         # flips with our_side
    assert p({"home_score": 2}).status_code == 200 and p({}).status_code == 422
    assert p({"home_score": 2, "away_score": 2, "result": "W"}).status_code == 422  # contradicts score
    assert p({"home_score": 2, "away_score": None}).status_code == 422             # pairs only
    cleared = p({"home_score": None, "away_score": None})
    assert cleared.json()["result"] is None and cleared.json()["home_score"] is None
    assert p({"result": "D"}).json()["result"] == "D"                              # manual, no score
    assert p({"home_score": -1, "away_score": 0}).status_code == 422
    assert p({"our_side": None}).status_code == 422
    assert client.patch("/api/matches/7", headers=zed, json={"result": "W"}).status_code == 404
    assert client.get("/api/matches/7", headers=zed).status_code == 404
    assert client.get("/api/matches/99999", headers=demo).status_code == 404
    p({"result": None, "our_side": "home"})


# ============================================================== insights
def test_insights_weather(client, demo):
    r = client.get("/api/insights/tags?key=weather", headers=demo)
    assert r.status_code == 200
    b = r.json()
    assert b["key"] == "weather" and b["scope"] == "our_team"
    assert b["baseline"]["matches"] == 7 and b["baseline"]["matches_with_data"] == 6
    assert b["baseline"]["wdl"] == {"w": 4, "d": 1, "l": 1, "unknown": 1}
    g = {x["value"]: x for x in b["groups"]}
    assert set(g) == {"Rainy", "Sunny"}
    rainy, sunny = g["Rainy"], g["Sunny"]
    assert rainy["matches"] == 3 and rainy["match_ids"] == [3, 5, 2]
    assert rainy["wdl"] == {"w": 2, "d": 0, "l": 1, "unknown": 0}
    assert sunny["wdl"] == {"w": 2, "d": 1, "l": 0, "unknown": 0}
    assert rainy["next_match"]["match_ids"] == [4, 1, 7]
    assert rainy["next_match"]["wdl"] == {"w": 1, "d": 1, "l": 0, "unknown": 1}
    assert rainy["next_match"]["matches_with_data"] == 2 and rainy["next_match"]["low_sample"] is True
    assert sunny["next_match"]["match_ids"] == [5, 6, 2]
    for grp in (rainy, sunny):
        assert 1 <= grp["avg_workload"] <= 3 and grp["avg_distance_km"] > 0 and grp["avg_sprints"] > 0
        assert grp["avg_distance_km"] == grp["metrics"]["distance_km"]
        assert sum(grp["injury_risk"].values()) > 0
    # rainy matches are lower-distance in the seed data
    assert rainy["avg_distance_km"] < sunny["avg_distance_km"]
    eff = [e for e in b["next_match_effect"] if e["value"] == "Rainy" and e["metric_key"] == "distance_km"][0]
    assert eff["metric"] == "distance" and eff["next"] == eff["next_avg"] and eff["pairs"] == 2
    assert {e["metric"] for e in b["next_match_effect"]} == {"distance", "speed", "sprints", "hsr", "workload"}
    assert rainy["workload"] == {k.lower(): v for k, v in rainy["injury_risk"].items()}
    assert b["baseline"]["avg_distance_km"] == b["baseline"]["metrics"]["distance_km"]
    assert {"avg_top_speed_mph", "avg_sprints", "avg_workload", "workload"} <= set(b["baseline"])
    assert eff["n"] == 2 and eff["change_pct"] is not None
    assert set(eff) == {"value", "metric", "metric_key", "change_pct", "delta", "next", "next_avg", "baseline", "n",
                        "pairs", "low_sample"}


def upload_queued(client, headers):
    import routers.videos as rv
    orig = rv.process_video
    rv.process_video = lambda vid: None
    try:
        return upload(client, headers).json()["id"]
    finally:
        rv.process_video = orig


def test_insights_alias_filters_and_errors(client, demo, zed):
    a = client.get("/api/insights?tag_key=weather", headers=demo).json()
    b = client.get("/api/insights/tags?key=weather", headers=demo).json()
    assert a == b
    assert client.get("/api/insights", headers=demo).status_code == 422
    assert client.get("/api/insights/tags", headers=demo).status_code == 422
    assert client.get("/api/insights?tag_key=nosuch", headers=demo).json()["groups"] == []
    one = client.get("/api/insights?tag_key=weather&player_id=21", headers=demo).json()
    assert one["scope"] == "player"
    rainy = next(x for x in one["groups"] if x["value"] == "Rainy")
    assert rainy["matches_with_data"] == 1 and rainy["avg_distance_km"] == 2.4    # only match 2 (legacy row)
    assert rainy["low_sample"] is True
    team2 = client.get("/api/insights?tag_key=weather&team_id=2", headers=demo).json()
    assert team2["scope"] == "team" and team2["baseline"]["matches"] == 2
    assert client.get("/api/insights?tag_key=weather&player_id=21", headers=zed).status_code == 404
    assert client.get("/api/insights?tag_key=weather&team_id=1", headers=zed).status_code == 404
    yan = register_and_login(client, "yan@example.com")
    assert client.put(f"/api/videos/{upload_queued(client, yan)}/tags", headers=yan,
                      json={"tags": [{"key": "weather", "value": "Dry"}]}).status_code == 200
    empty = client.get("/api/insights?tag_key=weather", headers=yan).json()   # tags but no stats yet
    assert empty["baseline"]["metrics"]["distance_km"] is None
    assert [gr["value"] for gr in empty["groups"]] == ["Dry"]
    assert all(gr["avg_distance_km"] is None and gr["matches_with_data"] == 0 and gr["avg_workload"] is None
               for gr in empty["groups"])
    assert client.get("/api/insights?tag_key=weather").status_code == 401
