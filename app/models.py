from sqlalchemy import (
    Column, Integer, String, Float, ForeignKey,
    Enum as SQLEnum, DateTime, Text, Boolean, UniqueConstraint,
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
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())

    products = relationship("Product", back_populates="company")
    blogger_invites = relationship("BloggerInvite", back_populates="company")
    blogger_companies = relationship("BloggerCompany", back_populates="company")


class Product(Base):
    __tablename__ = "products"

    id = Column(Integer, primary_key=True, index=True)
    company_id = Column(Integer, ForeignKey("companies.id"))
    name = Column(String, index=True)
    description = Column(Text, nullable=True)
    blogger_task_description = Column(Text, nullable=True)
    price = Column(Float)
    commission_rate = Column(Float, default=0.0)  # percentage, e.g. 10.0 = 10%
    image_url = Column(String, nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())

    company = relationship("Company", back_populates="products")
    orders = relationship("Order", back_populates="product")
    analytics = relationship("Analytics", back_populates="product")
    affiliate_links = relationship("AffiliateLink", back_populates="product")


class Blogger(Base):
    __tablename__ = "bloggers"

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

    orders = relationship("Order", back_populates="blogger")
    analytics = relationship("Analytics", back_populates="blogger")
    affiliate_links = relationship("AffiliateLink", back_populates="blogger")
    blogger_companies = relationship("BloggerCompany", back_populates="blogger")


class BloggerInvite(Base):
    """Invite token sent by a company to a blogger's email."""
    __tablename__ = "blogger_invites"

    id = Column(Integer, primary_key=True, index=True)
    company_id = Column(Integer, ForeignKey("companies.id"), nullable=False)
    blogger_email = Column(String, nullable=False, index=True)
    token = Column(String, unique=True, index=True, nullable=False)
    status = Column(SQLEnum(InviteStatus), default=InviteStatus.PENDING)
    expires_at = Column(DateTime(timezone=True), nullable=False)
    created_at = Column(DateTime(timezone=True), server_default=func.now())

    company = relationship("Company", back_populates="blogger_invites")


class BloggerCompany(Base):
    """Junction table: a blogger can work with many companies."""
    __tablename__ = "blogger_companies"

    id = Column(Integer, primary_key=True, index=True)
    blogger_id = Column(Integer, ForeignKey("bloggers.id"), nullable=False)
    company_id = Column(Integer, ForeignKey("companies.id"), nullable=False)
    created_at = Column(DateTime(timezone=True), server_default=func.now())

    __table_args__ = (UniqueConstraint("blogger_id", "company_id", name="uq_blogger_company"),)

    blogger = relationship("Blogger", back_populates="blogger_companies")
    company = relationship("Company", back_populates="blogger_companies")


class AffiliateLink(Base):
    __tablename__ = "affiliate_links"

    id = Column(Integer, primary_key=True, index=True)
    code = Column(String, unique=True, index=True)
    product_id = Column(Integer, ForeignKey("products.id"))
    blogger_id = Column(Integer, ForeignKey("bloggers.id"))
    click_count = Column(Integer, default=0)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())

    product = relationship("Product", back_populates="affiliate_links")
    blogger = relationship("Blogger", back_populates="affiliate_links")
    orders = relationship("Order", back_populates="affiliate_link")


class Order(Base):
    __tablename__ = "orders"

    id = Column(Integer, primary_key=True, index=True)
    product_id = Column(Integer, ForeignKey("products.id"))
    blogger_id = Column(Integer, ForeignKey("bloggers.id"))
    affiliate_link_id = Column(Integer, ForeignKey("affiliate_links.id"), nullable=True)
    quantity = Column(Integer)
    price_per_item = Column(Float)
    commission_amount = Column(Float, default=0.0)
    client_phone = Column(String)
    client_name = Column(String, nullable=True)
    note = Column(Text, nullable=True)
    is_manual = Column(Boolean, default=False)
    status = Column(SQLEnum(OrderStatus), default=OrderStatus.WAITING)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())

    product = relationship("Product", back_populates="orders")
    blogger = relationship("Blogger", back_populates="orders")
    affiliate_link = relationship("AffiliateLink", back_populates="orders")


class Analytics(Base):
    __tablename__ = "analytics"

    id = Column(Integer, primary_key=True, index=True)
    product_id = Column(Integer, ForeignKey("products.id"))
    blogger_id = Column(Integer, ForeignKey("bloggers.id"))
    visit_count = Column(Integer, default=0)
    order_count = Column(Integer, default=0)
    items_sold = Column(Integer, default=0)
    revenue = Column(Float, default=0.0)
    commission_paid = Column(Float, default=0.0)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())

    product = relationship("Product", back_populates="analytics")
    blogger = relationship("Blogger", back_populates="analytics")


class Admin(Base):
    __tablename__ = "admins"

    id = Column(Integer, primary_key=True, index=True)
    email = Column(String, unique=True, index=True)
    hashed_password = Column(String)
    name = Column(String)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())
