"""CV pipeline v1.2.0 fields: per-track metrics, heatmaps.json, zone edges / threshold preset in meta.json."""
import json

import pytest

import metrics_catalog as mc
import pipeline
from conftest import FAKE_MP4, register_and_login
from database import SessionLocal
from models import PlayerHeatmap, PlayerMatchStat

FORM = {"title": "v120", "match_date": "2026-12-01", "home_team": "V Home", "away_team": "V Away"}
META = {"pipeline_version": "1.2.0", "fps": 25.0, "frame_count": 15000, "duration_s": 600.0, "width": 1920,
        "height": 1080, "calibration": "/somewhere/my_calibration.json", "warnings": [],
        "speed_preset": "gps_standard", "hsr_threshold_kmh": 19.8, "sprint_threshold_kmh": 25.3,
        "zone_edges_kmh": {"walk": 7.0, "jog": 15.0, "run": 20.0, "hsr": 25.0}}


def grid(fill_cell=None, value=1.0, cols=21, rows=14):
    g = [[0.0] * cols for _ in range(rows)]
    if fill_cell:
        g[fill_cell[0]][fill_cell[1]] = value
    return g


def stat(tid, jersey, team=0, role="player", **kw):
    base = {"track_id": tid, "jersey_number": jersey, "team": team, "role": role, "injury_risk": "Low",
            "top_speed_mph": 18.0, "top_speed_kmh": 28.97, "distance_km": 1.0, "minutes_played": 4.0,
            "visible_minutes": 3.0, "coverage_pct": 30.0, "distance_per_min_m": 333.33, "avg_pitch_x": 20.0,
            "avg_pitch_y": 10.0, "high_speed_distance_km": 0.1, "sprint_distance_km": 0.05, "hsr_count": 3,
            "sprint_count": 2, "hi_efforts_count": 5, "zone_walk_km": 0.3, "zone_jog_km": 0.3, "zone_run_km": 0.2,
            "zone_hsr_km": 0.1, "zone_sprint_km": 0.1, "accel_count_high": 4, "decel_count_high": 1}
    base.update(kw)
    return base


def dets(tid, jersey, n=10, x=20.0, y=10.0, team=0, role="player"):
    return [{"frame": f, "timestamp": f / 25, "track_id": tid, "class": "player", "team": team, "role": role,
             "jersey_number": jersey, "bbox_x1": 1, "bbox_y1": 1, "bbox_x2": 2, "bbox_y2": 2, "confidence": 0.9,
             "pitch_x": x, "pitch_y": y} for f in range(n)]


@pytest.fixture(scope="module")
def vuser(client):
    return register_and_login(client, "v120@example.com")


def run(client, headers, monkeypatch, out):
    monkeypatch.setattr(pipeline, "run_pipeline", lambda video: out)
    v = client.post("/api/videos", headers=headers, data=FORM,
                    files={"file": ("clip.mp4", FAKE_MP4, "video/mp4")}).json()
    d = client.get(f"/api/videos/{v['id']}", headers=headers).json()
    assert d["status"] == "done", d["error_message"]
    stats = client.get(f"/api/videos/{v['id']}/stats?include=metrics", headers=headers).json()
    return v["id"], d, stats


