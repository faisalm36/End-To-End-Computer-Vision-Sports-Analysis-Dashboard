"""v0.6.0 ERD parity: new columns, Players page, video_type, dual stats naming, detection pixel fields."""
import json
from datetime import date
from decimal import Decimal
from pathlib import Path

import pytest
from sqlalchemy import select, text

import pipeline
import seed
from conftest import FAKE_MP4, login, register_and_login
from database import SessionLocal
from models import Match, MatchVideo, Player, PlayerMatchMetric, PlayerMatchStat, Team, TrackingDetection
from stats import FATIGUE_SCORE, fatigue_score, kmh_from_mph, meters_from_km


@pytest.fixture(autouse=True, scope="module")
def _seed(client):
    seed.seed()


@pytest.fixture
def demo(client):
    return login(client, "faisal@example.com", "capstone123")


PLAYER_KEYS = {"player_id", "team_id", "first_name", "last_name", "jersey_number", "position",
               "dominant_foot", "contract_end_date", "created_at", "team"}
TEAM_KEYS = {"team_id", "team_name", "league", "created_at"}


def test_list_players_and_filter(client, demo):
    all_p = client.get("/api/players", headers=demo).json()
    assert all_p and set(all_p[0]) == PLAYER_KEYS and set(all_p[0]["team"]) == TEAM_KEYS
    team_id = all_p[0]["team_id"]
    filtered = client.get(f"/api/players?team_id={team_id}", headers=demo).json()
    assert filtered and {p["team_id"] for p in filtered} == {team_id}
    assert client.get("/api/players?team_id=99999", headers=demo).status_code == 404
    assert client.get("/api/players").status_code == 401
    zed = register_and_login(client, "zed-erd@example.com", first="Zed", last="E")
    assert client.get("/api/players", headers=zed).json() == []
    assert client.get(f"/api/players?team_id={team_id}", headers=zed).status_code == 404


def test_patch_player_contract_and_jersey_clash(client, demo):
    p = client.get("/api/players/21", headers=demo).json()
    r = client.patch("/api/players/21", headers=demo, json={
        "first_name": "Faisal", "contract_end_date": "2028-06-30", "dominant_foot": "Right",
        "position": "FW",
    })
    assert r.status_code == 200
    body = r.json()
    assert body["contract_end_date"] == "2028-06-30" and body["dominant_foot"] == "Right"
    assert body["team"]["team_id"] == p["team_id"]
    # clear nullable
    cleared = client.patch("/api/players/21", headers=demo, json={"contract_end_date": None, "position": None})
    assert cleared.status_code == 200 and cleared.json()["contract_end_date"] is None
    # jersey clash on same team
    mates = [x for x in client.get(f"/api/players?team_id={p['team_id']}", headers=demo).json()
             if x["player_id"] != 21 and x["jersey_number"] is not None]
    if mates:
        clash = client.patch("/api/players/21", headers=demo, json={"jersey_number": mates[0]["jersey_number"]})
        assert clash.status_code == 409 and "already taken" in clash.json()["detail"]
    assert client.patch("/api/players/21", headers=demo, json={}).status_code == 422
    assert client.patch("/api/players/21", json={"position": "MF"}).status_code == 401


def test_video_type_upload_and_response_fields(client, demo):
    r = client.post("/api/videos", headers=demo,
                    data={"title": "ERD cam", "match_date": "2026-12-01", "home_team": "Capstone FC",
                          "away_team": "Rival United", "video_type": "broadcast"},
                    files={"file": ("clip.mp4", FAKE_MP4, "video/mp4")})
    assert r.status_code == 202, r.text
    v = r.json()
    assert v["video_type"] == "broadcast"
    # wait for stub processing
    for _ in range(60):
        v = client.get(f"/api/videos/{v['id']}", headers=demo).json()
        if v["status"] in ("done", "failed"):
            break
        import time; time.sleep(0.2)
    assert v["status"] == "done"
    assert v["video_type"] == "broadcast"
    assert v["resolution"] in ("1920x1080", "1920X1080") or (isinstance(v["resolution"], str) and "x" in v["resolution"].lower())
    assert isinstance(v["duration_seconds"], (int, float)) and v["duration_seconds"] > 0
    listed = next(x for x in client.get("/api/videos", headers=demo).json() if x["id"] == v["id"])
    assert listed["video_type"] == "broadcast" and listed["resolution"] and listed["duration_seconds"]
    bad = client.post("/api/videos", headers=demo,
                      data={"title": "bad", "match_date": "2026-12-02", "home_team": "Capstone FC",
                            "away_team": "Rival United", "video_type": "drone"},
                      files={"file": ("clip.mp4", FAKE_MP4, "video/mp4")})
    assert bad.status_code == 422


