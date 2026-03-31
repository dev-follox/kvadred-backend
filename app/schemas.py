import re
from pydantic import BaseModel, EmailStr, field_validator
from typing import Optional, List, Dict, Any
from datetime import datetime
from .models import OrderStatus, InviteStatus


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

    @field_validator("password")
    @classmethod
    def password_strength(cls, v: str) -> str:
        return _validate_password_strength(v)


class CompanyUpdate(BaseModel):
    full_name: Optional[str] = None
    phone_number: Optional[str] = None
    company_name: Optional[str] = None
    description: Optional[str] = None


class PasswordUpdate(BaseModel):
    current_password: str
    new_password: str

    @field_validator("new_password")
    @classmethod
    def new_password_strength(cls, v: str) -> str:
        return _validate_password_strength(v)


class Company(CompanyBase):
    id: int
    telegram_chat_id: Optional[str] = None
    created_at: datetime
    updated_at: Optional[datetime] = None

    class Config:
        from_attributes = True


# ─── Product ────────────────────────────────────────────────────────────────

class ProductBase(BaseModel):
    name: str
    description: Optional[str] = None
    price: float
    commission_rate: float = 0.0
    image_url: Optional[str] = None
    blogger_task_description: Optional[str] = None


class ProductCreate(ProductBase):
    company_id: int


class ProductUpdate(BaseModel):
    name: Optional[str] = None
    description: Optional[str] = None
    price: Optional[float] = None
    commission_rate: Optional[float] = None
    image_url: Optional[str] = None
    blogger_task_description: Optional[str] = None


class Product(ProductBase):
    id: int
    company_id: int
    created_at: datetime
    updated_at: Optional[datetime] = None

    class Config:
        from_attributes = True


# ─── Blogger ─────────────────────────────────────────────────────────────────

class BloggerBase(BaseModel):
    name: str
    email: EmailStr
    bio: Optional[str] = None


class BloggerCreate(BloggerBase):
    password: str

    @field_validator("password")
    @classmethod
    def password_strength(cls, v: str) -> str:
        return _validate_password_strength(v)


class BloggerUpdate(BaseModel):
    name: Optional[str] = None
    bio: Optional[str] = None


class Blogger(BloggerBase):
    id: int
    telegram_chat_id: Optional[str] = None
    created_at: datetime
    updated_at: Optional[datetime] = None

    class Config:
        from_attributes = True


# ─── Blogger Invite ──────────────────────────────────────────────────────────

class BloggerInviteCreate(BaseModel):
    blogger_email: EmailStr


class BloggerInviteAccept(BaseModel):
    token: str
    name: str
    password: str

    @field_validator("password")
    @classmethod
    def password_strength(cls, v: str) -> str:
        return _validate_password_strength(v)


class BloggerInvite(BaseModel):
    id: int
    company_id: int
    blogger_email: str
    token: str
    status: InviteStatus
    expires_at: datetime
    created_at: datetime

    class Config:
        from_attributes = True


# ─── BloggerCompany ──────────────────────────────────────────────────────────

class BloggerCompany(BaseModel):
    id: int
    blogger_id: int
    company_id: int
    created_at: datetime

    class Config:
        from_attributes = True


# ─── Affiliate Link ──────────────────────────────────────────────────────────

class AffiliateLinkBase(BaseModel):
    product_id: int
    blogger_id: int


class AffiliateLinkCreate(AffiliateLinkBase):
    pass


class AffiliateLink(AffiliateLinkBase):
    id: int
    code: str
    click_count: int
    created_at: datetime
    updated_at: Optional[datetime] = None

    class Config:
        from_attributes = True


class AffiliateLinkDetail(AffiliateLink):
    product: Product
    blogger: Blogger

    class Config:
        from_attributes = True


# ─── Order ───────────────────────────────────────────────────────────────────

class OrderBase(BaseModel):
    product_id: int
    blogger_id: int
    quantity: int
    price_per_item: float
    client_phone: str
    client_name: Optional[str] = None
    note: Optional[str] = None


class OrderCreate(OrderBase):
    affiliate_link_id: Optional[int] = None
    is_manual: bool = False


class OrderUpdate(BaseModel):
    client_phone: Optional[str] = None
    client_name: Optional[str] = None
    note: Optional[str] = None
    quantity: Optional[int] = None


class Order(OrderBase):
    id: int
    affiliate_link_id: Optional[int] = None
    commission_amount: float
    is_manual: bool
    status: OrderStatus
    created_at: datetime
    updated_at: Optional[datetime] = None

    class Config:
        from_attributes = True


class OrderWithDetails(Order):
    product: Optional[Product] = None
    blogger: Optional[Blogger] = None

    class Config:
        from_attributes = True


# ─── Analytics ───────────────────────────────────────────────────────────────

class AnalyticsBase(BaseModel):
    product_id: int
    blogger_id: int
    visit_count: int = 0
    order_count: int = 0
    items_sold: int = 0
    revenue: float = 0.0
    commission_paid: float = 0.0


class Analytics(AnalyticsBase):
    id: int
    created_at: datetime
    updated_at: Optional[datetime] = None
    blogger: Optional[Blogger] = None
    product: Optional[Product] = None

    class Config:
        from_attributes = True


class BloggerRanking(BaseModel):
    blogger: Blogger
    total_visits: int
    total_orders: int
    total_items_sold: int
    total_revenue: float
    total_commission: float
    conversion_rate: float


class AnalyticsDashboard(BaseModel):
    total_visits: int
    total_orders: int
    total_items_sold: int
    total_revenue: float
    total_commission_paid: float
    blogger_rankings: List[BloggerRanking]
    per_product: List[Analytics]


# ─── Auth / Token ─────────────────────────────────────────────────────────────

class Token(BaseModel):
    access_token: str
    token_type: str
    company_id: Optional[int] = None
    blogger_id: Optional[int] = None
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
