"""Original endpoints: /health, /api/players/stats, /api/players/{id} (stats shape unchanged; GET player is now owner-auth + enriched)."""
import pytest

import seed
from conftest import login


@pytest.fixture(autouse=True, scope="module")
def _fresh_seed(client):
    seed.seed()


def test_health(client):
    r = client.get("/health")
    assert r.status_code == 200
    assert r.json() == {"status": "ok", "db": "ok"}


def test_stats_shape(client):
    r = client.get("/api/players/stats")
    assert r.status_code == 200  # would be 422 if swallowed by /api/players/{player_id}
    data = r.json()
    assert isinstance(data, list) and data
    ids = {p["player_id"] for p in data}
    assert 23 not in ids  # player with no stats excluded
    faisal = next(p for p in data if p["player_id"] == 21)
    assert faisal == {"player_id": 21, "name": "Faisal Musa", "top_speed_mph": 19.2,
                      "distance_km": 4.5, "injury_risk": "Low"}
    for p in data:
        assert isinstance(p["top_speed_mph"], float) and isinstance(p["distance_km"], float)
        assert p["injury_risk"] in {"Low", "Medium", "High"}


def test_stats_filters(client):
    m1 = {p["player_id"]: p for p in client.get("/api/players/stats?match_id=1").json()}
    assert m1[10]["injury_risk"] == "Medium" and 22 not in m1
    t2 = client.get("/api/players/stats?team_id=2").json()
    assert {p["player_id"] for p in t2} == {1, 14, 8, 22}


def test_player_by_id(client):
    demo = login(client, "faisal@example.com", "capstone123")
    r = client.get("/api/players/21", headers=demo)
    assert r.status_code == 200 and r.json()["jersey_number"] == 21
    assert r.json()["team"]["team_name"] and "contract_end_date" in r.json()
    assert client.get("/api/players/21").status_code == 401
    assert client.get("/api/players/9999", headers=demo).status_code == 404


def test_cors_preflight_with_authorization(client):
    r = client.options("/api/videos", headers={
        "Origin": "http://localhost:5173",
        "Access-Control-Request-Method": "POST",
        "Access-Control-Request-Headers": "authorization,content-type",
    })
    assert r.status_code == 200
    assert r.headers["access-control-allow-origin"] == "http://localhost:5173"
    assert "authorization" in r.headers["access-control-allow-headers"].lower()
