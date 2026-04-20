from typing import List

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from .. import models, schemas, auth
from ..database import get_db
from ..services import affiliate as affiliate_service
from ..services.designer_company import effective_designer_bonus_percent
from ..services.rollup import increment_visit_for_link
from ..services.subscription import company_subscription_active

router = APIRouter(prefix="/affiliate-links", tags=["affiliate-links"])


@router.post("/", response_model=schemas.AffiliateLink)
def create_affiliate_link(
    body: schemas.AffiliateLinkCreate,
    db: Session = Depends(get_db),
    current_designer: models.Designer = Depends(auth.get_current_designer),
):
    link = affiliate_service.get_or_create_affiliate_link(db, current_designer, body.product_id)
    db.commit()
    db.refresh(link)
    return link


@router.get("/my-links", response_model=List[schemas.AffiliateLinkWithRollup])
def get_my_links(
    current_designer: models.Designer = Depends(auth.get_current_designer),
    db: Session = Depends(get_db),
):
    links = (
        db.query(models.AffiliateLink)
        .filter(models.AffiliateLink.designer_id == current_designer.id)
        .all()
    )
    out: List[schemas.AffiliateLinkWithRollup] = []
    for link in links:
        product = link.product
        designer = link.designer
        rollup = (
            db.query(models.Analytics)
            .filter(models.Analytics.affiliate_link_id == link.id)
            .first()
        )
        bonus = effective_designer_bonus_percent(db, current_designer.id, product.company_id)
        out.append(
            schemas.AffiliateLinkWithRollup(
                id=link.id,
                code=link.code,
                product_id=link.product_id,
                designer_id=link.designer_id,
                click_count=link.click_count or 0,
                created_at=link.created_at,
                updated_at=link.updated_at,
                product=schemas.Product.model_validate(product),
                designer=schemas.Designer.model_validate(designer),
                visit_count=rollup.visit_count if rollup else 0,
                order_count=rollup.order_count if rollup else 0,
                items_sold=rollup.items_sold if rollup else 0,
                revenue=rollup.revenue if rollup else 0.0,
                designer_bonus_paid=rollup.designer_bonus_paid if rollup else 0.0,
                platform_fee_paid=rollup.platform_fee_paid if rollup else 0.0,
                effective_bonus_percent=bonus,
            )
        )
    return out


@router.get("/{code}", response_model=schemas.AffiliateLinkDetail)
def get_affiliate_link(code: str, db: Session = Depends(get_db)):
    link = db.query(models.AffiliateLink).filter(models.AffiliateLink.code == code).first()
    if not link:
        raise HTTPException(status_code=404, detail="Affiliate link not found")
    product = link.product
    company = product.company
    if not company_subscription_active(company):
        raise HTTPException(status_code=403, detail="Affiliate link is not active")
    increment_visit_for_link(db, link)
    db.commit()
    db.refresh(link)
    return link


@router.delete("/{link_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_my_affiliate_link(
    link_id: int,
    db: Session = Depends(get_db),
    current_designer: models.Designer = Depends(auth.get_current_designer),
):
    link = (
        db.query(models.AffiliateLink)
        .filter(
            models.AffiliateLink.id == link_id,
            models.AffiliateLink.designer_id == current_designer.id,
        )
        .first()
    )
    if not link:
        raise HTTPException(status_code=404, detail="Affiliate link not found")
    db.query(models.Order).filter(models.Order.affiliate_link_id == link.id).update(
        {"affiliate_link_id": None}, synchronize_session=False
    )
    db.query(models.Analytics).filter(models.Analytics.affiliate_link_id == link.id).delete(
        synchronize_session=False
    )
    db.delete(link)
    db.commit()
    return None
