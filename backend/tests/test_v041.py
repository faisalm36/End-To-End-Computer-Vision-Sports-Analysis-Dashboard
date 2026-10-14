"""v0.4.1: safe distance_per_min (stub + real mapping + read path), speed-threshold defaults, tag cleanup on
video delete, PATCH /api/videos/{id}/players/{player_id}, PR #2 output tolerance, allowed extensions."""
import json
import shutil
import subprocess

import pytest

import metrics_catalog as mc
import pipeline
from config import Settings, settings
from conftest import FAKE_MP4, register_and_login
from database import SessionLocal
from models import MatchTag, MatchVideo, Player, PlayerMatchMetric, PlayerMatchStat, VideoPlayerOverride

FORM = {"title": "v041", "match_date": "2027-01-15"}
DEFAULTS = {**mc.DEFAULT_SPEED_THRESHOLDS, "source": "default"}


@pytest.fixture(scope="module")
def ana(client):
    return register_and_login(client, "ana.v041@example.com", first="Ana", last="V")


@pytest.fixture(scope="module")
def bob(client):
    return register_and_login(client, "bob.v041@example.com", first="Bob", last="V")


def upload(client, h, home, away, data=None, name="clip.mp4", body=FAKE_MP4, ctype="video/mp4"):
    r = client.post("/api/videos", headers=h, data={**FORM, "home_team": home, "away_team": away, **(data or {})},
                    files={"file": (name, body, ctype)})
    assert r.status_code == 202, r.text
    return r.json()


def ffmpeg_clip(tmp_root, name, seconds, fmt_args=()):
    if not shutil.which("ffmpeg"):
        pytest.skip("ffmpeg not installed")
    out = tmp_root / name
    subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-f", "lavfi", "-i",
                    f"testsrc=duration={seconds}:size=160x120:rate=10", *fmt_args, str(out)], check=True)
    return out.read_bytes()


# ------------------------------------------------------------------ 1. minutes_played / distance_per_min
def test_stub_one_second_clip_has_minutes_and_no_absurd_rate(client, ana):
    v = upload(client, ana, "Short H", "Short A")
    detail = client.get(f"/api/videos/{v['id']}", headers=ana).json()
    meta = detail["pipeline_meta"]
    assert meta["duration_s"] == 1.0 and any("clip length unknown" in w for w in meta["warnings"])
    rows = client.get(f"/api/videos/{v['id']}/stats?include=metrics", headers=ana).json()
    assert rows
    for r in rows:
        assert 0 < r["minutes_played"] <= 0.02 and 0 < r["visible_minutes"] <= 0.02        # 1 s, 2 decimals
        assert r["distance_per_min"] is None and r["metrics"]["distance_per_min"] is None   # < 0.1 min
        assert r["distance_km"] is not None and r["distance_km"] < 0.01                     # ~2 m, not 7 km
    raw = json.loads((settings.CV_OUTPUT_DIR / f"video_{v['id']}" / "player_match_stats.json").read_text())
    players = [s for s in raw if s["role"] == "player"]
    assert all(s["distance_per_min_m"] is None and s["minutes_played_s"] > 0 and "distance_m" in s for s in players)


def test_stub_uses_real_clip_duration(client, ana, tmp_root):
    body = ffmpeg_clip(tmp_root, "twelve.mp4", 12, ("-pix_fmt", "yuv420p"))
    v = upload(client, ana, "Long H", "Long A", body=body)
    meta = client.get(f"/api/videos/{v['id']}", headers=ana).json()["pipeline_meta"]
    assert meta["duration_s"] == pytest.approx(12.0, abs=0.2) and meta["fps"] == pytest.approx(10.0)
    assert not any("clip length unknown" in w for w in meta["warnings"])
    rows = client.get(f"/api/videos/{v['id']}/stats", headers=ana).json()
    rates = [r["distance_per_min"] for r in rows if r["distance_per_min"] is not None]
    assert rates and all(60 <= x <= 150 for x in rates)                 # plausible m/min
    for r in rows:
        assert r["minutes_played"] <= 0.2 + 1e-9 and r["visible_minutes"] <= 0.2 + 1e-9
        if r["visible_minutes"] < mc.MIN_RATE_MINUTES:
            assert r["distance_per_min"] is None


