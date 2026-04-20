from typing import List

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import and_
from sqlalchemy.orm import Session

from .. import models, schemas, auth
from ..database import get_db
from ..services import affiliate as affiliate_service
from ..services.commission import compute_sale_amounts
from ..services.designer_company import ensure_designer_company, effective_designer_bonus_percent
from ..services.rollup import apply_processed_order_to_rollup
from ..services.subscription import assert_company_can_write, company_subscription_active
from ..services.telegram_webhook import telegram_service

router = APIRouter(prefix="/orders", tags=["orders"])


@router.post("/", response_model=schemas.Order)
async def create_order(order: schemas.OrderCreate, db: Session = Depends(get_db)):
    product = db.query(models.Product).filter(models.Product.id == order.product_id).first()
    if not product:
        raise HTTPException(status_code=404, detail="Product not found")

    company = product.company
    if not company_subscription_active(company):
        raise HTTPException(status_code=403, detail="Orders are not accepted for this company")

    designer = db.query(models.Designer).filter(models.Designer.id == order.designer_id).first()
    if not designer:
        raise HTTPException(status_code=404, detail="Designer not found")

    ensure_designer_company(db, order.designer_id, product.company_id)

    affiliate_link_id = order.affiliate_link_id
    if affiliate_link_id:
        link = db.query(models.AffiliateLink).filter(models.AffiliateLink.id == affiliate_link_id).first()
        if not link or link.product_id != order.product_id or link.designer_id != order.designer_id:
            raise HTTPException(status_code=400, detail="Invalid affiliate link for this product and designer")
    else:
        link = affiliate_service.get_or_create_affiliate_link(db, designer, order.product_id)
        affiliate_link_id = link.id

    bonus_pct = effective_designer_bonus_percent(db, order.designer_id, product.company_id)
    line, designer_bonus, platform_fee = compute_sale_amounts(
        order.quantity, order.price_per_item, bonus_pct
    )

    db_order = models.Order(
        product_id=order.product_id,
        designer_id=order.designer_id,
        affiliate_link_id=affiliate_link_id,
        quantity=order.quantity,
        price_per_item=order.price_per_item,
        line_revenue=line,
        designer_bonus_amount=designer_bonus,
        platform_fee_amount=platform_fee,
        client_phone=order.client_phone,
        client_name=order.client_name,
        note=order.note,
        is_manual=order.is_manual,
    )
    db.add(db_order)
    db.commit()
    db.refresh(db_order)

    if product.company and product.company.telegram_chat_id:
        message = (
            f"🛍️ *New order received!*\n\n"
            f"📦 *Order ID:* `#{db_order.id}`\n"
            f"👤 *Designer:* {designer.name}\n"
            f"🏪 *Product:* {product.name}\n"
            f"📊 *Quantity:* {order.quantity}\n"
            f"💰 *Price per item:* ₸{order.price_per_item:.2f}\n"
            f"💵 *Line revenue:* ₸{line:.2f}\n"
            f"🎁 *Designer bonus:* ₸{designer_bonus:.2f}\n"
            f"🏦 *Platform fee:* ₸{platform_fee:.2f}\n"
            f"📞 *Client phone:* `{order.client_phone}`\n"
            + (f"👤 *Client name:* {order.client_name}\n" if order.client_name else "")
            + (f"📝 *Note:* {order.note}\n" if order.note else "")
            + f"{'🖊️ Manual entry' if order.is_manual else '🔗 Via affiliate link'}"
        )
        try:
            await telegram_service.send_message(product.company.telegram_chat_id, message)
        except Exception:
            pass

    return db_order


@router.get("/", response_model=List[schemas.Order])
def get_orders(
    skip: int = 0,
    limit: int = 100,
    db: Session = Depends(get_db),
    current_company: models.Company = Depends(auth.get_current_company),
):
    product_ids = [
        p.id
        for p in db.query(models.Product)
        .filter(models.Product.company_id == current_company.id)
        .all()
    ]
    if not product_ids:
        return []
    return (
        db.query(models.Order)
        .filter(models.Order.product_id.in_(product_ids))
        .offset(skip)
        .limit(limit)
        .all()
    )


@router.get("/my-orders", response_model=List[schemas.OrderWithDetails])
def get_designer_orders(
    skip: int = 0,
    limit: int = 100,
    db: Session = Depends(get_db),
    current_designer: models.Designer = Depends(auth.get_current_designer),
):
    return (
        db.query(models.Order)
        .filter(models.Order.designer_id == current_designer.id)
        .offset(skip)
        .limit(limit)
        .all()
    )


@router.get("/{order_id}", response_model=schemas.OrderWithDetails)
def get_order(
    order_id: int,
    db: Session = Depends(get_db),
    current_company: models.Company = Depends(auth.get_current_company),
):
    order = (
        db.query(models.Order)
        .join(models.Product)
        .filter(
            models.Order.id == order_id,
            models.Product.company_id == current_company.id,
        )
        .first()
    )
    if not order:
        raise HTTPException(status_code=404, detail="Order not found")
    return order


@router.put("/{order_id}/status")
async def update_order_status(
    order_id: int,
    new_status: models.OrderStatus,
    db: Session = Depends(get_db),
    current_company: models.Company = Depends(auth.get_current_company),
):
    assert_company_can_write(current_company)
    order = (
        db.query(models.Order)
        .join(models.Product)
        .filter(
            and_(
                models.Order.id == order_id,
                models.Product.company_id == current_company.id,
            )
        )
        .first()
    )
    if not order:
        raise HTTPException(status_code=404, detail="Order not found")

    old_status = order.status
    order.status = new_status

    if new_status == models.OrderStatus.PROCESSED and old_status != models.OrderStatus.PROCESSED:
        apply_processed_order_to_rollup(db, order)

    db.commit()

    if current_company.telegram_chat_id:
        product = db.query(models.Product).filter(models.Product.id == order.product_id).first()
        if product:
            msg = (
                f"🔄 *Order status updated!*\n\n"
                f"📦 *Order ID:* `#{order.id}`\n"
                f"🏪 *Product:* {product.name}\n"
                f"📞 *Client phone:* `{order.client_phone}`\n"
                f"🔄 *Status:* {old_status.value} → {new_status.value}\n"
                f"📊 *Quantity:* {order.quantity}\n"
                f"💰 *Line revenue:* ₸{order.line_revenue:.2f}\n"
                f"🎁 *Designer bonus:* ₸{order.designer_bonus_amount:.2f}\n"
            )
            try:
                await telegram_service.send_message(current_company.telegram_chat_id, msg)
            except Exception:
                pass

    return {"status": "success", "order_id": order_id, "new_status": new_status}


@router.put("/{order_id}", response_model=schemas.Order)
def update_order(
    order_id: int,
    order_update: schemas.OrderUpdate,
    db: Session = Depends(get_db),
    current_company: models.Company = Depends(auth.get_current_company),
):
    assert_company_can_write(current_company)
    order = (
        db.query(models.Order)
        .join(models.Product)
        .filter(
            models.Order.id == order_id,
            models.Product.company_id == current_company.id,
        )
        .first()
    )
    if not order:
        raise HTTPException(status_code=404, detail="Order not found")
    for field, value in order_update.model_dump(exclude_unset=True).items():
        setattr(order, field, value)
    db.commit()
    db.refresh(order)
    return order
