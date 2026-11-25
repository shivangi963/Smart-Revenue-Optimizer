"""Feature engineering - the *only* place raw store context becomes model input.

The same function is used for training and for live inference, so there is no
train/serve skew.  Features follow the table in the base paper (demand, inventory,
time, weather, event, product) plus the interaction terms mentioned in the
minor-project report (e.g. temperature x category).
"""
from __future__ import annotations

from typing import Dict, List

import numpy as np
import pandas as pd

from .world import CATEGORY_KEYS, category_key, diurnal_profile, CATEGORIES

RAW_COLUMNS: List[str] = [
    "category", "base_price", "cost",
    "hour_of_day", "day_of_week", "month",
    "page_views_1h", "expected_page_views", "add_to_cart_rate", "conversion_rate",
    "stock_level", "max_stock",
    "temperature", "precipitation", "humidity",
    "is_holiday", "event_score", "days_to_event",
    "competitor_price",
]

# Engineered features, grouped by the factor they describe.
FEATURE_GROUPS: Dict[str, List[str]] = {
    "time_of_day": [
        "hour_of_day", "hour_sin", "hour_cos", "day_of_week", "is_weekend",
        "month", "month_sin", "month_cos",
        "monsoon_x_umbrella", "summer_x_icecream", "winter_x_hotbev",
    ],
    "demand": ["page_views_1h", "traffic_index", "add_to_cart_rate", "conversion_rate"],
    "inventory": ["stock_ratio", "low_stock_flag"],
    "weather": [
        "temperature", "precipitation", "humidity", "is_rainy", "is_hot",
        "rain_x_umbrella", "temp_x_icecream", "cold_x_hotbev",
    ],
    "holiday_effect": ["is_holiday", "event_score", "days_to_event", "event_proximity", "urgency_x_ticket"],
    "competition": ["competitor_ratio"],
    "product": ["cost_ratio"] + [f"cat_{k}" for k in CATEGORY_KEYS],
}
FEATURE_COLUMNS: List[str] = [c for cols in FEATURE_GROUPS.values() for c in cols]

GROUP_LABELS = {
    "time_of_day": "Time & Season",
    "demand": "Demand",
    "inventory": "Stock Level",
    "weather": "Weather",
    "holiday_effect": "Events & Holidays",
    "competition": "Competition",
    "product": "Product",
}

# Groups that can be "switched off" to explain a price (see services/explainer.py).
EXPLAIN_GROUPS = ["weather", "time_of_day", "holiday_effect", "demand", "inventory", "competition"]

# Raw columns controlled by each explainable group.
GROUP_RAW_COLUMNS: Dict[str, List[str]] = {
    "weather": ["temperature", "precipitation", "humidity"],
    "time_of_day": ["hour_of_day", "day_of_week", "month"],
    "holiday_effect": ["is_holiday", "event_score", "days_to_event"],
    "demand": ["page_views_1h", "add_to_cart_rate", "conversion_rate"],
    "inventory": ["stock_level"],
    "competition": ["competitor_price"],
}


def neutral_values(row: dict) -> dict:
    """Values that mean 'nothing unusual is happening' for each explainable group."""
    # 'normal' temperature differs by category: hot drinks are neutral at 22C, everything else ~26C
    neutral_temp = 22.0 if category_key(row["category"]) == "hot_beverage" else 26.0
    return {
        "temperature": neutral_temp, "precipitation": 0.0, "humidity": 60.0,
        "hour_of_day": 12, "day_of_week": 2, "month": 10,
        "is_holiday": 0, "event_score": 0.0, "days_to_event": 60.0,
        "page_views_1h": float(row["expected_page_views"]),   # traffic index = 1
        "add_to_cart_rate": 0.15, "conversion_rate": 0.30,
        "stock_level": int(round(0.5 * float(row["max_stock"]))),
        "competitor_price": float(row["base_price"]),
    }


