from collections import defaultdict
from datetime import datetime
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from .. import models, schemas, auth
from ..database import get_db
from ..services.rollup import increment_visit_for_link
from ..services.subscription import company_subscription_active

router = APIRouter(prefix="/analytics", tags=["analytics"])


def _processed_orders_for_company(
    db: Session,
    company_id: int,
    datetime_from: Optional[datetime],
    datetime_to: Optional[datetime],
):
    q = (
        db.query(models.Order)
        .join(models.Product)
        .filter(
            models.Product.company_id == company_id,
            models.Order.status == models.OrderStatus.PROCESSED,
        )
    )
    if datetime_from is not None:
        q = q.filter(models.Order.created_at >= datetime_from)
    if datetime_to is not None:
        q = q.filter(models.Order.created_at <= datetime_to)
    return q.all()


@router.post("/visit")
def record_visit(body: schemas.AffiliateVisitRequest, db: Session = Depends(get_db)):
    link = db.query(models.AffiliateLink).filter(models.AffiliateLink.code == body.code).first()
    if not link:
        raise HTTPException(status_code=404, detail="Affiliate link not found")
    company = link.product.company
    if not company_subscription_active(company):
        raise HTTPException(status_code=403, detail="Affiliate link is not active")
    increment_visit_for_link(db, link)
    db.commit()
    return {"status": "success"}


@router.get("/dashboard", response_model=schemas.AnalyticsDashboard)
def get_dashboard(
    db: Session = Depends(get_db),
    current_company: models.Company = Depends(auth.get_current_company),
):
    rows = (
        db.query(models.Analytics)
        .filter(models.Analytics.company_id == current_company.id)
        .all()
    )
    if not rows:
        return schemas.AnalyticsDashboard(
            total_visits=0,
            total_orders=0,
            total_items_sold=0,
            total_revenue=0.0,
            total_designer_bonus=0.0,
            total_platform_fee=0.0,
            designer_rankings=[],
            per_link=[],
        )

    total_visits = sum(r.visit_count or 0 for r in rows)
    total_orders = sum(r.order_count or 0 for r in rows)
    total_items_sold = sum(r.items_sold or 0 for r in rows)
    total_revenue = sum(float(r.revenue or 0) for r in rows)
    total_designer_bonus = sum(float(r.designer_bonus_paid or 0) for r in rows)
    total_platform_fee = sum(float(r.platform_fee_paid or 0) for r in rows)

    designer_map: dict = {}
    for row in rows:
        did = row.designer_id
        if did not in designer_map:
            designer_map[did] = {
                "total_visits": 0,
                "total_orders": 0,
                "total_items_sold": 0,
                "total_revenue": 0.0,
                "total_designer_bonus": 0.0,
                "total_platform_fee": 0.0,
            }
        designer_map[did]["total_visits"] += row.visit_count or 0
        designer_map[did]["total_orders"] += row.order_count or 0
        designer_map[did]["total_items_sold"] += row.items_sold or 0
        designer_map[did]["total_revenue"] += float(row.revenue or 0)
        designer_map[did]["total_designer_bonus"] += float(row.designer_bonus_paid or 0)
        designer_map[did]["total_platform_fee"] += float(row.platform_fee_paid or 0)

    designers = (
        db.query(models.Designer)
        .filter(models.Designer.id.in_(list(designer_map.keys())))
        .all()
    )
    designer_lookup = {d.id: d for d in designers}

    rankings = []
    for did, stats in designer_map.items():
        designer = designer_lookup.get(did)
        if not designer:
            continue
        visits = stats["total_visits"]
        orders = stats["total_orders"]
        conversion_rate = round(orders / visits * 100, 2) if visits > 0 else 0.0
        rankings.append(
            schemas.DesignerRanking(
                designer=schemas.Designer.model_validate(designer),
                total_visits=visits,
                total_orders=orders,
                total_items_sold=stats["total_items_sold"],
                total_revenue=stats["total_revenue"],
                total_designer_bonus=stats["total_designer_bonus"],
                total_platform_fee=stats["total_platform_fee"],
                conversion_rate=conversion_rate,
            )
        )

    rankings.sort(key=lambda x: x.total_revenue, reverse=True)

    per_link = [schemas.Analytics.model_validate(r) for r in rows]

    return schemas.AnalyticsDashboard(
        total_visits=total_visits,
        total_orders=total_orders,
        total_items_sold=total_items_sold,
        total_revenue=total_revenue,
        total_designer_bonus=total_designer_bonus,
        total_platform_fee=total_platform_fee,
        designer_rankings=rankings,
        per_link=per_link,
    )


