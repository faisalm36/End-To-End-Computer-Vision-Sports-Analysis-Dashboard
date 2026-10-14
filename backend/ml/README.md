# Player fatigue & injury-risk model (v0.7.0)

> **Not medical advice.** This is a decision-support demo for a capstone project. It is trained on a **synthetic
> proxy dataset**, has **never been validated against real injuries**, and must not be used to make medical,
> selection or return-to-play decisions. Treat `risk_percent` as "how much this session's workload pattern
> resembles patterns the sports-science literature associates with elevated risk", not as a probability of injury.

## Files
| File | What |
|---|---|
| `features.py` | **The one place** that turns app data into model features (`FEATURES`, `stat_values`, `match_features`, `csv_features`, display features). Remap here when the CV feature mapping changes. |
| `train_risk_model.py` | Seeded (`SEED=20261008`), reproducible generator + training. `python -m ml.train_risk_model` writes the two files below. |
| `risk_model.joblib` | sklearn `Pipeline(SimpleImputer(median) -> StandardScaler -> LogisticRegression)` + metadata. |
| `risk_model.meta.json` | Features, coefficients, intercept, imputer medians, metrics, seed, label rule, library versions, `trained_at`. |
| `scorer.py` | Loads the artifact once, scores a batch, returns `risk_percent`, level, per-feature contributions, top-5 factors. |
| `backfill_risk.py` | `python -m ml.backfill_risk [--dry-run]`: (re)score every existing stats row / CSV log. |
| `../risk_service.py` | Gates, per-player timelines (ACWR history), encrypted persistence, read helpers. |

## Model
* **Type:** logistic regression (L2, C=1.0) on standardised features, median imputation for missing values.
* **Output:** `risk_percent = 100 * P(label=1)`. Levels: **red >= 70, yellow 40-69.9, green < 40**
  (`RISK_RED_THRESHOLD` / `RISK_YELLOW_THRESHOLD` in `.env`).
* **Explainability:** contribution_i = coef_i x scaled_value_i (log-odds). `sum(contributions) + intercept = logit(risk/100)`.
  The API's `factors` are the top 5 **measured** features by |contribution| (imputed features are left out because
  they were not observed); `direction` = up (raises risk) / down.
* **Missing heart rate:** one model with an `hr_missing` indicator; HR is imputed with the training median when absent.
  Chosen over two models because it keeps one set of coefficients to explain, and the hold-out AUC with vs without HR
  is reported below. Missing HSR / minutes are imputed the same way (no indicator).

### Features (all exposure-normalised so CSV logs and CV clips share a scale)
| Feature | Meaning | CSV athlete log | CV row (calibrated only) |
|---|---|---|---|
| `acwr` | acute:chronic ratio of session load = this session / mean of previous <= 4 sessions (same player, same source) | load = gps_distance (km) | load = distance per visible minute (clips are partial, totals not comparable) |
| `distance_m_per_min` | distance / exposure minutes | gps_distance / minutes_played | distance_km / visible_minutes |
| `sprints_per_90` | sprints per 90 min of exposure | sprints / minutes_played x 90 | sprint_count / visible_minutes x 90 (never hi_efforts) |
| `hsr_m_per_min` | high-speed running per minute | not in CSV (imputed) | hsr_distance_km / visible_minutes |
| `top_speed_kmh` | peak speed | top_speed_kmh | top_speed_kmh (or mph x 1.609344) |
| `minutes_played` | time on the pitch | minutes_played | **null** (visible_minutes is exposure, never time on the pitch) |
| `heart_rate_avg` | average HR (bpm) | heart_rate | CSV heart_rate logged for that player **on the match date**, else missing |
| `hr_missing` | 1 when no HR | | |

**Never used as features:** `injury_risk` and `fatigue_risk_score` (ingest defaults), `high_intensity_efforts`
(= hsr_count + sprint_count, double counts), `accels`/`decels` (not reliably produced by the CV; display only, null
when absent, never fabricated), `heart_rate_max` (display only).

## Scoring gates (from the CV Engineer, verified against cv origin/main 52354fa)
CV physical-load numbers are not trustworthy without a custom pitch calibration. A CV stats row is scored only if ALL hold:

