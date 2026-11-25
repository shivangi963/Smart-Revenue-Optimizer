import numpy as np
import pandas as pd

from app.ml import world
from app.ml.baselines import rule_based_ratio
from app.ml.features import EXPLAIN_GROUPS, FEATURE_COLUMNS, RAW_COLUMNS, engineer_features, neutral_values
from app.services.explainer import shapley_contributions


def neutral_row(category="umbrella"):
    row = {"category": category, "base_price": 800.0, "cost": 400.0, "hour_of_day": 12, "day_of_week": 2,
           "month": 10, "page_views_1h": 0.0, "expected_page_views": float(world.expected_page_views(category, 12)),
           "add_to_cart_rate": 0.15, "conversion_rate": 0.30, "stock_level": 100, "max_stock": 200,
           "temperature": 22.0 if category == "hot_beverage" else 26.0, "precipitation": 0.0, "humidity": 60.0, "is_holiday": 0, "event_score": 0.0,
           "days_to_event": 60.0, "competitor_price": 800.0}
    row["page_views_1h"] = row["expected_page_views"]
    return row


def frame(**overrides):
    row = neutral_row(overrides.pop("category", "umbrella"))
    row.update(overrides)
    return pd.DataFrame([row])[RAW_COLUMNS]


def test_feature_matrix_shape_and_no_nans():
    rng = np.random.default_rng(0)
    raw = world.sample_raw_contexts(500, rng)
    X = engineer_features(raw[RAW_COLUMNS])
    assert list(X.columns) == FEATURE_COLUMNS
    assert not X.isna().any().any() and np.isfinite(X.to_numpy()).all()


def test_neutral_context_means_base_price_is_optimal():
    for cat in world.CATEGORY_KEYS:
        assert abs(world.willingness(frame(category=cat))[0] - 1.0) < 0.02


def test_neutral_values_are_really_neutral_for_every_category():
    for cat in world.CATEGORY_KEYS:
        row = neutral_row(cat)
        neutral = neutral_values(row)
        probe = {**row, **neutral}
        df = pd.DataFrame([probe])[RAW_COLUMNS]
        assert abs(world.willingness(df)[0] - 1.0) < 0.02, cat


def test_world_responds_the_way_the_paper_expects():
    assert world.willingness(frame(precipitation=0.9))[0] > 1.2                                   # umbrella + rain
    assert world.willingness(frame(category="ice_cream", temperature=38))[0] > 1.1                # ice cream + heat
    assert world.willingness(frame(category="ice_cream", temperature=10))[0] < 1.0
    assert world.willingness(frame(category="ticket", days_to_event=1, event_score=0.8))[0] > \
        world.willingness(frame(category="ticket", days_to_event=40))[0]                          # ticket urgency
    assert world.willingness(frame(stock_level=5))[0] > world.willingness(frame(stock_level=190))[0]
    assert world.willingness(frame(competitor_price=600))[0] < 1.0


def test_revenue_is_maximised_at_the_true_optimum():
    df = frame(precipitation=0.6)
    ratios = np.linspace(0.65, 1.8, 400)
    rev = [world.expected_revenue(df, [r])[0] for r in ratios]
    assert abs(ratios[int(np.argmax(rev))] - world.willingness(df)[0]) < 0.01


def test_rule_based_baseline_reacts_to_rain():
    assert rule_based_ratio(frame(precipitation=0.8))[0] > rule_based_ratio(frame())[0]


def test_shapley_efficiency_property():
    """Contributions must add up exactly to (full prediction - neutral prediction)."""
    row = neutral_row()
    row.update(precipitation=0.8, hour_of_day=20, stock_level=10, is_holiday=1, event_score=0.9, days_to_event=0)
    out = shapley_contributions(rule_based_ratio, row)
    total = sum(out["contributions"].values())
    assert abs(total - ((out["full_ratio"] - 1.0) * 100 - out["neutral_offset_pct"])) < 1e-6
    assert set(out["contributions"]) == set(EXPLAIN_GROUPS)
    assert out["contributions"]["weather"] > 0 and out["contributions"]["inventory"] > 0


def test_trained_models_beat_baselines(trained_model):
    m = {s["key"]: s for s in trained_model.metrics()["strategies"]}
    assert m["gradient_boosting"]["rmse"] < m["rule_based"]["rmse"] < m["static"]["rmse"]
    assert m["gradient_boosting"]["revenue_lift_pct"] > m["rule_based"]["revenue_lift_pct"] > 0
    assert m["oracle"]["revenue_lift_pct"] >= m["gradient_boosting"]["revenue_lift_pct"] - 0.2
    assert trained_model.metrics()["demand_model"]["r2_vs_expected"] > 0.8


def test_demand_is_monotone_in_price(trained_model):
    df = frame(precipitation=0.4)
    ratios = np.linspace(0.65, 1.8, 20)
    rep = pd.concat([df] * 20, ignore_index=True)
    units = trained_model.predict_units(rep, ratios, features=engineer_features(rep))
    assert np.all(np.diff(units) <= 1e-9)
