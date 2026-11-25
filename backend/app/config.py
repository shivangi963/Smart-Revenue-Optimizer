"""Central configuration. Every value can be overridden with an environment
variable or a `.env` file placed in `backend/` (see `.env.example`)."""
from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv

BACKEND_DIR = Path(__file__).resolve().parent.parent
PROJECT_DIR = BACKEND_DIR.parent

load_dotenv(BACKEND_DIR / ".env")
load_dotenv(PROJECT_DIR / ".env")


def _str(name: str, default: str) -> str:
    value = os.getenv(name)
    return value.strip() if value and value.strip() else default


def _bool(name: str, default: bool) -> bool:
    value = os.getenv(name)
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


def _int(name: str, default: int) -> int:
    try:
        return int(os.getenv(name, default))
    except (TypeError, ValueError):
        return default


@dataclass(frozen=True)
class Settings:
    app_name: str
    version: str
    # Database: SQLite by default (zero setup). For MySQL use e.g.
    #   mysql+pymysql://user:password@localhost:3306/smart_revenue
    database_url: str
    cors_origins: tuple
    model_dir: Path
    # Store context (drives weather, holidays and local time-of-day features)
    store_city: str
    store_timezone: str
    holiday_country: str
    base_currency: str
    # Behaviour
    price_refresh_seconds: int      # how long a computed price is considered fresh
    scheduler_enabled: bool
    scheduler_interval_seconds: int
    signal_simulator_enabled: bool  # generate synthetic demand signals + sales
    auto_train: bool                # train the ML model on first start if no artifact
    train_samples: int
    seed_history_hours: int
    # Authentication
    auth_enabled: bool
    secret_key: str
    token_expire_minutes: int
    ingest_api_key: str             # optional: lets scripts/storefronts POST /signals without a user login
    admin_username: str
    admin_password: str             # empty -> default demo password (flagged "must change")
    password_hash_iterations: int


def _load_secret_key() -> str:
    """SECRET_KEY from the environment, else a random key persisted in backend/.secret_key so that
    logins survive a restart (the file is git-ignored)."""
    env = os.getenv("SECRET_KEY", "").strip()
    if env:
        return env
    path = BACKEND_DIR / ".secret_key"
    try:
        if path.exists() and path.read_text().strip():
            return path.read_text().strip()
        import secrets

        key = secrets.token_urlsafe(48)
        path.write_text(key)
        return key
    except OSError:                       # read-only filesystem: ephemeral key (logins end on restart)
        import secrets

        return secrets.token_urlsafe(48)


def load_settings() -> Settings:
    default_db = f"sqlite:///{(BACKEND_DIR / 'pricing.db').as_posix()}"
    origins = _str(
        "CORS_ORIGINS", "http://localhost:3000,http://localhost:3001,http://127.0.0.1:3000"
    )
    return Settings(
        app_name="Smart Revenue Optimizer",
        version="2.0.0",
        database_url=_str("DATABASE_URL", default_db),
        cors_origins=tuple(o.strip() for o in origins.split(",") if o.strip()),
        model_dir=Path(_str("MODEL_DIR", str(BACKEND_DIR / "models"))),
        store_city=_str("STORE_CITY", "Bengaluru"),
        store_timezone=_str("STORE_TIMEZONE", "Asia/Kolkata"),
        holiday_country=_str("HOLIDAY_COUNTRY", "IN"),
        base_currency=_str("BASE_CURRENCY", "INR"),
        price_refresh_seconds=_int("PRICE_REFRESH_SECONDS", 120),
        scheduler_enabled=_bool("SCHEDULER_ENABLED", True),
        scheduler_interval_seconds=_int("SCHEDULER_INTERVAL_SECONDS", 300),
        signal_simulator_enabled=_bool("SIGNAL_SIMULATOR_ENABLED", True),
        auto_train=_bool("AUTO_TRAIN", True),
        train_samples=_int("TRAIN_SAMPLES", 25000),
        seed_history_hours=_int("SEED_HISTORY_HOURS", 48),
        auth_enabled=_bool("AUTH_ENABLED", True),
        secret_key=_load_secret_key(),
        token_expire_minutes=_int("TOKEN_EXPIRE_MINUTES", 480),
        ingest_api_key=os.getenv("INGEST_API_KEY", "").strip(),
        admin_username=_str("ADMIN_USERNAME", "admin"),
        admin_password=os.getenv("ADMIN_PASSWORD", "").strip(),
        password_hash_iterations=_int("PASSWORD_HASH_ITERATIONS", 240000),
    )


settings = load_settings()
