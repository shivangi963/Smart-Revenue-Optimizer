"""Training + evaluation.

Trains and compares, on the same hold-out set:
  * static pricing (baseline)          * rule-based pricing (baseline)
  * Linear Regression                  * Random Forest
  * Gradient Boosting                  (the three ML candidates from the paper)
and a separate *demand model* (monotone Poisson gradient boosting) that learns
units sold as a function of context + candidate price - used for the revenue
response curve and for scoring recommendations.

Metrics follow the paper: MAE, RMSE, R2, revenue lift and latency.
"""
from __future__ import annotations

import time
from datetime import datetime, timezone
from typing import Callable, Dict, Optional

import numpy as np
import pandas as pd
import sklearn
from sklearn.ensemble import GradientBoostingRegressor, RandomForestRegressor
from sklearn.linear_model import LinearRegression
from sklearn.metrics import r2_score
from sklearn.model_selection import train_test_split
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import StandardScaler

from . import world
from .baselines import rule_based_ratio, static_ratio
from .demand import (
    DEFAULT_GRID, DEMAND_COLUMNS, build_demand_model, fit_demand_model, peak_from_curve, predict_units,
)
from .features import FEATURE_COLUMNS, FEATURE_GROUPS, RAW_COLUMNS, engineer_features

MODEL_LABELS = {
    "oracle": "Oracle (upper bound)",
    "static": "Static pricing",
    "rule_based": "Rule-based",
    "linear": "Linear Regression",
    "random_forest": "Random Forest",
    "gradient_boosting": "Gradient Boosting",
}
ML_MODELS = ["linear", "random_forest", "gradient_boosting"]


def build_models(seed: int = 42) -> Dict[str, Pipeline]:
    return {
        "linear": Pipeline([("scale", StandardScaler()), ("model", LinearRegression())]),
        "random_forest": Pipeline([("model", RandomForestRegressor(
            n_estimators=120, max_depth=12, min_samples_leaf=5, n_jobs=-1, random_state=seed))]),
        "gradient_boosting": Pipeline([("model", GradientBoostingRegressor(
            n_estimators=250, learning_rate=0.08, max_depth=4, subsample=0.8, random_state=seed))]),
    }


# ---------------------------------------------------------------------------
def _evaluate(ratio_pred: np.ndarray, y_true: np.ndarray, raw: pd.DataFrame, static_rev: float,
              static_profit: float) -> dict:
    """Metrics for one strategy. Predictions are clipped to the same guardrail
    bounds the live system enforces, so every strategy is judged fairly."""
    cost_ratio = raw["cost"].to_numpy(float) / raw["base_price"].to_numpy(float)
    lo, hi = world.ratio_bounds(cost_ratio)
    r = np.clip(ratio_pred, lo, hi)
    base = raw["base_price"].to_numpy(float)
    err_price = (r - y_true) * base
    rev = float(world.expected_revenue(raw, r).sum())
    profit = float(world.expected_profit(raw, r).sum())
    return {
        "mae": float(np.mean(np.abs(err_price))),
        "rmse": float(np.sqrt(np.mean(err_price ** 2))),
        "mae_pct": float(np.mean(np.abs(r - y_true)) * 100.0),
        "r2": float(r2_score(y_true, r)),
        "revenue_lift_pct": (rev / static_rev - 1.0) * 100.0,
        "profit_lift_pct": (profit / static_profit - 1.0) * 100.0,
    }


def _latency_ms(fn: Callable[[], object], repeats: int = 60) -> float:
    fn()  # warm-up
    t0 = time.perf_counter()
    for _ in range(repeats):
        fn()
    return (time.perf_counter() - t0) / repeats * 1000.0


def _normalise(values: np.ndarray, names) -> Dict[str, float]:
    values = np.abs(np.asarray(values, dtype=float))
    total = values.sum() or 1.0
    return {n: float(v / total) for n, v in zip(names, values)}


