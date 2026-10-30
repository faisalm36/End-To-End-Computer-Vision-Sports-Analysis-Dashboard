"""v0.9.0 roster injury-risk (rir-1.0): injury CRUD + ownership, match surface -> recompute, roster/projection."""
from datetime import date, timedelta

import pytest
from sqlalchemy import select

import health_crypto as hc
from conftest import register_and_login
from database import SessionLocal
from models import Match, Player, PlayerInjury, PlayerMatchStat, PlayerRiskSnapshot, Team, User

TODAY = date.today()
EMAIL = "coach.injury@example.com"


def _uid(email):
    with SessionLocal() as db:
        return db.scalar(select(User.user_id).where(User.email == email))


@pytest.fixture(scope="module")
def coach(client):
    return register_and_login(client, EMAIL, first="Coach", last="Injury")


@pytest.fixture(scope="module")
def intruder(client):
    return register_and_login(client, "intruder.injury@example.com", first="In", last="Truder")


@pytest.fixture(scope="module")
def squad(coach):
    """Team with 2 players; player A played the last 3 matches on turf (weekly)."""
    with SessionLocal() as db:
        t = Team(user_id=_uid(EMAIL), team_name="Injury FC")
        opp = Team(user_id=_uid(EMAIL), team_name="Opp FC")
        db.add_all([t, opp])
        db.flush()
        a = Player(team_id=t.team_id, first_name="Ann", last_name="Kle", jersey_number=4, position="DF")
        b = Player(team_id=t.team_id, first_name="Bea", last_name="Fit", jersey_number=8, position="MF")
        db.add_all([a, b])
        db.flush()
        mids = []
        for k in (3, 2, 1):
            m = Match(home_team_id=t.team_id, away_team_id=opp.team_id, match_date=TODAY - timedelta(days=7 * k),
                      surface="turf")
            db.add(m)
            db.flush()
            mids.append(m.match_id)
            for pl in (a, b):
                db.add(PlayerMatchStat(player_id=pl.player_id, match_id=m.match_id, minutes_played=90,
                                       distance_km=10.0, sprint_count=20))
        db.commit()
        return {"team_id": t.team_id, "a": a.player_id, "b": b.player_id, "matches": mids}


def test_injury_crud_and_ownership(client, coach, intruder, squad):
    a = squad["a"]
    body = {"body_part": "ankle", "injury_type": "ligament_sprain", "side": "left",
            "injury_date": (TODAY - timedelta(days=140)).isoformat(),
            "return_date": (TODAY - timedelta(days=120)).isoformat(), "notes": "grade 2 sprain"}
    r = client.post(f"/api/players/{a}/injuries", json=body, headers=coach)
    assert r.status_code == 201, r.text
    inj = r.json()
    assert inj["days_missed"] == 20 and inj["notes"] == "grade 2 sprain" and inj["active"] is False
    with SessionLocal() as db:   # notes encrypted at rest
        raw = db.get(PlayerInjury, inj["injury_id"]).notes_enc
        assert raw and "sprain" not in raw
    assert client.get(f"/api/players/{a}/injuries", headers=intruder).status_code == 404
    assert client.post(f"/api/players/{a}/injuries", json=body, headers=intruder).status_code == 404
    assert client.delete(f"/api/players/{a}/injuries/{inj['injury_id']}", headers=intruder).status_code == 404
    assert client.get(f"/api/players/{a}/injuries").status_code == 401
    r = client.patch(f"/api/players/{a}/injuries/{inj['injury_id']}", json={"side": "right"}, headers=coach)
    assert r.status_code == 200 and r.json()["side"] == "right"
    lst = client.get(f"/api/players/{a}/injuries", headers=coach).json()
    assert [i["injury_id"] for i in lst] == [inj["injury_id"]]


def test_bad_dates_422(client, coach, squad):
    a = squad["a"]
    base = {"body_part": "knee", "injury_type": "tendon"}
    future = {**base, "injury_date": (TODAY + timedelta(days=3)).isoformat()}
    assert client.post(f"/api/players/{a}/injuries", json=future, headers=coach).status_code == 422
    backwards = {**base, "injury_date": (TODAY - timedelta(days=10)).isoformat(),
                 "return_date": (TODAY - timedelta(days=20)).isoformat()}
    assert client.post(f"/api/players/{a}/injuries", json=backwards, headers=coach).status_code == 422
    assert client.post(f"/api/players/{a}/injuries", json={**base, "body_part": "elbow",
                       "injury_date": TODAY.isoformat()}, headers=coach).status_code == 422
    r = client.get(f"/api/roster/injury-risk?next_date={(TODAY - timedelta(days=1)).isoformat()}", headers=coach)
    assert r.status_code == 422


