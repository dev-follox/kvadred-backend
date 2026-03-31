import mimetypes
import shutil
import os
from pathlib import Path
from typing import List

from fastapi import APIRouter, Depends, HTTPException, status, UploadFile, File
from fastapi.responses import FileResponse
from sqlalchemy.orm import Session

from .. import models, schemas, auth
from ..database import get_db

router = APIRouter(prefix="/products", tags=["products"])

UPLOAD_DIR = Path("uploads/products")
UPLOAD_DIR.mkdir(parents=True, exist_ok=True)


@router.get("/", response_model=List[schemas.Product])
def get_products(
    skip: int = 0,
    limit: int = 100,
    db: Session = Depends(get_db),
    current_company: models.Company = Depends(auth.get_current_company),
):
    return (
        db.query(models.Product)
        .filter(models.Product.company_id == current_company.id)
        .offset(skip)
        .limit(limit)
        .all()
    )


@router.get("/for-me", response_model=List[schemas.Product])
def get_products_for_blogger(
    db: Session = Depends(get_db),
    current_blogger: models.Blogger = Depends(auth.get_current_blogger),
):
    """Products accessible to the current blogger via their affiliate links."""
    links = (
        db.query(models.AffiliateLink)
        .filter(models.AffiliateLink.blogger_id == current_blogger.id)
        .all()
    )
    product_ids = [l.product_id for l in links]
    if not product_ids:
        return []
    return db.query(models.Product).filter(models.Product.id.in_(product_ids)).all()


@router.get("/for-me/detailed")
def get_products_for_blogger_detailed(
    db: Session = Depends(get_db),
    current_blogger: models.Blogger = Depends(auth.get_current_blogger),
):
    """Products for blogger with affiliate code and commission rate included."""
    results = (
        db.query(models.Product, models.AffiliateLink.code, models.AffiliateLink.click_count)
        .join(models.AffiliateLink, models.AffiliateLink.product_id == models.Product.id)
        .filter(models.AffiliateLink.blogger_id == current_blogger.id)
        .all()
    )
    return [
        {
            "id": p.id,
            "company_id": p.company_id,
            "name": p.name,
            "description": p.description,
            "price": p.price,
            "commission_rate": p.commission_rate,
            "image_url": p.image_url,
            "blogger_task_description": p.blogger_task_description,
            "affiliate_code": code,
            "click_count": click_count,
        }
        for (p, code, click_count) in results
    ]


@router.get("/images/{filename}")
async def get_product_image(filename: str):
    file_path = UPLOAD_DIR / filename
    if not file_path.exists():
        raise HTTPException(status_code=404, detail="Image not found")
    content_type, _ = mimetypes.guess_type(filename)
    return FileResponse(path=file_path, media_type=content_type or "application/octet-stream", filename=filename)


@router.post("/upload-image")
async def upload_product_image(
    image: UploadFile = File(...),
    current_company: models.Company = Depends(auth.get_current_company),
):
    if not image.content_type.startswith("image/"):
        raise HTTPException(status_code=400, detail="File must be an image")
    filename = f"{current_company.id}_{image.filename}"
    file_path = UPLOAD_DIR / filename
    try:
        with file_path.open("wb") as buffer:
            shutil.copyfileobj(image.file, buffer)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Could not upload image: {e}")
    return {"image_url": f"/products/images/{filename}"}


@router.get("/{product_id}", response_model=schemas.Product)
def get_product(
    product_id: int,
    blogger_id: int | None = None,
    db: Session = Depends(get_db),
):
    product = db.query(models.Product).filter(models.Product.id == product_id).first()
    if not product:
        raise HTTPException(status_code=404, detail="Product not found")
    if blogger_id:
        analytics = (
            db.query(models.Analytics)
            .filter(
                models.Analytics.product_id == product_id,
                models.Analytics.blogger_id == blogger_id,
            )
            .first()
        )
        if analytics:
            analytics.visit_count += 1
        else:
            analytics = models.Analytics(product_id=product_id, blogger_id=blogger_id, visit_count=1)
            db.add(analytics)
        db.commit()
    return product


@router.post("/", response_model=schemas.Product)
def create_product(
    product: schemas.ProductCreate,
    db: Session = Depends(get_db),
    current_company: models.Company = Depends(auth.get_current_company),
):
    if product.company_id != current_company.id:
        raise HTTPException(status_code=403, detail="Not authorized to create product for this company")
    db_product = models.Product(**product.model_dump())
    db.add(db_product)
    db.commit()
    db.refresh(db_product)
    return db_product


@router.put("/{product_id}", response_model=schemas.Product)
def update_product(
    product_id: int,
    product_update: schemas.ProductUpdate,
    db: Session = Depends(get_db),
    current_company: models.Company = Depends(auth.get_current_company),
):
    db_product = (
        db.query(models.Product)
        .filter(models.Product.id == product_id, models.Product.company_id == current_company.id)
        .first()
    )
    if not db_product:
        raise HTTPException(status_code=404, detail="Product not found")
    for field, value in product_update.model_dump(exclude_unset=True).items():
        setattr(db_product, field, value)
    db.commit()
    db.refresh(db_product)
    return db_product


@router.delete("/{product_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_product(
    product_id: int,
    db: Session = Depends(get_db),
    current_company: models.Company = Depends(auth.get_current_company),
):
    db_product = (
        db.query(models.Product)
        .filter(models.Product.id == product_id, models.Product.company_id == current_company.id)
        .first()
    )
    if not db_product:
        raise HTTPException(status_code=404, detail="Product not found")
    db.delete(db_product)
    db.commit()
    return None


@router.get("/{product_id}/orders", response_model=List[schemas.Order])
def get_product_orders(
    product_id: int,
    db: Session = Depends(get_db),
    current_company: models.Company = Depends(auth.get_current_company),
):
    product = (
        db.query(models.Product)
        .filter(models.Product.id == product_id, models.Product.company_id == current_company.id)
        .first()
    )
    if not product:
        raise HTTPException(status_code=404, detail="Product not found")
    return db.query(models.Order).filter(models.Order.product_id == product_id).all()


@router.get("/{product_id}/analytics", response_model=List[schemas.Analytics])
def get_product_analytics(
    product_id: int,
    db: Session = Depends(get_db),
    current_company: models.Company = Depends(auth.get_current_company),
):
    product = (
        db.query(models.Product)
        .filter(models.Product.id == product_id, models.Product.company_id == current_company.id)
        .first()
    )
    if not product:
        raise HTTPException(status_code=404, detail="Product not found")
    return (
        db.query(models.Analytics)
        .join(models.Blogger)
        .filter(models.Analytics.product_id == product_id)
        .all()
    )