def _run(client, h, monkeypatch, out, home="Map H", away="Map A"):
    monkeypatch.setattr(pipeline, "run_pipeline", lambda video: out)
    v = upload(client, h, home, away)
    d = client.get(f"/api/videos/{v['id']}", headers=h).json()
    assert d["status"] == "done", d["error_message"]
    return v["id"], d, client.get(f"/api/videos/{v['id']}/stats?include=metrics", headers=h).json()


def _dets(tid, jersey, team=0, n=4):
    return [{"frame": f, "timestamp": f / 30, "track_id": tid, "class": "player", "team": team, "role": "player",
             "jersey_number": jersey, "bbox_x1": 1, "bbox_y1": 1, "bbox_x2": 2, "bbox_y2": 2, "confidence": 0.9,
             "pitch_x": 30.0, "pitch_y": 20.0} for f in range(n)]


def test_real_mapping_never_divides_by_tiny_minutes(client, ana, monkeypatch):
    meta = {"pipeline_version": "1.2.0", "fps": 30.0, "frame_count": 30, "duration_s": 1.0, "calibration": None}
    stats = [  # the v0.4.0 bug: 7.3 km on a 1 s clip, minutes 0 / missing -> 438,000 m/min
        {"track_id": 1, "jersey_number": 4, "team": 0, "role": "player", "top_speed_mph": 18.0, "distance_km": 7.3,
         "injury_risk": "Low", "minutes_played": 0, "visible_minutes": 0.0167, "distance_per_min_m": 438000.0},
        {"track_id": 2, "jersey_number": 5, "team": 0, "role": "player", "top_speed_mph": 18.0, "distance_km": 7.3,
         "injury_risk": "Low"},                                            # no minutes -> null
    ]
    out = pipeline.PipelineOutput(detections=_dets(1, 4) + _dets(2, 5), player_stats=stats, source="real", meta=meta)
    _, _, rows = _run(client, ana, monkeypatch, out)
    assert len(rows) == 2 and all(r["distance_per_min"] is None for r in rows)
    # 0 stays 0 (not "missing"); absent stays null (v0.7.0: never the clip length)
    assert sorted(r["minutes_played"] for r in rows if r["minutes_played"] is not None) == [0.0]
    assert sum(r["minutes_played"] is None for r in rows) == 1


def test_pr2_seconds_metres_empty_heatmaps_and_team_letters(client, ana, monkeypatch):
    meta = {"pipeline_version": "2.0.0", "fps": 30.0, "frame_count": 18000, "duration_s": 600.0, "calibration": None,
            "warnings": [], "speed_preset": "gps_standard", "hsr_threshold_kmh": 19.8, "sprint_threshold_kmh": 25.3,
            "zone_edges_kmh": {"walk": 7.0, "jog": 15.0, "run": 19.79488, "hsr": 25.266638}}
    pr2 = {"player_uid": 1, "contributing_track_ids": [1], "detected_frames": 180, "total_frames": 190}
    stats = [  # two fragments of #9 (team "A"): rounded km/min would give 0.06 km / 0.2 min = 300 m/min
        {"track_id": 1, "jersey_number": 9, "team": "A", "role": "player", "top_speed_mph": 17.0, "distance_km": 0.03,
         "distance_m": 31.4, "minutes_played": 0.1, "minutes_played_s": 6.4, "visible_minutes": 0.1,
         "visible_minutes_s": 6.0, "distance_per_min_m": 314.0, "injury_risk": "Low", **pr2},
        {"track_id": 2, "jersey_number": 9, "team": "A", "role": "player", "top_speed_mph": 18.0, "distance_km": 0.03,
         "distance_m": 28.6, "minutes_played": 0.1, "minutes_played_s": 6.2, "visible_minutes": 0.1,
         "visible_minutes_s": 6.0, "distance_per_min_m": 286.0, "injury_risk": "Low", **pr2},
        # no calibration on this one: PR #2 nulls distance_km but may keep distance_m -> no rate
        {"track_id": 3, "jersey_number": 10, "team": "B", "role": "player", "top_speed_mph": None,
         "distance_km": None, "distance_m": 55.0, "minutes_played_s": 600.0, "visible_minutes_s": 540.0,
         "injury_risk": "Low", **pr2},
    ]
    out = pipeline.PipelineOutput(detections=_dets(1, 9) + _dets(2, 9) + _dets(3, 10, team=1), player_stats=stats,
                                  source="real", meta=meta, heatmaps={})        # PR #2 writes {} without calibration
    vid, detail, rows = _run(client, ana, monkeypatch, out)
    by_min = {r["minutes_played"]: r for r in rows}
    nine, ten = by_min[round(12.6 / 60, 2)], by_min[10.0]
    assert nine["visible_minutes"] == 0.2 and nine["distance_per_min"] == 300   # (31.4+28.6) m / 12 s * 60
    assert ten["distance_per_min"] is None and ten["visible_minutes"] == 9.0
    assert all(r["heatmap"]["source"] == "backend" for r in rows)
    pm = detail["pipeline_meta"]
    assert not any("heatmaps.json" in w or "Unknown per-player keys" in w for w in pm["warnings"]), pm["warnings"]
    assert nine["speed_thresholds"]["zone_edges_kmh"] == {"walk": 7.0, "jog": 15.0, "run": 19.8, "hsr": 25.3}
    with SessionLocal() as db:   # team "A" -> home, "B" -> away
        pids = {r["player_id"]: db.get(Player, r["player_id"]).team_id for r in rows}
        v = db.get(MatchVideo, vid)
        assert set(pids.values()) == {v.match.home_team_id, v.match.away_team_id}


