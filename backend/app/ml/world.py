"""The synthetic *market world* behind training and evaluation.

The project has no real sales logs, so (as described in the reports) we define a
latent demand model and learn from data sampled out of it.

For a product with base price b and context x the world assumes linear demand

    D(p | x) = V(x) * max(0, 1 - p / (2 * b * g(x)))

where
  * g(x) is a *willingness-to-pay multiplier* built from interpretable effects
    (time of day, season, weather, events, demand signals, stock, competition);
  * V(x) is the demand volume, proportional to page-views x cart rate x conversion.

Revenue R(p) = p * D(p | x) is maximised at p* = b * g(x), so the optimal price
*ratio* is exactly g(x).  At a neutral context g = 1 and the base price is optimal.
The ML models never see g - they only see observable features and noisy labels.
"""
from __future__ import annotations

from typing import Optional

import numpy as np
import pandas as pd

CATEGORIES = {
    "umbrella":     {"label": "Umbrella",     "pv_ref": 80,  "price_range": (300, 1500),  "max_stock": 200},
    "ice_cream":    {"label": "Ice Cream",    "pv_ref": 150, "price_range": (80, 400),    "max_stock": 300},
    "ticket":       {"label": "Event Ticket", "pv_ref": 60,  "price_range": (800, 6000),  "max_stock": 100},
    "hot_beverage": {"label": "Hot Beverage", "pv_ref": 120, "price_range": (60, 350),    "max_stock": 250},
    "generic":      {"label": "Generic",      "pv_ref": 90,  "price_range": (150, 3000),  "max_stock": 200},
}
CATEGORY_KEYS = list(CATEGORIES)

_ALIASES = {
    "icecream": "ice_cream", "event_ticket": "ticket", "concert_ticket": "ticket", "tickets": "ticket",
    "coffee": "hot_beverage", "tea": "hot_beverage", "beverage": "hot_beverage",
    "hot_chocolate": "hot_beverage", "umbrellas": "umbrella",
}

# Hard limits for the *ratio* (price / base price) used when labelling and evaluating.
RATIO_MIN = 0.65
RATIO_MAX = 1.80
MARGIN_FLOOR = 0.10


def category_key(name) -> str:
    """Map any free-text category onto one of the modelled categories."""
    if name is None:
        return "generic"
    key = str(name).strip().lower().replace(" ", "_").replace("-", "_")
    if key in CATEGORIES:
        return key
    return _ALIASES.get(key, "generic")


def diurnal_profile(hour) -> np.ndarray:
    """Relative traffic through the day: quiet at night, lunch bump, evening peak."""
    h = np.asarray(hour, dtype=float)
    return 0.30 + 0.55 * np.exp(-((h - 13.0) / 4.5) ** 2) + 0.85 * np.exp(-((h - 20.5) / 2.5) ** 2)


def expected_page_views(category, hour) -> np.ndarray:
    """Typical page views per hour for a category at a given hour."""
    if isinstance(category, (pd.Series, np.ndarray, list)):
        ref = np.array([CATEGORIES[category_key(c)]["pv_ref"] for c in category], dtype=float)
    else:
        ref = float(CATEGORIES[category_key(category)]["pv_ref"])
    return ref * diurnal_profile(hour)


def ratio_bounds(cost_ratio, margin_floor: float = MARGIN_FLOOR):
    lo = np.maximum(RATIO_MIN, np.asarray(cost_ratio, dtype=float) * (1.0 + margin_floor))
    hi = np.full_like(lo, RATIO_MAX, dtype=float)
    return lo, hi


