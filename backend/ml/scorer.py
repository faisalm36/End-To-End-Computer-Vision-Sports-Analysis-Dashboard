"""Score feature rows with the trained risk model. Vectorised: one pipeline call per batch (fast)."""
import threading
from pathlib import Path
from typing import Optional

import joblib
import numpy as np
import pandas as pd

from config import settings
from ml.features import FEATURES, LABELS

_lock = threading.Lock()
_cache: dict = {}


class RiskModelError(RuntimeError):
    pass


def load(path: Optional[Path] = None) -> tuple:
    """(pipeline, meta). Cached per path. Raises RiskModelError if missing/incompatible."""
    path = Path(path or settings.RISK_MODEL_PATH)
    with _lock:
        if path in _cache:
            return _cache[path]
        if not path.is_file():
            raise RiskModelError(f"risk model not found at {path} (run: python -m ml.train_risk_model)")
        try:
            art = joblib.load(path)
            pipe, meta = art["pipeline"], art["meta"]
        except Exception as e:  # noqa: BLE001
            raise RiskModelError(f"could not load risk model {path}: {type(e).__name__}: {e}") from e
        if list(meta.get("features") or []) != FEATURES:
            raise RiskModelError("risk model features do not match ml/features.FEATURES; retrain the model")
        _cache[path] = (pipe, meta)
        return pipe, meta


def model_version() -> str:
    return load()[1]["model_version"]


def level_for(risk_percent: Optional[float]) -> Optional[str]:
    if risk_percent is None:
        return None
    if risk_percent >= settings.RISK_RED_THRESHOLD:
        return "red"
    if risk_percent >= settings.RISK_YELLOW_THRESHOLD:
        return "yellow"
    return "green"


def score(rows: list[dict]) -> list[dict]:
    """rows = extract_features() dicts. Returns per row:
    {risk_percent, level, model_version, features: {name: raw value|None},
     contributions: [{feature, value, imputed, scaled, coef, contribution}] sorted by |contribution| desc,
     intercept}. contribution is in log-odds: sum(contributions) + intercept = logit(risk_percent/100)."""
    if not rows:
        return []
    pipe, meta = load()
    X = pd.DataFrame([{f: (np.nan if r.get(f) is None else float(r[f])) for f in FEATURES} for r in rows],
                     columns=FEATURES, dtype=float)
    prep = pipe[:-1]
    Z = prep.transform(X)
    model = pipe.named_steps["model"]
    coef = model.coef_[0]
    intercept = float(model.intercept_[0])
    proba = model.predict_proba(Z)[:, 1]
    contrib = Z * coef
    out = []
    raw = X.to_numpy()
    for i, r in enumerate(rows):
        risk = round(float(proba[i]) * 100.0, 1)
        cs = [{"feature": f, "value": None if np.isnan(raw[i, j]) else round(float(raw[i, j]), 4),
               "imputed": bool(np.isnan(raw[i, j])), "scaled": round(float(Z[i, j]), 4),
               "coef": round(float(coef[j]), 5), "contribution": round(float(contrib[i, j]), 4)}
              for j, f in enumerate(FEATURES)]
        cs.sort(key=lambda c: -abs(c["contribution"]))
        out.append({"risk_percent": risk, "level": level_for(risk), "model_version": meta["model_version"],
                    "features": {f: r.get(f) for f in FEATURES}, "contributions": cs,
                    "intercept": round(intercept, 5)})
    return out


def factors(contributions: list[dict], n: int = 5) -> list[dict]:
    """Top-n MEASURED drivers by |contribution| (imputed features are left out: they were not observed).
    [{feature, label, value, contribution (log-odds), direction up|down}]"""
    out = []
    for c in sorted(contributions or [], key=lambda c: -abs(c["contribution"])):
        if c.get("imputed"):
            continue
        out.append({"feature": c["feature"], "label": LABELS.get(c["feature"], c["feature"]), "value": c["value"],
                    "contribution": round(c["contribution"], 4),
                    "direction": "up" if c["contribution"] > 0 else "down"})
        if len(out) >= n:
            break
    return out
