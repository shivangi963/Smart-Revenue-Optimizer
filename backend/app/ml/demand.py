"""Demand model: how many units sell at a candidate price?

The model learns the *relative* price response  f(context, price_ratio) in [0, ~1]
(fraction of the current order rate that survives at that price) with a
monotone-decreasing gradient-boosted regressor.  Expected units are then

    units = V_hat * f(context, price_ratio),   V_hat = page_views * cart_rate * conversion * scale

which is far easier to learn than raw counts (the multiplicative volume term is
handled analytically).  Revenue = price * units gives the response curve in the
paper; its peak is located by fitting a quadratic to the model's curve, which
smooths the staircase shape of tree models.
"""
from __future__ import annotations

from typing import Tuple

import numpy as np
import pandas as pd
from sklearn.ensemble import HistGradientBoostingRegressor

from . import world
from .features import FEATURE_COLUMNS

DEMAND_COLUMNS = FEATURE_COLUMNS + ["price_ratio"]


def build_demand_model(seed: int = 42) -> HistGradientBoostingRegressor:
    monotone = [-1 if c == "price_ratio" else 0 for c in DEMAND_COLUMNS]   # demand never rises with price
    return HistGradientBoostingRegressor(
        loss="squared_error", max_iter=300, learning_rate=0.08, max_leaf_nodes=31,
        min_samples_leaf=40, monotonic_cst=monotone, random_state=seed)


def demand_frame(features: pd.DataFrame, ratio) -> pd.DataFrame:
    d = features.copy()
    d["price_ratio"] = np.asarray(ratio, dtype=float)
    return d[DEMAND_COLUMNS]


def fit_demand_model(model, features: pd.DataFrame, obs_ratio, units, volume):
    """Fit on relative demand units/V weighted by V (Poisson-like variance ~ 1/V)."""
    v = np.maximum(np.asarray(volume, dtype=float), 1e-3)
    y = np.asarray(units, dtype=float) / v
    model.fit(demand_frame(features, obs_ratio), y, sample_weight=v)
    return model


def predict_units(model, features: pd.DataFrame, ratio, volume) -> np.ndarray:
    rel = np.clip(model.predict(demand_frame(features, ratio)), 0.0, None)
    return rel * np.asarray(volume, dtype=float)


def peak_from_curve(ratios: np.ndarray, revenue: np.ndarray) -> Tuple[float, np.ndarray]:
    """Peak of a quadratic fit to the revenue curve (falls back to the raw argmax)."""
    ratios = np.asarray(ratios, dtype=float)
    revenue = np.asarray(revenue, dtype=float)
    scale = max(float(revenue.max()), 1e-9)
    c = np.polyfit(ratios, revenue / scale, 2)
    fitted = np.polyval(c, ratios) * scale
    if c[0] < 0:
        peak = float(np.clip(-c[1] / (2.0 * c[0]), ratios.min(), ratios.max()))
    else:
        peak = float(ratios[int(np.argmax(revenue))])
    return peak, fitted


DEFAULT_GRID = np.linspace(world.RATIO_MIN, world.RATIO_MAX, 24)
