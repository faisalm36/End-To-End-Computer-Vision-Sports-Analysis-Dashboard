"""Idempotent seed script. Run from backend/:  python seed.py

Creates any missing tables (via SQLAlchemy metadata), wipes existing rows in ALL tables
(including users you registered and their video rows; files in uploads/ are left alone),
then inserts sample data. Demo login: faisal@example.com / capstone123 Player IDs match the mock data in frontend/src/Dashboard.jsx.
"""
import json
import random
from datetime import date
from decimal import Decimal

from sqlalchemy import delete, select

import metrics_catalog as mc
import tagging
from database import Base, SessionLocal, engine
from security import hash_password
from models import (AthleteLog, CsvUpload, Match, MatchTag, MatchVideo, Player, PlayerHeatmap, PlayerMatchMetric,
                    PlayerMatchRisk, PlayerMatchStat, TagKey, TagValue, Team, TrackingDetection, User,
                    VideoPlayerOverride, PlayerTrack)

DEMO_EMAIL = "faisal@example.com"
DEMO_PASSWORD = "capstone123"  # demo only

# (player_id, team_id, first, last, jersey, position, foot)
PLAYERS = [
    (21, 1, "Faisal", "Musa", 21, "Forward", "Right"),
    (7, 1, "Luka", "Petrovic", 7, "Winger", "Left"),
    (10, 1, "Marco", "Silva", 10, "Midfielder", "Right"),
    (4, 1, "Tomas", "Novak", 4, "Defender", "Right"),
    (9, 1, "Andrej", "Kovac", 9, "Striker", "Both"),
    (1, 2, "Ivan", "Horvat", 1, "Goalkeeper", "Right"),
    (14, 2, "Jan", "Dvorak", 14, "Midfielder", "Left"),
    (8, 2, "Mateo", "Rossi", 8, "Midfielder", "Right"),
    (22, 2, "Diego", "Ramirez", 5, "Defender", "Right"),
    (23, 2, "Noah", "Becker", 17, "Forward", "Left"),  # no stats -> excluded from /api/players/stats
]

# (player_id, match_id, top_speed_mph, distance_km, injury_risk)
STATS = [
    (21, 1, "19.20", "2.100", "Low"),    (21, 2, "18.50", "2.400", "Low"),
    (7, 1, "21.40", "3.000", "Low"),     (7, 2, "20.90", "2.800", "Medium"),
    (10, 1, "20.10", "3.300", "Medium"), (10, 2, "19.70", "3.000", "High"),
    (4, 1, "17.80", "5.100", "Low"),
    (9, 1, "22.00", "4.900", "Medium"),
    (1, 1, "14.60", "2.300", "Low"),
    (14, 1, "20.70", "3.600", "High"),   (14, 2, "19.90", "3.400", "Medium"),
    (8, 1, "18.90", "6.100", "Low"),
    (22, 2, "18.20", "5.400", "Medium"),
]


# Extra sample matches (step 6) so tags / results / insights have something to show. Player 21 is left out of
# them on purpose so the original /api/players/stats sample numbers stay the same.
# (match_id, home_team_id, away_team_id, date, home_score, away_score, our_side, tags)
EXTRA_MATCHES = [
    (3, 1, 3, date(2026, 8, 22), 2, 1, None, [("Weather", "Rainy"), ("Pitch", "Grass")]),
    (4, 4, 1, date(2026, 8, 29), 1, 1, "away", [("Weather", "Sunny"), ("Pitch", "Turf")]),
    (5, 1, 4, date(2026, 9, 5), 0, 2, None, [("Weather", "Rainy"), ("Pitch", "Turf")]),
    (6, 3, 1, date(2026, 9, 19), 1, 2, "away", [("Weather", "Sunny"), ("Pitch", "Grass")]),
    (7, 1, 3, date(2026, 10, 3), None, None, None, []),          # upcoming: no score, no data
]
# results/tags for the two original matches (both teams are the demo user's, so our_side matters)
ORIGINAL_MATCH_RESULTS = {1: (3, 1, "home", [("Weather", "Sunny"), ("Pitch", "Grass")]),
                          2: (0, 1, "away", [("Weather", "Rainy"), ("Pitch", "Turf")])}
