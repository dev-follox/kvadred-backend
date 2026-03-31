from typing import List

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import and_
from sqlalchemy.orm import Session

from .. import models, schemas, auth
from ..database import get_db
from ..services.telegram_webhook import telegram_service

router = APIRouter(prefix="/orders", tags=["orders"])


def _calculate_commission(quantity: int, price_per_item: float, commission_rate: float) -> float:
    return round(quantity * price_per_item * commission_rate / 100, 2)


@router.post("/", response_model=schemas.Order)
async def create_order(order: schemas.OrderCreate, db: Session = Depends(get_db)):
    product = db.query(models.Product).filter(models.Product.id == order.product_id).first()
    if not product:
        raise HTTPException(status_code=404, detail="Product not found")

    blogger = db.query(models.Blogger).filter(models.Blogger.id == order.blogger_id).first()
    if not blogger:
        raise HTTPException(status_code=404, detail="Blogger not found")

    commission_amount = _calculate_commission(
        order.quantity, order.price_per_item, product.commission_rate
    )

    db_order = models.Order(
        product_id=order.product_id,
        blogger_id=order.blogger_id,
        affiliate_link_id=order.affiliate_link_id,
        quantity=order.quantity,
        price_per_item=order.price_per_item,
        commission_amount=commission_amount,
        client_phone=order.client_phone,
        client_name=order.client_name,
        note=order.note,
        is_manual=order.is_manual,
    )
    db.add(db_order)
    db.commit()
    db.refresh(db_order)

    # Telegram notification to company
    if product.company and product.company.telegram_chat_id:
        message = (
            f"🛍️ *New order received!*\n\n"
            f"📦 *Order ID:* `#{db_order.id}`\n"
            f"👤 *Blogger:* {blogger.name}\n"
            f"🏪 *Product:* {product.name}\n"
            f"📊 *Quantity:* {order.quantity}\n"
            f"💰 *Price per item:* ₸{order.price_per_item:.2f}\n"
            f"💵 *Total:* ₸{order.quantity * order.price_per_item:.2f}\n"
            f"🤝 *Commission:* ₸{commission_amount:.2f}\n"
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
    """All orders for the current company's products."""
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
def get_blogger_orders(
    skip: int = 0,
    limit: int = 100,
    db: Session = Depends(get_db),
    current_blogger: models.Blogger = Depends(auth.get_current_blogger),
):
    """All orders attributed to the current blogger."""
    return (
        db.query(models.Order)
        .filter(models.Order.blogger_id == current_blogger.id)
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

    if new_status == models.OrderStatus.PROCESSED:
        analytics = (
            db.query(models.Analytics)
            .filter(
                models.Analytics.product_id == order.product_id,
                models.Analytics.blogger_id == order.blogger_id,
            )
            .first()
        )
        total_amount = order.quantity * order.price_per_item
        if analytics:
            analytics.order_count += 1
            analytics.items_sold += order.quantity
            analytics.revenue += total_amount
            analytics.commission_paid += order.commission_amount
        else:
            db.add(
                models.Analytics(
                    product_id=order.product_id,
                    blogger_id=order.blogger_id,
                    order_count=1,
                    items_sold=order.quantity,
                    revenue=total_amount,
                    commission_paid=order.commission_amount,
                )
            )

    db.commit()

    # Notify company via Telegram
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
                f"💰 *Price per item:* ₸{order.price_per_item:.2f}\n"
                f"🤝 *Commission:* ₸{order.commission_amount:.2f}\n"
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
    """Update editable fields on an order (company-owned products only)."""
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
