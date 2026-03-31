import secrets
from datetime import datetime, timedelta, timezone
from typing import List

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from .. import models, schemas, auth
from ..database import get_db

router = APIRouter(prefix="/bloggers", tags=["bloggers"])

INVITE_EXPIRE_HOURS = 72


@router.post("/", response_model=schemas.Blogger)
def create_blogger(blogger: schemas.BloggerCreate, db: Session = Depends(get_db)):
    """Self-register a new blogger account."""
    if db.query(models.Blogger).filter(models.Blogger.email == blogger.email).first():
        raise HTTPException(status_code=400, detail="Email already registered")
    hashed_password = auth.get_password_hash(blogger.password)
    db_blogger = models.Blogger(
        name=blogger.name,
        email=blogger.email,
        bio=blogger.bio,
        hashed_password=hashed_password,
    )
    db.add(db_blogger)
    db.commit()
    db.refresh(db_blogger)
    return db_blogger


@router.get("/me", response_model=schemas.Blogger)
def get_me(current_blogger: models.Blogger = Depends(auth.get_current_blogger)):
    return current_blogger


@router.put("/me", response_model=schemas.Blogger)
def update_me(
    blogger_update: schemas.BloggerUpdate,
    current_blogger: models.Blogger = Depends(auth.get_current_blogger),
    db: Session = Depends(get_db),
):
    for field, value in blogger_update.model_dump(exclude_unset=True).items():
        setattr(current_blogger, field, value)
    db.commit()
    db.refresh(current_blogger)
    return current_blogger


@router.put("/me/password", status_code=status.HTTP_204_NO_CONTENT)
def update_my_password(
    body: schemas.PasswordUpdate,
    current_blogger: models.Blogger = Depends(auth.get_current_blogger),
    db: Session = Depends(get_db),
):
    if not current_blogger.hashed_password:
        raise HTTPException(status_code=400, detail="Account uses external login")
    if not auth.verify_password(body.current_password, current_blogger.hashed_password):
        raise HTTPException(status_code=400, detail="Current password is incorrect")
    current_blogger.hashed_password = auth.get_password_hash(body.new_password)
    db.commit()
    return None


@router.post("/me/telegram", response_model=schemas.Blogger)
def link_telegram(
    body: schemas.TelegramLink,
    current_blogger: models.Blogger = Depends(auth.get_current_blogger),
    db: Session = Depends(get_db),
):
    """Link a Telegram chat to the blogger's account for notifications."""
    current_blogger.telegram_chat_id = body.telegram_chat_id
    db.commit()
    db.refresh(current_blogger)
    return current_blogger


@router.get("/me/companies", response_model=List[schemas.Company])
def get_my_companies(
    current_blogger: models.Blogger = Depends(auth.get_current_blogger),
    db: Session = Depends(get_db),
):
    """Return all companies the current blogger is associated with."""
    rows = (
        db.query(models.BloggerCompany)
        .filter(models.BloggerCompany.blogger_id == current_blogger.id)
        .all()
    )
    company_ids = [r.company_id for r in rows]
    if not company_ids:
        return []
    return db.query(models.Company).filter(models.Company.id.in_(company_ids)).all()


@router.get("/", response_model=List[schemas.Blogger])
def get_bloggers(
    skip: int = 0,
    limit: int = 100,
    db: Session = Depends(get_db),
    current_company: models.Company = Depends(auth.get_current_company),
):
    """List all bloggers associated with the current company."""
    rows = (
        db.query(models.BloggerCompany)
        .filter(models.BloggerCompany.company_id == current_company.id)
        .all()
    )
    blogger_ids = [r.blogger_id for r in rows]
    if not blogger_ids:
        return []
    return (
        db.query(models.Blogger)
        .filter(models.Blogger.id.in_(blogger_ids))
        .offset(skip)
        .limit(limit)
        .all()
    )


# ─── Invite flow ─────────────────────────────────────────────────────────────

