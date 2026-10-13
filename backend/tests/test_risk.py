"""v0.7.0 injury-risk dashboard: crypto, model, gates, pipeline fixes, roster/history/CSV API, latency."""
import base64
import io
import math
import time
from datetime import date, timedelta

import pytest
from sqlalchemy import select, text

import health_crypto as hc
import pipeline
import risk_service as rs
from config import settings
from conftest import FAKE_MP4, register_and_login
from database import SessionLocal
from ml import features as F
from ml import scorer
from models import (AthleteLog, Match, MatchVideo, Player, PlayerMatchMetric, PlayerMatchRisk, PlayerMatchStat, Team,
                    User)

FORM = {"match_date": "2026-09-01"}
KEY = base64.b64decode(settings.HEALTH_DATA_KEY)


# ------------------------------------------------------------------ helpers
@pytest.fixture(scope="module")
def coach(client):
    return register_and_login(client, "coach.risk@example.com", first="Coach", last="Risk")


@pytest.fixture(scope="module")
def other(client):
    return register_and_login(client, "other.risk@example.com", first="Other", last="Risk")


def _uid(email):
    with SessionLocal() as db:
        return db.scalar(select(User.user_id).where(User.email == email))


def _team(email, name, players):
    """players = [(first, last, jersey)] -> (team_id, [player_id])"""
    with SessionLocal() as db:
        t = Team(user_id=_uid(email), team_name=name)
        db.add(t)
        db.flush()
        ps = [Player(team_id=t.team_id, first_name=f, last_name=l, jersey_number=j, position="MF") for f, l, j in players]
        db.add_all(ps)
        db.commit()
        return t.team_id, [p.player_id for p in ps]


@pytest.fixture(scope="module")
def squad(client, coach):
    return _team("coach.risk@example.com", "Risk FC",
                 [("Ada", "Lovelace", 7), ("Bo", "Jackson", 9), ("Cy", "Young", 10), ("Di", "Prince", 11)])


def csv_post(client, h, body, name="logs.csv", ctype="text/csv", **data):
    if isinstance(body, str):
        body = body.encode()
    return client.post("/api/uploads/csv", headers=h, files={"file": (name, body, ctype)},
                       data={k: str(v).lower() if isinstance(v, bool) else str(v) for k, v in data.items()})


# ------------------------------------------------------------------ crypto
def test_crypto_roundtrip_nonce_tamper_wrong_key():
    a, b = hc.encrypt_float(152.5, KEY), hc.encrypt_float(152.5, KEY)
    assert a != b                                              # random 96-bit nonce per value
    assert len(base64.b64decode(a)) == 12 + len(repr(152.5)) + 16
    assert hc.decrypt_float(a, KEY) == 152.5
    assert hc.decrypt_json(hc.encrypt_json({"x": [1, 2]}, KEY), KEY) == {"x": [1, 2]}
    raw = bytearray(base64.b64decode(a))
    raw[-1] ^= 1
    with pytest.raises(hc.HealthDecryptError):
        hc.decrypt_float(base64.b64encode(bytes(raw)).decode(), KEY)
    raw = bytearray(base64.b64decode(a))
    raw[3] ^= 1                                                # nonce tamper
    with pytest.raises(hc.HealthDecryptError):
        hc.decrypt_float(base64.b64encode(bytes(raw)).decode(), KEY)
    with pytest.raises(hc.HealthDecryptError):
        hc.decrypt_float(a, b"\x22" * 32)                      # wrong key
    with pytest.raises(hc.HealthDecryptError):
        hc.decrypt_float("not base64!!", KEY)


def test_crypto_key_validation(monkeypatch):
    for bad, msg in (("", "not set"), ("%%%", "not valid base64"),
                     (base64.b64encode(b"x" * 16).decode(), "16 bytes")):
        with pytest.raises(hc.HealthKeyError, match=msg):
            hc.parse_key(bad)
    monkeypatch.setattr(settings, "HEALTH_DATA_KEY", "")
    ok, msg = hc.key_status()
    assert not ok and "not set" in msg
    with pytest.raises(hc.HealthKeyError):
        hc.encrypt_float(1.0)