# meta.json speed-threshold keys as the CV pipeline writes them (same values as the API fallback)
SEED_THRESHOLDS_META = {"speed_preset": mc.DEFAULT_SPEED_THRESHOLDS["preset"],
                        "hsr_threshold_kmh": mc.DEFAULT_SPEED_THRESHOLDS["hsr_kmh"],
                        "sprint_threshold_kmh": mc.DEFAULT_SPEED_THRESHOLDS["sprint_kmh"],
                        "zone_edges_kmh": dict(mc.DEFAULT_SPEED_THRESHOLDS["zone_edges_kmh"])}

# (match_id, video_id, [(player_id, top_speed, distance_km, risk)]) - Capstone FC players 7, 10, 4, 9
EXTRA_STATS = [
    (3, 2, [(7, 19.8, 2.4, "Low"), (10, 18.9, 2.7, "Medium"), (4, 16.9, 4.1, "Low"), (9, 20.6, 3.8, "Medium")]),
    (4, 3, [(7, 21.1, 3.2, "Low"), (10, 20.4, 3.5, "Medium"), (4, 17.5, 5.0, "Low"), (9, 21.5, 4.6, "Medium")]),
    (5, 4, [(7, 19.2, 2.2, "Medium"), (10, 18.3, 2.5, "High"), (4, 16.4, 3.9, "Low"), (9, 19.9, 3.5, "High")]),
    (6, 5, [(7, 21.6, 3.4, "Low"), (10, 20.8, 3.6, "Low"), (4, 17.9, 5.2, "Low"), (9, 21.9, 4.8, "Medium")]),
]
AVG_POS = {21: (70, 34), 7: (62, 12), 10: (52, 36), 4: (28, 30), 9: (78, 40), 1: (6, 34), 14: (50, 28),
           8: (48, 42), 22: (30, 50)}


def _sample_metrics(db, stat: PlayerMatchStat, rng: random.Random, minutes: float, with_heatmap: bool,
                   pipeline_grid: bool = False) -> None:
    """Plausible demo values in the shape of CV pipeline v1.2.0. pipeline_grid=True stores a heatmaps.json-style
    21x14 grid in seconds (source=pipeline); otherwise the backend's 12x8 sample-count grid (source=backend)."""
    dist = float(stat.distance_km)
    visible = round(minutes * rng.uniform(0.82, 0.95), 2)
    hsr_n, spr_n = rng.randint(8, 30), rng.randint(4, 18)
    zones = [rng.uniform(0.25, 0.35), rng.uniform(0.3, 0.4), rng.uniform(0.15, 0.2), rng.uniform(0.07, 0.1),
             rng.uniform(0.02, 0.05)]
    zones = [round(dist * z / sum(zones), 3) for z in zones]
    vals = {"minutes_played": minutes, "visible_minutes": visible, "coverage_pct": round(visible / minutes * 100, 1),
            "distance_per_min": round(dist * 1000 / visible, 2),
            "top_speed_kmh": round(float(stat.top_speed_mph) * 1.60934, 2),
            "hsr_distance_km": round(dist * rng.uniform(0.09, 0.14), 3),
            "sprint_distance_km": round(dist * rng.uniform(0.03, 0.05), 3),
            "hsr_count": float(hsr_n), "sprint_count": float(spr_n), "high_intensity_efforts": float(hsr_n + spr_n),
            "accels": float(rng.randint(3, 20)), "decels": float(rng.randint(3, 20)),
            **{f"zone{i}_distance_km": z for i, z in enumerate(zones, 1)}}
    x0, y0 = AVG_POS.get(stat.player_id, (52, 34))
    pts = [(min(max(rng.gauss(x0, 9), 0), 105), min(max(rng.gauss(y0, 7), 0), 68)) for _ in range(300)]
    cells, samples, mean = mc.heatmap(pts, 105.0, 68.0)
    vals["avg_pitch_x"], vals["avg_pitch_y"] = round(mean[0], 2), round(mean[1], 2)
    db.add_all([PlayerMatchMetric(stat_id=stat.stat_id, metric_key=k, value=v) for k, v in vals.items()])
    if with_heatmap and pipeline_grid:
        grid = [[0.0] * 21 for _ in range(14)]
        for x, y in pts:  # one sample every 2 s
            grid[min(int(y / 68 * 14), 13)][min(int(x / 105 * 21), 20)] += 2.0
        db.add(PlayerHeatmap(stat_id=stat.stat_id, grid_cols=21, grid_rows=14, pitch_length_m=105.0,
                             pitch_width_m=68.0, samples=samples, cells=json.dumps(grid), source="pipeline",
                             cell_unit="seconds"))
    elif with_heatmap:
        db.add(PlayerHeatmap(stat_id=stat.stat_id, grid_cols=mc.GRID_COLS, grid_rows=mc.GRID_ROWS,
                             pitch_length_m=105.0, pitch_width_m=68.0, samples=samples, cells=json.dumps(cells),
                             source="backend", cell_unit="samples"))