@router.post("/invite", response_model=schemas.BloggerInvite)
def invite_blogger(
    body: schemas.BloggerInviteCreate,
    current_company: models.Company = Depends(auth.get_current_company),
    db: Session = Depends(get_db),
):
    """Company sends an invite link to a blogger's email."""
    token = secrets.token_urlsafe(32)
    expires_at = datetime.now(timezone.utc) + timedelta(hours=INVITE_EXPIRE_HOURS)
    invite = models.BloggerInvite(
        company_id=current_company.id,
        blogger_email=body.blogger_email,
        token=token,
        expires_at=expires_at,
    )
    db.add(invite)
    db.commit()
    db.refresh(invite)
    return invite


@router.get("/invite/{token}", response_model=schemas.BloggerInvite)
def get_invite_info(token: str, db: Session = Depends(get_db)):
    """Fetch invite details so the frontend can pre-fill the registration form."""
    invite = db.query(models.BloggerInvite).filter(models.BloggerInvite.token == token).first()
    if not invite:
        raise HTTPException(status_code=404, detail="Invite not found")
    if invite.status != models.InviteStatus.PENDING:
        raise HTTPException(status_code=400, detail=f"Invite is {invite.status.value}")
    if invite.expires_at.replace(tzinfo=timezone.utc) < datetime.now(timezone.utc):
        invite.status = models.InviteStatus.EXPIRED
        db.commit()
        raise HTTPException(status_code=400, detail="Invite has expired")
    return invite


@router.post("/invite/{token}/accept", response_model=schemas.Token)
def accept_invite(
    token: str,
    body: schemas.BloggerInviteAccept,
    db: Session = Depends(get_db),
):
    """
    Accept an invite: creates a blogger account (or links existing) and
    associates them with the inviting company.
    """
    invite = db.query(models.BloggerInvite).filter(models.BloggerInvite.token == token).first()
    if not invite:
        raise HTTPException(status_code=404, detail="Invite not found")
    if invite.status != models.InviteStatus.PENDING:
        raise HTTPException(status_code=400, detail=f"Invite is {invite.status.value}")
    if invite.expires_at.replace(tzinfo=timezone.utc) < datetime.now(timezone.utc):
        invite.status = models.InviteStatus.EXPIRED
        db.commit()
        raise HTTPException(status_code=400, detail="Invite has expired")

    # Get or create the blogger
    blogger = db.query(models.Blogger).filter(models.Blogger.email == invite.blogger_email).first()
    if not blogger:
        blogger = models.Blogger(
            name=body.name,
            email=invite.blogger_email,
            hashed_password=auth.get_password_hash(body.password),
        )
        db.add(blogger)
        db.flush()

    # Link blogger ↔ company if not already linked
    existing_link = (
        db.query(models.BloggerCompany)
        .filter(
            models.BloggerCompany.blogger_id == blogger.id,
            models.BloggerCompany.company_id == invite.company_id,
        )
        .first()
    )
    if not existing_link:
        db.add(models.BloggerCompany(blogger_id=blogger.id, company_id=invite.company_id))

    invite.status = models.InviteStatus.ACCEPTED
    db.commit()
    db.refresh(blogger)

    from datetime import timedelta
    access_token = auth.create_access_token(
        data={"sub": blogger.email, "role": "BLOGGER", "blogger_id": blogger.id},
        expires_delta=timedelta(minutes=auth.ACCESS_TOKEN_EXPIRE_MINUTES),
    )
    return {
        "access_token": access_token,
        "token_type": "bearer",
        "company_id": None,
        "blogger_id": blogger.id,
        "admin_id": None,
        "email": blogger.email,
        "name": blogger.name,
        "role": "BLOGGER",
    }


@router.post("/me/join-company/{company_id}", response_model=schemas.BloggerCompany)
def join_company(
    company_id: int,
    current_blogger: models.Blogger = Depends(auth.get_current_blogger),
    db: Session = Depends(get_db),
):
    """Manually associate an authenticated blogger with a company."""
    company = db.query(models.Company).filter(models.Company.id == company_id).first()
    if not company:
        raise HTTPException(status_code=404, detail="Company not found")
    existing = (
        db.query(models.BloggerCompany)
        .filter(
            models.BloggerCompany.blogger_id == current_blogger.id,
            models.BloggerCompany.company_id == company_id,
        )
        .first()
    )
    if existing:
        return existing
    link = models.BloggerCompany(blogger_id=current_blogger.id, company_id=company_id)
    db.add(link)
    db.commit()
    db.refresh(link)
    return link
