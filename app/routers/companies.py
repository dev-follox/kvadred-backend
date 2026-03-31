from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session
from typing import List

from .. import models, schemas, auth
from ..database import get_db
from ..services.telegram_webhook import telegram_service

router = APIRouter(prefix="/companies", tags=["companies"])


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
            db.query(models.Order).filter(
                models.Order.affiliate_link_id.in_(link_ids)
            ).update({"affiliate_link_id": None}, synchronize_session=False)
        db.query(models.Order).filter(
            models.Order.product_id.in_(product_ids)
        ).delete(synchronize_session=False)
        db.query(models.Analytics).filter(
            models.Analytics.product_id.in_(product_ids)
        ).delete(synchronize_session=False)
        db.query(models.AffiliateLink).filter(
            models.AffiliateLink.product_id.in_(product_ids)
        ).delete(synchronize_session=False)
    db.query(models.BloggerInvite).filter(
        models.BloggerInvite.company_id == company_id
    ).delete(synchronize_session=False)
    db.query(models.BloggerCompany).filter(
        models.BloggerCompany.company_id == company_id
    ).delete(synchronize_session=False)
    db.query(models.Product).filter(
        models.Product.company_id == company_id
    ).delete(synchronize_session=False)
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


@router.get("/{company_id}/bloggers", response_model=List[schemas.Blogger])
def get_company_bloggers(
    company_id: int,
    current_company: models.Company = Depends(auth.get_current_company),
    db: Session = Depends(get_db),
):
    """List all bloggers associated with this company."""
    if current_company.id != company_id:
        raise HTTPException(status_code=403, detail="Not authorized")
    rows = (
        db.query(models.BloggerCompany)
        .filter(models.BloggerCompany.company_id == company_id)
        .all()
    )
    blogger_ids = [r.blogger_id for r in rows]
    if not blogger_ids:
        return []
    return db.query(models.Blogger).filter(models.Blogger.id.in_(blogger_ids)).all()