def test_missing_key_gives_503(client, coach, squad, monkeypatch):
    monkeypatch.setattr(settings, "HEALTH_DATA_KEY", "")
    r = client.get(f"/api/roster/risk?team_id={squad[0]}", headers=coach)
    assert r.status_code == 503 and "HEALTH_DATA_KEY" in r.json()["detail"]
    r = csv_post(client, coach, "date,player\n2026-09-01,Ada Lovelace\n")
    assert r.status_code == 503


# ------------------------------------------------------------------ model
def test_model_reproducible_and_metrics():
    from ml import train_risk_model as T
    a, b = T.train(write=False), T.train(write=False)
    assert a["coefficients"] == b["coefficients"] and a["metrics"] == b["metrics"]
    m = a["metrics"]
    assert m["roc_auc"] > 0.8 and 0 < m["brier"] < 0.2 and m["holdout_rows"] > 1000
    _, meta = scorer.load()
    assert meta["features"] == F.FEATURES and meta["coefficients"] == a["coefficients"]
    assert "SYNTHETIC" in meta["training_data"] and "not" in meta["disclaimer"].lower()


def test_contributions_explain_the_score():
    row = F.csv_features({"gps_distance_km": 11.8, "minutes_played": 90, "heart_rate": 171, "sprints": 30,
                          "top_speed_kmh": 31.0}, [9.0, 9.2, 8.8, 9.1])
    r = scorer.score([row])[0]
    logit = sum(c["contribution"] for c in r["contributions"]) + r["intercept"]
    assert abs(100 / (1 + math.exp(-logit)) - r["risk_percent"]) < 0.2
    fac = scorer.factors(r["contributions"])
    assert len(fac) == 5 and {"acwr", "heart_rate_avg"} <= {f["feature"] for f in fac[:3]}
    assert all(f["direction"] == ("up" if f["contribution"] > 0 else "down") for f in fac)
    assert [abs(f["contribution"]) for f in fac] == sorted((abs(f["contribution"]) for f in fac), reverse=True)
    assert all(set(f) == {"feature", "label", "value", "contribution", "direction"} for f in fac)
    assert not any(f["feature"] == "hsr_m_per_min" for f in fac)             # imputed -> not a factor
    low = scorer.score([F.csv_features({"gps_distance_km": 6.0, "minutes_played": 90, "sprints": 8},
                                       [9.0, 9.2, 8.8, 9.1])])[0]
    assert low["risk_percent"] < r["risk_percent"] and r["level"] == "red" and low["level"] == "green"


def test_levels_and_configurable_thresholds(monkeypatch):
    assert [scorer.level_for(x) for x in (70, 69.9, 40, 39.9, None)] == ["red", "yellow", "yellow", "green", None]
    monkeypatch.setattr(settings, "RISK_RED_THRESHOLD", 80.0)
    monkeypatch.setattr(settings, "RISK_YELLOW_THRESHOLD", 50.0)
    assert [scorer.level_for(x) for x in (79, 50, 49)] == ["yellow", "yellow", "green"]


def test_features_never_use_defaults_or_double_counts():
    v = F.stat_values({"injury_risk": "High", "fatigue_risk_score": 85.0, "high_intensity_efforts": 30,
                       "hi_efforts_count": 30})
    assert v["sprint_count"] is None and v["accels"] is None and v["decels"] is None
    feats = F.match_features(v, 10.0, [], None, None)
    assert all(feats[k] is None for k in F.FEATURES if k != "hr_missing")
    assert "injury_risk" not in F.FEATURES and "fatigue_risk_score" not in F.FEATURES
    # rates over exposure; visible_minutes never becomes minutes_played
    f2 = F.match_features(F.stat_values({"distance_km": 0.5, "sprint_count": 2, "visible_minutes": 5.0}), 5.0, [], None, None)
    assert f2["distance_m_per_min"] == 100.0 and f2["sprints_per_90"] == 36.0 and f2["minutes_played"] is None
    assert F.match_features(F.stat_values({"distance_km": 0.5}), 0.5, [], None, None)["distance_m_per_min"] is None


