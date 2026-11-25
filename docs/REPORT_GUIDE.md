# Report & viva guide

How the **Smart Revenue Optimizer** base paper maps onto the code, which numbers to put in your
Results chapter, and what an examiner is likely to ask. Regenerate all figures/tables any time with
`python generate_report_assets.py` (output in `docs/report_assets/`).

## 1. Paper section → implementation

| Base-paper section | Where it lives |
|---|---|
| 1.4 Objectives – predict price from features | `backend/app/ml/trainer.py`, `features.py` |
| 1.4 – external APIs (weather) | `services/weather_service.py` (Open-Meteo), `holiday_service.py`, `exchange_service.py` |
| 1.4 – simulate stock, page views, orders | `services/simulator.py`, `POST /signals`, `data/synthetic_data.py` |
| 1.4 – dashboard, history, explanations | `frontend/src/components/*` |
| 2.3/2.4 Candidate ML methods | Linear Regression, Random Forest, Gradient Boosting + rule-based + static (`trainer.py`) |
| 3.5 Functional requirements | products API · signals API · weather/holiday APIs · model · explainer · charts |
| 3.6 Non-functional | modular layers; median pricing latency < 10 ms; `tests/` |
| 4.2 Five layers | dashboard · `services/*_service.py` · `ml/features.py` · `ml/registry.py` · `services/explainer.py` |
| 4.5 Feature table | `ml/features.py` → `FEATURE_GROUPS` (35 features) |
| 4.6 `P = min(Pmax, max(Pmin, P*))` | `services/guardrails.py` (+ margin floor, step, volatility cap, rules) |
| 4.7/4.8 Algorithm / pseudocode | `services/pricing_engine.py → PricingEngine.recommend()` |
| 5.1 Stack (FastAPI, React, MySQL, sklearn) | as built; MySQL via `DATABASE_URL` (SQLite is the zero-setup default) |
| 5.4 Tables `products, demand_logs, weather_logs, price_history` | `models.py`: `products`, `price_signals`, `weather_logs`, `price_history` (+ `price_recommendations`, `sales_logs`, `pricing_rules`, `ml_models`) |
| 5.5 Testing (unit / integration / user) | `backend/tests` (43 tests) |
| 5.6 Expected cases (umbrella rain, ice-cream heat, ticket urgency) | `tests/test_api.py::test_simulation_behaves_like_the_paper_says`, Fig. 3 |
| 5.7 Metrics MAE, RMSE, R², revenue lift, latency | Model Analytics tab · `results.md` |
| 5.8 Graphs (price trend, feature importance, revenue vs price) | `fig3_price_trend_24h`, `fig1_feature_importance`, `fig4_revenue_vs_price` |

## 2. Things to update in the paper

* **Figure 2** shows *illustrative* importances (Demand 35 / Stock 25 / Weather 20 / Time 10 / Events 10).
  Replace it with `fig1_feature_importance.png` (real, from the trained model) and quote the real table in `results.md`.
* Figures 1 and 3 can stay as diagrams; add `fig3_price_trend_24h.png` as the *measured* 24-hour behaviour.
* Add the **model comparison table** (`results.md`) and `fig2_model_comparison.png` in the evaluation chapter.
* Mention the two models: the **price model** (regression, recommends the price) and the **demand model**
  (units vs price; draws the revenue curve and scores each recommendation).
* The paper lists Streamlit/MongoDB as options – state what you actually used (React, MySQL/SQLite).
* The paper's prices are in ₹ (the app now uses ₹ too).

## 3. Headline results (25 000 synthetic observations, 5 000 held out)

| Strategy | RMSE (₹) | R² | Revenue lift vs static |
|---|---:|---:|---:|
| Static pricing | 333.5 | −0.29 | 0 % |
| Rule-based | 256.9 | 0.19 | +1.70 % |
| Linear Regression | 62.1 | 0.943 | +4.50 % |
| Random Forest | 95.5 | 0.822 | +4.26 % |
| **Gradient Boosting** | **45.5** | **0.966** | **+4.59 %** |
| Oracle (upper bound) | 34.9 | 0.985 | +4.64 % |

Gradient Boosting reaches **99 %** of the oracle's lift, with ~1.5 ms inference. The live dashboard measures
a comparable realised lift (≈ +3 – 5 %) on simulated sales. *(Your numbers will differ slightly after retraining
because the training set is regenerated; they are reproducible with the same `--seed`.)*

## 4. Likely examiner questions

**Why synthetic data?** No real sales log exists for a student project (the minor-project report also says so).
We define an explicit latent demand model, train only on *observable* features and noisy labels, and evaluate
on unseen contexts. The pipeline accepts real data through `/signals` + retraining.

**Isn't that circular – the model just learns your formula?** Partly, and we say so. What it demonstrates is the
engineering: feature pipeline, model comparison, explainability, guardrails, serving, monitoring. Comparing
against baselines on the *same* world is still meaningful (e.g. rule-based captures 37 % of attainable lift,
Gradient Boosting 99 %). Real-world validation needs A/B price tests – listed as future work.

**Why does Linear Regression do so well?** Because of the engineered interaction features (rain×umbrella,
temperature×ice-cream, …). Ablation on the same data: Linear Regression R² falls from **0.942 → 0.753** when they are
removed, while Gradient Boosting only drops **0.966 → 0.945** because it learns interactions by itself. This makes a
good "feature engineering matters" point for the report. Random Forest (R² 0.82) trails both here – with 120 depth-limited
trees it approximates the smooth additive effects in coarse steps (likely cause; we did not tune it).

**Revenue or profit?** The reports specify revenue `R = p × D`. We maximise expected revenue; the margin floor and
min price guardrails keep every price profitable (profit lift is reported too).

**How is a price explained?** Exact Shapley values over six factor groups (weather, time, events, demand, stock,
competition): all 2⁶ = 64 combinations are evaluated; contributions add up exactly to the price change.

**What stops crazy prices?** `guardrails.py`: min/max, margin floor, ±10 % change per update, step rounding,
admin rules, freeze. All unit-tested.

**What happens offline?** Weather falls back to deterministic simulated weather (flagged in the UI); the model
still serves; exchange rates use an offline table.

## 5. Future work (for the conclusion)
Learn per-product elasticity from real A/B price experiments · reinforcement-learning / bandit pricing ·
competitor price scraping · inventory forecasting · multi-store pricing · drift monitoring and scheduled retraining.