# ---------------------------------------------------------------------------
# Latent willingness-to-pay
# ---------------------------------------------------------------------------
def log_willingness_parts(df: pd.DataFrame) -> dict:
    """Additive log-effects of each factor group on the optimal price ratio."""
    h = df["hour_of_day"].to_numpy(float)
    dow = df["day_of_week"].to_numpy(float)
    month = df["month"].to_numpy(float)
    temp = df["temperature"].to_numpy(float)
    precip = df["precipitation"].to_numpy(float)
    is_hol = df["is_holiday"].to_numpy(float)
    ev = df["event_score"].to_numpy(float)
    dte = df["days_to_event"].to_numpy(float)
    traffic = df["page_views_1h"].to_numpy(float) / np.maximum(df["expected_page_views"].to_numpy(float), 1.0)
    cart = df["add_to_cart_rate"].to_numpy(float)
    conv = df["conversion_rate"].to_numpy(float)
    stock_ratio = np.clip(df["stock_level"].to_numpy(float) / np.maximum(df["max_stock"].to_numpy(float), 1.0), 0, 1)
    comp_ratio = df["competitor_price"].to_numpy(float) / df["base_price"].to_numpy(float)

    cat = df["category"].map(category_key).to_numpy()
    umb, ice, tix, hot = (cat == "umbrella"), (cat == "ice_cream"), (cat == "ticket"), (cat == "hot_beverage")

    # --- time of day / week / season -------------------------------------
    night_dist = np.minimum(np.abs(h - 3.0), 24.0 - np.abs(h - 3.0))
    time_eff = (
        0.07 * np.exp(-((h - 20.0) / 2.5) ** 2)        # evening shopping peak
        - 0.08 * np.exp(-(night_dist / 3.0) ** 2)      # night lull
        + 0.04 * (dow >= 5)                            # weekend
    )
    time_eff = np.where(tix, 0.5 * time_eff, time_eff)  # tickets are less hour-sensitive
    season = (
        0.08 * (umb & (month >= 6) & (month <= 9))                      # monsoon
        + 0.06 * (ice & (month >= 3) & (month <= 6))                    # summer
        + 0.06 * (hot & ((month >= 11) | (month <= 2)))                 # winter
    )
    time_eff = time_eff + season

    # --- weather -----------------------------------------------------------
    weather_eff = np.zeros_like(temp)
    weather_eff += np.where(umb, 0.30 * precip - 0.03 * (temp > 34), 0.0)
    weather_eff += np.where(ice, np.clip(0.014 * (temp - 26.0), -0.15, 0.12) - 0.10 * precip, 0.0)
    weather_eff += np.where(hot, np.clip(0.012 * (22.0 - temp), -0.10, 0.15) + 0.12 * precip, 0.0)
    weather_eff += np.where(tix, -0.06 * precip, 0.0)

    # --- events / holidays -------------------------------------------------
    event_eff = 0.06 * is_hol + 0.12 * ev
    event_eff += np.where(tix, 0.25 * np.exp(-dte / 14.0), 0.05 * np.exp(-dte / 10.0))

    # --- demand signals ----------------------------------------------------
    demand_eff = (
        0.20 * np.tanh(1.2 * (traffic - 1.0))
        + 0.10 * np.tanh(6.0 * (cart - 0.15))
        + 0.08 * np.tanh(5.0 * (conv - 0.30))
    )

    # --- inventory ---------------------------------------------------------
    inventory_eff = 0.10 * (1.0 - 2.0 * stock_ratio) + 0.05 * (stock_ratio < 0.10)

    # --- competition -------------------------------------------------------
    competition_eff = np.clip(0.35 * (comp_ratio - 1.0), -0.12, 0.12)

    return {
        "time_of_day": time_eff,
        "weather": weather_eff,
        "holiday_effect": event_eff,
        "demand": demand_eff,
        "inventory": inventory_eff,
        "competition": competition_eff,
    }


def willingness(df: pd.DataFrame) -> np.ndarray:
    """g(x): the unconstrained optimal price ratio."""
    total = sum(log_willingness_parts(df).values())
    return np.clip(np.exp(total), 0.60, 1.80)


def true_optimal_ratio(df: pd.DataFrame) -> np.ndarray:
    cost_ratio = df["cost"].to_numpy(float) / df["base_price"].to_numpy(float)
    lo, hi = ratio_bounds(cost_ratio)
    return np.clip(willingness(df), lo, hi)


VOLUME_SCALE = 10.0


def demand_volume(df: pd.DataFrame) -> np.ndarray:
    """V(x): orders/hour scale, from page views x cart rate x conversion.
    This is computable from observed signals, so the demand model may use it."""
    return (
        df["page_views_1h"].to_numpy(float)
        * df["add_to_cart_rate"].to_numpy(float)
        * df["conversion_rate"].to_numpy(float)
        * VOLUME_SCALE
    )


def expected_units(df: pd.DataFrame, ratio) -> np.ndarray:
    """Expected units sold per hour at price = ratio * base_price."""
    g = willingness(df)
    r = np.asarray(ratio, dtype=float)
    return demand_volume(df) * np.maximum(0.0, 1.0 - r / (2.0 * g))


