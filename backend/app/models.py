"""ORM tables. Mirrors the schema described in the project reports:
products, signals (demand + weather), price_recommendations, price_history,
models, rules - plus weather_logs and sales_logs for monitoring."""
from __future__ import annotations

from sqlalchemy import (
    Boolean, Column, DateTime, Float, ForeignKey, Index, Integer, String, Text,
)
from sqlalchemy.orm import relationship

from .database import Base
from .utils.timeutils import utcnow


class Product(Base):
    __tablename__ = "products"

    id = Column(Integer, primary_key=True, index=True)
    sku = Column(String(50), unique=True, index=True, nullable=False)
    name = Column(String(100), nullable=False)
    category = Column(String(50), nullable=False)
    base_price = Column(Float, nullable=False)
    cost = Column(Float, nullable=False)
    price_min = Column(Float, default=0.0)
    price_max = Column(Float, default=9999999.0)
    price_step = Column(Float, default=1.0)
    margin_floor = Column(Float, default=0.10)      # price >= cost * (1 + margin_floor)
    max_change_pct = Column(Float, default=0.10)    # volatility cap per price update
    current_stock = Column(Integer, default=0)
    max_stock = Column(Integer, default=200)
    current_price = Column(Float, nullable=True)    # last applied price
    is_active = Column(Boolean, default=True)
    created_at = Column(DateTime, default=utcnow)
    updated_at = Column(DateTime, default=utcnow, onupdate=utcnow)

    signals = relationship("PriceSignal", back_populates="product", cascade="all, delete-orphan")
    recommendations = relationship("PriceRecommendation", back_populates="product", cascade="all, delete-orphan")
    history = relationship("PriceHistory", back_populates="product", cascade="all, delete-orphan")


class PriceSignal(Base):
    """One observation of demand + context for a product (demand_logs/weather_logs)."""
    __tablename__ = "price_signals"
    __table_args__ = (Index("ix_signal_product_ts", "product_id", "timestamp"),)

    id = Column(Integer, primary_key=True, index=True)
    product_id = Column(Integer, ForeignKey("products.id"), index=True, nullable=False)
    timestamp = Column(DateTime, default=utcnow)
    page_views = Column(Integer, default=0)
    add_to_carts = Column(Integer, default=0)
    conversions = Column(Integer, default=0)
    stock_level = Column(Integer)
    temperature = Column(Float)
    precipitation = Column(Float)
    humidity = Column(Float)
    weather_code = Column(Integer)
    is_holiday = Column(Boolean, default=False)
    event_score = Column(Float, default=0.0)
    competitor_price = Column(Float)
    source = Column(String(20), default="api")      # api | simulator | seed

    product = relationship("Product", back_populates="signals")


class WeatherLog(Base):
    __tablename__ = "weather_logs"

    id = Column(Integer, primary_key=True)
    timestamp = Column(DateTime, default=utcnow, index=True)
    city = Column(String(60))
    temperature = Column(Float)
    humidity = Column(Float)
    precipitation = Column(Float)
    condition = Column(String(40))
    weather_code = Column(Integer)
    wind_speed = Column(Float)
    source = Column(String(20))


class PriceRecommendation(Base):
    __tablename__ = "price_recommendations"
    __table_args__ = (Index("ix_rec_product_ts", "product_id", "timestamp"),)

    id = Column(Integer, primary_key=True, index=True)
    product_id = Column(Integer, ForeignKey("products.id"), index=True, nullable=False)
    timestamp = Column(DateTime, default=utcnow)
    recommended_price = Column(Float, nullable=False)   # raw model output
    base_price = Column(Float, nullable=False)
    final_price = Column(Float, nullable=False)         # after guardrails
    model_version = Column(String(60))
    model_type = Column(String(40))
    confidence = Column(Float, default=0.0)
    rationale = Column(Text)
    constraints_hit = Column(Text)                      # JSON list
    payload_json = Column(Text)                         # full explanation payload (cached for the API)
    latency_ms = Column(Float)

    product = relationship("Product", back_populates="recommendations")


class PriceHistory(Base):
    __tablename__ = "price_history"
    __table_args__ = (Index("ix_hist_product_ts", "product_id", "timestamp"),)

    id = Column(Integer, primary_key=True, index=True)
    product_id = Column(Integer, ForeignKey("products.id"), index=True, nullable=False)
    timestamp = Column(DateTime, default=utcnow)
    price = Column(Float, nullable=False)
    source = Column(String(30), default="model")        # model | seed | manual

    product = relationship("Product", back_populates="history")


class SalesLog(Base):
    """Simulated sales per interval, with the counterfactual 'keep base price'
    outcome so the dashboard can show realised revenue lift."""
    __tablename__ = "sales_logs"
    __table_args__ = (Index("ix_sales_product_ts", "product_id", "timestamp"),)

    id = Column(Integer, primary_key=True)
    product_id = Column(Integer, ForeignKey("products.id"), index=True, nullable=False)
    timestamp = Column(DateTime, default=utcnow)
    price = Column(Float, nullable=False)
    units = Column(Float, nullable=False)
    revenue = Column(Float, nullable=False)
    baseline_units = Column(Float, nullable=False)
    baseline_revenue = Column(Float, nullable=False)


class PricingRule(Base):
    """Admin-defined guardrails (the /rules API)."""
    __tablename__ = "pricing_rules"

    id = Column(Integer, primary_key=True)
    scope = Column(String(20), nullable=False)          # global | category | product
    scope_value = Column(String(60), nullable=True)     # category name or product id
    rule_type = Column(String(30), nullable=False)
    value = Column(Float, nullable=False, default=0.0)
    is_active = Column(Boolean, default=True)
    note = Column(String(200))
    created_at = Column(DateTime, default=utcnow)


class MLModelRecord(Base):
    __tablename__ = "ml_models"

    id = Column(Integer, primary_key=True)
    version = Column(String(60), index=True)
    model_type = Column(String(40))
    trained_at = Column(DateTime, default=utcnow)
    n_samples = Column(Integer)
    metrics_json = Column(Text)
    artifact_path = Column(String(300))
    is_active = Column(Boolean, default=False)


class User(Base):
    """Dashboard users. Role 'admin' can change anything; 'viewer' is read-only."""
    __tablename__ = "users"

    id = Column(Integer, primary_key=True)
    username = Column(String(40), unique=True, index=True, nullable=False)
    password_hash = Column(String(255), nullable=False)
    role = Column(String(20), nullable=False, default="viewer")
    is_active = Column(Boolean, default=True)
    must_change_password = Column(Boolean, default=False)
    token_version = Column(Integer, default=0)          # bump to invalidate every token of this user
    created_at = Column(DateTime, default=utcnow)
    last_login = Column(DateTime, nullable=True)
