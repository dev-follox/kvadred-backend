import re
from datetime import datetime
from typing import List, Optional

from pydantic import BaseModel, EmailStr, Field, field_validator

from .models import InviteStatus, OrderStatus


def _validate_password_strength(value: str) -> str:
    errors = []
    if len(value) < 8:
        errors.append("at least 8 characters")
    if not re.search(r"[A-Z]", value):
        errors.append("at least one uppercase letter")
    if not re.search(r"[a-z]", value):
        errors.append("at least one lowercase letter")
    if not re.search(r"\d", value):
        errors.append("at least one number")
    if re.search(r"^[a-zA-Z0-9]*$", value):
        errors.append("at least one special character")
    if errors:
        raise ValueError("Password must have: " + "; ".join(errors))
    return value


# ─── Company ────────────────────────────────────────────────────────────────


class CompanyBase(BaseModel):
    full_name: str
    email: EmailStr
    phone_number: Optional[str] = None
    company_name: str
    description: Optional[str] = None


class CompanyCreate(CompanyBase):
    password: str
    default_designer_bonus_percent: float = Field(ge=0, le=100)

    @field_validator("password")
    @classmethod
    def password_strength(cls, v: str) -> str:
        return _validate_password_strength(v)


class CompanyUpdate(BaseModel):
    full_name: Optional[str] = None
    phone_number: Optional[str] = None
    company_name: Optional[str] = None
    description: Optional[str] = None
    default_designer_bonus_percent: Optional[float] = Field(default=None, ge=0, le=100)


class Company(CompanyBase):
    id: int
    telegram_chat_id: Optional[str] = None
    default_designer_bonus_percent: float
    subscription_expires_at: Optional[datetime] = None
    created_at: datetime
    updated_at: Optional[datetime] = None

    class Config:
        from_attributes = True


class CompanySubscriptionAdminUpdate(BaseModel):
    subscription_expires_at: Optional[datetime] = None
    default_designer_bonus_percent: Optional[float] = Field(default=None, ge=0, le=100)


class PasswordUpdate(BaseModel):
    current_password: str
    new_password: str

    @field_validator("new_password")
    @classmethod
    def new_password_strength(cls, v: str) -> str:
        return _validate_password_strength(v)


# ─── Product ────────────────────────────────────────────────────────────────


class ProductBase(BaseModel):
    name: str
    description: Optional[str] = None
    price: float
    image_url: Optional[str] = None
    designer_task_description: Optional[str] = None


class ProductCreate(ProductBase):
    company_id: int


class ProductUpdate(BaseModel):
    name: Optional[str] = None
    description: Optional[str] = None
    price: Optional[float] = None
    image_url: Optional[str] = None
    designer_task_description: Optional[str] = None


class Product(ProductBase):
    id: int
    company_id: int
    created_at: datetime
    updated_at: Optional[datetime] = None

    class Config:
        from_attributes = True


# ─── Designer ───────────────────────────────────────────────────────────────


class DesignerBase(BaseModel):
    name: str
    email: EmailStr
    bio: Optional[str] = None


class DesignerCreate(DesignerBase):
    password: str

    @field_validator("password")
    @classmethod
    def password_strength(cls, v: str) -> str:
        return _validate_password_strength(v)


class DesignerUpdate(BaseModel):
    name: Optional[str] = None
    bio: Optional[str] = None


class Designer(DesignerBase):
    id: int
    telegram_chat_id: Optional[str] = None
    created_at: datetime
    updated_at: Optional[datetime] = None

    class Config:
        from_attributes = True


# ─── Designer Invite ─────────────────────────────────────────────────────────


class DesignerInviteCreate(BaseModel):
    designer_email: EmailStr


class DesignerInviteAccept(BaseModel):
    token: str
    name: str
    password: str

    @field_validator("password")
    @classmethod
    def password_strength(cls, v: str) -> str:
        return _validate_password_strength(v)


class DesignerInvite(BaseModel):
    id: int
    company_id: int
    designer_email: str
    token: str
    status: InviteStatus
    expires_at: datetime
    created_at: datetime

    class Config:
        from_attributes = True


# ─── DesignerCompany ─────────────────────────────────────────────────────────


class DesignerCompany(BaseModel):
    id: int
    designer_id: int
    company_id: int
    bonus_percent_override: Optional[float] = None
    created_at: datetime

    class Config:
        from_attributes = True


class DesignerCompanyWithDesigner(DesignerCompany):
    designer: Designer
    effective_bonus_percent: float


class DesignerBonusUpdate(BaseModel):
    bonus_percent_override: Optional[float] = Field(default=None, ge=0, le=100)


# ─── Affiliate Link ──────────────────────────────────────────────────────────


class AffiliateLinkCreate(BaseModel):
    product_id: int