def test_v120_mapping_and_fragment_merge(client, vuser, monkeypatch):
    stats_in = [
        stat(1, 7),                                                        # two fragments of #7 -> one player
        stat(2, 7, top_speed_mph=20.0, top_speed_kmh=32.19, distance_km=2.0, minutes_played=5.0, visible_minutes=5.0,
             coverage_pct=50.0, avg_pitch_x=60.0, avg_pitch_y=30.0, hsr_count=1, sprint_count=1, hi_efforts_count=2,
             accel_count_high=2, decel_count_high=2, zone_walk_km=0.5, player_uid="p-abc", future_metric=1.5),
        stat(3, 9, team=1, coverage_pct=80.0),
        stat(4, None, team=None, role="referee"),
    ]
    heat = {"1": grid((2, 4), 3.0), "2": grid((6, 12), 5.0), "3": grid((13, 20), 2.0), "4": grid((7, 10), 9.0)}
    out = pipeline.PipelineOutput(detections=dets(1, 7) + dets(2, 7, x=60, y=30) + dets(3, 9, team=1)
                                  + dets(4, None, team=None, role="referee"),
                                  player_stats=stats_in, source="real", meta=dict(META), heatmaps=heat)
    vid, detail, stats = run(client, vuser, monkeypatch, out)
    meta = detail["pipeline_meta"]
    assert meta["zone_edges_kmh"] == META["zone_edges_kmh"] and meta["speed_preset"] == "gps_standard"
    assert meta["adapter_metrics"]["heatmap_grid"] == "pipeline"
    assert meta["adapter_metrics"]["sources"]["minutes_played"] == {"pipeline": 2}
    assert meta["adapter_metrics"]["speed_thresholds"]["hsr_kmh"] == 19.8
    unknown = [w for w in meta["warnings"] if "Unknown per-player keys" in w]
    assert len(unknown) == 1 and "future_metric" in unknown[0] and "player_uid" not in unknown[0]
    assert not any("hsr_count" in w or "zone_walk_km" in w for w in meta["warnings"])

    assert len(stats) == 2                                                  # referee skipped
    p7 = next(r for r in stats if r["distance_km"] == 3.0)
    m = p7["metrics"]
    assert p7["top_speed_mph"] == 20.0 and m["top_speed_kmh"] == 32.2 and p7["top_speed_kmh"] == 32.2
    assert p7["minutes_played"] == 9.0 and p7["visible_minutes"] == 8.0 and p7["coverage_pct"] == 80.0
    assert p7["distance_per_min"] == 375.0                                  # 3 km / 8 tracked min
    assert p7["hsr_count"] == 4 and p7["sprint_count"] == 3 and p7["high_intensity_efforts"] == 7   # not doubled
    assert p7["accels"] == 6 and p7["decels"] == 3
    assert p7["speed_zones"] == {"walk": 0.8, "jog": 0.6, "run": 0.4, "hsr": 0.2, "sprint": 0.2}
    # position weighted by tracked minutes: (20*3 + 60*5) / 8 = 45, (10*3 + 30*5) / 8 = 22.5
    assert p7["avg_position"] == {"x": 45.0, "y": 22.5}
    assert p7["speed_thresholds"] == {"preset": "gps_standard", "hsr_kmh": 19.8, "sprint_kmh": 25.3,
                                      "zone_edges_kmh": META["zone_edges_kmh"], "source": "pipeline"}
    hm = p7["heatmap"]
    assert (hm["cols"], hm["rows"], hm["source"], hm["cell_unit"]) == (21, 14, "pipeline", "seconds")
    assert hm["cells"][2 * 21 + 4] == 0.6 and hm["cells"][6 * 21 + 12] == 1.0 and hm["samples"] == 20
    body = client.get(f"/api/videos/{vid}/heatmap", headers=vuser).json()
    assert body["grid"]["cols"] == 21 and body["grid"]["source"] == "pipeline"
    pl = next(p for p in body["players"] if p["samples"] == 20)
    assert pl["counts"][6][12] == 5.0 and pl["counts"][2][4] == 3.0      # seconds, summed over fragments
    p9 = next(r for r in stats if r is not p7)
    assert p9["coverage_pct"] == 80.0 and p9["distance_per_min"] == 333


def test_v120_without_calibration(client, vuser, monkeypatch):
    phys = ["top_speed_mph", "top_speed_kmh", "distance_km", "minutes_played", "visible_minutes",
            "distance_per_min_m", "avg_pitch_x", "avg_pitch_y", "high_speed_distance_km", "sprint_distance_km",
            "hsr_count", "sprint_count", "hi_efforts_count", "zone_walk_km", "zone_jog_km", "zone_run_km",
            "zone_hsr_km", "zone_sprint_km", "accel_count_high", "decel_count_high", "coverage_pct"]
    s = stat(1, 5, **{k: None for k in phys})
    d = dets(1, 5)
    for x in d:
        x["pitch_x"] = x["pitch_y"] = None
    meta = {**META, "calibration": None}
    out = pipeline.PipelineOutput(detections=d, player_stats=[s], source="real", meta=meta, heatmaps={})
    vid, detail, stats = run(client, vuser, monkeypatch, out)
    r = stats[0]
    assert r["top_speed_mph"] is None and r["distance_km"] is None and r["top_speed_kmh"] is None
    for k in ("visible_minutes", "coverage_pct", "distance_per_min", "hsr_count", "sprint_count", "accels",
              "decels", "high_intensity_efforts"):
        assert r[k] is None, k
    assert r["minutes_played"] is None          # v0.7.0: pipeline gave null -> stays null (never the clip length)
    assert r["speed_zones"] is None and r["avg_position"] is None and r["heatmap"] is None
    assert detail["pipeline_meta"]["adapter_metrics"]["heatmap_grid"] is None
    assert detail["pipeline_meta"]["adapter_metrics"]["sources"]["minutes_played"] == {}


