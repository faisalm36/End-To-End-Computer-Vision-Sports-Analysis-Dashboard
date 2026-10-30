

from datetime import date, timedelta
import pytest
from injury_risk.risk_model import *  # noqa: F403

D = date(2026, 10, 27)

def turf_run(n, end=D - timedelta(days=7), surface="turf"):
    return [MatchLoad(end - timedelta(days=7 * i), surface, 90, 10.0, 600, 20) for i in range(n)]

def test_baseline_low():
    r = score_player(D, [], turf_run(4, surface="grass"), 25, "grass")
    assert r.multiplier == 1.0 and r.band == "low" and 10 < r.score < 20

def test_bounds_and_cap():
    inj = [Injury("ankle", D - timedelta(days=60), 20), Injury("ankle", D - timedelta(days=200), 40)]
    r = score_player(D, inj, turf_run(5, end=D - timedelta(days=3)), 36, "turf")
    assert 0 <= r.score <= 100 and r.multiplier <= M_CAP

def test_previous_injury_raises_and_decays():
    base = score_player(D, [], [], None, None).score
    recent = score_player(D, [Injury("hamstring", D - timedelta(days=40), 14)], [], None, None).score
    old = score_player(D, [Injury("hamstring", D - timedelta(days=600), 14)], [], None, None).score
    assert recent > old > base

def test_currently_injured():
    r = score_player(D, [Injury("knee", D - timedelta(days=5), 30)], [])
    assert r.status == "injured" and r.score == 100

def test_turf_streak_next_turf_raises_for_injury_prone():
    inj = [Injury("ankle", D - timedelta(days=300), 21)]
    m = turf_run(3)
    on_turf = score_player(D, inj, m, 27, "turf")
    on_grass = score_player(D, inj, m, 27, "grass")
    assert on_turf.score > on_grass.score
    keys = {f.key for f in on_turf.factors}
    assert {"turf_ankle", "turf_streak"} <= keys

def test_turf_streak_grows_with_length():
    inj = [Injury("knee", D - timedelta(days=300), 21)]
    s1 = score_player(D, inj, turf_run(1), 27, "turf").score
    s3 = score_player(D, inj, turf_run(3), 27, "turf").score
    assert s3 > s1

def test_turf_no_effect_without_joint_history():
    # Kuitunen 2023: overall incidence not higher on turf -> no surface penalty for healthy players
    a = score_player(D, [], turf_run(3), 27, "turf").score
    b = score_player(D, [], turf_run(3), 27, "grass").score
    assert a <= b * 1.06  # only possible surface-switch effect

def test_congestion_muscle_rr():
    inj = [Injury("hamstring", D - timedelta(days=400), 10)]
    r = score_player(D, inj, [MatchLoad(D - timedelta(days=3), "grass", 90)], None, "grass")
    f = [x for x in r.factors if x.key == "congestion"][0]
    assert f.multiplier == CONGESTION_MUSCLE_RR

def test_acwr_spike():
    m = [MatchLoad(D - timedelta(days=d), "grass", 90, None, hsr) for d, hsr in
         [(2, 1500), (5, 1500), (14, 300), (21, 300)]]
    r = score_player(D, [], m, None, "grass")
    assert any(f.key == "acwr_high" for f in r.factors)

def test_missing_data_low_confidence_neutral():
    r = score_player(D)
    assert r.confidence == "low" and r.multiplier == 1.0

def test_history_and_projection():
    inj = [Injury("ankle", D - timedelta(days=200), 21)]
    m = turf_run(4)
    h = score_history(inj, m, 27)
    assert len(h) == 4 and all(0 <= x.score <= 100 for x in h)
    p = project_next(D, D + timedelta(days=4), "turf", inj, m, 27)
    assert p.as_of == D + timedelta(days=4)

def test_bands():
    assert band_for(10) == "low" and band_for(30) == "moderate" and band_for(70) == "high"
