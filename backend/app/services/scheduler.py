"""Background scheduler.
Every N seconds: simulate storefront traffic -> re-price all products -> log weather."""
from __future__ import annotations

import asyncio
import logging

from starlette.concurrency import run_in_threadpool

from ..config import settings
from ..database import session_scope
from ..models import WeatherLog
from ..utils.timeutils import iso_z, utcnow
from .pricing_engine import PricingEngine
from .simulator import simulate_tick

log = logging.getLogger("scheduler")


class Scheduler:
    def __init__(self, engine: PricingEngine):
        self.engine = engine
        self.runs = 0
        self.last_run = None
        self.last_error = None
        self.running = False

    def tick(self) -> None:
        with session_scope() as db:
            weather = self.engine.weather.get_weather()
            if settings.signal_simulator_enabled:
                simulate_tick(db, self.engine, interval_minutes=settings.scheduler_interval_seconds / 60.0,
                              weather=weather)
            self.engine.refresh_all(db)
            db.add(WeatherLog(city=weather["city"], temperature=weather["temperature"], humidity=weather.get("humidity"),
                              precipitation=weather["precipitation"], condition=weather["condition"],
                              weather_code=weather.get("weather_code"), wind_speed=weather.get("wind_speed"),
                              source=weather.get("source")))
        self.runs += 1
        self.last_run = iso_z(utcnow())
        self.last_error = None

    async def run(self) -> None:
        self.running = True
        await asyncio.sleep(10)              # let the app finish starting
        while True:
            try:
                await run_in_threadpool(self.tick)
            except Exception as exc:         # keep the loop alive no matter what
                self.last_error = str(exc)
                log.exception("scheduler tick failed")
            await asyncio.sleep(settings.scheduler_interval_seconds)

    def status(self) -> dict:
        return {"enabled": settings.scheduler_enabled, "running": self.running, "runs": self.runs,
                "last_run": self.last_run, "last_error": self.last_error,
                "interval_seconds": settings.scheduler_interval_seconds,
                "simulator": settings.signal_simulator_enabled}
