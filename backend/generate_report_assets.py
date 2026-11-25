"""Generate the figures and tables for the project report from the *trained model*.

    python generate_report_assets.py            # writes ../docs/report_assets/

Produces (PNG, 200 dpi) the charts promised in the base paper plus extra evaluation plots,
a Markdown file with all result tables, and a CSV sample of the training data.
Needs matplotlib:  pip install matplotlib
"""
import warnings
from pathlib import Path

warnings.filterwarnings("ignore")

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd

from app.ml import world
from app.ml.demand import DEFAULT_GRID, peak_from_curve
from app.ml.features import FEATURE_GROUPS, GROUP_LABELS, RAW_COLUMNS, engineer_features, raw_frame
from app.ml.registry import model_service
from app.ml.trainer import MODEL_LABELS

OUT = Path(__file__).resolve().parent.parent / "docs" / "report_assets"
OUT.mkdir(parents=True, exist_ok=True)
PURPLE, BLUE, GREEN, RED, GREY = "#764ba2", "#667eea", "#10b981", "#ef4444", "#9ca3af"
plt.rcParams.update({"font.size": 10, "axes.spines.top": False, "axes.spines.right": False, "axes.grid": True,
                     "grid.alpha": 0.25, "figure.dpi": 100})

if not model_service.load():
    print("No saved model - training one (about a minute)...")
    model_service.train()
metrics = model_service.metrics()
rows = {r["key"]: r for r in metrics["strategies"]}
active = model_service.active_type


def save(fig, name):
    fig.tight_layout()
    fig.savefig(OUT / name, dpi=200)
    plt.close(fig)
    print("  wrote", name)


def base_row(category, base, cost, hour=12, **kw):
    pv = float(world.expected_page_views(category, hour))
    row = {"category": category, "base_price": base, "cost": cost, "hour_of_day": hour, "day_of_week": 2, "month": 10,
           "page_views_1h": pv, "expected_page_views": pv, "add_to_cart_rate": 0.15, "conversion_rate": 0.30,
           "stock_level": 100, "max_stock": 200, "temperature": 26.0, "precipitation": 0.0, "humidity": 60.0,
           "is_holiday": 0, "event_score": 0.0, "days_to_event": 60.0, "competitor_price": base}
    row.update(kw)
    return row


# ---- Figure 1: feature importance (paper Fig. 2) ------------------------------------------------
print("Figures:")
fi = model_service.feature_importance(top=10)
groups = list(reversed(fi["grouped"]))
fig, ax = plt.subplots(figsize=(7, 4))
ax.barh([g["label"] for g in groups], [g["pct"] for g in groups], color=[BLUE, PURPLE, GREEN, "#f59e0b", RED, "#06b6d4", GREY][:len(groups)][::-1])
for i, g in enumerate(groups):
    ax.text(g["pct"] + 0.5, i, f"{g['pct']:.1f}%", va="center")
ax.set_xlabel("Share of total feature importance (%)")
ax.set_title(f"Feature importance by factor group ({fi['model_label']})")
save(fig, "fig1_feature_importance.png")

# ---- Figure 2: model comparison -------------------------------------------------------------------
order = ["static", "rule_based", "linear", "random_forest", "gradient_boosting", "oracle"]
labels = [MODEL_LABELS[k].replace(" (upper bound)", "\n(upper bound)").replace(" ", "\n", 1) for k in order]
fig, axes = plt.subplots(1, 3, figsize=(12, 3.8))
for ax, (key, title, fmt) in zip(axes, [("rmse", "RMSE (price units, lower is better)", "{:.1f}"),
                                         ("r2", "R² (higher is better)", "{:.3f}"),
                                         ("revenue_lift_pct", "Revenue lift vs static pricing (%)", "{:.2f}")]):
    vals = [rows[k][key] for k in order]
    colors = [GREY if k in ("static", "oracle") else (PURPLE if k == active else BLUE) for k in order]
    bars = ax.bar(labels, vals, color=colors)
    ax.set_title(title, fontsize=10)
    ax.tick_params(axis="x", labelsize=7)
    for b, v in zip(bars, vals):
        ax.text(b.get_x() + b.get_width() / 2, max(v, 0), fmt.format(v), ha="center", va="bottom", fontsize=7)
save(fig, "fig2_model_comparison.png")

# ---- Figure 3: 24-hour price trend (paper Fig. 3) -------------------------------------------------
scenarios = [
    ("Premium Umbrella — monsoon day, rain builds in the evening", "umbrella", 799, 400,
     lambda h: dict(month=8, precipitation=float(np.clip(0.15 + 0.7 * np.exp(-((h - 19) / 3.5) ** 2), 0, 1)), temperature=24 - 3 * np.exp(-((h - 19) / 4) ** 2))),
    ("Artisanal Ice Cream — hot summer day", "ice_cream", 199, 85,
     lambda h: dict(month=4, temperature=30 + 8 * np.exp(-((h - 15) / 4.5) ** 2), precipitation=0.0)),
    ("Concert Ticket — festival 3 days away", "ticket", 2499, 1500,
     lambda h: dict(month=11, days_to_event=3, event_score=0.8 * np.exp(-3 / 4), temperature=26.0)),
]
fig, axes = plt.subplots(1, 3, figsize=(13, 3.8))
for ax, (title, cat, base, cost, ctx) in zip(axes, scenarios):
    hours = np.arange(24)
    rows_ = [base_row(cat, base, cost, hour=int(h), **ctx(h)) for h in hours]
    ratio, _, _ = model_service.predict_ratio(raw_frame(rows_))
    prices = np.clip(ratio, 0.65, 1.8) * base
    ax.plot(hours, prices, marker="o", ms=4, color=BLUE, lw=2)
    ax.axhline(base, color=GREY, ls="--", lw=1)
    ax.text(0.3, base, " base", va="bottom", fontsize=8, color="#6b7280")
    ax.set_title(title, fontsize=8.5)
    ax.set_xlabel("Hour of day")
    ax.set_xticks([0, 6, 12, 18, 23])
