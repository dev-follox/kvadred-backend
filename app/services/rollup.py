from sqlalchemy.orm import Session

from .. import models


def ensure_analytics_row_for_link(db: Session, link: models.AffiliateLink) -> models.Analytics:
    row = (
        db.query(models.Analytics)
        .filter(models.Analytics.affiliate_link_id == link.id)
        .first()
    )
    if row:
        return row
    product = db.query(models.Product).filter(models.Product.id == link.product_id).first()
    if not product:
        raise ValueError("Product missing for affiliate link")
    row = models.Analytics(
        affiliate_link_id=link.id,
        product_id=link.product_id,
        company_id=product.company_id,
        designer_id=link.designer_id,
    )
    db.add(row)
    db.flush()
    return row


def increment_visit_for_link(db: Session, link: models.AffiliateLink) -> None:
    link.click_count = (link.click_count or 0) + 1
    analytics = ensure_analytics_row_for_link(db, link)
    analytics.visit_count = (analytics.visit_count or 0) + 1


def apply_processed_order_to_rollup(db: Session, order: models.Order) -> None:
    if not order.affiliate_link_id:
        return
    link = db.query(models.AffiliateLink).filter(models.AffiliateLink.id == order.affiliate_link_id).first()
    if not link:
        return
    analytics = ensure_analytics_row_for_link(db, link)
    analytics.order_count = (analytics.order_count or 0) + 1
    analytics.items_sold = (analytics.items_sold or 0) + (order.quantity or 0)
    line = round((order.quantity or 0) * float(order.price_per_item or 0), 2)
    analytics.revenue = round(float(analytics.revenue or 0) + line, 2)
    analytics.designer_bonus_paid = round(
        float(analytics.designer_bonus_paid or 0) + float(order.designer_bonus_amount or 0), 2
    )
    analytics.platform_fee_paid = round(
        float(analytics.platform_fee_paid or 0) + float(order.platform_fee_amount or 0), 2
    )
