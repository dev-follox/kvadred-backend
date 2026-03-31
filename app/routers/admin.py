import re
import logging
from pathlib import Path
from typing import List

from alembic import command
from alembic.config import Config
from alembic.runtime.migration import MigrationContext
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import create_engine, inspect, text
from sqlalchemy.orm import Session, sessionmaker

from ..database import DATABASE_URL, get_db
from .. import models, schemas, auth
from ..constants import DEFAULT_ADMIN_EMAIL, DEFAULT_ADMIN_PASSWORD, DEFAULT_ADMIN_NAME

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/admin", tags=["admin"])


# ─── Migrations ──────────────────────────────────────────────────────────────

@router.post("/migrate")
async def run_migrations():
    """Run all pending Alembic migrations to head."""
    try:
        alembic_ini_path = str(Path(__file__).parent.parent.parent / "alembic.ini")
        alembic_cfg = Config(alembic_ini_path)
        alembic_cfg.set_main_option("sqlalchemy.url", DATABASE_URL)

        try:
            command.upgrade(alembic_cfg, "heads")
        except Exception as migration_error:
            error_str = str(migration_error)
            if "Can't locate revision" in error_str or "No such revision" in error_str:
                match = re.search(r"'(.*?)'", error_str)
                if match:
                    missing_rev = match.group(1)
                    engine = create_engine(DATABASE_URL)
                    with engine.connect() as conn:
                        conn.execute(
                            text("DELETE FROM alembic_version WHERE version_num = :rev"),
                            {"rev": missing_rev},
                        )
                        conn.commit()
                    engine.dispose()
                    command.upgrade(alembic_cfg, "heads")
                else:
                    raise migration_error
            else:
                raise migration_error

        engine = create_engine(DATABASE_URL)
        with engine.connect() as conn:
            ctx = MigrationContext.configure(conn)
            try:
                current_rev = ctx.get_current_revision()
            except Exception:
                heads = ctx.get_current_heads()
                current_rev = ", ".join(heads) if heads else "unknown"

        inspector = inspect(engine)
        admin_created = False
        if "admins" in inspector.get_table_names():
            Session_ = sessionmaker(bind=engine)
            db_session = Session_()
            try:
                if db_session.query(models.Admin).count() == 0:
                    db_session.add(
                        models.Admin(
                            email=DEFAULT_ADMIN_EMAIL,
                            hashed_password=auth.get_password_hash(DEFAULT_ADMIN_PASSWORD),
                            name=DEFAULT_ADMIN_NAME,
                        )
                    )
                    db_session.commit()
                    admin_created = True
            except Exception as e:
                db_session.rollback()
                logger.warning(f"Failed to create default admin: {e}")
            finally:
                db_session.close()
        engine.dispose()

        response = {
            "message": "Migrations completed successfully",
            "current_revision": current_rev,
            "status": "up_to_date",
        }
        if admin_created:
            response["admin_created"] = True
            response["admin_email"] = DEFAULT_ADMIN_EMAIL
            response["message"] += ". Default admin created."
        return response

    except Exception as e:
        import traceback
        logger.error(f"Migration failed: {e}\n{traceback.format_exc()}")
        raise HTTPException(status_code=500, detail=f"Migration failed: {e}")


# ─── Admin management ─────────────────────────────────────────────────────────

@router.post("/create", response_model=schemas.Admin)
def create_admin(
    admin: schemas.AdminCreate,
    current_admin: models.Admin = Depends(auth.get_current_admin),
    db: Session = Depends(get_db),
):
    if db.query(models.Admin).filter(models.Admin.email == admin.email).first():
        raise HTTPException(status_code=400, detail="Admin with this email already exists")
    db_admin = models.Admin(
        email=admin.email,
        name=admin.name,
        hashed_password=auth.get_password_hash(admin.password),
    )
    db.add(db_admin)
    db.commit()
    db.refresh(db_admin)
    return db_admin


# ─── Companies ────────────────────────────────────────────────────────────────

@router.get("/companies", response_model=List[schemas.Company])
def list_companies(
    skip: int = 0,
    limit: int = 100,
    current_admin: models.Admin = Depends(auth.get_current_admin),
    db: Session = Depends(get_db),
):
    return db.query(models.Company).offset(skip).limit(limit).all()


@router.get("/companies/{company_id}", response_model=schemas.Company)
def get_company(
    company_id: int,
    current_admin: models.Admin = Depends(auth.get_current_admin),
    db: Session = Depends(get_db),
):
    company = db.query(models.Company).filter(models.Company.id == company_id).first()
    if not company:
        raise HTTPException(status_code=404, detail="Company not found")
    return company


