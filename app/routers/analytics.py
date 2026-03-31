from typing import List

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import func
from sqlalchemy.orm import Session

from .. import models, schemas, auth
from ..database import get_db

router = APIRouter(prefix="/analytics", tags=["analytics"])


@router.post("/visit")
def record_visit(
    product_id: int,
    blogger_id: int,
    db: Session = Depends(get_db),
):
    """Increment visit counter for a product/blogger pair."""
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
    return {"status": "success"}


@router.get("/dashboard", response_model=schemas.AnalyticsDashboard)
def get_dashboard(
    db: Session = Depends(get_db),
    current_company: models.Company = Depends(auth.get_current_company),
):
    """Full analytics dashboard for the current company."""
    product_ids = [
        p.id
        for p in db.query(models.Product)
        .filter(models.Product.company_id == current_company.id)
        .all()
    ]
    if not product_ids:
        return schemas.AnalyticsDashboard(
            total_visits=0,
            total_orders=0,
            total_items_sold=0,
            total_revenue=0.0,
            total_commission_paid=0.0,
            blogger_rankings=[],
            per_product=[],
        )

    rows = (
        db.query(models.Analytics)
        .filter(models.Analytics.product_id.in_(product_ids))
        .all()
    )

    total_visits = sum(r.visit_count for r in rows)
    total_orders = sum(r.order_count for r in rows)
    total_items_sold = sum(r.items_sold for r in rows)
    total_revenue = sum(r.revenue for r in rows)
    total_commission_paid = sum(r.commission_paid for r in rows)

    # Aggregate per blogger
    blogger_map: dict = {}
    for row in rows:
        bid = row.blogger_id
        if bid not in blogger_map:
            blogger_map[bid] = {
                "total_visits": 0,
                "total_orders": 0,
                "total_items_sold": 0,
                "total_revenue": 0.0,
                "total_commission": 0.0,
            }
        blogger_map[bid]["total_visits"] += row.visit_count
        blogger_map[bid]["total_orders"] += row.order_count
        blogger_map[bid]["total_items_sold"] += row.items_sold
        blogger_map[bid]["total_revenue"] += row.revenue
        blogger_map[bid]["total_commission"] += row.commission_paid

    bloggers = (
        db.query(models.Blogger)
        .filter(models.Blogger.id.in_(list(blogger_map.keys())))
        .all()
    )
    blogger_lookup = {b.id: b for b in bloggers}

    rankings = []
    for bid, stats in blogger_map.items():
        blogger = blogger_lookup.get(bid)
        if not blogger:
            continue
        visits = stats["total_visits"]
        orders = stats["total_orders"]
        conversion_rate = round(orders / visits * 100, 2) if visits > 0 else 0.0
        rankings.append(
            schemas.BloggerRanking(
                blogger=blogger,
                total_visits=visits,
                total_orders=orders,
                total_items_sold=stats["total_items_sold"],
                total_revenue=stats["total_revenue"],
                total_commission=stats["total_commission"],
                conversion_rate=conversion_rate,
            )
        )

    rankings.sort(key=lambda x: x.total_revenue, reverse=True)

    return schemas.AnalyticsDashboard(
        total_visits=total_visits,
        total_orders=total_orders,
        total_items_sold=total_items_sold,
        total_revenue=total_revenue,
        total_commission_paid=total_commission_paid,
        blogger_rankings=rankings,
        per_product=rows,
    )


@router.get("/leaderboard", response_model=List[schemas.BloggerRanking])
def get_leaderboard(
    db: Session = Depends(get_db),
    current_company: models.Company = Depends(auth.get_current_company),
):
    """Blogger rankings sorted by revenue for the current company."""
    dashboard = get_dashboard(db=db, current_company=current_company)
    return dashboard.blogger_rankings


@router.get("/blogger/{blogger_id}", response_model=List[schemas.Analytics])
def get_blogger_analytics(
    blogger_id: int,
    db: Session = Depends(get_db),
    current_company: models.Company = Depends(auth.get_current_company),
):
    """Per-product analytics for a specific blogger (company-scoped)."""
    product_ids = [
        p.id
        for p in db.query(models.Product)
        .filter(models.Product.company_id == current_company.id)
        .all()
    ]
    return (
        db.query(models.Analytics)
        .filter(
            models.Analytics.blogger_id == blogger_id,
            models.Analytics.product_id.in_(product_ids),
        )
        .all()
    )


@router.get("/my-stats", response_model=List[schemas.Analytics])
def get_my_stats(
    current_blogger: models.Blogger = Depends(auth.get_current_blogger),
    db: Session = Depends(get_db),
):
    """Blogger's own stats across all products."""
    return (
        db.query(models.Analytics)
        .filter(models.Analytics.blogger_id == current_blogger.id)
        .all()
    )