def test_player_risk_turf_vs_grass(client, coach, squad):
    a = squad["a"]
    turf = client.get(f"/api/players/{a}/injury-risk?next_surface=turf", headers=coach).json()
    grass = client.get(f"/api/players/{a}/injury-risk?next_surface=grass", headers=coach).json()
    assert turf["projection"]["score"] > grass["projection"]["score"]
    keys = {f["key"] for f in turf["projection"]["factors"]}
    assert {"previous_injury", "turf_ankle", "turf_streak"} <= keys
    assert len(turf["previous"]) == 3 and all(p["surface"] == "turf" for p in turf["previous"])
    assert "not medical advice" in turf["disclaimer"]
    pr = client.get(f"/api/players/{a}/injury-risk/projection?surface=turf&minutes=45", headers=coach)
    assert pr.status_code == 200 and pr.json()["projection"]["score"] < turf["projection"]["score"]


def test_roster_sorted_and_delta(client, coach, squad):
    r = client.get(f"/api/roster/injury-risk?team_id={squad['team_id']}&next_surface=turf", headers=coach)
    assert r.status_code == 200, r.text
    rows = r.json()["players"]
    assert [x["player_id"] for x in rows] == [squad["a"], squad["b"]]       # injured-history player first
    assert rows[0]["delta"] == round(rows[0]["projected"] - rows[0]["current"], 1)
    assert rows[1]["has_injury_history"] is False
    asc = client.get(f"/api/roster/injury-risk?team_id={squad['team_id']}&sort=asc", headers=coach).json()["players"]
    assert [x["projected"] for x in asc] == sorted(x["projected"] for x in asc)


def test_surface_edit_triggers_recompute(client, coach, squad):
    mid = squad["matches"][-1]
    r = client.patch(f"/api/matches/{mid}", json={"surface": "grass"}, headers=coach)
    assert r.status_code == 200, r.text
    assert r.json()["surface"] == "grass"
    with SessionLocal() as db:
        snap = db.scalar(select(PlayerRiskSnapshot).where(PlayerRiskSnapshot.player_id == squad["a"],
                                                          PlayerRiskSnapshot.match_id == mid))
        assert snap is not None and snap.next_surface == "grass"
        assert hc.decrypt_float(snap.score_enc, hc.parse_key(hc.settings.HEALTH_DATA_KEY)) >= 0
    # last match now grass -> turf streak broken for a turf projection
    turf = client.get(f"/api/players/{squad['a']}/injury-risk?next_surface=turf", headers=coach).json()
    assert "turf_streak" not in {f["key"] for f in turf["projection"]["factors"]}
    assert client.patch(f"/api/matches/{mid}", json={"surface": "lava"}, headers=coach).status_code == 422


def test_delete_injury_and_active_injury(client, coach, squad):
    b = squad["b"]
    r = client.post(f"/api/players/{b}/injuries", json={"body_part": "hamstring", "injury_type": "muscle_strain",
                    "injury_date": (TODAY - timedelta(days=2)).isoformat()}, headers=coach)
    assert r.status_code == 201 and r.json()["active"] is True
    risk = client.get(f"/api/players/{b}/injury-risk", headers=coach).json()
    assert risk["current"]["status"] == "injured" and risk["current"]["score"] == 100
    assert client.delete(f"/api/players/{b}/injuries/{r.json()['injury_id']}", headers=coach).status_code == 204
    risk = client.get(f"/api/players/{b}/injury-risk", headers=coach).json()
    assert risk["current"]["status"] == "scored"


def test_birth_date_patch(client, coach, squad):
    r = client.patch(f"/api/players/{squad['b']}", json={"birth_date": "1990-01-01"}, headers=coach)
    assert r.status_code == 200 and r.json()["birth_date"] == "1990-01-01"
    risk = client.get(f"/api/players/{squad['b']}/injury-risk", headers=coach).json()
    assert "age" in {f["key"] for f in risk["factors"]}