def test_aggregate_floor_also_fixes_rows_stored_before_041():
    agg = lambda rows: mc.aggregate(rows, ["distance_per_min"])["distance_per_min"]  # noqa: E731
    assert agg([{"distance_km": 7.3, "minutes_played": 0.0167, "distance_per_min": 438000.0}]) is None
    assert agg([{"distance_km": 7.3, "visible_minutes": 0.0, "minutes_played": 0.0, "distance_per_min": 5.0}]) is None
    assert agg([{"distance_km": 1.0, "minutes_played": 0.04}, {"distance_km": 1.0, "minutes_played": 0.05}]) is None
    assert agg([{"distance_km": 1.0, "minutes_played": 5.0}, {"distance_km": 1.0, "minutes_played": 5.0}]) == 200
    assert agg([{"distance_km": 1.0, "distance_per_min": 123.0}]) == 123          # minutes unknown: stored value
    assert pipeline.distance_per_min(1.0, 0.0999) is None and pipeline.distance_per_min(1.0, 0.1) == 10000
    assert pipeline.distance_per_min(None, 5) is None and pipeline.distance_per_min(1.0, None) is None


def test_old_stored_absurd_rate_is_hidden_by_the_api(client, ana):
    v = upload(client, ana, "Old H", "Old A")
    with SessionLocal() as db:   # simulate a v0.4.0 row: 438,000 m/min with minutes_played 1 s
        sid = db.query(PlayerMatchStat).filter_by(video_id=v["id"]).first().stat_id
        for key, val in (("distance_per_min", 438000.0), ("minutes_played", 0.0167), ("visible_minutes", None)):
            db.query(PlayerMatchMetric).filter_by(stat_id=sid, metric_key=key).update({"value": val})
        db.commit()
    rows = client.get(f"/api/videos/{v['id']}/stats", headers=ana).json()
    assert all(r["distance_per_min"] is None for r in rows)


# ------------------------------------------------------------------ 2. speed thresholds
def test_seed_and_stub_meta_carry_thresholds(client, ana):
    demo = client.post("/api/auth/login", json={"email": "faisal@example.com", "password": "capstone123"}).json()
    h = {"Authorization": f"Bearer {demo['access_token']}"}
    for vid in (1, 2):
        rows = client.get(f"/api/videos/{vid}/stats", headers=h).json()
        assert rows[0]["speed_thresholds"] == {**mc.DEFAULT_SPEED_THRESHOLDS, "source": "pipeline"}
    v = upload(client, ana, "Thr H", "Thr A")
    meta = client.get(f"/api/videos/{v['id']}", headers=ana).json()["pipeline_meta"]
    assert (meta["hsr_threshold_kmh"], meta["sprint_threshold_kmh"]) == (19.8, 25.3)
    assert meta["zone_edges_kmh"] == mc.DEFAULT_SPEED_THRESHOLDS["zone_edges_kmh"]


