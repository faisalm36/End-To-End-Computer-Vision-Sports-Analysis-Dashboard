"""Train the fatigue / injury-risk model on a SYNTHETIC proxy dataset (seeded, reproducible).

    cd backend && .venv/bin/python -m ml.train_risk_model          # writes ml/risk_model.joblib + .meta.json

Model: sklearn Pipeline(SimpleImputer(median) -> StandardScaler -> LogisticRegression). Explainable: per-feature
contribution = coef_i * scaled_value_i (log-odds), summed with the intercept = the logit of risk_percent/100.
Data + label rule: see generate() and ml/README.md. This is NOT a validated clinical model.
"""
import json
import math
import sys
from datetime import datetime, timezone
from pathlib import Path

import joblib
import numpy as np
import pandas as pd
import sklearn
from sklearn.impute import SimpleImputer
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import accuracy_score, brier_score_loss, precision_score, recall_score, roc_auc_score
from sklearn.model_selection import train_test_split
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import StandardScaler

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from ml.features import ACWR_CHRONIC_WINDOW, FEATURES  # noqa: E402

MODEL_VERSION = "risk-lr-0.7.0"
SEED = 20261008
N_PLAYERS, N_MATCHES = 400, 24
HR_MISSING_RATE = 0.45      # most matches come from video (no HR); CSV logs add it
OUT = Path(__file__).resolve().parent
MODEL_PATH, META_PATH = OUT / "risk_model.joblib", OUT / "risk_model.meta.json"


def _sig(x):
    return 1.0 / (1.0 + np.exp(-x))


def generate(seed: int = SEED) -> pd.DataFrame:
    """Synthetic per-player-per-match workloads + a PROXY 'elevated-risk session' label.

    Session load for ACWR = total distance (km); rates are normalised by minutes (exposure).
    Label rule (proxy, grounded in the workload-injury literature; see README):
      logit = -1.35
              + 3.0  * (ACWR - 1.0)              acute spike vs chronic load (Gabbett 2016; Hulin 2016; Bowen 2017)
              + 0.50 * z(HSR m/min)              high-speed running (modelling assumption)
              + 0.50 * z(sprints per 90)
              + 0.70 * z(avg heart rate)         internal load (Impellizzeri 2004)
              + 0.35 * z(minutes played)         exposure
              + 0.30 * z(distance m/min)
              + N(0, 0.6) noise
      label ~ Bernoulli(sigmoid(logit)). True values drive the label even where a column is masked (not measured).
    Masking mimics real inputs: HR missing in 45% of rows (video-only), HSR in 50% (CSV logs lack it),
    minutes in 15% (CV rows: visible_minutes is exposure, not time on the pitch).
    """
    rng = np.random.default_rng(seed)
    rows = []
    for p in range(N_PLAYERS):
        fitness = rng.normal(0, 1)
        base_km = rng.normal(10.3, 0.8) + 0.25 * fitness
        hr_rest = rng.normal(158, 6) - 2.0 * fitness
        hist = []
        for m in range(N_MATCHES):
            minutes = float(rng.choice([90, 90, 90, 90, 85, 75, 60, 45, 30, 20]))
            load = rng.lognormal(0, 0.12) * (rng.choice([1.0, 1.35, 0.65], p=[0.82, 0.12, 0.06]))
            dist = max(0.3, base_km * minutes / 90 * load + rng.normal(0, 0.3))
            hsr = max(0.0, dist * rng.normal(0.075, 0.018) * load ** 0.8)
            sprints = float(rng.poisson(max(0.1, 2.0 * dist * load * rng.uniform(0.7, 1.3))))
            top = float(np.clip(rng.normal(30.5 + 0.8 * fitness, 1.6) + 0.8 * (load - 1), 22, 37))
            hr = float(np.clip(hr_rest + 14 * (load - 1) + rng.normal(0, 4), 120, 195))
            prior = [x for x in hist[-ACWR_CHRONIC_WINDOW:] if x > 0]
            acwr = min(dist / (sum(prior) / len(prior)), 5.0) if prior else np.nan
            rows.append({"player": p, "match": m, "acwr": acwr, "distance_m_per_min": dist * 1000 / minutes,
                         "sprints_per_90": sprints / minutes * 90, "hsr_m_per_min": hsr * 1000 / minutes,
                         "top_speed_kmh": top, "minutes_played": minutes, "heart_rate_true": hr})
            hist.append(dist)
    df = pd.DataFrame(rows)
    z = lambda c: (df[c] - df[c].mean()) / df[c].std()  # noqa: E731
    logit = (-1.35 + 3.0 * (df["acwr"].fillna(1.0) - 1.0) + 0.50 * z("hsr_m_per_min") + 0.50 * z("sprints_per_90")
             + 0.70 * z("heart_rate_true") + 0.35 * z("minutes_played") + 0.30 * z("distance_m_per_min")
             + rng.normal(0, 0.6, len(df)))
    df["label"] = (rng.uniform(size=len(df)) < _sig(logit)).astype(int)
    hr_missing = rng.uniform(size=len(df)) < HR_MISSING_RATE
    df["heart_rate_avg"] = np.where(hr_missing, np.nan, df["heart_rate_true"])
    df["hr_missing"] = hr_missing.astype(float)
    df.loc[rng.uniform(size=len(df)) < 0.50, "hsr_m_per_min"] = np.nan
    df.loc[rng.uniform(size=len(df)) < 0.15, "minutes_played"] = np.nan
    return df