# ------------------------------------------------------------------ pipeline fixes (CV Engineer list A)
def _dets(tid, jersey, team=0, n=4):
    return [{"frame": f, "timestamp": f / 30, "track_id": tid, "class": "player", "team": team, "role": "player",
             "jersey_number": jersey, "bbox_x1": 1, "bbox_y1": 1, "bbox_x2": 2, "bbox_y2": 2, "confidence": 0.9,
             "pitch_x": 30.0, "pitch_y": 20.0} for f in range(n)]


def _ingest(client, h, monkeypatch, out, home, away="Gate Away"):
    monkeypatch.setattr(pipeline, "run_pipeline", lambda video: out)
    r = client.post("/api/videos", headers=h, data={**FORM, "home_team": home, "away_team": away},
                    files={"file": ("clip.mp4", FAKE_MP4, "video/mp4")})
    assert r.status_code == 202, r.text
    vid = r.json()["id"]
    d = client.get(f"/api/videos/{vid}", headers=h).json()
    assert d["status"] == "done", d["error_message"]
    return vid, d, client.get(f"/api/videos/{vid}/stats?include=metrics", headers=h).json()


META = {"pipeline_version": "1.2.0", "fps": 30.0, "frame_count": 18000, "duration_s": 600.0}


def test_pipeline_fixes_minutes_zero_accels_hi_efforts(client, coach, monkeypatch):
    s1 = {"track_id": 1, "jersey_number": 4, "team": 0, "role": "player", "top_speed_mph": 0.0, "distance_km": 0.0,
          "visible_minutes": 0.0, "hi_efforts_count": 12, "injury_risk": "High"}   # no minutes, no accels, no sprints
    out = pipeline.PipelineOutput(detections=_dets(1, 4), player_stats=[s1], source="real",
                                  meta={**META, "calibration": "cv/config/my_pitch.json"})
    _, _, rows = _ingest(client, coach, monkeypatch, out, "Fix FC")
    r = rows[0]
    assert r["minutes_played"] is None                         # never duration_s / 60
    assert r["distance_km"] == 0.0 and r["top_speed_mph"] == 0.0   # 0.0 is a value
    assert r["visible_minutes"] == 0.0 and r["distance_per_min"] is None
    assert r["accels"] is None and r["decels"] is None         # never fabricated
    assert r["sprint_count"] is None                           # hi_efforts never fills sprint_count


# ------------------------------------------------------------------ gates (CV Engineer list B)
def _history(client, h, pid):
    r = client.get(f"/api/players/{pid}/risk", headers=h)
    assert r.status_code == 200, r.text
    return r.json()["history"]


@pytest.mark.parametrize("case,meta_extra,stat_extra,status,dq,note", [
    ("nocal", {"calibration": None}, {}, "uncalibrated", None, "no custom pitch calibration"),
    ("nonestr", {"calibration": "none"}, {}, "uncalibrated", None, "no custom pitch calibration"),
    ("default", {"calibration": "cv/config/default_calibration.json"}, {}, "uncalibrated", None, "no custom"),
    ("dvalid", {"calibration": "/data/cal/pitch7.json"}, {"distance_valid": False}, "uncalibrated", None,
     "distance_valid=false"),
    ("short", {"calibration": "/data/cal/pitch7.json"}, {"visible_minutes": 0.5}, "insufficient_data", "calibrated",
     "visible_minutes < 1"),
    ("nodist", {"calibration": "/data/cal/pitch7.json"}, {"distance_km": None}, "insufficient_data", "calibrated",
     "distance missing"),
    ("ok", {"calibration": "/data/cal/pitch7.json"}, {}, "scored", "calibrated", None),
])
def test_cv_gates(client, coach, monkeypatch, case, meta_extra, stat_extra, status, dq, note):
    team_name = f"Gate {case}"
    _, (pid,) = _team("coach.risk@example.com", team_name, [("Gate", case, 8)])
    s = {"track_id": 1, "jersey_number": 8, "team": 0, "role": "player", "top_speed_mph": 18.0, "distance_km": 0.9,
         "visible_minutes": 8.0, "sprint_count": 3, "high_speed_distance_km": 0.08, **stat_extra}
    out = pipeline.PipelineOutput(detections=_dets(1, 8), player_stats=[s], source="real", meta={**META, **meta_extra})
    _ingest(client, coach, monkeypatch, out, team_name)
    (h,) = _history(client, coach, pid)
    assert h["score_status"] == status and h["data_quality"] == dq and h["source"] == "match"
    if status == "scored":
        assert 0 <= h["risk_percent"] <= 100 and h["level"] in ("red", "yellow", "green") and h["factors"]
        assert h["score_note"] is None
    else:
        assert h["risk_percent"] is None and h["level"] == "unknown" and h["factors"] == []
        assert note in h["score_note"]