def test_bad_heatmap_grid_falls_back_to_backend(client, vuser, monkeypatch):
    out = pipeline.PipelineOutput(detections=dets(1, 3) + dets(2, 4, x=80), source="real", meta=dict(META),
                                  player_stats=[stat(1, 3), stat(2, 4)],
                                  heatmaps={"1": grid((0, 0), 1.0), "2": [[1, 2], [3]]})   # ragged -> invalid
    vid, detail, stats = run(client, vuser, monkeypatch, out)
    by_src = sorted(r["heatmap"]["source"] for r in stats)
    assert by_src == ["backend", "pipeline"]
    assert detail["pipeline_meta"]["adapter_metrics"]["heatmap_grid"] == "mixed"
    assert any("used backend heatmaps" in w for w in detail["pipeline_meta"]["warnings"])
    backend = next(r for r in stats if r["heatmap"]["source"] == "backend")
    assert (backend["heatmap"]["cols"], backend["heatmap"]["rows"]) == (12, 8)


def test_read_heatmaps_file(tmp_path):
    assert pipeline._read_heatmaps(tmp_path) == ({}, None)
    (tmp_path / "heatmaps.json").write_text("{nope")
    hm, w = pipeline._read_heatmaps(tmp_path)
    assert hm == {} and "not valid JSON" in w
    (tmp_path / "heatmaps.json").write_text(json.dumps({1: grid()}))
    hm, w = pipeline._read_heatmaps(tmp_path)
    assert list(hm) == ["1"] and w is None
    assert mc.valid_grid(hm["1"]) == (21, 14) and mc.valid_grid([[1, -1]]) is None and mc.valid_grid([]) is None


def test_stub_emits_v120_shape(client, vuser):
    v = client.post("/api/videos", headers=vuser, data={**FORM, "home_team": "Stub H", "away_team": "Stub A"},
                    files={"file": ("clip.mp4", FAKE_MP4, "video/mp4")}).json()
    stats = client.get(f"/api/videos/{v['id']}/stats", headers=vuser).json()
    assert stats and all(r["heatmap"]["source"] == "pipeline" and r["heatmap"]["cols"] == 21 for r in stats)
    assert all(r["speed_zones"] and r["hsr_count"] is not None and r["accels"] is not None for r in stats)
    assert stats[0]["speed_thresholds"]["preset"] == "gps_standard"
    with SessionLocal() as db:
        ids = [s.stat_id for s in db.query(PlayerMatchStat).filter_by(video_id=v["id"])]
        assert {h.cell_unit for h in db.query(PlayerHeatmap).filter(PlayerHeatmap.stat_id.in_(ids))} == {"seconds"}


def test_single_track_keeps_pipeline_distance_per_min(client, vuser, monkeypatch):
    # pipeline rounds distance_km / visible_minutes to 2 dp; its own distance_per_min_m is more precise
    s = stat(1, 11, distance_km=0.03, minutes_played=0.1, visible_minutes=0.1, distance_per_min_m=288.7)
    out = pipeline.PipelineOutput(detections=dets(1, 11), player_stats=[s], source="real", meta=dict(META),
                                  heatmaps={"1": grid((0, 0), 1.0)})
    vid, detail, stats = run(client, vuser, monkeypatch, out)
    assert stats[0]["distance_per_min"] == 289 and stats[0]["metrics"]["distance_per_min"] == 289   # not 300
    assert mc.aggregate([{"distance_km": 0.03, "visible_minutes": 0.1, "distance_per_min": 288.7},
                         {"distance_km": 0.03, "visible_minutes": 0.1, "distance_per_min": 288.7}]
                        )["distance_per_min"] == 300   # several rows: ratio of sums