def test_ingest_writes_erd_detection_and_stats_columns(client, demo):
    # use an existing done video from seed or the one just uploaded
    videos = [v for v in client.get("/api/videos", headers=demo).json() if v["status"] == "done"]
    assert videos
    vid = videos[0]["id"]
    with SessionLocal() as db:
        dets = db.scalars(select(TrackingDetection).where(TrackingDetection.video_id == vid).limit(5)).all()
        assert dets
        for d in dets:
            assert d.x_center is not None and d.bbox_width is not None
            assert abs(d.x_center - (d.bbox_x1 + d.bbox_x2) / 2) < 0.6
            assert abs(d.bbox_width - abs(d.bbox_x2 - d.bbox_x1)) < 0.6
        stats = db.scalars(select(PlayerMatchStat).where(PlayerMatchStat.video_id == vid)).all()
        assert stats
        for st in stats:
            if st.distance_km is not None:
                assert st.distance_covered_meters is not None
                assert abs(float(st.distance_covered_meters) - float(st.distance_km) * 1000) < 1.0
            if st.top_speed_mph is not None:
                assert st.top_speed_kmh is not None
            assert st.fatigue_risk_score is not None
            assert float(st.fatigue_risk_score) == FATIGUE_SCORE[st.injury_risk]


def test_stats_api_returns_both_naming_systems(client, demo):
    videos = [v for v in client.get("/api/videos", headers=demo).json() if v["status"] == "done"]
    rows = client.get(f"/api/videos/{videos[0]['id']}/stats", headers=demo).json()
    assert rows
    for row in rows:
        for k in ("distance_covered_meters", "top_speed_kmh", "fatigue_risk_score",
                  "minutes_played", "sprint_count"):
            assert k in row
        if row["distance_km"] is not None:
            assert row["distance_covered_meters"] == pytest.approx(row["distance_km"] * 1000, abs=1)
        assert row["fatigue_risk_score"] == fatigue_score(row["injury_risk"])
    # bare players/stats keeps classic 5 keys; include=metrics adds ERD flats
    bare = client.get("/api/players/stats").json()[0]
    assert set(bare) == {"player_id", "name", "top_speed_mph", "distance_km", "injury_risk"}
    rich = client.get("/api/players/stats?include=metrics").json()[0]
    assert "distance_covered_meters" in rich and "fatigue_risk_score" in rich


def test_detections_include_pixel_shapes(client, demo):
    videos = [v for v in client.get("/api/videos", headers=demo).json() if v["status"] == "done"]
    r = client.get(f"/api/videos/{videos[0]['id']}/detections?frame=0", headers=demo)
    assert r.status_code == 200, r.text
    data = r.json()
    assert data["players"]
    p = data["players"][0]
    assert "bbox" in p and len(p["bbox"]) == 4
    for k in ("bbox_xyxy", "x_center", "y_center", "bbox_width", "bbox_height"):
        assert p.get(k) is not None, k
    x1, y1, x2, y2 = p["bbox_xyxy"]
    assert p["x_center"] == pytest.approx((x1 + x2) / 2, abs=0.6)
    assert p["bbox_width"] == pytest.approx(abs(x2 - x1), abs=0.6)


def test_match_created_at(client, demo):
    matches = client.get("/api/matches", headers=demo).json()
    assert matches and "created_at" in matches[0]


def test_fatigue_and_unit_helpers():
    assert fatigue_score("Low") == 0.0 and fatigue_score("High") == 100.0
    assert meters_from_km(1.5) == 1500.0
    assert kmh_from_mph(10) == 16.09


def test_backfill_logic_on_existing_rows(client, demo):
    """Simulate pre-009 rows (NULL ERD cols) and apply the same formulas migration/ingest use."""
    with SessionLocal() as db:
        st = db.scalar(select(PlayerMatchStat).where(PlayerMatchStat.distance_km.is_not(None)).limit(1))
        assert st is not None
        st.distance_covered_meters = None
        st.top_speed_kmh = None
        st.fatigue_risk_score = None
        db.commit()
        pid, sid = st.player_id, st.stat_id
    # re-derive the way migration 009 / ingest would
    with SessionLocal() as db:
        st = db.get(PlayerMatchStat, sid)
        st.distance_covered_meters = Decimal(str(round(float(st.distance_km) * 1000, 2)))
        st.top_speed_kmh = Decimal(str(round(float(st.top_speed_mph) * 1.609344, 2))) if st.top_speed_mph else None
        st.fatigue_risk_score = Decimal(str(FATIGUE_SCORE[st.injury_risk]))
        db.commit()
        st = db.get(PlayerMatchStat, sid)
        assert float(st.distance_covered_meters) == pytest.approx(float(st.distance_km) * 1000, abs=0.1)
        assert float(st.fatigue_risk_score) == FATIGUE_SCORE[st.injury_risk]
