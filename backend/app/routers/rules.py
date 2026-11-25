"""Guardrail administration: GET/POST/PUT/DELETE /rules."""
from __future__ import annotations

from typing import List

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from ..container import engine
from ..database import get_db
from ..models import PricingRule, Product
from ..schemas import RuleCreate, RuleOut, RuleUpdate
from ..security import require_admin
from ..services.guardrails import RULE_TYPES, SCOPES

router = APIRouter(prefix="/rules", tags=["Rules"])


@router.get("/types")
def rule_types():
    return {"scopes": list(SCOPES),
            "rule_types": [{"type": k, "description": d, "unit": u} for k, (d, u) in RULE_TYPES.items()]}


@router.get("", response_model=List[RuleOut])
def list_rules(db: Session = Depends(get_db)):
    return db.query(PricingRule).order_by(PricingRule.id).all()


@router.post("", response_model=RuleOut, status_code=201, dependencies=[Depends(require_admin)])
def create_rule(body: RuleCreate, db: Session = Depends(get_db)):
    if body.scope == "product" and not db.get(Product, int(body.scope_value) if body.scope_value.isdigit() else -1):
        raise HTTPException(404, f"Product '{body.scope_value}' not found")
    rule = PricingRule(**body.model_dump())
    db.add(rule)
    db.commit()
    engine.refresh_all(db)               # apply immediately
    return rule


@router.put("/{rule_id}", response_model=RuleOut, dependencies=[Depends(require_admin)])
def update_rule(rule_id: int, body: RuleUpdate, db: Session = Depends(get_db)):
    rule = db.get(PricingRule, rule_id)
    if not rule:
        raise HTTPException(404, "Rule not found")
    for k, v in body.model_dump(exclude_unset=True).items():
        setattr(rule, k, v)
    db.commit()
    engine.refresh_all(db)
    return rule


@router.delete("/{rule_id}", dependencies=[Depends(require_admin)])
def delete_rule(rule_id: int, db: Session = Depends(get_db)):
    rule = db.get(PricingRule, rule_id)
    if not rule:
        raise HTTPException(404, "Rule not found")
    db.delete(rule)
    db.commit()
    engine.refresh_all(db)
    return {"message": "Rule deleted", "id": rule_id}
