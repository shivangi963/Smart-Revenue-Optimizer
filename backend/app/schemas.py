"""Request/response schemas (Pydantic v2)."""
from __future__ import annotations

from datetime import datetime
from typing import Any, Dict, Optional

import re

from pydantic import BaseModel, ConfigDict, Field, field_serializer, field_validator, model_validator

from .services.guardrails import RULE_TYPES, SCOPES
from .utils.timeutils import iso_z


class _Out(BaseModel):
    model_config = ConfigDict(from_attributes=True)


# ------------------------------------------------------------------ products
class ProductBase(BaseModel):
    sku: str = Field(min_length=1, max_length=50)
    name: str = Field(min_length=1, max_length=100)
    category: str = Field(min_length=1, max_length=50)
    base_price: float = Field(gt=0)
    cost: float = Field(ge=0)
    price_min: float = Field(default=0.0, ge=0)
    price_max: float = Field(default=9_999_999.0, gt=0)
    price_step: float = Field(default=1.0, gt=0)
    margin_floor: float = Field(default=0.10, ge=0, lt=5)
    max_change_pct: float = Field(default=0.10, gt=0, le=1)
    current_stock: int = Field(default=100, ge=0)
    max_stock: int = Field(default=200, gt=0)

    @model_validator(mode="after")
    def _check(self):
        if self.price_min > self.price_max:
            raise ValueError("price_min cannot exceed price_max")
        if self.cost > self.base_price:
            raise ValueError("cost cannot exceed base_price")
        return self


class ProductCreate(ProductBase):
    pass


class ProductUpdate(BaseModel):
    name: Optional[str] = Field(default=None, min_length=1, max_length=100)
    category: Optional[str] = None
    base_price: Optional[float] = Field(default=None, gt=0)
    cost: Optional[float] = Field(default=None, ge=0)
    price_min: Optional[float] = Field(default=None, ge=0)
    price_max: Optional[float] = Field(default=None, gt=0)
    price_step: Optional[float] = Field(default=None, gt=0)
    margin_floor: Optional[float] = Field(default=None, ge=0, lt=5)
    max_change_pct: Optional[float] = Field(default=None, gt=0, le=1)
    current_stock: Optional[int] = Field(default=None, ge=0)
    max_stock: Optional[int] = Field(default=None, gt=0)
    is_active: Optional[bool] = None


class ProductOut(_Out):
    id: int
    sku: str
    name: str
    category: str
    base_price: float
    cost: float
    price_min: float
    price_max: float
    price_step: float
    margin_floor: float
    max_change_pct: float
    current_stock: int
    max_stock: int
    current_price: Optional[float] = None
    is_active: bool
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None

    @field_serializer("created_at", "updated_at")
    def _ser(self, v):
        return iso_z(v)


class StockUpdate(BaseModel):
    new_stock: int = Field(ge=0)


# ------------------------------------------------------------------- signals
class SignalCreate(BaseModel):
    product_id: int
    page_views: int = Field(default=0, ge=0)
    add_to_carts: int = Field(default=0, ge=0)
    conversions: int = Field(default=0, ge=0)
    stock_level: Optional[int] = Field(default=None, ge=0)
    temperature: Optional[float] = None
    precipitation: Optional[float] = Field(default=None, ge=0, le=1)
    humidity: Optional[float] = Field(default=None, ge=0, le=100)
    weather_code: Optional[int] = None
    is_holiday: Optional[bool] = None
    event_score: Optional[float] = Field(default=None, ge=0, le=1)
    competitor_price: Optional[float] = Field(default=None, gt=0)

    @model_validator(mode="after")
    def _funnel(self):
        if self.add_to_carts > self.page_views and self.page_views > 0:
            raise ValueError("add_to_carts cannot exceed page_views")
        if self.conversions > self.add_to_carts and self.add_to_carts > 0:
            raise ValueError("conversions cannot exceed add_to_carts")
        return self