def expected_revenue(df: pd.DataFrame, ratio) -> np.ndarray:
    return np.asarray(ratio, dtype=float) * df["base_price"].to_numpy(float) * expected_units(df, ratio)


def expected_profit(df: pd.DataFrame, ratio) -> np.ndarray:
    price = np.asarray(ratio, dtype=float) * df["base_price"].to_numpy(float)
    return (price - df["cost"].to_numpy(float)) * expected_units(df, ratio)


# ---------------------------------------------------------------------------
# Sampling
# ---------------------------------------------------------------------------
def sample_raw_contexts(n: int, rng: np.random.Generator, category: Optional[str] = None) -> pd.DataFrame:
    """Draw n random store contexts (raw, un-engineered columns)."""
    if category is None:
        cat = rng.choice(CATEGORY_KEYS, size=n)
    else:
        cat = np.full(n, category_key(category))

    lo = np.array([CATEGORIES[c]["price_range"][0] for c in cat], dtype=float)
    hi = np.array([CATEGORIES[c]["price_range"][1] for c in cat], dtype=float)
    base = np.exp(rng.uniform(np.log(lo), np.log(hi)))
    cost_ratio = rng.uniform(0.35, 0.70, n)

    hour = rng.integers(0, 24, n)
    dow = rng.integers(0, 7, n)
    month = rng.integers(1, 13, n)
    expected_pv = expected_page_views(list(cat), hour)
    pv = rng.poisson(expected_pv * rng.lognormal(0.0, 0.35, n))
    cart = np.clip(rng.beta(3, 17, n), 0.01, 0.60)
    conv = np.clip(rng.beta(3, 7, n), 0.02, 0.90)

    max_stock = np.array([CATEGORIES[c]["max_stock"] for c in cat])
    stock = (max_stock * rng.beta(2, 2, n)).astype(int)

    raining = rng.random(n) < 0.30
    precip = np.where(raining, rng.beta(2, 3, n), rng.uniform(0.0, 0.03, n))
    temp = 24.0 + rng.uniform(-8, 6, n) + 5.0 * np.sin((month - 4) / 12.0 * 2 * np.pi) + rng.normal(0, 4, n) - 3.0 * raining
    temp = np.clip(temp, -5.0, 44.0)
    humidity = np.clip(55.0 + 30.0 * precip + rng.normal(0, 10, n), 20.0, 100.0)

    dte = np.minimum(np.floor(rng.exponential(20.0, n)), 60.0)
    is_hol = (dte == 0).astype(int)
    event_score = rng.uniform(0.5, 1.0, n) * np.exp(-dte / 4.0)

    competitor = base * np.clip(rng.normal(1.0, 0.10, n), 0.70, 1.40)

    return pd.DataFrame({
        "category": cat,
        "base_price": base,
        "cost": base * cost_ratio,
        "hour_of_day": hour,
        "day_of_week": dow,
        "month": month,
        "page_views_1h": pv,
        "expected_page_views": expected_pv,
        "add_to_cart_rate": cart,
        "conversion_rate": conv,
        "stock_level": stock,
        "max_stock": max_stock,
        "temperature": temp,
        "precipitation": precip,
        "humidity": humidity,
        "is_holiday": is_hol,
        "event_score": event_score,
        "days_to_event": dte,
        "competitor_price": competitor,
    })


def add_labels(raw: pd.DataFrame, rng: np.random.Generator) -> pd.DataFrame:
    """Attach the noisy training targets + latent truth used for evaluation."""
    df = raw.copy()
    g = willingness(df)
    cost_ratio = df["cost"].to_numpy(float) / df["base_price"].to_numpy(float)
    lo, hi = ratio_bounds(cost_ratio)

    # Price-model target: the optimal ratio, observed with a little market noise.
    df["true_g"] = g
    df["label_ratio"] = np.clip(g * np.exp(rng.normal(0.0, 0.02, len(df))), lo, hi)

    # Demand-model target: units sold at an *experimented* price near the optimum.
    obs_ratio = np.clip(df["label_ratio"].to_numpy() * np.exp(rng.normal(0.0, 0.35, len(df))), 0.55, 2.0)
    df["obs_ratio"] = obs_ratio
    mean_units = demand_volume(df) * np.maximum(0.0, 1.0 - obs_ratio / (2.0 * g))
    df["units"] = rng.poisson(mean_units)
    return df