def raw_frame(rows: List[dict]) -> pd.DataFrame:
    """Build a raw DataFrame with every expected column (fails loudly if one is missing)."""
    df = pd.DataFrame(rows)
    missing = [c for c in RAW_COLUMNS if c not in df.columns]
    if missing:
        raise ValueError(f"Missing raw context columns: {missing}")
    return df[RAW_COLUMNS].reset_index(drop=True)


def default_expected_pv(category: str, hour: int) -> float:
    return float(CATEGORIES[category_key(category)]["pv_ref"] * diurnal_profile(hour))


def engineer_features(raw: pd.DataFrame) -> pd.DataFrame:
    """Raw store context -> model-ready numeric feature matrix (FEATURE_COLUMNS)."""
    f: Dict[str, np.ndarray] = {}

    h = raw["hour_of_day"].to_numpy(float)
    dow = raw["day_of_week"].to_numpy(float)
    m = raw["month"].to_numpy(float)
    cat = raw["category"].map(category_key).to_numpy()
    c = {k: (cat == k).astype(float) for k in CATEGORY_KEYS}

    # time
    f["hour_of_day"] = h
    f["hour_sin"] = np.sin(2 * np.pi * h / 24.0)
    f["hour_cos"] = np.cos(2 * np.pi * h / 24.0)
    f["day_of_week"] = dow
    f["is_weekend"] = (dow >= 5).astype(float)
    f["month"] = m
    f["month_sin"] = np.sin(2 * np.pi * (m - 1) / 12.0)
    f["month_cos"] = np.cos(2 * np.pi * (m - 1) / 12.0)
    f["monsoon_x_umbrella"] = c["umbrella"] * ((m >= 6) & (m <= 9))
    f["summer_x_icecream"] = c["ice_cream"] * ((m >= 3) & (m <= 6))
    f["winter_x_hotbev"] = c["hot_beverage"] * ((m >= 11) | (m <= 2))

    # demand
    pv = raw["page_views_1h"].to_numpy(float)
    f["page_views_1h"] = pv
    f["traffic_index"] = pv / np.maximum(raw["expected_page_views"].to_numpy(float), 1.0)
    f["add_to_cart_rate"] = raw["add_to_cart_rate"].to_numpy(float)
    f["conversion_rate"] = raw["conversion_rate"].to_numpy(float)

    # inventory
    stock_ratio = np.clip(raw["stock_level"].to_numpy(float) / np.maximum(raw["max_stock"].to_numpy(float), 1.0), 0, 1)
    f["stock_ratio"] = stock_ratio
    f["low_stock_flag"] = (stock_ratio < 0.10).astype(float)

    # weather (+ category interactions)
    temp = raw["temperature"].to_numpy(float)
    precip = raw["precipitation"].to_numpy(float)
    f["temperature"] = temp
    f["precipitation"] = precip
    f["humidity"] = raw["humidity"].to_numpy(float)
    f["is_rainy"] = (precip > 0.2).astype(float)
    f["is_hot"] = (temp >= 32).astype(float)
    f["rain_x_umbrella"] = precip * c["umbrella"]
    f["temp_x_icecream"] = (temp - 26.0) * c["ice_cream"]
    f["cold_x_hotbev"] = np.clip(22.0 - temp, -10, 15) * c["hot_beverage"]

    # events
    dte = raw["days_to_event"].to_numpy(float)
    f["is_holiday"] = raw["is_holiday"].to_numpy(float)
    f["event_score"] = raw["event_score"].to_numpy(float)
    f["days_to_event"] = dte
    f["event_proximity"] = np.exp(-dte / 14.0)
    f["urgency_x_ticket"] = f["event_proximity"] * c["ticket"]

    # competition + product
    base = raw["base_price"].to_numpy(float)
    f["competitor_ratio"] = np.clip(raw["competitor_price"].to_numpy(float) / base, 0.5, 1.6)
    f["cost_ratio"] = raw["cost"].to_numpy(float) / base
    for k in CATEGORY_KEYS:
        f[f"cat_{k}"] = c[k]

    return pd.DataFrame({col: f[col] for col in FEATURE_COLUMNS}, index=raw.index)
