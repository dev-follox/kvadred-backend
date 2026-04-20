import secrets
from datetime import datetime, timedelta, timezone
from typing import List

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from .. import models, schemas, auth
from ..database import get_db
from ..services.designer_company import effective_designer_bonus_percent
from ..services.subscription import assert_company_can_write, company_subscription_active

router = APIRouter(prefix="/companies", tags=["companies"])

INVITE_EXPIRE_HOURS = 72


@router.post("/", response_model=schemas.Company)
def create_company(company: schemas.CompanyCreate, db: Session = Depends(get_db)):
    if db.query(models.Company).filter(models.Company.email == company.email).first():
        raise HTTPException(status_code=400, detail="Email already registered")
    hashed_password = auth.get_password_hash(company.password)
    db_company = models.Company(
        email=company.email,
        full_name=company.full_name,
        phone_number=company.phone_number,
        company_name=company.company_name,
        description=company.description,
        hashed_password=hashed_password,
        default_designer_bonus_percent=company.default_designer_bonus_percent,
        subscription_expires_at=None,
    )
    db.add(db_company)
    db.commit()
    db.refresh(db_company)
    return db_company


@router.get("/me", response_model=schemas.Company)
def get_me(current_company: models.Company = Depends(auth.get_current_company)):
    return current_company


@router.put("/me", response_model=schemas.Company)
def update_me(
    company_update: schemas.CompanyUpdate,
    current_company: models.Company = Depends(auth.get_current_company),
    db: Session = Depends(get_db),
):
    assert_company_can_write(current_company)
    update_data = company_update.model_dump(exclude_unset=True)
    for field, value in update_data.items():
        setattr(current_company, field, value)
    db.commit()
    db.refresh(current_company)
    return current_company


@router.put("/me/password", status_code=status.HTTP_204_NO_CONTENT)
def update_my_password(
    body: schemas.PasswordUpdate,
    current_company: models.Company = Depends(auth.get_current_company),
    db: Session = Depends(get_db),
):
    assert_company_can_write(current_company)
    if not current_company.hashed_password:
        raise HTTPException(
            status_code=400,
            detail="Account uses external login; password cannot be changed here",
        )
    if not auth.verify_password(body.current_password, current_company.hashed_password):
        raise HTTPException(status_code=400, detail="Current password is incorrect")
    current_company.hashed_password = auth.get_password_hash(body.new_password)
    db.commit()
    return None


@router.delete("/me", status_code=status.HTTP_204_NO_CONTENT)
def delete_me(
    current_company: models.Company = Depends(auth.get_current_company),
    db: Session = Depends(get_db),
):
    assert_company_can_write(current_company)
    company_id = current_company.id
    product_ids = [
        p.id
        for p in db.query(models.Product).filter(models.Product.company_id == company_id).all()
    ]
    if product_ids:
        link_ids = [
            l.id
            for l in db.query(models.AffiliateLink)
            .filter(models.AffiliateLink.product_id.in_(product_ids))
            .all()
        ]
        if link_ids:
            db.query(models.Analytics).filter(
                models.Analytics.affiliate_link_id.in_(link_ids)
            ).delete(synchronize_session=False)
            db.query(models.Order).filter(models.Order.affiliate_link_id.in_(link_ids)).update(
                {"affiliate_link_id": None}, synchronize_session=False
            )
        db.query(models.Order).filter(models.Order.product_id.in_(product_ids)).delete(
            synchronize_session=False
        )
        db.query(models.AffiliateLink).filter(models.AffiliateLink.product_id.in_(product_ids)).delete(
            synchronize_session=False
        )
    db.query(models.DesignerInvite).filter(models.DesignerInvite.company_id == company_id).delete(
        synchronize_session=False
    )
    db.query(models.DesignerCompany).filter(models.DesignerCompany.company_id == company_id).delete(
        synchronize_session=False
    )
    db.query(models.Product).filter(models.Product.company_id == company_id).delete(
        synchronize_session=False
    )
    db.query(models.Company).filter(models.Company.id == company_id).delete(synchronize_session=False)
    db.commit()
    return None


@router.get("/{company_id}", response_model=schemas.Company)
def get_company(
    company_id: int,
    current_company: models.Company = Depends(auth.get_current_company),
    db: Session = Depends(get_db),
):
    if current_company.id != company_id:
        raise HTTPException(status_code=403, detail="Not authorized")
    company = db.query(models.Company).filter(models.Company.id == company_id).first()
    if not company:
        raise HTTPException(status_code=404, detail="Company not found")
    return company