def seed() -> None:
    Base.metadata.create_all(bind=engine)  # no-op for tables that already exist

    with SessionLocal() as db:
        mc.ensure_definitions(db)
        # Clear in child -> parent order so FKs are never violated.
        for model in (PlayerMatchRisk, AthleteLog, CsvUpload, MatchTag, TagValue, TagKey, PlayerHeatmap, PlayerMatchMetric, TrackingDetection,
                      VideoPlayerOverride, PlayerTrack, PlayerMatchStat, MatchVideo, Match, Player, Team, User):
            db.execute(delete(model))
        db.commit()

        db.add(User(
            user_id=1, first_name="Faisal", last_name="Musa", email="faisal@example.com",
            password_hash=hash_password(DEMO_PASSWORD), role="admin",
        ))
        db.flush()
        db.add_all([
            Team(team_id=1, user_id=1, team_name="Capstone FC", league="College Premier"),
            Team(team_id=2, user_id=1, team_name="Rival United", league="College Premier"),
        ])
        db.flush()
        db.add_all([
            Player(player_id=pid, team_id=tid, first_name=fn, last_name=ln,
                   jersey_number=j, position=pos, dominant_foot=foot)
            for pid, tid, fn, ln, j, pos, foot in PLAYERS
        ])
        db.add_all([
            Match(match_id=1, home_team_id=1, away_team_id=2, match_date=date(2026, 9, 12),
                  stadium_name="University Stadium", weather_condition="Sunny", tactical_formation="4-3-3"),
            Match(match_id=2, home_team_id=2, away_team_id=1, match_date=date(2026, 9, 26),
                  stadium_name="Riverside Park", weather_condition="Rainy", tactical_formation="4-4-2"),
        ])
        db.flush()
        db.add(MatchVideo(video_id=1, match_id=1, user_id=1, title="Capstone FC vs Rival United (sample)",
                          file_name="match1_capstone_vs_rival.mp4",
                          file_path="videos/match1_capstone_vs_rival.mp4", fps=30.0,
                          processing_status="done", stage="done", progress=100,
                          pipeline_meta=json.dumps({"adapter_source": "seed", **SEED_THRESHOLDS_META,
                                                    "warnings": []})))
        db.flush()
        # Match 1 stats belong to sample video 1 (so /api/videos/1/stats works); match 2 rows are
        # legacy stats with no video (video_id NULL). Both count in /api/players/stats.
        db.add_all([
            PlayerMatchStat(player_id=pid, match_id=mid, video_id=1 if mid == 1 else None,
                            top_speed_mph=Decimal(s), distance_km=Decimal(d), injury_risk=r)
            for pid, mid, s, d, r in STATS
        ])
        db.add_all([
            TrackingDetection(video_id=1, player_id=pid, track_id=tid, frame_number=f,
                              object_class="player", jersey_number=None,
                              bbox_x1=x1, bbox_y1=y1, bbox_x2=x1 + 40, bbox_y2=y1 + 90,
                              confidence=c, pitch_x=px, pitch_y=py)
            for pid, tid, f, x1, y1, c, px, py in [
                (21, 1, 1, 612.0, 340.0, 0.94, 52.3, 34.1),
                (7, 2, 1, 830.5, 298.0, 0.91, 60.8, 20.4),
                (10, 3, 1, 455.0, 402.5, 0.88, 44.0, 40.2),
                (21, 1, 2, 618.0, 338.0, 0.95, 52.6, 34.0),
                (7, 2, 2, 836.0, 296.5, 0.90, 61.1, 20.2),
                (None, 7, 2, 1020.0, 250.0, 0.62, None, None),  # unidentified track
            ]
        ])
        db.flush()

        # ---- step 6 sample data: more matches, results, tags, extended metrics + heatmaps ----
        db.add_all([Team(team_id=3, user_id=1, team_name="Harbor City", league="College Premier"),
                    Team(team_id=4, user_id=1, team_name="Northside Athletic", league="College Premier")])
        db.flush()
        tag_plan = {}
        for mid, (hs, as_, side, tags) in ORIGINAL_MATCH_RESULTS.items():
            m = db.get(Match, mid)
            m.home_score, m.away_score, m.our_side = hs, as_, side
            tag_plan[mid] = tags
        for mid, home, away, d, hs, as_, side, tags in EXTRA_MATCHES:
            db.add(Match(match_id=mid, home_team_id=home, away_team_id=away, match_date=d, home_score=hs,
                         away_score=as_, our_side=side))
            tag_plan[mid] = tags
        db.flush()
        from match_logic import match_result
        for m in db.scalars(select(Match)).all():
            m.result = match_result(m, 1)
        for mid, tags in tag_plan.items():
            if tags:
                tagging.add_tags(db, 1, mid, tags)
        rng = random.Random(2026)
        for mid, vid, rows in EXTRA_STATS:
            db.add(MatchVideo(video_id=vid, match_id=mid, user_id=1, title=f"Sample match {mid} (seed)",
                              file_name=f"sample_match{mid}.mp4", file_path=f"videos/sample_match{mid}.mp4",
                              fps=30.0, processing_status="done", stage="done", progress=100,
                              pipeline_meta=json.dumps({"adapter_source": "seed", "duration_s": 3600.0,
                                                        "pipeline_version": "1.2.0", **SEED_THRESHOLDS_META,
                                                        "warnings": []})))
            db.flush()
            for pid, spd, dist, risk in rows:
                db.add(PlayerMatchStat(player_id=pid, match_id=mid, video_id=vid,
                                       top_speed_mph=Decimal(str(spd)), distance_km=Decimal(str(dist)),
                                       injury_risk=risk))
        db.flush()
        for st in db.scalars(select(PlayerMatchStat).order_by(PlayerMatchStat.stat_id)).all():
            # video 1 keeps the backend 12x8 grid (older pipeline), videos 2-5 look like pipeline v1.2.0 (21x14)
            _sample_metrics(db, st, rng, minutes=60.0, with_heatmap=st.video_id is not None,
                            pipeline_grid=st.video_id not in (None, 1))
        db.commit()

    with SessionLocal() as db:  # demo injury-risk rows (data_quality 'demo'); needs HEALTH_DATA_KEY
        try:
            import risk_service
            rows = risk_service.rescore_players(db, [p for p in db.scalars(select(Player.player_id)).all()])
            db.commit()
            print(f"Risk: {sum(r['score_status'] == 'scored' for r in rows)} demo row(s) scored")
        except Exception as e:  # noqa: BLE001
            print(f"Risk scoring skipped: {e}")

    print(f"Seeded: 1 user, 4 teams, {len(PLAYERS)} players, {2 + len(EXTRA_MATCHES)} matches (with results/tags), "
          f"{len(STATS) + sum(len(r) for _, _, r in EXTRA_STATS)} player_match_stats (+ metrics/heatmaps), "
          f"{1 + len(EXTRA_STATS)} match_videos, 6 tracking_detections.\n"
          f"Demo login: {DEMO_EMAIL} / {DEMO_PASSWORD}")


if __name__ == "__main__":
    seed()
