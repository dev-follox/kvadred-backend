from datetime import datetime, timezone

from fastapi import HTTPException, status
from sqlalchemy.orm import Session

from .. import models


def company_subscription_active(company: models.Company) -> bool:
    if company.subscription_expires_at is None:
        return False
    return company.subscription_expires_at > datetime.now(timezone.utc)


def assert_company_can_write(company: models.Company) -> None:
    if not company_subscription_active(company):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Company subscription is inactive. Renew subscription to perform this action.",
        )


def assert_company_catalog_readable_for_designer(db: Session, company_id: int) -> models.Company:
    company = db.query(models.Company).filter(models.Company.id == company_id).first()
    if not company:
        raise HTTPException(status_code=404, detail="Company not found")
    if not company_subscription_active(company):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="This company is not available.",
        )
    return company
