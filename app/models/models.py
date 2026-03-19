from sqlalchemy import Column, String, Float, Integer, Boolean, DateTime, ForeignKey, Text, Date
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func
from app.database import Base
import uuid

class Hub(Base):
    __tablename__ = "hubs"

    id           = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    hub_code     = Column(String(50), unique=True, nullable=False, index=True)
    hub_name     = Column(String(200), nullable=True)
    sitting_location = Column(String(200), nullable=True)
    city         = Column(String(100), nullable=True, index=True)
    state        = Column(String(100), nullable=True, index=True)
    tier         = Column(String(50), nullable=True, index=True)
    facility_type = Column(String(50), nullable=True)
    site_category = Column(String(100), nullable=True)
    cost_centre  = Column(String(100), nullable=True)
    sub_cost_centre = Column(String(100), nullable=True)
    manager_name = Column(String(200), nullable=True)
    is_active    = Column(Boolean, default=True)
    created_at   = Column(DateTime(timezone=True), server_default=func.now())
    updated_at   = Column(DateTime(timezone=True), onupdate=func.now())

    expenses     = relationship("Expense", back_populates="hub", lazy="dynamic")
    aggregates   = relationship("HubAggregate", back_populates="hub", lazy="dynamic")
    sqft         = relationship("HubSqft", back_populates="hub", uselist=False)
    users        = relationship("User", back_populates="hub", lazy="dynamic")


class ExpenseCategory(Base):
    __tablename__ = "expense_categories"

    id           = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    category_key = Column(String(100), unique=True, nullable=False)
    display_name = Column(String(200), nullable=False)
    raw_chains   = Column(Text, nullable=True)  # comma-separated raw category_chain values that map here

    expenses     = relationship("Expense", back_populates="category", lazy="dynamic")


class Expense(Base):
    __tablename__ = "expenses"

    id              = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    hub_id          = Column(UUID(as_uuid=True), ForeignKey("hubs.id"), nullable=False, index=True)
    category_id     = Column(UUID(as_uuid=True), ForeignKey("expense_categories.id"), nullable=True, index=True)
    raw_category_chain = Column(String(300), nullable=True)
    employee_name   = Column(String(200), nullable=True)
    employee_id     = Column(String(50), nullable=True)
    role            = Column(String(200), nullable=True)
    band            = Column(String(20), nullable=True)
    expense_date    = Column(Date, nullable=True, index=True)
    expense_amount  = Column(Float, nullable=True)
    approved_amount = Column(Float, nullable=True)
    base_amount     = Column(Float, nullable=True)
    transaction_status = Column(String(50), nullable=True, index=True)
    report_id       = Column(String(100), nullable=True)
    report_name     = Column(String(300), nullable=True)
    description     = Column(Text, nullable=True)
    policy_violation = Column(Boolean, default=False)
    bill_available  = Column(String(10), nullable=True)
    vendor_name     = Column(String(200), nullable=True)
    attachment_url  = Column(Text, nullable=True)
    created_at      = Column(DateTime(timezone=True), server_default=func.now())

    hub             = relationship("Hub", back_populates="expenses")
    category        = relationship("ExpenseCategory", back_populates="expenses")


class HubAggregate(Base):
    """Pre-computed monthly roll-ups per hub per category — powers all charts"""
    __tablename__ = "hub_aggregates"

    id              = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    hub_id          = Column(UUID(as_uuid=True), ForeignKey("hubs.id"), nullable=False, index=True)
    category_id     = Column(UUID(as_uuid=True), ForeignKey("expense_categories.id"), nullable=True, index=True)
    month           = Column(Integer, nullable=False)   # 1-12
    year            = Column(Integer, nullable=False)   # 2025
    total_amount    = Column(Float, default=0.0)
    approved_amount = Column(Float, default=0.0)
    transaction_count = Column(Integer, default=0)
    policy_violation_count = Column(Integer, default=0)
    refreshed_at    = Column(DateTime(timezone=True), server_default=func.now())

    hub             = relationship("Hub", back_populates="aggregates")


class HubSqft(Base):
    __tablename__ = "hub_sqft"

    id           = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    hub_id       = Column(UUID(as_uuid=True), ForeignKey("hubs.id"), unique=True, nullable=False)
    sqft_area    = Column(Float, nullable=False)
    effective_from = Column(Date, nullable=True)
    source       = Column(String(100), default="manual_upload")
    created_at   = Column(DateTime(timezone=True), server_default=func.now())

    hub          = relationship("Hub", back_populates="sqft")


class User(Base):
    __tablename__ = "users"

    id           = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    hub_id       = Column(UUID(as_uuid=True), ForeignKey("hubs.id"), nullable=True)  # NULL = admin
    name         = Column(String(200), nullable=False)
    email        = Column(String(200), unique=True, nullable=False, index=True)
    hashed_password = Column(String(300), nullable=False)
    role         = Column(String(20), nullable=False, default="hi")  # "admin" | "hi"
    department   = Column(String(100), nullable=True)
    is_active    = Column(Boolean, default=True)
    last_login   = Column(DateTime(timezone=True), nullable=True)
    created_at   = Column(DateTime(timezone=True), server_default=func.now())

    hub          = relationship("Hub", back_populates="users")


class ETLLog(Base):
    """Track every ETL run"""
    __tablename__ = "etl_logs"

    id           = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    started_at   = Column(DateTime(timezone=True), server_default=func.now())
    finished_at  = Column(DateTime(timezone=True), nullable=True)
    status       = Column(String(20), default="running")  # running | success | failed
    rows_processed = Column(Integer, default=0)
    rows_inserted  = Column(Integer, default=0)
    error_message  = Column(Text, nullable=True)
    triggered_by   = Column(String(50), default="scheduler")  # scheduler | manual | api