class AffiliateLink(BaseModel):
    id: int
    code: str
    product_id: int
    designer_id: int
    click_count: int
    created_at: datetime
    updated_at: Optional[datetime] = None

    class Config:
        from_attributes = True


class AffiliateLinkDetail(AffiliateLink):
    product: Product
    designer: Designer

    class Config:
        from_attributes = True


class AffiliateLinkWithRollup(AffiliateLinkDetail):
    visit_count: int = 0
    order_count: int = 0
    items_sold: int = 0
    revenue: float = 0.0
    designer_bonus_paid: float = 0.0
    platform_fee_paid: float = 0.0
    effective_bonus_percent: float


# ─── Order ───────────────────────────────────────────────────────────────────


class OrderBase(BaseModel):
    product_id: int
    designer_id: int
    quantity: int
    price_per_item: float
    client_phone: str
    client_name: Optional[str] = None
    note: Optional[str] = None


class OrderCreate(OrderBase):
    affiliate_link_id: Optional[int] = None
    is_manual: bool = False


class DesignerManualOrderCreate(BaseModel):
    product_id: int
    quantity: int
    price_per_item: float
    client_phone: str
    client_name: Optional[str] = None
    note: Optional[str] = None
    attachment_url: Optional[str] = None


class OrderUpdate(BaseModel):
    client_phone: Optional[str] = None
    client_name: Optional[str] = None
    note: Optional[str] = None
    quantity: Optional[int] = None


class Order(OrderBase):
    id: int
    affiliate_link_id: Optional[int] = None
    line_revenue: float
    designer_bonus_amount: float
    platform_fee_amount: float
    attachment_url: Optional[str] = None
    is_manual: bool
    status: OrderStatus
    created_at: datetime
    updated_at: Optional[datetime] = None

    class Config:
        from_attributes = True


class OrderWithDetails(Order):
    product: Optional[Product] = None
    designer: Optional[Designer] = None

    class Config:
        from_attributes = True


# ─── Analytics ───────────────────────────────────────────────────────────────


class AffiliateVisitRequest(BaseModel):
    code: str


class Analytics(BaseModel):
    id: int
    affiliate_link_id: int
    product_id: int
    company_id: int
    designer_id: int
    visit_count: int = 0
    order_count: int = 0
    items_sold: int = 0
    revenue: float = 0.0
    designer_bonus_paid: float = 0.0
    platform_fee_paid: float = 0.0
    created_at: datetime
    updated_at: Optional[datetime] = None
    designer: Optional[Designer] = None
    product: Optional[Product] = None

    class Config:
        from_attributes = True


class DesignerRanking(BaseModel):
    designer: Designer
    total_visits: int
    total_orders: int
    total_items_sold: int
    total_revenue: float
    total_designer_bonus: float
    total_platform_fee: float
    conversion_rate: float


class AnalyticsDashboard(BaseModel):
    total_visits: int
    total_orders: int
    total_items_sold: int
    total_revenue: float
    total_designer_bonus: float
    total_platform_fee: float
    designer_rankings: List[DesignerRanking]
    per_link: List[Analytics]


class CompanyProductAnalyticsRow(BaseModel):
    product_id: int
    product_name: str
    items_sold: int
    revenue: float
    designer_bonus: float
    platform_fee: float


class CompanyProductDesignerBreakdownRow(BaseModel):
    designer_id: int
    designer_name: str
    designer_email: str
    items_sold: int
    revenue: float
    designer_bonus: float
    platform_fee: float


class CompanyDesignerAnalyticsRow(BaseModel):
    designer_id: int
    designer_name: str
    designer_email: str
    items_sold: int
    revenue: float
    designer_bonus: float
    platform_fee: float


class CompanyDesignerProductBreakdownRow(BaseModel):
    product_id: int
    product_name: str
    items_sold: int
    revenue: float
    designer_bonus: float
    platform_fee: float


# ─── Auth / Token ─────────────────────────────────────────────────────────────


class Token(BaseModel):
    access_token: str
    token_type: str
    company_id: Optional[int] = None
    designer_id: Optional[int] = None
    admin_id: Optional[int] = None
    email: str
    name: str
    role: str


class TokenData(BaseModel):
    email: Optional[str] = None


class TelegramLink(BaseModel):
    telegram_chat_id: str


# ─── Admin ────────────────────────────────────────────────────────────────────


class AdminBase(BaseModel):
    email: EmailStr
    name: str


class AdminCreate(AdminBase):
    password: str

    @field_validator("password")
    @classmethod
    def password_strength(cls, v: str) -> str:
        return _validate_password_strength(v)


class Admin(AdminBase):
    id: int
    created_at: datetime
    updated_at: Optional[datetime] = None

    class Config:
        from_attributes = True