@router.get("/leaderboard", response_model=List[schemas.DesignerRanking])
def get_leaderboard(
    db: Session = Depends(get_db),
    current_company: models.Company = Depends(auth.get_current_company),
):
    dashboard = get_dashboard(db=db, current_company=current_company)
    return dashboard.designer_rankings


@router.get("/designer/{designer_id}", response_model=List[schemas.Analytics])
def get_designer_analytics(
    designer_id: int,
    db: Session = Depends(get_db),
    current_company: models.Company = Depends(auth.get_current_company),
):
    return (
        db.query(models.Analytics)
        .filter(
            models.Analytics.designer_id == designer_id,
            models.Analytics.company_id == current_company.id,
        )
        .all()
    )


@router.get("/my-stats", response_model=List[schemas.Analytics])
def get_my_stats(
    current_designer: models.Designer = Depends(auth.get_current_designer),
    db: Session = Depends(get_db),
):
    return (
        db.query(models.Analytics)
        .filter(models.Analytics.designer_id == current_designer.id)
        .all()
    )


@router.get("/company/products", response_model=List[schemas.CompanyProductAnalyticsRow])
def company_product_order_analytics(
    sort: str = Query("revenue", pattern="^(revenue|designer_bonus|platform_fee)$"),
    datetime_from: Optional[datetime] = Query(None, alias="from"),
    datetime_to: Optional[datetime] = Query(None, alias="to"),
    db: Session = Depends(get_db),
    current_company: models.Company = Depends(auth.get_current_company),
):
    orders = _processed_orders_for_company(db, current_company.id, datetime_from, datetime_to)
    by_product: dict = defaultdict(lambda: {"items": 0, "revenue": 0.0, "designer_bonus": 0.0, "platform_fee": 0.0, "name": ""})
    for o in orders:
        p = o.product
        by_product[o.product_id]["name"] = p.name
        by_product[o.product_id]["items"] += o.quantity or 0
        by_product[o.product_id]["revenue"] += float(o.line_revenue or 0)
        by_product[o.product_id]["designer_bonus"] += float(o.designer_bonus_amount or 0)
        by_product[o.product_id]["platform_fee"] += float(o.platform_fee_amount or 0)

    rows = [
        schemas.CompanyProductAnalyticsRow(
            product_id=pid,
            product_name=data["name"],
            items_sold=data["items"],
            revenue=round(data["revenue"], 2),
            designer_bonus=round(data["designer_bonus"], 2),
            platform_fee=round(data["platform_fee"], 2),
        )
        for pid, data in by_product.items()
    ]
    sort_key = {
        "revenue": lambda r: r.revenue,
        "designer_bonus": lambda r: r.designer_bonus,
        "platform_fee": lambda r: r.platform_fee,
    }[sort]
    rows.sort(key=sort_key, reverse=True)
    return rows


