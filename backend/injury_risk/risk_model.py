"""Roster injury-risk scoring (pure Python, no DB). Model version: rir-1.0.

NOT MEDICAL ADVICE. An explainable, literature-informed screening index for coaches/players.
It is not a validated clinical prediction model and must not be used to clear or bar a player.

Model:  p = 1 - exp(-lambda0 * hours * M),  M = product of factor multipliers (capped at M_CAP)
        score = 100 * p / p_max   (p_max = p at M_CAP for a 90-min match), bands low/moderate/high.
Each multiplier is tagged 'evidence' (value taken from a cited study) or 'design' (our choice). See model.md.
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field
from datetime import date, timedelta
from typing import Optional

MODEL_VERSION = "rir-1.0"

# --- constants -----------------------------------------------------------------------------------------------
LAMBDA0_MATCH = 27.5 / 1000.0   # evidence: match injuries / player-hour, Ekstrand 2011 UEFA study
M_CAP = 8.0                     # design
BANDS = ((25.0, "low"), (50.0, "moderate"), (101.0, "high"))   # design

PREV_INJURY_HR = 2.7            # evidence: Hägglund 2006 (any injury next season)
PREV_INJURY_HALF_LIFE_D = 180   # design: decay of the prior-injury effect after return to play
PREV_INJURY_LOOKBACK_D = 730    # design: ignore injuries that ended >2 years ago (unless recurrent)
RECENT_RETURN_D = 56            # design: re-injury window (8 wks); Ekstrand 2011: re-injuries 12% of injuries
RECENT_RETURN_MULT = 1.5        # design
SAME_SITE_MULT = 1.5            # design, informed by Hägglund 2006 (2-3x identical) & Arnason 2004 (OR 4.6-11.6)
RECURRENT_MULT = 1.25           # design: >=2 injuries at same body part
SEVERE_DAYS = 28                # evidence-style cut: UEFA severity "severe" >28 days
SEVERE_MULT = 1.15              # design
MUSCLE_SITES = {"hamstring", "groin", "quadriceps", "calf", "adductor"}
JOINT_SITES = {"ankle", "knee", "foot"}

CONGESTION_DAYS = 4             # evidence: Bengtsson 2013 (<=4 vs >=6 days)
CONGESTION_RR = 1.09            # evidence: total injury RR
CONGESTION_MUSCLE_RR = 1.32     # evidence: muscle injury RR, used if player has a prior muscle injury

AGE_REF = 28                    # design
AGE_STEP = 1.03                 # design: attenuated vs Arnason OR 1.1/yr (Hägglund 2006 found no age effect)
AGE_CAP = 1.3                   # design

TURF_ANKLE_RR = 1.81            # evidence: Ekstrand 2006 ankle sprain in matches on 3G turf vs grass
TURF_STREAK_STEP = 0.05         # design: per decayed recent turf match, only for prior lower-limb joint injury
TURF_STREAK_CAP = 1.25          # design
TURF_STREAK_DECAY = 0.7         # design: weight of each older match (most recent = 1)
SURFACE_SWITCH_MULT = 1.05      # design: Williams 2011 notes switching surfaces "may be a precursor"

ACWR_HIGH, ACWR_HIGH_MULT = 1.5, 1.15   # design, deliberately small (Impellizzeri 2020 criticism)
ACWR_LOW, ACWR_LOW_MULT = 0.8, 1.05     # design
ACWR_MIN_CHRONIC_MATCHES = 3


@dataclass
class Injury:
    body_part: str               # e.g. hamstring, ankle, knee, groin, other
    injury_date: date
    days_missed: int = 0
    injury_type: str = ""        # muscle strain, ligament sprain, fracture, contusion, ...
    side: str = ""
    return_date: Optional[date] = None

    @property
    def end(self) -> date:
        return self.return_date or (self.injury_date + timedelta(days=max(0, self.days_missed)))


@dataclass
class MatchLoad:
    match_date: date
    surface: Optional[str] = None          # 'turf' | 'grass' | None
    minutes: Optional[float] = None
    distance_km: Optional[float] = None
    hsr_m: Optional[float] = None           # high-speed running metres
    sprints: Optional[int] = None


@dataclass
class Factor:
    key: str
    label: str
    multiplier: float
    basis: str                   # 'evidence' | 'design'
    detail: str = ""


@dataclass
class RiskResult:
    as_of: date
    score: float
    band: str
    probability: float
    multiplier: float
    confidence: str
    factors: list = field(default_factory=list)
    model_version: str = MODEL_VERSION
    status: str = "scored"       # 'scored' | 'injured'


def band_for(score: float) -> str:
    for upper, name in BANDS:
        if score < upper:
            return name
    return "high"


def _p(mult: float, hours: float) -> float:
    return 1.0 - math.exp(-LAMBDA0_MATCH * hours * mult)


P_MAX = _p(M_CAP, 1.5)


def _norm(s: Optional[str]) -> Optional[str]:
    if s is None:
        return None
    s = s.strip().lower()
    return {"artificial": "turf", "artificial turf": "turf", "3g": "turf", "synthetic": "turf",
            "natural": "grass", "natural grass": "grass"}.get(s, s) or None


def _injury_factors(injuries, as_of):
    out = []
    past = [i for i in injuries if i.injury_date <= as_of]
    active = [i for i in past if i.end > as_of]
    if active:
        return out, True
    relevant = [i for i in past if (as_of - i.end).days <= PREV_INJURY_LOOKBACK_D]
    if relevant:
        last = max(relevant, key=lambda i: i.end)
        since = (as_of - last.end).days
        decay = 0.5 ** (since / PREV_INJURY_HALF_LIFE_D)
        m = 1.0 + (PREV_INJURY_HR - 1.0) * decay
        out.append(Factor("previous_injury", "Previous injury", m, "evidence",
                          f"HR {PREV_INJURY_HR} decayed, {since} d since return from {last.body_part}"))
        if since <= RECENT_RETURN_D:
            out.append(Factor("recent_return", "Recently returned from injury", RECENT_RETURN_MULT, "design",
                              f"returned {since} d ago (<= {RECENT_RETURN_D} d window)"))
        if last.days_missed > SEVERE_DAYS:
            out.append(Factor("severe_injury", "Last injury was severe (>28 d)", SEVERE_MULT, "design",
                              f"{last.days_missed} days missed"))
    by_part = {}
    for i in past:
        by_part.setdefault(i.body_part.lower(), []).append(i)
    recurrent = [p for p, lst in by_part.items() if len(lst) >= 2 and p != "other"]
    if recurrent:
        out.append(Factor("recurrent_site", "Recurrent injury at same site", RECURRENT_MULT, "design",
                          ", ".join(sorted(recurrent))))
    return out, False


def _load_factors(matches, as_of, next_surface, injuries):
    out, notes = [], []
    hist = sorted([m for m in matches if m.match_date < as_of], key=lambda m: m.match_date)
    parts = {i.body_part.lower() for i in injuries if i.injury_date <= as_of}
    # congestion
    if hist:
        rest = (as_of - hist[-1].match_date).days
        if rest <= CONGESTION_DAYS:
            muscle = bool(parts & MUSCLE_SITES)
            rr = CONGESTION_MUSCLE_RR if muscle else CONGESTION_RR
            out.append(Factor("congestion", "Short recovery between matches", rr, "evidence",
                              f"{rest} d rest (Bengtsson 2013 {'muscle' if muscle else 'total'} RR)"))
    # surface
    ns = _norm(next_surface)
    joint = bool(parts & JOINT_SITES)
    if ns == "turf":
        if parts & {"ankle", "foot"}:
            out.append(Factor("turf_ankle", "Turf + prior ankle/foot injury", TURF_ANKLE_RR, "evidence",
                              "Ekstrand 2006 ankle sprain RR on 3G turf"))
        if joint:
            w, streak = 1.0, 0.0
            for m in reversed(hist[-5:]):
                if _norm(m.surface) == "turf":
                    streak += w
                elif _norm(m.surface) == "grass":
                    break
                w *= TURF_STREAK_DECAY
            if streak > 0:
                mult = min(TURF_STREAK_CAP, 1.0 + TURF_STREAK_STEP * streak * 2)
                out.append(Factor("turf_streak", "Consecutive turf matches", round(mult, 4), "design",
                                  f"weighted turf streak {streak:.2f}"))
    if ns in ("turf", "grass") and hist and _norm(hist[-1].surface) in ("turf", "grass") \
            and _norm(hist[-1].surface) != ns:
        out.append(Factor("surface_switch", "Switching playing surface", SURFACE_SWITCH_MULT, "design",
                          f"{_norm(hist[-1].surface)} -> {ns}"))
    if ns is None:
        notes.append("next-match surface unknown")
    # ACWR on high-speed running (fallback distance): acute = last 7 d, chronic = mean weekly over 28 d
    def load(m):
        return m.hsr_m if m.hsr_m is not None else (m.distance_km * 1000 if m.distance_km is not None else None)
    acute = [load(m) for m in hist if (as_of - m.match_date).days <= 7]
    chronic = [load(m) for m in hist if (as_of - m.match_date).days <= 28]
    if len(chronic) >= ACWR_MIN_CHRONIC_MATCHES and None not in chronic and None not in acute:
        c = sum(chronic) / 4.0
        a = sum(acute)
        if c > 0:
            r = a / c
            if r > ACWR_HIGH:
                out.append(Factor("acwr_high", "Load spike (ACWR)", ACWR_HIGH_MULT, "design", f"ACWR {r:.2f}"))
            elif r < ACWR_LOW and a > 0:
                out.append(Factor("acwr_low", "Under-loaded (ACWR)", ACWR_LOW_MULT, "design", f"ACWR {r:.2f}"))
    else:
        notes.append("not enough load history for ACWR")
    return out, notes


def score_player(as_of: date, injuries=(), matches=(), age: Optional[int] = None,
                 next_surface: Optional[str] = None, expected_minutes: float = 90.0) -> RiskResult:
    injuries, matches = list(injuries), list(matches)
    inj_f, injured = _injury_factors(injuries, as_of)
    if injured:
        return RiskResult(as_of, 100.0, "high", 1.0, M_CAP, "high",
                          [Factor("currently_injured", "Currently injured", M_CAP, "design", "not available")],
                          status="injured")
    load_f, notes = _load_factors(matches, as_of, next_surface, injuries)
    factors = inj_f + load_f
    if age is not None and age > AGE_REF:
        factors.append(Factor("age", "Age", min(AGE_CAP, AGE_STEP ** (age - AGE_REF)), "design",
                              f"age {age}"))
    elif age is None:
        notes.append("age unknown")
    m = 1.0
    for f in factors:
        m *= f.multiplier
    m = min(m, M_CAP)
    hours = max(0.0, expected_minutes) / 60.0
    p = _p(m, hours)
    score = round(min(100.0, 100.0 * p / P_MAX), 1)
    have_hist = bool(injuries) or len(matches) >= ACWR_MIN_CHRONIC_MATCHES
    confidence = "low" if not have_hist else ("medium" if notes else "high")
    res = RiskResult(as_of, score, band_for(score), round(p, 4), round(m, 4), confidence, factors)
    res.notes = notes
    return res


def score_history(injuries, matches, age=None):
    """Previous scores: one per past match, scored as of that match day with that match's surface."""
    out = []
    for mt in sorted(matches, key=lambda m: m.match_date):
        out.append(score_player(mt.match_date, injuries, matches, age, mt.surface,
                                mt.minutes if mt.minutes else 90.0))
    return out


def project_next(as_of, next_match_date, next_surface, injuries, matches, age=None, expected_minutes=90.0):
    return score_player(next_match_date, injuries, [m for m in matches if m.match_date <= as_of],
                        age, next_surface, expected_minutes)