class SignalOut(_Out):
    id: int
    product_id: int
    timestamp: datetime
    page_views: int
    add_to_carts: int
    conversions: int
    stock_level: Optional[int] = None
    temperature: Optional[float] = None
    precipitation: Optional[float] = None
    humidity: Optional[float] = None
    is_holiday: Optional[bool] = None
    event_score: Optional[float] = None
    competitor_price: Optional[float] = None
    source: Optional[str] = None

    @field_serializer("timestamp")
    def _ser(self, v):
        return iso_z(v)


# --------------------------------------------------------------------- rules
class RuleCreate(BaseModel):
    scope: str
    scope_value: Optional[str] = None
    rule_type: str
    value: float = 0.0
    is_active: bool = True
    note: Optional[str] = Field(default=None, max_length=200)

    @model_validator(mode="after")
    def _check(self):
        if self.scope not in SCOPES:
            raise ValueError(f"scope must be one of {list(SCOPES)}")
        if self.rule_type not in RULE_TYPES:
            raise ValueError(f"rule_type must be one of {list(RULE_TYPES)}")
        if self.scope != "global" and not self.scope_value:
            raise ValueError("scope_value is required for category/product rules")
        if self.rule_type != "freeze" and self.value < 0:
            raise ValueError("value cannot be negative")
        if self.rule_type in {"margin_floor", "max_discount_pct", "max_markup_pct", "max_change_pct"} and self.value > 5:
            raise ValueError("percentage rules are fractions (0.10 = 10%)")
        return self


class RuleUpdate(BaseModel):
    value: Optional[float] = None
    is_active: Optional[bool] = None
    note: Optional[str] = None


class RuleOut(_Out):
    id: int
    scope: str
    scope_value: Optional[str] = None
    rule_type: str
    value: float
    is_active: bool
    note: Optional[str] = None
    created_at: Optional[datetime] = None

    @field_serializer("created_at")
    def _ser(self, v):
        return iso_z(v)


# ---------------------------------------------------------------- simulation
class SimulationRequest(BaseModel):
    product_id: int
    features: Dict[str, Any] = Field(default_factory=dict)
    manual_adjustments: Optional[Dict[str, float]] = None


# --------------------------------------------------------------------- model
class RetrainRequest(BaseModel):
    n_samples: Optional[int] = Field(default=None, ge=2000, le=100000)
    seed: int = 42


class ModelSelect(BaseModel):
    model_type: str


# ---------------------------------------------------------------------- auth
_USERNAME_RE = re.compile(r"^[A-Za-z0-9_.-]{3,40}$")


def _check_password(v: str) -> str:
    if len(v) < 8:
        raise ValueError("password must be at least 8 characters")
    if len(v) > 128:
        raise ValueError("password must be at most 128 characters")
    if v.strip() == "" or v.lower() in {"password", "12345678", "admin123", "password1"}:
        raise ValueError("that password is too easy to guess")
    return v


class UserCreate(BaseModel):
    username: str
    password: str
    role: str = "viewer"

    @field_validator("username")
    @classmethod
    def _u(cls, v):
        if not _USERNAME_RE.match(v):
            raise ValueError("username must be 3-40 characters: letters, digits, '.', '_' or '-'")
        return v

    @field_validator("password")
    @classmethod
    def _p(cls, v):
        return _check_password(v)

    @field_validator("role")
    @classmethod
    def _r(cls, v):
        if v not in ("admin", "viewer"):
            raise ValueError("role must be 'admin' or 'viewer'")
        return v


class UserUpdate(BaseModel):
    role: Optional[str] = None
    is_active: Optional[bool] = None
    password: Optional[str] = None

    @field_validator("role")
    @classmethod
    def _r(cls, v):
        if v is not None and v not in ("admin", "viewer"):
            raise ValueError("role must be 'admin' or 'viewer'")
        return v

    @field_validator("password")
    @classmethod
    def _p(cls, v):
        return _check_password(v) if v is not None else v


class ChangePassword(BaseModel):
    current_password: str
    new_password: str

    @field_validator("new_password")
    @classmethod
    def _p(cls, v):
        return _check_password(v)


class UserOut(_Out):
    id: int
    username: str
    role: str
    is_active: bool
    must_change_password: bool = False
    created_at: Optional[datetime] = None
    last_login: Optional[datetime] = None

    @field_serializer("created_at", "last_login")
    def _ser(self, v):
        return iso_z(v)