def test_placeholder_players_are_not_scored(client, coach, monkeypatch):
    s = {"track_id": 3, "jersey_number": 77, "team": 0, "role": "player", "top_speed_mph": 18.0, "distance_km": 0.9,
         "visible_minutes": 8.0}
    out = pipeline.PipelineOutput(detections=_dets(3, 77), player_stats=[s], source="real",
                                  meta={**META, "calibration": "/data/cal/pitch7.json"})
    vid, d, rows = _ingest(client, coach, monkeypatch, out, "Ghost FC")
    assert d["pipeline_meta"]["risk_gate"]["placeholder_player_ids"]
    with SessionLocal() as db:
        r = db.scalar(select(PlayerMatchRisk).where(PlayerMatchRisk.video_id == vid))
        assert r.score_status == "insufficient_data" and "no roster match" in r.score_note
        assert r.risk_percent_enc is None and r.level == "unknown"


def test_stub_rows_are_demo(client, coach, monkeypatch):
    _, (pid,) = _team("coach.risk@example.com", "Stub FC", [("Stu", "Bee", 5)])
    s = {"track_id": 1, "jersey_number": 5, "team": 0, "role": "player", "top_speed_mph": 18.0, "distance_km": 0.9,
         "visible_minutes": 8.0, "sprint_count": 2}
    out = pipeline.PipelineOutput(detections=_dets(1, 5), player_stats=[s], source="stub", meta={**META, "calibration": None})
    _ingest(client, coach, monkeypatch, out, "Stub FC")
    (h,) = _history(client, coach, pid)
    assert h["score_status"] == "scored" and h["data_quality"] == "demo"


# ------------------------------------------------------------------ roster endpoint
ROSTER_KEYS = {"player_id", "name", "first_name", "last_name", "jersey_number", "position", "team", "risk_percent",
               "level", "source", "match_id", "match_date", "video_id", "model_version", "computed_at", "features",
               "factors", "score_status", "score_note", "data_quality"}


def test_roster_auth_scope_and_validation(client, coach, other, squad):
    tid = squad[0]
    assert client.get(f"/api/roster/risk?team_id={tid}").status_code == 401
    assert client.get(f"/api/roster/risk?team_id={tid}", headers=other).status_code == 404
    assert client.get("/api/roster/risk?team_id=999999", headers=coach).status_code == 404
    r = client.get(f"/api/roster/risk?team_id={tid}&sort=sideways", headers=coach)
    assert r.status_code == 422 and "detail" in r.json()
    assert client.get(f"/api/roster/risk?team_id={tid}&match_id=999999", headers=coach).status_code == 404
    assert client.get(f"/api/players/{squad[1][0]}/risk", headers=other).status_code == 404