@router.delete("/companies/{company_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_company(
    company_id: int,
    current_admin: models.Admin = Depends(auth.get_current_admin),
    db: Session = Depends(get_db),
):
    company = db.query(models.Company).filter(models.Company.id == company_id).first()
    if not company:
        raise HTTPException(status_code=404, detail="Company not found")
    product_ids = [p.id for p in db.query(models.Product).filter(models.Product.company_id == company_id).all()]
    if product_ids:
        link_ids = [l.id for l in db.query(models.AffiliateLink).filter(models.AffiliateLink.product_id.in_(product_ids)).all()]
        if link_ids:
            db.query(models.Order).filter(models.Order.affiliate_link_id.in_(link_ids)).update({"affiliate_link_id": None}, synchronize_session=False)
        db.query(models.Order).filter(models.Order.product_id.in_(product_ids)).delete(synchronize_session=False)
        db.query(models.Analytics).filter(models.Analytics.product_id.in_(product_ids)).delete(synchronize_session=False)
        db.query(models.AffiliateLink).filter(models.AffiliateLink.product_id.in_(product_ids)).delete(synchronize_session=False)
    db.query(models.BloggerInvite).filter(models.BloggerInvite.company_id == company_id).delete(synchronize_session=False)
    db.query(models.BloggerCompany).filter(models.BloggerCompany.company_id == company_id).delete(synchronize_session=False)
    db.query(models.Product).filter(models.Product.company_id == company_id).delete(synchronize_session=False)
    db.query(models.Company).filter(models.Company.id == company_id).delete(synchronize_session=False)
    db.commit()
    return None


# ─── Bloggers ─────────────────────────────────────────────────────────────────

@router.get("/bloggers", response_model=List[schemas.Blogger])
def list_bloggers(
    skip: int = 0,
    limit: int = 100,
    current_admin: models.Admin = Depends(auth.get_current_admin),
    db: Session = Depends(get_db),
):
    return db.query(models.Blogger).offset(skip).limit(limit).all()


@router.get("/bloggers/{blogger_id}", response_model=schemas.Blogger)
def get_blogger(
    blogger_id: int,
    current_admin: models.Admin = Depends(auth.get_current_admin),
    db: Session = Depends(get_db),
):
    blogger = db.query(models.Blogger).filter(models.Blogger.id == blogger_id).first()
    if not blogger:
        raise HTTPException(status_code=404, detail="Blogger not found")
    return blogger


@router.delete("/bloggers/{blogger_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_blogger(
    blogger_id: int,
    current_admin: models.Admin = Depends(auth.get_current_admin),
    db: Session = Depends(get_db),
):
    blogger = db.query(models.Blogger).filter(models.Blogger.id == blogger_id).first()
    if not blogger:
        raise HTTPException(status_code=404, detail="Blogger not found")
    db.query(models.BloggerCompany).filter(models.BloggerCompany.blogger_id == blogger_id).delete(synchronize_session=False)
    db.query(models.Analytics).filter(models.Analytics.blogger_id == blogger_id).delete(synchronize_session=False)
    db.query(models.AffiliateLink).filter(models.AffiliateLink.blogger_id == blogger_id).delete(synchronize_session=False)
    db.query(models.Order).filter(models.Order.blogger_id == blogger_id).delete(synchronize_session=False)
    db.query(models.Blogger).filter(models.Blogger.id == blogger_id).delete(synchronize_session=False)
    db.commit()
    return None


# ─── Orders ───────────────────────────────────────────────────────────────────

@router.get("/orders", response_model=List[schemas.Order])
def list_orders(
    skip: int = 0,
    limit: int = 200,
    current_admin: models.Admin = Depends(auth.get_current_admin),
    db: Session = Depends(get_db),
):
    return db.query(models.Order).offset(skip).limit(limit).all()


# ─── Products ─────────────────────────────────────────────────────────────────

@router.get("/products", response_model=List[schemas.Product])
def list_products(
    skip: int = 0,
    limit: int = 100,
    current_admin: models.Admin = Depends(auth.get_current_admin),
    db: Session = Depends(get_db),
):
    return db.query(models.Product).offset(skip).limit(limit).all()


# ─── Analytics ────────────────────────────────────────────────────────────────

@router.get("/analytics", response_model=List[schemas.Analytics])
def list_analytics(
    skip: int = 0,
    limit: int = 200,
    current_admin: models.Admin = Depends(auth.get_current_admin),
    db: Session = Depends(get_db),
):
    return db.query(models.Analytics).offset(skip).limit(limit).all()
