from datetime import datetime, timedelta, timezone
from typing import List

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from .. import models, schemas, auth
from ..database import get_db
from ..services import affiliate as affiliate_service
from ..services.commission import compute_sale_amounts
from ..services.designer_company import effective_designer_bonus_percent, ensure_designer_company
from ..services.subscription import assert_company_catalog_readable_for_designer
from ..services.subscription import company_subscription_active

router = APIRouter(prefix="/designers", tags=["designers"])

INVITE_EXPIRE_HOURS = 72


@router.post("/", response_model=schemas.Designer)
def create_designer(designer: schemas.DesignerCreate, db: Session = Depends(get_db)):
    if db.query(models.Designer).filter(models.Designer.email == designer.email).first():
        raise HTTPException(status_code=400, detail="Email already registered")
    hashed_password = auth.get_password_hash(designer.password)
    db_designer = models.Designer(
        name=designer.name,
        email=designer.email,
        bio=designer.bio,
        hashed_password=hashed_password,
    )
    db.add(db_designer)
    db.commit()
    db.refresh(db_designer)
    return db_designer


@router.get("/me", response_model=schemas.Designer)
def get_me(current_designer: models.Designer = Depends(auth.get_current_designer)):
    return current_designer


@router.put("/me", response_model=schemas.Designer)
def update_me(
    designer_update: schemas.DesignerUpdate,
    current_designer: models.Designer = Depends(auth.get_current_designer),
    db: Session = Depends(get_db),
):
    for field, value in designer_update.model_dump(exclude_unset=True).items():
        setattr(current_designer, field, value)
    db.commit()
    db.refresh(current_designer)
    return current_designer


@router.put("/me/password", status_code=status.HTTP_204_NO_CONTENT)
def update_my_password(
    body: schemas.PasswordUpdate,
    current_designer: models.Designer = Depends(auth.get_current_designer),
    db: Session = Depends(get_db),
):
    if not current_designer.hashed_password:
        raise HTTPException(status_code=400, detail="Account uses external login")
    if not auth.verify_password(body.current_password, current_designer.hashed_password):
        raise HTTPException(status_code=400, detail="Current password is incorrect")
    current_designer.hashed_password = auth.get_password_hash(body.new_password)
    db.commit()
    return None


@router.post("/me/telegram", response_model=schemas.Designer)
def link_telegram(
    body: schemas.TelegramLink,
    current_designer: models.Designer = Depends(auth.get_current_designer),
    db: Session = Depends(get_db),
):
    current_designer.telegram_chat_id = body.telegram_chat_id
    db.commit()
    db.refresh(current_designer)
    return current_designer


@router.get("/catalog/companies", response_model=List[schemas.Company])
def list_subscribed_companies(
    current_designer: models.Designer = Depends(auth.get_current_designer),
    db: Session = Depends(get_db),
):
    now = datetime.now(timezone.utc)
    return (
        db.query(models.Company)
        .filter(
            models.Company.subscription_expires_at.isnot(None),
            models.Company.subscription_expires_at > now,
        )
        .order_by(models.Company.company_name)
        .all()
    )


@router.get("/catalog/companies/{company_id}/products", response_model=List[schemas.Product])
def list_company_catalog(
    company_id: int,
    current_designer: models.Designer = Depends(auth.get_current_designer),
    db: Session = Depends(get_db),
):
    assert_company_catalog_readable_for_designer(db, company_id)
    return (
        db.query(models.Product)
        .filter(models.Product.company_id == company_id)
        .order_by(models.Product.name)
        .all()
    )


@router.get("/me/companies", response_model=List[schemas.Company])
def get_my_companies(
    current_designer: models.Designer = Depends(auth.get_current_designer),
    db: Session = Depends(get_db),
):
    rows = (
        db.query(models.DesignerCompany)
        .filter(models.DesignerCompany.designer_id == current_designer.id)
        .all()
    )
    company_ids = [r.company_id for r in rows]
    if not company_ids:
        return []
    return db.query(models.Company).filter(models.Company.id.in_(company_ids)).all()


@router.post("/me/join-company/{company_id}", response_model=schemas.DesignerCompany)
def join_company(
    company_id: int,
    current_designer: models.Designer = Depends(auth.get_current_designer),
    db: Session = Depends(get_db),
):
    company = db.query(models.Company).filter(models.Company.id == company_id).first()
    if not company:
        raise HTTPException(status_code=404, detail="Company not found")
    if not company_subscription_active(company):
        raise HTTPException(status_code=403, detail="This company is not accepting new partnerships")
    existing = (
        db.query(models.DesignerCompany)
        .filter(
            models.DesignerCompany.designer_id == current_designer.id,
            models.DesignerCompany.company_id == company_id,
        )
        .first()
    )
    if existing:
        return existing
    link = models.DesignerCompany(designer_id=current_designer.id, company_id=company_id)
    db.add(link)
    db.commit()
    db.refresh(link)
    return link