def train_all(n_samples: int = 25000, seed: int = 42,
              progress: Optional[Callable[[str], None]] = None) -> dict:
    """Train every candidate, evaluate on a hold-out set and return a bundle."""
    say = progress or (lambda _m: None)
    started = time.time()
    rng = np.random.default_rng(seed)

    say(f"Generating {n_samples:,} synthetic market observations...")
    data = world.add_labels(world.sample_raw_contexts(n_samples, rng), rng)
    X = engineer_features(data[RAW_COLUMNS])
    y = data["label_ratio"].to_numpy(float)

    idx = np.arange(len(data))
    tr, te = train_test_split(idx, test_size=0.2, random_state=seed)
    X_tr, X_te, y_tr, y_te = X.iloc[tr], X.iloc[te], y[tr], y[te]
    raw_te = data.iloc[te][RAW_COLUMNS].reset_index(drop=True)
    full_te = data.iloc[te].reset_index(drop=True)

    static_pred = static_ratio(raw_te)
    static_rev = float(world.expected_revenue(raw_te, np.clip(static_pred, *world.ratio_bounds(
        raw_te["cost"].to_numpy(float) / raw_te["base_price"].to_numpy(float)))).sum())
    static_profit = float(world.expected_profit(raw_te, np.clip(static_pred, *world.ratio_bounds(
        raw_te["cost"].to_numpy(float) / raw_te["base_price"].to_numpy(float)))).sum())

    strategies: Dict[str, dict] = {}
    strategies["oracle"] = _evaluate(world.true_optimal_ratio(raw_te), y_te, raw_te, static_rev, static_profit)
    strategies["oracle"]["latency_ms"] = 0.0
    strategies["static"] = _evaluate(static_pred, y_te, raw_te, static_rev, static_profit)
    strategies["rule_based"] = _evaluate(rule_based_ratio(raw_te), y_te, raw_te, static_rev, static_profit)

    one_row_raw = raw_te.iloc[[0]]
    strategies["static"]["latency_ms"] = 0.0
    strategies["rule_based"]["latency_ms"] = _latency_ms(lambda: rule_based_ratio(one_row_raw))

    models: Dict[str, Pipeline] = {}
    importance: Dict[str, Dict[str, float]] = {}
    for name, pipe in build_models(seed).items():
        say(f"Training {MODEL_LABELS[name]}...")
        t0 = time.time()
        pipe.fit(X_tr, y_tr)
        train_seconds = time.time() - t0
        inner = pipe.named_steps["model"]
        if hasattr(inner, "n_jobs"):
            inner.set_params(n_jobs=1)         # thread start-up costs more than it saves for 1 row
        pred = pipe.predict(X_te)
        m = _evaluate(pred, y_te, raw_te, static_rev, static_profit)
        m["train_seconds"] = float(train_seconds)
        m["latency_ms"] = _latency_ms(lambda p=pipe: p.predict(engineer_features(one_row_raw)))
        strategies[name] = m
        models[name] = pipe
        if hasattr(inner, "feature_importances_"):
            importance[name] = _normalise(inner.feature_importances_, FEATURE_COLUMNS)
        else:
            importance[name] = _normalise(inner.coef_, FEATURE_COLUMNS)   # standardised coefficients

    best = min(ML_MODELS, key=lambda n: strategies[n]["rmse"])

    # ---- demand model (own, larger sample for a smoother price response) ----
    say("Training demand model (units sold vs. price)...")
    n_demand = int(min(max(2 * n_samples, 5000), 60000))
    d_data = world.add_labels(world.sample_raw_contexts(n_demand, np.random.default_rng(seed + 1)),
                              np.random.default_rng(seed + 2))
    d_X = engineer_features(d_data[RAW_COLUMNS])
    d_idx = np.arange(n_demand)
    d_tr, d_te = train_test_split(d_idx, test_size=0.15, random_state=seed)
    dm = build_demand_model(seed)
    t0 = time.time()
    fit_demand_model(dm, d_X.iloc[d_tr], d_data["obs_ratio"].to_numpy()[d_tr], d_data["units"].to_numpy()[d_tr],
                     world.demand_volume(d_data.iloc[d_tr]))
    dm_seconds = time.time() - t0

    d_test = d_data.iloc[d_te].reset_index(drop=True)
    d_Xte = d_X.iloc[d_te].reset_index(drop=True)
    vol = world.demand_volume(d_test)
    pred_units = predict_units(dm, d_Xte, d_test["obs_ratio"].to_numpy(), vol)
    true_units = world.expected_units(d_test, d_test["obs_ratio"].to_numpy())
    demand_metrics = {
        "r2_vs_observed": float(r2_score(d_test["units"].to_numpy(float), pred_units)),
        "r2_vs_expected": float(r2_score(true_units, pred_units)),
        "mae_units": float(np.mean(np.abs(pred_units - true_units))),
        "train_seconds": float(dm_seconds),
        "n_samples": n_demand,
    }
    # Does the learned revenue curve peak where the true one does?
    peak_err = []
    for i in range(min(300, len(d_Xte))):
        rows = pd.concat([d_Xte.iloc[[i]]] * len(DEFAULT_GRID), ignore_index=True)
        units = predict_units(dm, rows, DEFAULT_GRID, np.full(len(DEFAULT_GRID), vol[i]))
        peak, _ = peak_from_curve(DEFAULT_GRID, units * DEFAULT_GRID)
        peak_err.append(abs(peak - float(np.clip(d_test.loc[i, "true_g"], world.RATIO_MIN, world.RATIO_MAX))))
    demand_metrics["optimum_mae_pct"] = float(np.mean(peak_err) * 100.0)

    group_importance = {}
    for name, imp in importance.items():
        group_importance[name] = {
            g: float(sum(imp[c] for c in cols)) for g, cols in FEATURE_GROUPS.items()
        }

    now = datetime.now(timezone.utc)
    bundle = {
        "version": f"v{now:%Y%m%d.%H%M}",
        "trained_at": now.replace(tzinfo=None).isoformat(timespec="seconds") + "Z",
        "n_samples": int(n_samples),
        "n_train": int(len(tr)),
        "n_test": int(len(te)),
        "seed": int(seed),
        "best_model": best,
        "models": models,
        "demand_model": dm,
        "metrics": {"strategies": strategies, "demand_model": demand_metrics},
        "importance": importance,
        "group_importance": group_importance,
        "feature_columns": FEATURE_COLUMNS,
        "demand_columns": DEMAND_COLUMNS,
        "sklearn_version": sklearn.__version__,
        "total_seconds": float(time.time() - started),
    }
    say(f"Training complete in {bundle['total_seconds']:.1f}s - best model: {MODEL_LABELS[best]}")
    return bundle
