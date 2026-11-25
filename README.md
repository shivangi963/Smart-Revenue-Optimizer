# 🎯 Smart Revenue Optimizer

Real-time, **explainable dynamic pricing** for e-commerce. The system reads live weather, the holiday
calendar, demand signals (page views, carts, orders), stock levels and competitor prices, asks a trained
machine-learning model for the revenue-maximising price, keeps it inside business guardrails, and tells
you *why* in plain English.

Major-project upgrade of the *Dynamic Pricing Engine* mini project (FastAPI + React; SQLite by default, MySQL optional).

| | |
|---|---|
| **Backend** | FastAPI · SQLAlchemy (SQLite default, MySQL optional) · scikit-learn |
| **Frontend** | React 18 · Recharts |
| **ML** | Linear Regression vs Random Forest vs Gradient Boosting (+ static & rule-based baselines), a monotone demand model, exact Shapley explanations |
| **Result** | Gradient Boosting captures **99 %** of the revenue lift a perfect oracle could get (≈ +4.6 % vs static pricing) at **< 10 ms** per price |

---

## 🚀 Quick start

You need **Python 3.10 – 3.12** and **Node.js 18+**. Open two terminals.

**Terminal 1 – backend**
```bash
cd backend
# Create your local environment file (PowerShell / Windows)
copy ..\.env.example .env
# On macOS/Linux, use: cp ../.env.example .env
python -m venv venv
venv\Scripts\activate            # Windows      (Mac/Linux: source venv/bin/activate)
pip install -r ../requirements.txt
python run.py
```
> **First login:** if you leave `ADMIN_PASSWORD` unset, the first run creates **`admin` / `admin123`** and requires
> you to change that password. If you set your own `ADMIN_USERNAME` and `ADMIN_PASSWORD` in `backend/.env`,
> those credentials are used and the forced password-change prompt is skipped. Never commit `backend/.env`.

**Terminal 2 – frontend**
```bash
cd frontend
npm install
npm start
```
Open **http://localhost:3000** (API docs: http://localhost:8000/docs).

> **First start:** there is no trained model yet, so the backend trains one in the background (~1 minute).
> The app works immediately using simple rules and switches to the ML model automatically – the header
> shows "Training model…" until it finishes. The trained model is cached in `backend/models/`.
> Demo products and 48 hours of price/sales history are created on first run so every chart has data.

### Optional: export a synthetic training dataset
Run this from inside `backend/` after installing the backend dependencies:
```bash
python ../data/synthetic_data.py --export training_data.csv --rows 5000
```
This creates a CSV file in the current `backend/` directory.

---

## 🧭 What you can do in the UI

| Tab | Purpose |
|---|---|
| **Dashboard** | KPIs, product cards, current price with factor breakdown + plain-English justification, live weather, upcoming festivals, 24 h revenue impact vs static pricing |
| **Simulator** | What-if sliders (weather, hour, traffic, stock, competitor, festival…) with instant re-pricing and explanation |
| **History & Forecast** | Applied price history + 24-hour forecast, and the audit trail of recent decisions |
| **Model Analytics** | Model comparison table (MAE/RMSE/R²/revenue lift/latency), feature importance, revenue-vs-price curve, live model switching & retraining |
| **Admin** | Add/remove products, update stock, create guardrail rules (min/max, margin floor, max discount/markup, change cap, freeze) |
| **Currency** | Convert prices for international shoppers |

---

## 🔐 Login & roles

| Role | Can do |
|---|---|
| **Administrator** | everything: products, stock, guardrail rules, retrain/switch models, manage users |
| **Viewer** | read-only: dashboard, history, analytics, what-if simulator |

* Passwords are stored as salted **PBKDF2-SHA256** hashes (never in plain text); sessions are signed **JWT** tokens that expire (8 h).
* Changing a password, changing a role or disabling a user **instantly revokes** that user's existing sessions.
* 5 wrong passwords lock that username for 5 minutes (brute-force protection); wrong user vs wrong password look identical.
* Permissions are enforced **on the server** (the UI merely hides buttons) - covered by automated tests, including forged tokens.
* Scripts/storefronts can POST `/signals` with an `X-API-Key` header (set `INGEST_API_KEY`) instead of a user login.
* `AUTH_ENABLED=false` switches login off for local experiments only.
* Swagger (`/docs`) has an **Authorize** button - sign in there to try the API.
* Limitation: the token is kept in the browser's localStorage; a production deployment should use HTTPS and httpOnly cookies.

## 🏗️ How it works

```
 Storefront signals ─┐                               ┌─► price history, audit trail
 Live weather ───────┤   Feature      ML model       │
 Holiday calendar ───┼─► engineering ─► (GBR) ─► Guardrails ─► Final price + Shapley explanation
 Stock / competitor ─┘   (35 features)      ▲        (min/max, margin,           │
                                            │         volatility cap, rules)     ▼
                              Demand model (units vs price) ──► revenue curve, confidence, expected lift
```

* **Market world** (`app/ml/world.py`) – no real sales logs exist, so (as in the minor-project report) a latent
  demand model generates training data: `D(p) = V·max(0, 1 − p/(2·b·g(x)))`, where `g(x)` combines time, season,
  weather, events, demand, stock and competition. Revenue peaks at `p* = b·g(x)`; the models only ever see
  observable features + noisy labels.
* **Feature engineering** (`app/ml/features.py`) – one function for training *and* serving (no train/serve skew),
  including category × weather interaction terms.
