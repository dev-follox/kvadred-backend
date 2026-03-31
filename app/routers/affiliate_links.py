import secrets
from typing import List

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from .. import models, schemas, auth
from ..database import get_db

router = APIRouter(prefix="/affiliate-links", tags=["affiliate-links"])


def generate_unique_code(db: Session) -> str:
    while True:
        code = secrets.token_urlsafe(8)
        if not db.query(models.AffiliateLink).filter(models.AffiliateLink.code == code).first():
            return code


@router.post("/", response_model=schemas.AffiliateLink)
def create_affiliate_link(
    link: schemas.AffiliateLinkCreate,
    db: Session = Depends(get_db),
    current_company: models.Company = Depends(auth.get_current_company),
):
    product = (
        db.query(models.Product)
        .filter(
            models.Product.id == link.product_id,
            models.Product.company_id == current_company.id,
        )
        .first()
    )
    if not product:
        raise HTTPException(status_code=404, detail="Product not found or does not belong to your company")

    blogger = db.query(models.Blogger).filter(models.Blogger.id == link.blogger_id).first()
    if not blogger:
        raise HTTPException(status_code=404, detail="Blogger not found")

    existing = (
        db.query(models.AffiliateLink)
        .filter(
            models.AffiliateLink.product_id == link.product_id,
            models.AffiliateLink.blogger_id == link.blogger_id,
        )
        .first()
    )
    if existing:
        return existing

    # Ensure blogger ↔ company association exists
    bc_exists = (
        db.query(models.BloggerCompany)
        .filter(
            models.BloggerCompany.blogger_id == link.blogger_id,
            models.BloggerCompany.company_id == current_company.id,
        )
        .first()
    )
    if not bc_exists:
        db.add(models.BloggerCompany(blogger_id=link.blogger_id, company_id=current_company.id))

    db_link = models.AffiliateLink(
        code=generate_unique_code(db),
        product_id=link.product_id,
        blogger_id=link.blogger_id,
    )
    db.add(db_link)
    db.commit()
    db.refresh(db_link)
    return db_link


@router.get("/my-links", response_model=List[schemas.AffiliateLinkDetail])
def get_my_links(
    current_blogger: models.Blogger = Depends(auth.get_current_blogger),
    db: Session = Depends(get_db),
):
    """Return all affiliate links for the authenticated blogger."""
    return (
        db.query(models.AffiliateLink)
        .filter(models.AffiliateLink.blogger_id == current_blogger.id)
        .all()
    )


@router.get("/{code}", response_model=schemas.AffiliateLinkDetail)
def get_affiliate_link(code: str, db: Session = Depends(get_db)):
    """Resolve an affiliate code — also increments click counter."""
    link = db.query(models.AffiliateLink).filter(models.AffiliateLink.code == code).first()
    if not link:
        raise HTTPException(status_code=404, detail="Affiliate link not found")

    link.click_count += 1

    analytics = (
        db.query(models.Analytics)
        .filter(
            models.Analytics.product_id == link.product_id,
            models.Analytics.blogger_id == link.blogger_id,
        )
        .first()
    )
    if analytics:
        analytics.visit_count += 1
    else:
        db.add(
            models.Analytics(
                product_id=link.product_id,
                blogger_id=link.blogger_id,
                visit_count=1,
            )
        )
    db.commit()
    db.refresh(link)
    return link


@router.delete("/{link_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_affiliate_link(
    link_id: int,
    db: Session = Depends(get_db),
    current_company: models.Company = Depends(auth.get_current_company),
):
    link = (
        db.query(models.AffiliateLink)
        .join(models.Product)
        .filter(
            models.AffiliateLink.id == link_id,
            models.Product.company_id == current_company.id,
        )
        .first()
    )
    if not link:
        raise HTTPException(status_code=404, detail="Affiliate link not found")
    db.delete(link)
    db.commit()
    return None