def test_roster_no_data_shape(client, coach, squad):
    r = client.get(f"/api/roster/risk?team_id={squad[0]}", headers=coach)
    assert r.status_code == 200 and float(r.headers["X-Response-Time-ms"]) >= 0
    b = r.json()
    assert set(b) == {"team_id", "match_id", "sort", "model_version", "thresholds", "generated_at", "latency_ms", "players"}
    assert b["thresholds"] == {"red": 70, "yellow": 40} and b["generated_at"].endswith("Z")
    p = b["players"][0]
    assert set(p) == ROSTER_KEYS and set(p["features"]) == set(F.DISPLAY_FEATURES)
    assert p["level"] == "unknown" and p["score_status"] == "no_data" and p["risk_percent"] is None


CSV = """Player Name,Date,GPS_Distance,Heart Rate,Minutes,Sprints,Top Speed,HR max,notes
Ada Lovelace,2026-09-01,9.1,150,90,15,30.1,182,ok
Ada Lovelace,2026-09-04,9.0,151,90,14,30.4,181,
Ada Lovelace,2026-09-08,12.6,172,90,32,31.0,195,spike
Bo Jackson,09/08/2026,8.5,,88,10,29.0,,
Cy Young,2026-13-01,9.0,150,90,10,30,,bad date
Cy Young,2026-09-08,9.0,300,90,10,30,,bad hr
Nobody Here,2026-09-08,9.0,150,90,10,30,,
"""


def test_csv_dry_run_then_store_then_roster_then_delete(client, coach, squad):
    tid, pids = squad
    r = csv_post(client, coach, CSV, team_id=tid, dry_run=True)
    assert r.status_code == 200, r.text
    b = r.json()
    assert b["upload_id"] is None and b["dry_run"] is True
    assert (b["rows_total"], b["rows_valid"], b["rows_invalid"], b["rows_unmatched"]) == (7, 4, 2, 1)
    assert b["columns_detected"] == {"player": "Player Name", "date": "Date", "gps_distance": "GPS_Distance",
                                     "heart_rate": "Heart Rate", "minutes_played": "Minutes", "sprints": "Sprints",
                                     "top_speed_kmh": "Top Speed", "heart_rate_max": "HR max"}
    errs = {(e["row"], e["column"]) for e in b["errors"]}
    assert errs == {(6, "Date"), (7, "Heart Rate")}
    assert b["unmatched"] == [{"row": 8, "player": "Nobody Here"}]
    assert [x["row"] for x in b["results"]] == [2, 3, 4, 5]
    spike = b["results"][2]
    assert spike["level"] == "red" and spike["score_status"] == "scored" and "acwr" in {f["feature"] for f in spike["factors"][:3]}
    with SessionLocal() as db:
        assert db.scalar(select(AthleteLog).where(AthleteLog.player_id.in_(pids))) is None   # dry run stores nothing

    r = csv_post(client, coach, CSV, team_id=tid)
    assert r.status_code == 201, r.text
    up = r.json()
    assert up["upload_id"] and [x["risk_percent"] for x in up["results"]] == [x["risk_percent"] for x in b["results"]]
    # no plaintext health data at rest
    with SessionLocal() as db:
        rows = db.execute(text("SELECT heart_rate_enc, heart_rate_max_enc FROM athlete_logs WHERE upload_id=:u"),
                          {"u": up["upload_id"]}).all()
        hrs = sorted(hc.decrypt_float(a, KEY) for a, _ in rows if a)
        assert hrs == [150.0, 151.0, 172.0]
        risk = db.execute(text("SELECT risk_percent_enc, details_enc FROM player_match_risk WHERE log_id IS NOT NULL")).all()
        for enc, det in risk + [(a, b2) for a, b2 in rows if a]:
            for v in (enc, det):
                if v is None:
                    continue
                with pytest.raises(ValueError):
                    float(v)
                assert "{" not in v and "heart" not in v
        cols = {c[1] for c in db.execute(text("PRAGMA table_info(athlete_logs)")).all()}
        assert "heart_rate" not in cols and "heart_rate_enc" in cols
    # roster: Ada red first, Bo next, then players with no data (sorted last)
    ro = client.get(f"/api/roster/risk?team_id={tid}&sort=desc", headers=coach).json()
    names = [p["name"] for p in ro["players"]]
    assert names[0] == "Ada Lovelace" and ro["players"][0]["level"] == "red"
    assert ro["players"][0]["source"] == "csv" and ro["players"][0]["match_date"] == "2026-09-08"
    assert ro["players"][0]["data_quality"] == "csv" and ro["players"][0]["computed_at"].endswith("Z")
    assert ro["players"][0]["features"]["heart_rate_avg"] == 172.0 and ro["players"][0]["features"]["heart_rate_max"] == 195.0
    assert [p["risk_percent"] is None for p in ro["players"]] == [False, False, True, True]
    asc = client.get(f"/api/roster/risk?team_id={tid}&sort=asc", headers=coach).json()["players"]
    assert asc[0]["name"] == "Bo Jackson" and asc[2]["risk_percent"] is None
    hist = _history(client, coach, pids[0])
    assert [h["match_date"] for h in hist] == ["2026-09-08", "2026-09-04", "2026-09-01"]
    # list + delete (owner only), recompute
    lst = client.get("/api/uploads/csv", headers=coach).json()
    assert lst[0]["upload_id"] == up["upload_id"] and lst[0]["rows_valid"] == 4 and lst[0]["created_at"].endswith("Z")
    assert client.get("/api/uploads/csv", headers=other_headers(client)).json() == []
    assert client.delete(f"/api/uploads/csv/{up['upload_id']}", headers=other_headers(client)).status_code == 404
    assert client.delete(f"/api/uploads/csv/{up['upload_id']}", headers=coach).status_code == 204
    assert _history(client, coach, pids[0]) == []
    with SessionLocal() as db:
        assert db.scalar(select(AthleteLog).where(AthleteLog.upload_id == up["upload_id"])) is None


