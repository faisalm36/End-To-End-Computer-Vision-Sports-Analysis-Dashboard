"""Score every existing player_match_stats / athlete_logs row (deploy step after migration 010).

    cd backend && .venv/bin/python -m ml.backfill_risk            # all players
    cd backend && .venv/bin/python -m ml.backfill_risk --dry-run  # compute + summarise, write nothing

Needs HEALTH_DATA_KEY in backend/.env (never printed). Idempotent: replaces each player's risk rows.
"""
import argparse
import sys
import time
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from sqlalchemy import select  # noqa: E402

import risk_service as rs  # noqa: E402
from database import SessionLocal  # noqa: E402
from models import AthleteLog, PlayerMatchStat  # noqa: E402


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()
    t0 = time.perf_counter()
    with SessionLocal() as db:
        pids = sorted(set(db.scalars(select(PlayerMatchStat.player_id)).all())
                      | set(db.scalars(select(AthleteLog.player_id)).all()))
        try:
            rows = rs.compute(db, pids) if args.dry_run else rs.rescore_players(db, pids)
        except rs.RiskUnavailable as e:
            print(f"ERROR: {e}")
            return 2
        if not args.dry_run:
            db.commit()
    status = Counter(r["score_status"] for r in rows)
    quality = Counter(str(r["data_quality"]) for r in rows)
    levels = Counter(r["level"] for r in rows)
    print(f"{'DRY RUN: ' if args.dry_run else ''}players={len(pids)} rows={len(rows)} status={dict(status)} "
          f"data_quality={dict(quality)} levels={dict(levels)} in {(time.perf_counter() - t0) * 1000:.0f} ms")
    return 0


if __name__ == "__main__":
    sys.exit(main())
