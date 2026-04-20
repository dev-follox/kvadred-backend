import secrets

from fastapi import HTTPException, status
from sqlalchemy.orm import Session

from .. import models
from .designer_company import ensure_designer_company
from .rollup import ensure_analytics_row_for_link
from .subscription import assert_company_catalog_readable_for_designer


def generate_unique_code(db: Session) -> str:
    while True:
        code = secrets.token_urlsafe(8)
        if not db.query(models.AffiliateLink).filter(models.AffiliateLink.code == code).first():
            return code


def get_or_create_affiliate_link(
    db: Session, designer: models.Designer, product_id: int
) -> models.AffiliateLink:
    existing = (
        db.query(models.AffiliateLink)
        .filter(
            models.AffiliateLink.designer_id == designer.id,
            models.AffiliateLink.product_id == product_id,
        )
        .first()
    )
    if existing:
        return existing

    product = db.query(models.Product).filter(models.Product.id == product_id).first()
    if not product:
        raise HTTPException(status_code=404, detail="Product not found")

    assert_company_catalog_readable_for_designer(db, product.company_id)
    ensure_designer_company(db, designer.id, product.company_id)

    link = models.AffiliateLink(
        code=generate_unique_code(db),
        product_id=product_id,
        designer_id=designer.id,
    )
    db.add(link)
    db.flush()
    ensure_analytics_row_for_link(db, link)
    return link
