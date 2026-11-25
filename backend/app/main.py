"""Smart Revenue Optimizer - FastAPI application."""
from __future__ import annotations

import asyncio
import logging
from contextlib import asynccontextmanager

from fastapi import Depends, FastAPI
from fastapi.middleware.cors import CORSMiddleware

from .config import settings
from .container import engine, model_service
from .database import init_db, session_scope
from .routers import analytics, auth, external, model, pricing, products, rules, signals, system
from .security import ensure_default_admin, get_current_user
from .services.scheduler import Scheduler
from .services.seed import backfill_history, seed_products

log = logging.getLogger("smart-revenue")
logging.basicConfig(level=logging.INFO, format="%(levelname)s  %(name)s: %(message)s")


def _backfill() -> None:
    """Populate price/sales history once a pricing model exists (no-op if history exists)."""
    try:
        with session_scope() as db:
            n = backfill_history(db, engine)
        if n:
            log.info("Backfilled %d hours of price history", n)
    except Exception:
        log.exception("History backfill failed")


@asynccontextmanager
async def lifespan(app: FastAPI):
    init_db()
    with session_scope() as db:
        created = seed_products(db)
    if created:
        log.info("Seeded %d demo products", created)

    with session_scope() as db:
        warning = ensure_default_admin(db)
    if warning:
        log.warning(warning)
    if not settings.auth_enabled:
        log.warning("AUTH_ENABLED=false - every request is treated as an administrator. Development only!")

    model_service.on_ready(_backfill)
    if model_service.load():
        log.info("Loaded model %s (%s)", model_service.version, model_service.model_type)
    elif settings.auto_train:
        log.info("No saved model found - training in the background (the API works meanwhile "
                 "using the rule-based fallback)...")
        model_service.train_async()
    else:
        _backfill()

    scheduler = Scheduler(engine)
    system.register_scheduler(scheduler)
    task = None
    if settings.scheduler_enabled:
        task = asyncio.create_task(scheduler.run())
    yield
    if task:
        task.cancel()


app = FastAPI(
    title=settings.app_name,
    description="Real-time, explainable dynamic pricing: weather, holidays, demand and stock signals -> "
                "ML price recommendation -> business guardrails.",
    version=settings.version,
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=list(settings.cors_origins),
    allow_origin_regex=r"http://(localhost|127\.0\.0\.1)(:\d+)?",
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Public: health/config and the login endpoints themselves.
app.include_router(system.router)
app.include_router(auth.router)
# Signals do their own per-route checks (they also accept an ingest API key).
app.include_router(signals.router)
# Everything else needs a signed-in user (admin-only actions are marked on the individual routes).
for r in (products.router, pricing.router, rules.router, external.router, analytics.router, model.router):
    app.include_router(r, dependencies=[Depends(get_current_user)])

if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host="0.0.0.0", port=8000)