@router.get("/invites/{token}", response_model=schemas.DesignerInvite)
def get_invite_info(token: str, db: Session = Depends(get_db)):
    invite = db.query(models.DesignerInvite).filter(models.DesignerInvite.token == token).first()
    if not invite:
        raise HTTPException(status_code=404, detail="Invite not found")
    if invite.status != models.InviteStatus.PENDING:
        raise HTTPException(status_code=400, detail=f"Invite is {invite.status.value}")
    if invite.expires_at.replace(tzinfo=timezone.utc) < datetime.now(timezone.utc):
        invite.status = models.InviteStatus.EXPIRED
        db.commit()
        raise HTTPException(status_code=400, detail="Invite has expired")
    return invite


@router.post("/invites/{token}/accept", response_model=schemas.Token)
def accept_invite(
    token: str,
    body: schemas.DesignerInviteAccept,
    db: Session = Depends(get_db),
):
    invite = db.query(models.DesignerInvite).filter(models.DesignerInvite.token == token).first()
    if not invite:
        raise HTTPException(status_code=404, detail="Invite not found")
    if invite.status != models.InviteStatus.PENDING:
        raise HTTPException(status_code=400, detail=f"Invite is {invite.status.value}")
    if invite.expires_at.replace(tzinfo=timezone.utc) < datetime.now(timezone.utc):
        invite.status = models.InviteStatus.EXPIRED
        db.commit()
        raise HTTPException(status_code=400, detail="Invite has expired")

    designer = db.query(models.Designer).filter(models.Designer.email == invite.designer_email).first()
    if not designer:
        designer = models.Designer(
            name=body.name,
            email=invite.designer_email,
            hashed_password=auth.get_password_hash(body.password),
        )
        db.add(designer)
        db.flush()

    existing_link = (
        db.query(models.DesignerCompany)
        .filter(
            models.DesignerCompany.designer_id == designer.id,
            models.DesignerCompany.company_id == invite.company_id,
        )
        .first()
    )
    if not existing_link:
        db.add(models.DesignerCompany(designer_id=designer.id, company_id=invite.company_id))

    invite.status = models.InviteStatus.ACCEPTED
    db.commit()
    db.refresh(designer)

    access_token = auth.create_access_token(
        data={"sub": designer.email, "role": "DESIGNER", "designer_id": designer.id},
        expires_delta=timedelta(minutes=auth.ACCESS_TOKEN_EXPIRE_MINUTES),
    )
    return {
        "access_token": access_token,
        "token_type": "bearer",
        "company_id": None,
        "designer_id": designer.id,
        "admin_id": None,
        "email": designer.email,
        "name": designer.name,
        "role": "DESIGNER",
    }


@router.post("/me/manual-orders", response_model=schemas.Order)
def create_manual_order(
    body: schemas.DesignerManualOrderCreate,
    current_designer: models.Designer = Depends(auth.get_current_designer),
    db: Session = Depends(get_db),
):
    product = db.query(models.Product).filter(models.Product.id == body.product_id).first()
    if not product:
        raise HTTPException(status_code=404, detail="Product not found")
    assert_company_catalog_readable_for_designer(db, product.company_id)
    ensure_designer_company(db, current_designer.id, product.company_id)
    link = affiliate_service.get_or_create_affiliate_link(db, current_designer, body.product_id)

    bonus_pct = effective_designer_bonus_percent(db, current_designer.id, product.company_id)
    line, designer_bonus, platform_fee = compute_sale_amounts(
        body.quantity, body.price_per_item, bonus_pct
    )

    order = models.Order(
        product_id=body.product_id,
        designer_id=current_designer.id,
        affiliate_link_id=link.id,
        quantity=body.quantity,
        price_per_item=body.price_per_item,
        line_revenue=line,
        designer_bonus_amount=designer_bonus,
        platform_fee_amount=platform_fee,
        client_phone=body.client_phone,
        client_name=body.client_name,
        note=body.note,
        attachment_url=body.attachment_url,
        is_manual=True,
    )
    db.add(order)
    db.commit()
    db.refresh(order)
    return order