axes[0].set_ylabel("Recommended price (INR)")
save(fig, "fig3_price_trend_24h.png")

# ---- Figure 4: revenue vs candidate price (paper 'response curve') -------------------------------
fig, axes = plt.subplots(1, 3, figsize=(13, 3.8))
for ax, (title, cat, base, cost, ctx) in zip(axes, scenarios):
    row = base_row(cat, base, cost, hour=19 if cat != "ice_cream" else 15, **ctx(19 if cat != "ice_cream" else 15))
    frame = raw_frame([row])
    feats = engineer_features(frame)
    rep_raw, rep_feat = pd.concat([frame] * len(DEFAULT_GRID), ignore_index=True), pd.concat([feats] * len(DEFAULT_GRID), ignore_index=True)
    units = model_service.predict_units(rep_raw, DEFAULT_GRID, features=rep_feat)
    prices = DEFAULT_GRID * base
    revenue = units * prices
    peak, fitted = peak_from_curve(DEFAULT_GRID, revenue)
    rec = float(np.clip(model_service.predict_ratio(frame)[0][0], 0.65, 1.8)) * base
    ax.plot(prices, revenue, "o", ms=3, color="#c4b5fd", label="demand model")
    ax.plot(prices, fitted, color=PURPLE, lw=2, label="smoothed")
    ax.axvline(base, color=GREY, ls="--", lw=1, label="base price")
    ax.axvline(rec, color=BLUE, lw=2, label="recommended")
    ax.set_title(title.split(" — ")[0], fontsize=9)
    ax.set_xlabel("Candidate price (INR)")
axes[0].set_ylabel("Expected revenue / hour (INR)")
axes[0].legend(fontsize=7)
save(fig, "fig4_revenue_vs_price.png")

# ---- Figure 5: predicted vs actual on unseen data -------------------------------------------------
rng = np.random.default_rng(2026)
test = world.add_labels(world.sample_raw_contexts(3000, rng), rng)
X = engineer_features(test[RAW_COLUMNS])
pred = model_service.predict_ratio_features(X)
fig, ax = plt.subplots(figsize=(4.8, 4.6))
ax.scatter(test["label_ratio"], pred, s=5, alpha=0.35, color=BLUE)
ax.plot([0.6, 1.8], [0.6, 1.8], color=RED, lw=1.5, label="perfect prediction")
ax.set_xlabel("Actual optimal price ratio")
ax.set_ylabel("Predicted price ratio")
ax.set_title(f"{MODEL_LABELS[active]}: predicted vs actual (3,000 new contexts)", fontsize=9)
ax.legend()
save(fig, "fig5_predicted_vs_actual.png")

# ---- tables ----------------------------------------------------------------------------------------
md = ["# Results tables (auto-generated)\n",
      f"Model version **{metrics['version']}**, trained on {metrics['n_train'] + metrics['n_test']:,} synthetic observations "
      f"({metrics['n_train']:,} train / {metrics['n_test']:,} test). MAE/RMSE in INR; revenue/profit lift vs static base-price pricing.\n",
      "## Model comparison\n", "| Strategy | MAE | RMSE | R² | Revenue lift | Profit lift | Latency (ms) |", "|---|---:|---:|---:|---:|---:|---:|"]
for k in order:
    r = rows[k]
    md.append(f"| {r['label']} | {r['mae']:.2f} | {r['rmse']:.2f} | {r['r2']:.3f} | {r['revenue_lift_pct']:+.2f}% | "
              f"{r['profit_lift_pct']:+.1f}% | {r['latency_ms']:.2f} |")
share = rows["gradient_boosting"]["revenue_lift_pct"] / rows["oracle"]["revenue_lift_pct"] * 100
md += ["", f"Gradient Boosting captures **{share:.0f}%** of the revenue lift attainable by a perfect oracle.\n",
       "## Feature importance by group (" + fi["model_label"] + ")\n", "| Group | Importance |", "|---|---:|"]
md += [f"| {g['label']} | {g['pct']:.1f}% |" for g in fi["grouped"]]
md += ["", "## Top individual features\n", "| Feature | Importance |", "|---|---:|"]
md += [f"| {f['feature']} | {f['pct']:.1f}% |" for f in fi["top_features"]]
d = metrics["demand_model"]
md += ["", "## Demand model\n", f"- R² vs true expected demand: **{d['r2_vs_expected']:.3f}**",
       f"- Mean absolute error: {d['mae_units']:.2f} units/hour",
       f"- Revenue-maximising price located within **{d['optimum_mae_pct']:.1f}%** of the true optimum (of base price)", "",
       "## Feature table\n", "| Group | Features |", "|---|---|"]
md += [f"| {GROUP_LABELS[g]} | {', '.join(cols)} |" for g, cols in FEATURE_GROUPS.items()]
(OUT / "results.md").write_text("\n".join(md), encoding="utf-8")
test.rename(columns={"label_ratio": "optimal_price_ratio", "true_g": "latent_willingness", "obs_ratio": "observed_price_ratio",
                     "units": "units_sold"}).head(200).round(4).to_csv(OUT / "training_data_sample.csv", index=False)
print("Tables: results.md, training_data_sample.csv\nDone ->", OUT)