* **Explainability** (`app/services/explainer.py`) – exact Shapley values over six factor groups; contributions
  sum exactly to the model's price change.
* **Guardrails** (`app/services/guardrails.py`) – `P = min(Pmax, max(Pmin, P*))` plus margin floor, step rounding,
  per-update volatility cap and admin rules (product > category > global).
* **Demand sensing** is smoothed over the last 3 observations (a moving average) – one hour with 5 carts is too noisy.
* **Scheduler** – every 5 min: simulate storefront traffic → re-price → log weather. (`.env`: `SCHEDULER_*`)

### Project layout
```
backend/app/
  main.py  config.py  database.py  models.py  schemas.py  container.py
  ml/        world.py  features.py  trainer.py  demand.py  baselines.py  registry.py
  services/  pricing_engine.py  guardrails.py  explainer.py  weather_service.py  holiday_service.py
             exchange_service.py  simulator.py  seed.py  scheduler.py  metrics.py
  routers/   products  pricing  signals  rules  external  analytics  model  system
backend/tests/        unit + API + browser-free integration tests
frontend/src/components/   Dashboard, Simulator, History, Model Analytics, Admin, Currency
data/synthetic_data.py     push signals to the API / export the training dataset
docs/REPORT_GUIDE.md       maps the base paper to the code + viva preparation
```

---

## 🔌 API (full interactive docs at `/docs`)

| Endpoint | |
|---|---|
| `GET /products` · `POST /products` · `PUT/DELETE /products/{id}` | product management |
| `POST /products/{id}/update_stock` | set stock → instant re-price |
| `GET /prices/{id}/current` · `GET /prices/current` | live price + factors + explanation |
| `POST /simulate_price` | what-if (nothing stored) |
| `GET /history/{id}` · `GET /recommendations/{id}` | price history · decision audit trail |
| `POST /signals` · `GET /signals/{id}` · `POST /signals/simulate` | demand signals |
| `GET/POST/PUT/DELETE /rules` · `GET /rules/types` | guardrail admin |
| `GET /api/weather/current` · `/forecast` · `GET /api/holidays/upcoming` | external context |
| `GET /api/exchange/currencies` · `/rates` · `/convert` | currency |
| `GET /api/dashboard/stats` · `/api/analytics/revenue-summary` | KPIs |
| `GET /api/analytics/revenue-curve/{id}` · `/price-forecast/{id}` | paper Fig. 3 & 4 |
| `GET /api/model/info` · `/metrics` · `/feature-importance` · `/latency` | evaluation |
| `POST /api/model/retrain` · `POST /api/model/select` | retrain / switch model |
| `POST /auth/login` · `GET /auth/me` · `POST /auth/change-password` | sign in / session / password |
| `POST /auth/register` | public registration; new accounts are always **Viewer** |
| `GET/POST/PUT/DELETE /auth/users` | user management (admin; create/update/delete users) |
| `GET /health` · `GET /api/config` | system (public) |

---

## ⚙️ Configuration

Copy the root `.env.example` file to `backend/.env` and edit the values you need. The defaults work with local SQLite.

**Optional MySQL setup:** create a database first, then set the following in `backend/.env` (replace the username/password):
```env
DATABASE_URL=mysql+pymysql://root:yourpassword@localhost:3306/smart_revenue
```
The MySQL server must be running. The required PyMySQL driver is included in `requirements.txt`; tables are created automatically.

**Admin credentials:** by default, the first startup creates `admin` / `admin123` and flags it for a password change. To choose credentials before the first startup, uncomment and set `ADMIN_USERNAME` and `ADMIN_PASSWORD` in `backend/.env`. When `ADMIN_PASSWORD` is set, the app does not force a first-login password change.

**Frontend API URL:** the frontend defaults to `http://localhost:8000`. Only if your backend runs at another address, create `frontend/.env` using `frontend/.env.example` and set `REACT_APP_API_URL`.

**Live weather** uses Open-Meteo (free, no key). If the API is unreachable the app falls back to
*deterministic simulated weather* (marked "simulated" in the UI) so it never breaks offline.
Change `STORE_CITY` (Bengaluru, Mumbai, Delhi, Chennai, Hyderabad, Kolkata, Pune, London, New York, …).

**Real data:** set `SIGNAL_SIMULATOR_ENABLED=false`, POST real funnel counts to `/signals`, then retrain.

---

## ⚠️ Honest limitations
* The ML models are trained on **synthetic** data from an assumed demand model (no real shop is attached), so
  the reported lift is *relative to that world*, not a field measurement. The architecture is ready for real
  data: feed `/signals` + real sales, then retrain.
* Sales shown on the dashboard are **simulated** from the same world, logged next to the "keep base price"
  counterfactual.
* Price elasticity is assumed linear; real catalogues need per-product elasticity learning (A/B price tests).

## 🛠️ Troubleshooting
| Problem | Fix |
|---|---|
| `ModuleNotFoundError: app` | run `python run.py` from inside `backend/` |
| Pip fails building pydantic/numpy | use Python 3.10–3.12 (3.13 is too new for the pinned versions) |
| Header says "Training model…" for long | first run only; check the backend terminal; or run `python train_model.py` |
| Frontend: "Can't reach the backend" | start the backend first; or set `REACT_APP_API_URL` |
| Port 8000/3000 busy | stop the other process, or `uvicorn app.main:app --port 8010` + `REACT_APP_API_URL` |
| `pytest` TypeError about `app=` | `pip install "httpx<0.28"` (already pinned in requirements-dev.txt) |
# Smart-Revenue-Optimizer