@router.get(
    "/company/products/{product_id}/designers",
    response_model=List[schemas.CompanyProductDesignerBreakdownRow],
)
def company_product_designer_breakdown(
    product_id: int,
    sort: str = Query("revenue", pattern="^(revenue|designer_bonus|platform_fee)$"),
    datetime_from: Optional[datetime] = Query(None, alias="from"),
    datetime_to: Optional[datetime] = Query(None, alias="to"),
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

    orders = _processed_orders_for_company(db, current_company.id, datetime_from, datetime_to)
    orders = [o for o in orders if o.product_id == product_id]
    by_designer: dict = defaultdict(lambda: {"items": 0, "revenue": 0.0, "designer_bonus": 0.0, "platform_fee": 0.0})
    for o in orders:
        by_designer[o.designer_id]["items"] += o.quantity or 0
        by_designer[o.designer_id]["revenue"] += float(o.line_revenue or 0)
        by_designer[o.designer_id]["designer_bonus"] += float(o.designer_bonus_amount or 0)
        by_designer[o.designer_id]["platform_fee"] += float(o.platform_fee_amount or 0)

    designers = (
        db.query(models.Designer).filter(models.Designer.id.in_(list(by_designer.keys()) or [0])).all()
    )
    dmap = {d.id: d for d in designers}

    rows = []
    for did, data in by_designer.items():
        d = dmap.get(did)
        if not d:
            continue
        rows.append(
            schemas.CompanyProductDesignerBreakdownRow(
                designer_id=did,
                designer_name=d.name,
                designer_email=d.email,
                items_sold=data["items"],
                revenue=round(data["revenue"], 2),
                designer_bonus=round(data["designer_bonus"], 2),
                platform_fee=round(data["platform_fee"], 2),
            )
        )
    sort_key = {
        "revenue": lambda r: r.revenue,
        "designer_bonus": lambda r: r.designer_bonus,
        "platform_fee": lambda r: r.platform_fee,
    }[sort]
    rows.sort(key=sort_key, reverse=True)
    return rows


@router.get("/company/designers", response_model=List[schemas.CompanyDesignerAnalyticsRow])
def company_designer_analytics(
    sort: str = Query("revenue", pattern="^(revenue|designer_bonus|platform_fee)$"),
    datetime_from: Optional[datetime] = Query(None, alias="from"),
    datetime_to: Optional[datetime] = Query(None, alias="to"),
    db: Session = Depends(get_db),
    current_company: models.Company = Depends(auth.get_current_company),
):
    orders = _processed_orders_for_company(db, current_company.id, datetime_from, datetime_to)
    by_designer: dict = defaultdict(lambda: {"items": 0, "revenue": 0.0, "designer_bonus": 0.0, "platform_fee": 0.0})
    for o in orders:
        by_designer[o.designer_id]["items"] += o.quantity or 0
        by_designer[o.designer_id]["revenue"] += float(o.line_revenue or 0)
        by_designer[o.designer_id]["designer_bonus"] += float(o.designer_bonus_amount or 0)
        by_designer[o.designer_id]["platform_fee"] += float(o.platform_fee_amount or 0)

    designers = (
        db.query(models.Designer).filter(models.Designer.id.in_(list(by_designer.keys()) or [0])).all()
    )
    dmap = {d.id: d for d in designers}

    rows = []
    for did, data in by_designer.items():
        d = dmap.get(did)
        if not d:
            continue
        rows.append(
            schemas.CompanyDesignerAnalyticsRow(
                designer_id=did,
                designer_name=d.name,
                designer_email=d.email,
                items_sold=data["items"],
                revenue=round(data["revenue"], 2),
                designer_bonus=round(data["designer_bonus"], 2),
                platform_fee=round(data["platform_fee"], 2),
            )
        )
    sort_key = {
        "revenue": lambda r: r.revenue,
        "designer_bonus": lambda r: r.designer_bonus,
        "platform_fee": lambda r: r.platform_fee,
    }[sort]
    rows.sort(key=sort_key, reverse=True)
    return rows


@router.get(
    "/company/designers/{designer_id}/products",
    response_model=List[schemas.CompanyDesignerProductBreakdownRow],
)
def company_designer_product_breakdown(
    designer_id: int,
    sort: str = Query("revenue", pattern="^(revenue|designer_bonus|platform_fee)$"),
    datetime_from: Optional[datetime] = Query(None, alias="from"),
    datetime_to: Optional[datetime] = Query(None, alias="to"),
    db: Session = Depends(get_db),
    current_company: models.Company = Depends(auth.get_current_company),
):
    orders = _processed_orders_for_company(db, current_company.id, datetime_from, datetime_to)
    orders = [o for o in orders if o.designer_id == designer_id]
    by_product: dict = defaultdict(lambda: {"items": 0, "revenue": 0.0, "designer_bonus": 0.0, "platform_fee": 0.0, "name": ""})
    for o in orders:
        p = o.product
        by_product[o.product_id]["name"] = p.name
        by_product[o.product_id]["items"] += o.quantity or 0
        by_product[o.product_id]["revenue"] += float(o.line_revenue or 0)
        by_product[o.product_id]["designer_bonus"] += float(o.designer_bonus_amount or 0)
        by_product[o.product_id]["platform_fee"] += float(o.platform_fee_amount or 0)

    rows = [
        schemas.CompanyDesignerProductBreakdownRow(
            product_id=pid,
            product_name=data["name"],
            items_sold=data["items"],
            revenue=round(data["revenue"], 2),
            designer_bonus=round(data["designer_bonus"], 2),
            platform_fee=round(data["platform_fee"], 2),
        )
        for pid, data in by_product.items()
    ]
    sort_key = {
        "revenue": lambda r: r.revenue,
        "designer_bonus": lambda r: r.designer_bonus,
        "platform_fee": lambda r: r.platform_fee,
    }[sort]
    rows.sort(key=sort_key, reverse=True)
    return rows
