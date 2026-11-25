"""Non-ML baselines used (a) as comparison rows in the evaluation table and
(b) as a safety-net while the ML model is still training on first start."""
from __future__ import annotations

import numpy as np
import pandas as pd

from .world import category_key


def static_ratio(raw: pd.DataFrame) -> np.ndarray:
    """Static pricing: always charge the base price."""
    return np.ones(len(raw), dtype=float)


def rule_based_ratio(raw: pd.DataFrame) -> np.ndarray:
    """Hand-written if/else rules - what a store manager might configure."""
    cat = raw["category"].map(category_key).to_numpy()
    h = raw["hour_of_day"].to_numpy(float)
    temp = raw["temperature"].to_numpy(float)
    precip = raw["precipitation"].to_numpy(float)
    traffic = raw["page_views_1h"].to_numpy(float) / np.maximum(raw["expected_page_views"].to_numpy(float), 1.0)
    stock_ratio = raw["stock_level"].to_numpy(float) / np.maximum(raw["max_stock"].to_numpy(float), 1.0)
    comp = raw["competitor_price"].to_numpy(float) / raw["base_price"].to_numpy(float)
    dte = raw["days_to_event"].to_numpy(float)

    r = np.ones(len(raw), dtype=float)
    r += np.where((cat == "umbrella") & (precip > 0.3), 0.12, 0.0)
    r += np.where((cat == "ice_cream") & (temp > 30), 0.10, 0.0)
    r += np.where((cat == "hot_beverage") & (temp < 18), 0.08, 0.0)
    r += np.where((cat == "ticket") & (dte <= 7), 0.10, 0.0)
    r += np.where((h >= 18) & (h <= 22), 0.04, 0.0)
    r -= np.where(h <= 5, 0.04, 0.0)
    r += np.where(raw["is_holiday"].to_numpy(float) > 0, 0.06, 0.0)
    r += np.where(traffic > 1.3, 0.05, 0.0)
    r -= np.where(traffic < 0.7, 0.05, 0.0)
    r += np.where(stock_ratio < 0.10, 0.05, 0.0)
    r -= np.where(stock_ratio > 0.80, 0.05, 0.0)
    r += np.where(comp > 1.05, 0.03, 0.0)
    r -= np.where(comp < 0.95, 0.04, 0.0)
    return r
