from sqlalchemy import (
    Column,
    Integer,
    String,
    Float,
    ForeignKey,
    Enum as SQLEnum,
    DateTime,
    Text,
    Boolean,
    UniqueConstraint,
)
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func
import enum
from .database import Base


class OrderStatus(str, enum.Enum):
    WAITING = "waiting_to_process"
    PROCESSED = "processed"
    CANCELLED = "cancelled"


class InviteStatus(str, enum.Enum):
    PENDING = "pending"
    ACCEPTED = "accepted"
    EXPIRED = "expired"


class Company(Base):
    __tablename__ = "companies"

    id = Column(Integer, primary_key=True, index=True)
    full_name = Column(String, index=True)
    email = Column(String, unique=True, index=True)
    phone_number = Column(String, nullable=True)
    company_name = Column(String, index=True)
    description = Column(Text, nullable=True)
    hashed_password = Column(String, nullable=True)
    telegram_chat_id = Column(String, nullable=True)
    oauth_provider = Column(String, nullable=True)
    oauth_provider_id = Column(String, nullable=True)
    default_designer_bonus_percent = Column(Float, nullable=False, default=10.0)
    subscription_expires_at = Column(DateTime(timezone=True), nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())

    products = relationship("Product", back_populates="company")
    designer_invites = relationship("DesignerInvite", back_populates="company")
    designer_companies = relationship("DesignerCompany", back_populates="company")


class Product(Base):
    __tablename__ = "products"

    id = Column(Integer, primary_key=True, index=True)
    company_id = Column(Integer, ForeignKey("companies.id"))
    name = Column(String, index=True)
    description = Column(Text, nullable=True)
    designer_task_description = Column(Text, nullable=True)
    price = Column(Float)
    image_url = Column(String, nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())

    company = relationship("Company", back_populates="products")
    orders = relationship("Order", back_populates="product")
    analytics = relationship("Analytics", back_populates="product")
    affiliate_links = relationship("AffiliateLink", back_populates="product")


class Designer(Base):
    __tablename__ = "designers"

    id = Column(Integer, primary_key=True, index=True)
    name = Column(String, index=True)
    email = Column(String, unique=True, index=True)
    hashed_password = Column(String, nullable=True)
    bio = Column(Text, nullable=True)
    telegram_chat_id = Column(String, nullable=True)
    oauth_provider = Column(String, nullable=True)
    oauth_provider_id = Column(String, nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())

    orders = relationship("Order", back_populates="designer")
    analytics = relationship("Analytics", back_populates="designer")
    affiliate_links = relationship("AffiliateLink", back_populates="designer")
    designer_companies = relationship("DesignerCompany", back_populates="designer")


class DesignerInvite(Base):
    __tablename__ = "designer_invites"

    id = Column(Integer, primary_key=True, index=True)
    company_id = Column(Integer, ForeignKey("companies.id"), nullable=False)
    designer_email = Column(String, nullable=False, index=True)
    token = Column(String, unique=True, index=True, nullable=False)
    status = Column(SQLEnum(InviteStatus), default=InviteStatus.PENDING)
    expires_at = Column(DateTime(timezone=True), nullable=False)
    created_at = Column(DateTime(timezone=True), server_default=func.now())

    company = relationship("Company", back_populates="designer_invites")


class DesignerCompany(Base):
    __tablename__ = "designer_companies"

    id = Column(Integer, primary_key=True, index=True)
    designer_id = Column(Integer, ForeignKey("designers.id"), nullable=False)
    company_id = Column(Integer, ForeignKey("companies.id"), nullable=False)
    bonus_percent_override = Column(Float, nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())

    __table_args__ = (UniqueConstraint("designer_id", "company_id", name="uq_designer_company"),)

    designer = relationship("Designer", back_populates="designer_companies")
    company = relationship("Company", back_populates="designer_companies")


class AffiliateLink(Base):
    __tablename__ = "affiliate_links"

    id = Column(Integer, primary_key=True, index=True)
    code = Column(String, unique=True, index=True)
    product_id = Column(Integer, ForeignKey("products.id"))
    designer_id = Column(Integer, ForeignKey("designers.id"))
    click_count = Column(Integer, default=0)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())

    __table_args__ = (UniqueConstraint("designer_id", "product_id", name="uq_affiliate_designer_product"),)

    product = relationship("Product", back_populates="affiliate_links")
    designer = relationship("Designer", back_populates="affiliate_links")
    orders = relationship("Order", back_populates="affiliate_link")
    rollup = relationship("Analytics", back_populates="affiliate_link", uselist=False)


class Order(Base):
    __tablename__ = "orders"

    id = Column(Integer, primary_key=True, index=True)
    product_id = Column(Integer, ForeignKey("products.id"))
    designer_id = Column(Integer, ForeignKey("designers.id"))
    affiliate_link_id = Column(Integer, ForeignKey("affiliate_links.id"), nullable=True)
    quantity = Column(Integer)
    price_per_item = Column(Float)
    line_revenue = Column(Float, default=0.0)
    designer_bonus_amount = Column(Float, default=0.0)
    platform_fee_amount = Column(Float, default=0.0)
    client_phone = Column(String)
    client_name = Column(String, nullable=True)
    note = Column(Text, nullable=True)
    attachment_url = Column(String, nullable=True)
    is_manual = Column(Boolean, default=False)
    status = Column(SQLEnum(OrderStatus), default=OrderStatus.WAITING)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())

    product = relationship("Product", back_populates="orders")
    designer = relationship("Designer", back_populates="orders")
    affiliate_link = relationship("AffiliateLink", back_populates="orders")


class Analytics(Base):
    """Per-affiliate-link rollup (denormalized product/company/designer for filtering)."""

    __tablename__ = "analytics"

    id = Column(Integer, primary_key=True, index=True)
    affiliate_link_id = Column(Integer, ForeignKey("affiliate_links.id"), nullable=False, unique=True)
    product_id = Column(Integer, ForeignKey("products.id"), nullable=False)
    company_id = Column(Integer, ForeignKey("companies.id"), nullable=False)
    designer_id = Column(Integer, ForeignKey("designers.id"), nullable=False)
    visit_count = Column(Integer, default=0)
    order_count = Column(Integer, default=0)
    items_sold = Column(Integer, default=0)
    revenue = Column(Float, default=0.0)
    designer_bonus_paid = Column(Float, default=0.0)
    platform_fee_paid = Column(Float, default=0.0)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())

    product = relationship("Product", back_populates="analytics")
    designer = relationship("Designer", back_populates="analytics")
    affiliate_link = relationship("AffiliateLink", back_populates="rollup")


class Admin(Base):
    __tablename__ = "admins"

    id = Column(Integer, primary_key=True, index=True)
    email = Column(String, unique=True, index=True)
    hashed_password = Column(String)
    name = Column(String)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())