@router.post("/{company_id}/telegram", response_model=schemas.Company)
def link_telegram(
    company_id: int,
    body: schemas.TelegramLink,
    current_company: models.Company = Depends(auth.get_current_company),
    db: Session = Depends(get_db),
):
    assert_company_can_write(current_company)
    if current_company.id != company_id:
        raise HTTPException(status_code=403, detail="Not authorized")
    current_company.telegram_chat_id = body.telegram_chat_id
    db.commit()
    db.refresh(current_company)
    return current_company


@router.get("/{company_id}/telegram/setup")
def telegram_setup_info(
    company_id: int,
    current_company: models.Company = Depends(auth.get_current_company),
):
    if current_company.id != company_id:
        raise HTTPException(status_code=403, detail="Not authorized")
    return {
        "instructions": (
            "1. Open Telegram and search for the Kvadred bot.\n"
            "2. Send /start to the bot.\n"
            "3. Copy your Chat ID from the bot's response.\n"
            "4. POST that Chat ID to /companies/{company_id}/telegram."
        ),
        "is_linked": current_company.telegram_chat_id is not None,
        "telegram_chat_id": current_company.telegram_chat_id,
    }


@router.post("/me/designer-invites", response_model=schemas.DesignerInvite)
def invite_designer(
    body: schemas.DesignerInviteCreate,
    current_company: models.Company = Depends(auth.get_current_company),
    db: Session = Depends(get_db),
):
    assert_company_can_write(current_company)
    token = secrets.token_urlsafe(32)
    expires_at = datetime.now(timezone.utc) + timedelta(hours=INVITE_EXPIRE_HOURS)
    invite = models.DesignerInvite(
        company_id=current_company.id,
        designer_email=body.designer_email,
        token=token,
        expires_at=expires_at,
    )
    db.add(invite)
    db.commit()
    db.refresh(invite)
    return invite


@router.get("/me/designers", response_model=List[schemas.DesignerCompanyWithDesigner])
def list_company_designers(
    current_company: models.Company = Depends(auth.get_current_company),
    db: Session = Depends(get_db),
):
    assert_company_can_write(current_company)
    rows = (
        db.query(models.DesignerCompany)
        .filter(models.DesignerCompany.company_id == current_company.id)
        .order_by(models.DesignerCompany.created_at.asc())
        .all()
    )
    out: List[schemas.DesignerCompanyWithDesigner] = []
    for row in rows:
        designer = row.designer
        eff = effective_designer_bonus_percent(db, row.designer_id, current_company.id)
        out.append(
            schemas.DesignerCompanyWithDesigner(
                id=row.id,
                designer_id=row.designer_id,
                company_id=row.company_id,
                bonus_percent_override=row.bonus_percent_override,
                created_at=row.created_at,
                designer=schemas.Designer.model_validate(designer),
                effective_bonus_percent=eff,
            )
        )
    return out


@router.patch(
    "/me/designers/{designer_id}/bonus",
    response_model=schemas.DesignerCompany,
)
def update_designer_bonus(
    designer_id: int,
    body: schemas.DesignerBonusUpdate,
    current_company: models.Company = Depends(auth.get_current_company),
    db: Session = Depends(get_db),
):
    assert_company_can_write(current_company)
    row = (
        db.query(models.DesignerCompany)
        .filter(
            models.DesignerCompany.company_id == current_company.id,
            models.DesignerCompany.designer_id == designer_id,
        )
        .first()
    )
    if not row:
        raise HTTPException(status_code=404, detail="Designer is not linked to this company")
    row.bonus_percent_override = body.bonus_percent_override
    db.commit()
    db.refresh(row)
    return row


@router.delete(
    "/me/affiliate-links/{link_id}",
    status_code=status.HTTP_204_NO_CONTENT,
)
def delete_company_affiliate_link(
    link_id: int,
    db: Session = Depends(get_db),
    current_company: models.Company = Depends(auth.get_current_company),
):
    assert_company_can_write(current_company)
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
    db.query(models.Order).filter(models.Order.affiliate_link_id == link.id).update(
        {"affiliate_link_id": None}, synchronize_session=False
    )
    db.query(models.Analytics).filter(models.Analytics.affiliate_link_id == link.id).delete(
        synchronize_session=False
    )
    db.delete(link)
    db.commit()
    return None
