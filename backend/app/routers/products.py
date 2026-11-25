"""Product management + stock updates."""
from __future__ import annotations

from typing import List

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from ..container import engine
from ..database import get_db
from ..models import Product
from ..schemas import ProductCreate, ProductOut, ProductUpdate, StockUpdate
from ..security import require_admin

router = APIRouter(tags=["Products"])


def get_product_or_404(db: Session, product_id: int) -> Product:
    product = db.get(Product, product_id)
    if not product:
        raise HTTPException(404, f"Product {product_id} not found")
    return product


@router.get("/products", response_model=List[ProductOut])
def list_products(include_inactive: bool = False, db: Session = Depends(get_db)):
    q = db.query(Product)
    if not include_inactive:
        q = q.filter(Product.is_active.is_(True))
    return q.order_by(Product.id).all()


@router.get("/products/{product_id}", response_model=ProductOut)
def get_product(product_id: int, db: Session = Depends(get_db)):
    return get_product_or_404(db, product_id)


@router.post("/products", response_model=ProductOut, status_code=201, dependencies=[Depends(require_admin)])
def create_product(body: ProductCreate, db: Session = Depends(get_db)):
    if db.query(Product).filter(Product.sku == body.sku).first():
        raise HTTPException(409, f"SKU '{body.sku}' already exists")
    product = Product(**body.model_dump())
    db.add(product)
    db.commit()
    engine.refresh_product(db, product)          # give it a first price straight away
    db.refresh(product)
    return product


@router.put("/products/{product_id}", response_model=ProductOut, dependencies=[Depends(require_admin)])
def update_product(product_id: int, body: ProductUpdate, db: Session = Depends(get_db)):
    product = get_product_or_404(db, product_id)
    changes = body.model_dump(exclude_unset=True)
    for key, value in changes.items():
        setattr(product, key, value)
    if (product.price_min or 0) > (product.price_max or 0):
        db.rollback()
        raise HTTPException(422, "price_min cannot exceed price_max")
    db.commit()
    if product.is_active:
        engine.refresh_product(db, product)
    db.refresh(product)
    return product


@router.delete("/products/{product_id}", dependencies=[Depends(require_admin)])
def deactivate_product(product_id: int, db: Session = Depends(get_db)):
    """Soft delete: history is kept, the product just stops being priced."""
    product = get_product_or_404(db, product_id)
    product.is_active = False
    db.commit()
    return {"message": f"Product {product_id} deactivated", "id": product_id}


@router.post("/products/{product_id}/update_stock", dependencies=[Depends(require_admin)])
def update_stock(product_id: int, body: StockUpdate, db: Session = Depends(get_db)):
    product = get_product_or_404(db, product_id)
    product.current_stock = body.new_stock
    if body.new_stock > (product.max_stock or 0):
        product.max_stock = body.new_stock
    db.commit()
    price = engine.refresh_product(db, product)  # stock is a pricing signal -> re-price now
    db.refresh(product)
    return {"product": ProductOut.model_validate(product).model_dump(mode="json"), "price": price}
