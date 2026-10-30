# Roster Injury Risk model rir-1.0

> **Disclaimer:** screening/education index only, not medical advice or a diagnosis. Return-to-play and selection decisions belong to qualified medical staff.

## Formula
`p = 1 − exp(−λ0 · h · M)`, `score = 100 · p / p_max`, where
- λ0 = 27.5 injuries / 1000 match-hours (Ekstrand 2011), h = expected minutes / 60
- M = product of multipliers below, capped at 8 (design); p_max = p at M=8, 90 min (≈28%)
- Bands (design): low < 25 ≤ moderate < 50 ≤ high. A baseline player scores ≈14 (≈4% per 90 min).
- `p` is shown as a "relative indicator", not a calibrated probability, until validated on our own data.

## Factors
| Factor | Multiplier | Basis |
|---|---|---|
| Previous injury (≤2 y) | 1 + 1.7·0.5^(days since return/180) → 2.7 at return | HR 2.7 evidence; decay design |
| Returned ≤56 days ago | ×1.5 | design (re-injury window) |
| Last injury severe (>28 d missed) | ×1.15 | design |
| Recurrent injury at same body part (≥2) | ×1.25 | design, informed by Hägglund/Arnason |
| ≤4 days since last match | ×1.09 (×1.32 if prior muscle injury) | evidence (Bengtsson 2013) |
| Next match on turf + prior ankle/foot injury | ×1.81 | evidence (Ekstrand 2006) |
| Turf streak (prior ankle/knee/foot injury, next match turf) | 1 + 0.1·Σ0.7^k over consecutive recent turf matches, cap 1.25 | **design** |
| Surface switch (last ≠ next) | ×1.05 | design (Williams 2011 hypothesis) |
| ACWR (HSR, else distance) >1.5 / <0.8 | ×1.15 / ×1.05 | design, contested (Impellizzeri) |
| Age >28 | 1.03^(age−28), cap 1.3 | design |
| Currently injured | status "injured", score 100 | — |

## Current / previous / projected
- **Current**: as of today, next surface unknown, 90 min.
- **Previous**: one snapshot per past match, scored as of match day with that match's surface and minutes -> trend line.
- **Projected**: as of next match date, given its surface (param), using only matches already played; congestion uses days from last match to the next fixture.

Example (prior ankle sprain 120 d ago, last 3 matches on turf, age 27): next on grass 31.8 (moderate); next on turf 63.5 (high).

## Missing data
Unknown factors are neutral (×1). Confidence: low = no injuries entered and <3 matches; medium = some inputs missing (surface, ACWR, age); high otherwise. Players with no system history are prompted to enter injury history (body part, type, side, date, days missed / return date).

## Validation plan
Log real injuries -> compare snapshot scores vs subsequent injuries (Brier score, AUC); refit design weights (e.g. Poisson/Cox) once enough events exist.
