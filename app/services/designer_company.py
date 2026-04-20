from sqlalchemy.orm import Session

from .. import models


def effective_designer_bonus_percent(
    db: Session, designer_id: int, company_id: int
) -> float:
    company = db.query(models.Company).filter(models.Company.id == company_id).first()
    if not company:
        raise ValueError("Company not found")
    row = (
        db.query(models.DesignerCompany)
        .filter(
            models.DesignerCompany.designer_id == designer_id,
            models.DesignerCompany.company_id == company_id,
        )
        .first()
    )
    if row and row.bonus_percent_override is not None:
        return float(row.bonus_percent_override)
    return float(company.default_designer_bonus_percent)


def ensure_designer_company(
    db: Session, designer_id: int, company_id: int
) -> models.DesignerCompany:
    existing = (
        db.query(models.DesignerCompany)
        .filter(
            models.DesignerCompany.designer_id == designer_id,
            models.DesignerCompany.company_id == company_id,
        )
        .first()
    )
    if existing:
        return existing
    link = models.DesignerCompany(designer_id=designer_id, company_id=company_id)
    db.add(link)
    db.flush()
    return link