| Gate | Rule | Fails as |
|---|---|---|
| (a) | `distance_valid` is not false (video meta or any of the player's tracks) **and** distance_km is not null | uncalibrated (distance_valid=false) / insufficient_data (distance missing) |
| (b) | `meta.calibration` is a real custom path: not null, not `none`, not `default_calibration.json` (calibration_quality can't tell them apart) | uncalibrated |
| (c) | `visible_minutes >= 1` | insufficient_data |
| (d) | counts/distances are normalised by visible_minutes before the model (see table) | (by construction) |
| (e) | players without a roster match (placeholder "Unknown #.." players) are not scored and not merged across videos | insufficient_data (no roster match) |

Rows failing a gate are **stored** with `risk_percent = null`, `level = 'unknown'`, `score_status` =
`uncalibrated` (any calibration/distance_valid failure) or `insufficient_data`, and `score_note` listing every failed gate.
`data_quality`: `calibrated` (real CV, gates a+b pass), `csv` (athlete logs), `demo` (stub / seed rows or stats without
a video: scored with gates a-distance, c-exposure (visible_minutes, else minutes_played) and e only), `null` (uncalibrated CV).
CSV rows are scored when at least one load value (gps_distance, heart_rate, sprints, top_speed) is present.
**CSV athlete logs are the main real scoring path right now.** The gate facts the CV gives at ingest
(placeholder players, per-player distance_valid) are kept in `match_videos.pipeline_meta.risk_gate` so rescoring and
backfill apply the same gates later.

The roster's "latest" score per player = newest date among **scored** rows (a gated row only if nothing was ever
scored); on the same date a match row beats a CSV row.

## Training data (synthetic proxy, clearly labelled)
No public dataset with per-match GPS load, heart rate **and** injury labels was integrated, so the model is trained on
a synthetic dataset generated by `train_risk_model.generate()`: 400 players x 24 matches = 9,600 rows. Each player
has a latent fitness level, a baseline distance and HR; each session has minutes (subs included) and a load multiplier
with occasional spikes (12% x1.35) and dips (6% x0.65) that create ACWR variation. Masking mimics real inputs: HR
missing in 45% of rows, HSR in 50%, minutes in 15%.

**Label rule (proxy "elevated-risk session", not an injury):**

    logit = -1.35 + 3.0 x (ACWR - 1) + 0.50 z(HSR m/min) + 0.50 z(sprints/90) + 0.70 z(avg HR)
            + 0.35 z(minutes) + 0.30 z(distance m/min) + N(0, 0.6)
    label ~ Bernoulli(sigmoid(logit))           # prevalence ~ 34%

Grounding (direction of effects, not magnitudes):
* Gabbett TJ. *The training-injury prevention paradox.* Br J Sports Med 2016;50:273-280 (ACWR spikes).
* Hulin BT et al. *The acute:chronic workload ratio predicts injury...* Br J Sports Med 2016;50:231-236.
* Bowen L et al. *Accumulated workloads and the ACWR relate to injury risk in elite youth football players.* Br J Sports Med 2017;51:452-459.
* HSR / sprint terms are a **modelling assumption** (acute high-speed load raising risk); the evidence is mixed - e.g. Malone S et al. (J Sci Med Sport 2017) found high *chronic* exposure to maximal-velocity running protective.
* Impellizzeri FM et al. *Use of RPE-based training load in soccer.* Med Sci Sports Exerc 2004;36:1042-1047 (internal load).
* Counterpoint: Impellizzeri FM et al. *Acute:chronic workload ratio: conceptual issues and fundamental pitfalls.* IJSPP 2020 - ACWR is debated.

## Hold-out metrics (whole players held out, 25%; threshold 0.5)
holdout_rows 2400 | train_rows 7200 | prevalence 0.3385 | accuracy 0.8275 | roc_auc 0.8942 | precision 0.7801 | recall 0.6637 | brier 0.1202 | threshold 0.5 | roc_auc_with_hr 0.9044 | roc_auc_without_hr 0.8821

These measure how well the model recovers **its own synthetic label rule**; they say nothing about real-world accuracy.

## Limitations
* Synthetic labels: the model can only be as right as the label rule. Replace with real, consented injury data before any real use.
* Logistic regression is linear in the (scaled) features: no U-shape for very low ACWR, no interactions.
* ACWR needs history: the first session of each player has no ACWR (imputed). CSV and CV histories are kept separate.
* CV inputs are only used when calibrated (gates); uncalibrated CV clips are shown as `uncalibrated`.
* Heart rate comes only from CSV logs; matches without a same-day CSV HR are scored with `hr_missing = 1`.

## Security
Heart rate (`athlete_logs.heart_rate_enc`, `heart_rate_max_enc`), risk scores (`player_match_risk.risk_percent_enc`)
and the feature/contribution snapshot (`details_enc`, contains HR) are encrypted with **AES-256-GCM**: random 96-bit
nonce per value, stored as base64(nonce || ciphertext || tag), key = `HEALTH_DATA_KEY` (base64 of 32 bytes, backend/.env).
`level`, `score_status`, `score_note`, `data_quality` stay plaintext (needed for filtering; coarse). Passwords are
bcrypt-hashed (unchanged). Losing the key makes the encrypted values unreadable: back it up with the DB backups.

## Retraining
    cd backend && .venv/bin/python -m ml.train_risk_model && .venv/bin/python -m ml.backfill_risk
scikit-learn / numpy / joblib are pinned in requirements.txt because the artifact is a pickle.