def other_headers(client):
    return register_and_login(client, "other.risk@example.com", first="Other", last="Risk")


def test_csv_upload_rejections(client, coach, other, squad):
    assert client.post("/api/uploads/csv", files={"file": ("a.csv", b"date,player\n", "text/csv")}).status_code == 401
    assert csv_post(client, other, "date,player\n2026-09-01,x\n", team_id=squad[0]).status_code == 404
    r = csv_post(client, coach, "player,gps_distance\nAda Lovelace,9\n")
    assert r.status_code == 422 and r.json() == {"detail": "missing required column(s): date", "missing_columns": ["date"]}
    r = csv_post(client, coach, "date,heart_rate\n2026-09-01,150\n")
    assert r.status_code == 422 and r.json()["missing_columns"] == ["player_id|jersey_number|player"]
    assert csv_post(client, coach, "").status_code == 422
    assert csv_post(client, coach, "date,player\n").json()["detail"] == "no data rows"
    assert csv_post(client, coach, "date,player\n2026-09-01,x\n", name="logs.png", ctype="image/png").status_code == 415
    assert csv_post(client, coach, b"date,player\n2026-09-01,\xff\xfe\n").status_code == 415
    big = "date,player,notes\n" + ("2026-09-01,Ada Lovelace," + "x" * 1000 + "\n") * 5300
    assert csv_post(client, coach, big).status_code == 413
    many = "date,player\n" + "2026-09-01,Ada Lovelace\n" * 5001
    assert csv_post(client, coach, many).status_code == 413


def test_csv_matching_by_id_and_jersey(client, coach, squad):
    tid, pids = squad
    body = (f"player_id,jersey_number,date,gps_distance_m,heart_rate\n{pids[2]},,2026-09-02,9500,140\n"
            f",11,2026-09-02,8000,\nabc,,2026-09-02,1,\n999999,,2026-09-02,1,\n")
    b = csv_post(client, coach, body, team_id=tid, dry_run=True).json()
    assert [(x["row"], x["player_id"]) for x in b["results"]] == [(2, pids[2]), (3, pids[3])]
    assert b["errors"][0]["row"] == 4 and b["errors"][0]["column"] == "player_id"
    assert b["unmatched"] == [{"row": 5, "player": "999999"}]
    assert b["columns_detected"]["gps_distance_m"] == "gps_distance_m"