def build_pipeline() -> Pipeline:
    return Pipeline([("impute", SimpleImputer(strategy="median")), ("scale", StandardScaler()),
                     ("model", LogisticRegression(C=1.0, max_iter=2000))])


def train(seed: int = SEED, write: bool = True) -> dict:
    df = generate(seed)
    X, y = df[FEATURES], df["label"].to_numpy()
    groups = df["player"].unique()
    tr_players, te_players = train_test_split(groups, test_size=0.25, random_state=seed)  # hold out whole players
    tr, te = df["player"].isin(tr_players).to_numpy(), df["player"].isin(te_players).to_numpy()
    pipe = build_pipeline().fit(X[tr], y[tr])
    p = pipe.predict_proba(X[te])[:, 1]
    pred = (p >= 0.5).astype(int)
    metrics = {"holdout_rows": int(te.sum()), "train_rows": int(tr.sum()), "prevalence": round(float(y.mean()), 4),
               "accuracy": round(accuracy_score(y[te], pred), 4), "roc_auc": round(roc_auc_score(y[te], p), 4),
               "precision": round(precision_score(y[te], pred, zero_division=0), 4),
               "recall": round(recall_score(y[te], pred, zero_division=0), 4),
               "brier": round(brier_score_loss(y[te], p), 4), "threshold": 0.5}
    hr_rows = te & (df["hr_missing"].to_numpy() == 0)
    if hr_rows.any():
        metrics["roc_auc_with_hr"] = round(roc_auc_score(y[hr_rows], pipe.predict_proba(X[hr_rows])[:, 1]), 4)
        no_hr = te & ~hr_rows
        metrics["roc_auc_without_hr"] = round(roc_auc_score(y[no_hr], pipe.predict_proba(X[no_hr])[:, 1]), 4)
    model = pipe.named_steps["model"]
    meta = {
        "model_version": MODEL_VERSION, "model_type": "LogisticRegression (StandardScaler, median imputer) in an sklearn Pipeline",
        "features": FEATURES, "coefficients": dict(zip(FEATURES, [round(float(c), 5) for c in model.coef_[0]])),
        "intercept": round(float(model.intercept_[0]), 5),
        "imputer_medians": dict(zip(FEATURES, [None if math.isnan(v) else round(float(v), 4)
                                               for v in pipe.named_steps["impute"].statistics_])),
        "metrics": metrics, "seed": seed, "n_players": N_PLAYERS, "n_matches_per_player": N_MATCHES,
        "training_data": "SYNTHETIC proxy dataset generated by ml/train_risk_model.py (no real injury labels)",
        "label_rule": "Bernoulli(sigmoid(-1.35 + 3.0*(ACWR-1) + 0.50*z(HSR m/min) + 0.50*z(sprints/90) + 0.70*z(HR) "
                      "+ 0.35*z(minutes) + 0.30*z(distance m/min) + N(0,0.6))) = proxy 'elevated-risk session', "
                      "not an injury",
        "hr_handling": "single model: hr_missing indicator + HR imputed with the training median when absent",
        "trained_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "sklearn_version": sklearn.__version__, "numpy_version": np.__version__, "pandas_version": pd.__version__,
        "disclaimer": "Decision-support demo on synthetic data. Not medical advice; not validated on real injuries.",
    }
    if write:
        joblib.dump({"pipeline": pipe, "meta": meta}, MODEL_PATH)
        META_PATH.write_text(json.dumps(meta, indent=2) + "\n")
    return meta


if __name__ == "__main__":
    m = train()
    print(json.dumps({"model_version": m["model_version"], "metrics": m["metrics"],
                      "coefficients": m["coefficients"]}, indent=2))