@pytest.mark.parametrize("meta,expected", [
    ('{"adapter_source": "seed", "warnings": []}', DEFAULTS),                          # pre-0.4.1 seeded row
    (None, DEFAULTS),
    ('not json', DEFAULTS),
    ('{"hsr_threshold_kmh": 20.0}', {**DEFAULTS, "hsr_kmh": 20.0, "source": "mixed"}),
])
def test_thresholds_fall_back_to_defaults(client, ana, meta, expected):
    v = upload(client, ana, "Fallback H", "Fallback A")
    with SessionLocal() as db:
        db.get(MatchVideo, v["id"]).pipeline_meta = meta
        db.commit()
    rows = client.get(f"/api/videos/{v['id']}/stats", headers=ana).json()
    assert rows and all(r["speed_thresholds"] == expected for r in rows)


# ------------------------------------------------------------------ 3. tags when a video is deleted
def _match_tags(client, h, match_id):
    r = client.get(f"/api/matches/{match_id}/tags", headers=h)
    return r.status_code, r.json()


def test_deleting_the_only_video_removes_the_match_tags(client, ana):
    v = upload(client, ana, "Tag H", "Tag A", data={"tags": json.dumps([{"key": "Weather", "value": "Sunny"}])})
    mid = v["match_id"]
    assert _match_tags(client, ana, mid) == (200, [{"key": "Weather", "value": "Sunny"}])
    assert client.delete(f"/api/videos/{v['id']}", headers=ana).status_code == 204
    status, tags = _match_tags(client, ana, mid)
    assert status == 200 and tags == []                            # the match itself is kept (no orphan cleanup)
    with SessionLocal() as db:
        assert db.query(MatchTag).filter_by(match_id=mid).count() == 0
    # the tag key/value stay in the user's vocabulary for autocomplete
    assert "Sunny" in json.dumps(client.get("/api/tags", headers=ana).json())


def test_tags_stay_while_other_videos_remain(client, ana):
    a = upload(client, ana, "Two H", "Two A", data={"tags": json.dumps([{"key": "Pitch", "value": "Turf"}])})
    b = upload(client, ana, "x", "y", data={"match_id": str(a["match_id"])})
    assert b["match_id"] == a["match_id"]
    assert client.delete(f"/api/videos/{a['id']}", headers=ana).status_code == 204
    assert _match_tags(client, ana, a["match_id"])[1] == [{"key": "Pitch", "value": "Turf"}]
    assert client.delete(f"/api/videos/{b['id']}", headers=ana).status_code == 204
    assert _match_tags(client, ana, a["match_id"])[1] == []


def test_tags_stay_when_the_match_has_legacy_stats(client):
    demo = client.post("/api/auth/login", json={"email": "faisal@example.com", "password": "capstone123"}).json()
    h = {"Authorization": f"Bearer {demo['access_token']}"}
    before = _match_tags(client, h, 2)[1]                          # seeded match 2: legacy stats, no video
    assert before
    v = upload(client, h, "x", "y", data={"match_id": "2"})
    assert client.delete(f"/api/videos/{v['id']}", headers=h).status_code == 204
    assert _match_tags(client, h, 2)[1] == before