# ------------------------------------------------------------------ 3-second requirement
def test_latency_25_players_x_10_matches(client, coach):
    tid, pids = _team("coach.risk@example.com", "Latency FC", [(f"P{i}", f"L{i}", i + 1) for i in range(25)])
    opp, _ = _team("coach.risk@example.com", "Latency Opp", [])
    with SessionLocal() as db:
        for m in range(10):
            match = Match(home_team_id=tid, away_team_id=opp, match_date=date(2026, 8, 1) + timedelta(days=7 * m))
            db.add(match)
            db.flush()
            for i, pid in enumerate(pids):
                st = PlayerMatchStat(player_id=pid, match_id=match.match_id, video_id=None, distance_km=9 + (i + m) % 4,
                                     minutes_played=90.0, sprint_count=10 + (i * m) % 15, top_speed_kmh=29 + i % 5)
                db.add(st)
                db.flush()
                db.add(PlayerMatchMetric(stat_id=st.stat_id, metric_key="hsr_distance_km", value=0.6 + 0.02 * i))
        db.commit()
        t0 = time.perf_counter()
        rows = rs.rescore_players(db, pids)
        db.commit()
        backfill_ms = (time.perf_counter() - t0) * 1000
    assert sum(r["score_status"] == "scored" for r in rows) == 250
    t0 = time.perf_counter()
    r = client.get(f"/api/roster/risk?team_id={tid}", headers=coach)
    roster_ms = (time.perf_counter() - t0) * 1000
    assert r.status_code == 200 and len(r.json()["players"]) == 25
    assert all(p["data_quality"] == "demo" for p in r.json()["players"])
    lines = ["player,date,gps_distance,heart_rate,minutes_played,sprints,top_speed_kmh"]
    for i in range(25):
        for m in range(10):
            lines.append(f"P{i} L{i},2026-07-{m + 1:02d},{9 + (i + m) % 4},{145 + (i + m) % 20},90,{10 + m},{29 + i % 5}")
    t0 = time.perf_counter()
    up = csv_post(client, coach, "\n".join(lines) + "\n", team_id=tid)
    csv_ms = (time.perf_counter() - t0) * 1000
    assert up.status_code == 201 and up.json()["rows_valid"] == 250
    print(f"\nLATENCY roster_risk={roster_ms:.0f}ms (header {r.headers['X-Response-Time-ms']}) "
          f"csv_250_rows={csv_ms:.0f}ms (header {up.headers['X-Response-Time-ms']}) rescore_250={backfill_ms:.0f}ms")
    assert roster_ms < 3000 and csv_ms < 3000
    t0 = time.perf_counter()
    assert client.get(f"/api/roster/risk?team_id={tid}", headers=coach).status_code == 200
    assert (time.perf_counter() - t0) * 1000 < 3000
    client.delete(f"/api/uploads/csv/{up.json()['upload_id']}", headers=coach)


def test_example_csv_scores_against_seed_demo_team(client):
    from pathlib import Path
    from conftest import login
    import seed
    h = login(client, seed.DEMO_EMAIL, seed.DEMO_PASSWORD)
    body = (Path(__file__).resolve().parents[1] / "docs" / "example_athlete_logs.csv").read_bytes()
    b = csv_post(client, h, body, name="example_athlete_logs.csv", team_id=1, dry_run=True).json()
    assert (b["rows_total"], b["rows_valid"], b["rows_invalid"], b["rows_unmatched"]) == (6, 6, 0, 0)
    assert b["results"][2]["level"] == "red" and all(r["score_status"] == "scored" for r in b["results"])
    seeded = client.get("/api/roster/risk?team_id=1", headers=h).json()["players"]
    assert any(p["data_quality"] == "demo" and p["score_status"] == "scored" for p in seeded)