# ------------------------------------------------------------------ 4. PATCH /api/videos/{id}/players/{player_id}
def test_patch_video_player_jersey(client, ana, bob):
    v = upload(client, ana, "Patch H", "Patch A")
    url = f"/api/videos/{v['id']}"
    rows = client.get(f"{url}/stats", headers=ana).json()
    p1, p2 = rows[0]["player_id"], rows[1]["player_id"]
    with SessionLocal() as db:
        roster_before = db.get(Player, p1).jersey_number
    r = client.patch(f"{url}/players/{p1}", headers=ana, json={"jersey_number": 42})
    assert r.status_code == 200, r.text
    row = r.json()
    assert row["jersey_number"] == 42 and set(row) == set(rows[0])        # same shape as GET .../stats rows
    assert {k: row[k] for k in row if k != "jersey_number"} == {k: rows[0][k] for k in row if k != "jersey_number"}
    assert next(x for x in client.get(f"{url}/stats", headers=ana).json() if x["player_id"] == p1)["jersey_number"] == 42
    with SessionLocal() as db:
        assert db.get(Player, p1).jersey_number == roster_before            # roster untouched (per-video override)
    # one number per team per video
    clash = client.patch(f"{url}/players/{p2}", headers=ana, json={"jersey_number": 42})
    assert clash.status_code == 409 and "#42" in clash.json()["detail"]
    # null = "no number in this video"; then the number is free again
    r = client.patch(f"{url}/players/{p1}", headers=ana, json={"jersey_number": None})
    assert r.status_code == 200 and r.json()["jersey_number"] is None
    assert client.patch(f"{url}/players/{p2}", headers=ana, json={"jersey_number": 42}).json()["jersey_number"] == 42
    assert client.patch(f"{url}/players/{p2}", headers=ana, json={"jersey_number": 0}).json()["jersey_number"] == 0
    # validation
    for bad in ({"jersey_number": 100}, {"jersey_number": -1}, {"jersey_number": "7"}, {"jersey_number": True},
                {"jersey_number": 7.5}, {}, {"jersey_number": 7, "name": "x"}):
        assert client.patch(f"{url}/players/{p1}", headers=ana, json=bad).status_code == 422, bad
    # auth / ownership / membership
    assert client.patch(f"{url}/players/{p1}", json={"jersey_number": 1}).status_code == 401
    assert client.patch(f"{url}/players/{p1}", headers=bob, json={"jersey_number": 1}).status_code == 404
    assert client.patch("/api/videos/999999/players/1", headers=ana, json={"jersey_number": 1}).status_code == 404
    other = client.get(f"/api/videos/{upload(client, ana, 'Other H', 'Other A')['id']}/stats", headers=ana).json()
    missing = client.patch(f"{url}/players/{other[0]['player_id']}", headers=ana, json={"jersey_number": 1})
    assert missing.status_code == 404 and missing.json()["detail"] == "Player not found in this video"
    # other videos and the cross-video endpoint ignore the override
    assert all(x["jersey_number"] != 0 or x["player_id"] != p2 for x in other)
    # delete cascades the override rows
    assert client.delete(url, headers=ana).status_code == 204
    with SessionLocal() as db:
        assert db.query(VideoPlayerOverride).filter_by(video_id=v["id"]).count() == 0


def test_patch_video_player_409_until_done(client, ana):
    v = upload(client, ana, "Busy H", "Busy A")
    pid = client.get(f"/api/videos/{v['id']}/stats", headers=ana).json()[0]["player_id"]
    with SessionLocal() as db:
        db.get(MatchVideo, v["id"]).processing_status = "processing"
        db.commit()
    r = client.patch(f"/api/videos/{v['id']}/players/{pid}", headers=ana, json={"jersey_number": 3})
    assert r.status_code == 409 and r.json()["status"] == "processing"


# ------------------------------------------------------------------ 5. allowed extensions
def test_code_default_extensions():
    assert Settings.model_fields["ALLOWED_VIDEO_EXTENSIONS"].default == "mp4,mov,avi,mkv"
    assert settings.allowed_video_extensions == {"mp4", "mov", "avi", "mkv"}


@pytest.mark.parametrize("ext,ctype,args", [
    ("avi", "video/x-msvideo", ("-c:v", "mpeg4")),
    ("mkv", "video/x-matroska", ("-c:v", "mpeg4")),
    ("mov", "video/quicktime", ("-pix_fmt", "yuv420p")),
])
def test_avi_mkv_mov_upload_probe_and_thumbnail(client, ana, tmp_root, ext, ctype, args):
    body = ffmpeg_clip(tmp_root, f"clip3s.{ext}", 3, args)
    v = upload(client, ana, f"{ext} H", f"{ext} A", name=f"clip.{ext}", body=body, ctype=ctype)
    d = client.get(f"/api/videos/{v['id']}", headers=ana).json()
    assert d["status"] == "done" and d["duration_seconds"] == pytest.approx(3.0, abs=0.2)
    assert d["thumbnail_url"]                                     # ffmpeg decoded the container


def test_new_code_before_migration_007(client, ana, monkeypatch):
    """Deploy order safety: without the video_player_overrides table, stats/delete work and PATCH says 503."""
    import stats
    import routers.videos as rv
    monkeypatch.setattr(stats, "has_overrides_table", lambda db: False)
    monkeypatch.setattr(rv, "has_overrides_table", lambda db: False)
    v = upload(client, ana, "Pre007 H", "Pre007 A")
    rows = client.get(f"/api/videos/{v['id']}/stats", headers=ana).json()
    assert rows
    r = client.patch(f"/api/videos/{v['id']}/players/{rows[0]['player_id']}", headers=ana, json={"jersey_number": 5})
    assert r.status_code == 503 and "007" in r.json()["detail"]
    assert client.delete(f"/api/videos/{v['id']}", headers=ana).status_code == 204
