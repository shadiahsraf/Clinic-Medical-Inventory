"""SQLAlchemy schema. Money = integer e4 units (see money.py). Quantities = integers."""
from datetime import datetime, date
from sqlalchemy import (String, Integer, Text, Boolean, ForeignKey, CheckConstraint,
                        UniqueConstraint, Index, Date, DateTime, text)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


def now() -> datetime:
    return datetime.now().replace(microsecond=0)


class Base(DeclarativeBase):
    pass


class Setting(Base):
    __tablename__ = "settings"
    key: Mapped[str] = mapped_column(String(80), primary_key=True)
    value: Mapped[str] = mapped_column(Text)


class Counter(Base):
    """Monotonic counters for item codes / document numbers (never reused)."""
    __tablename__ = "counters"
    name: Mapped[str] = mapped_column(String(40), primary_key=True)
    value: Mapped[int] = mapped_column(Integer, default=0)


class Role(Base):
    __tablename__ = "roles"
    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(60), unique=True)
    permissions: Mapped[list["RolePermission"]] = relationship(cascade="all, delete-orphan", lazy="selectin")


class RolePermission(Base):
    __tablename__ = "role_permissions"
    role_id: Mapped[int] = mapped_column(ForeignKey("roles.id"), primary_key=True)
    permission: Mapped[str] = mapped_column(String(60), primary_key=True)


class User(Base):
    __tablename__ = "users"
    id: Mapped[int] = mapped_column(primary_key=True)
    username: Mapped[str] = mapped_column(String(60), unique=True)
    display_name: Mapped[str] = mapped_column(String(120))
    password_hash: Mapped[str] = mapped_column(String(255))
    role_id: Mapped[int] = mapped_column(ForeignKey("roles.id"))
    active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=now)
    role: Mapped[Role] = relationship(lazy="selectin")

    def has(self, perm: str) -> bool:
        return self.active and any(p.permission == perm for p in self.role.permissions)


class Category(Base):
    __tablename__ = "categories"
    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(120), unique=True)


class Unit(Base):
    __tablename__ = "units"
    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(60), unique=True)


class Item(Base):
    __tablename__ = "items"
    id: Mapped[int] = mapped_column(primary_key=True)
    code: Mapped[str] = mapped_column(String(20), unique=True)
    name: Mapped[str] = mapped_column(String(200), index=True)
    description: Mapped[str | None] = mapped_column(Text)
    category_id: Mapped[int | None] = mapped_column(ForeignKey("categories.id"))
    unit_id: Mapped[int] = mapped_column(ForeignKey("units.id"))
    pack_unit_id: Mapped[int | None] = mapped_column(ForeignKey("units.id"))
    pack_factor: Mapped[int | None] = mapped_column(Integer)
    min_stock: Mapped[int] = mapped_column(Integer, default=0)
    target_stock: Mapped[int | None] = mapped_column(Integer)
    barcode: Mapped[str | None] = mapped_column(String(64), unique=True)
    active: Mapped[bool] = mapped_column(Boolean, default=True)
    notes: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=now)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=now, onupdate=now)
    category: Mapped[Category | None] = relationship(lazy="selectin")
    unit: Mapped[Unit] = relationship(foreign_keys=[unit_id], lazy="selectin")
    __table_args__ = (CheckConstraint("min_stock >= 0"),
                      CheckConstraint("pack_factor IS NULL OR pack_factor > 0"))


class Supplier(Base):
    __tablename__ = "suppliers"
    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(200), unique=True)
    phone: Mapped[str | None] = mapped_column(String(40))
    address: Mapped[str | None] = mapped_column(Text)
    contact_person: Mapped[str | None] = mapped_column(String(120))
    notes: Mapped[str | None] = mapped_column(Text)
    active: Mapped[bool] = mapped_column(Boolean, default=True)


class Department(Base):
    __tablename__ = "departments"
    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(200), unique=True)
    dept_type: Mapped[str | None] = mapped_column(String(80))
    location: Mapped[str | None] = mapped_column(String(120))
    doctor: Mapped[str | None] = mapped_column(String(120))
    contact: Mapped[str | None] = mapped_column(String(120))
    notes: Mapped[str | None] = mapped_column(Text)
    active: Mapped[bool] = mapped_column(Boolean, default=True)


# ---------------- Incoming ----------------
class IncomingDoc(Base):
    __tablename__ = "incoming_docs"
    id: Mapped[int] = mapped_column(primary_key=True)
    number: Mapped[str] = mapped_column(String(30), unique=True)
    doc_date: Mapped[date] = mapped_column(Date)
    source_type: Mapped[str] = mapped_column(String(12))  # purchase | donation
    supplier_id: Mapped[int | None] = mapped_column(ForeignKey("suppliers.id"))
    donor_name: Mapped[str | None] = mapped_column(String(200))
    reference: Mapped[str | None] = mapped_column(String(80))
    status: Mapped[str] = mapped_column(String(12), default="draft")  # draft|confirmed|cancelled
    notes: Mapped[str | None] = mapped_column(Text)
    cancel_reason: Mapped[str | None] = mapped_column(Text)
    created_by: Mapped[int] = mapped_column(ForeignKey("users.id"))
    created_at: Mapped[datetime] = mapped_column(DateTime, default=now)
    confirmed_at: Mapped[datetime | None] = mapped_column(DateTime)
    lines: Mapped[list["IncomingLine"]] = relationship(cascade="all, delete-orphan", lazy="selectin")
    __table_args__ = (CheckConstraint("source_type IN ('purchase','donation')"),
                      CheckConstraint("status IN ('draft','confirmed','cancelled')"))


class IncomingLine(Base):
    __tablename__ = "incoming_lines"
    id: Mapped[int] = mapped_column(primary_key=True)
    doc_id: Mapped[int] = mapped_column(ForeignKey("incoming_docs.id"))
    item_id: Mapped[int] = mapped_column(ForeignKey("items.id"))
    quantity: Mapped[int] = mapped_column(Integer)
    unit_cost: Mapped[int] = mapped_column(Integer)      # purchase cost, or donation estimated value
    expiry_date: Mapped[date | None] = mapped_column(Date)
    __table_args__ = (CheckConstraint("quantity > 0"), CheckConstraint("unit_cost >= 0"))


class Batch(Base):
    __tablename__ = "batches"
    id: Mapped[int] = mapped_column(primary_key=True)
    item_id: Mapped[int] = mapped_column(ForeignKey("items.id"), index=True)
    received_date: Mapped[date] = mapped_column(Date)
    received_seq: Mapped[int] = mapped_column(Integer)   # FIFO tiebreak
    original_qty: Mapped[int] = mapped_column(Integer)
    remaining_qty: Mapped[int] = mapped_column(Integer)
    unit_cost: Mapped[int] = mapped_column(Integer)
    source_line_id: Mapped[int | None] = mapped_column(ForeignKey("incoming_lines.id"))
    source_kind: Mapped[str] = mapped_column(String(12), default="incoming")  # incoming|adjustment
    expiry_date: Mapped[date | None] = mapped_column(Date)
    status: Mapped[str] = mapped_column(String(10), default="active")  # active|depleted|cancelled
    __table_args__ = (CheckConstraint("remaining_qty >= 0"),
                      CheckConstraint("remaining_qty <= original_qty"),
                      Index("ix_batch_fifo", "item_id", "received_date", "received_seq"))


class StockMovement(Base):
    """Immutable ledger. Sum(qty_delta) per batch == batch.remaining_qty - always."""
    __tablename__ = "stock_movements"
    id: Mapped[int] = mapped_column(primary_key=True)
    ts: Mapped[datetime] = mapped_column(DateTime, default=now, index=True)
    move_date: Mapped[date] = mapped_column(Date, index=True)
    item_id: Mapped[int] = mapped_column(ForeignKey("items.id"), index=True)
    batch_id: Mapped[int] = mapped_column(ForeignKey("batches.id"), index=True)
    kind: Mapped[str] = mapped_column(String(20))
    # incoming, issue, return, damage, adjustment, incoming_reversal
    qty_delta: Mapped[int] = mapped_column(Integer)
    unit_cost: Mapped[int] = mapped_column(Integer)
    value_delta: Mapped[int] = mapped_column(Integer)   # qty_delta * unit_cost
    doc_type: Mapped[str] = mapped_column(String(20))
    doc_id: Mapped[int] = mapped_column(Integer)
    department_id: Mapped[int | None] = mapped_column(ForeignKey("departments.id"))
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"))


# ---------------- Payments / cash ----------------
class SupplierPayment(Base):
    __tablename__ = "supplier_payments"
    id: Mapped[int] = mapped_column(primary_key=True)
    doc_id: Mapped[int] = mapped_column(ForeignKey("incoming_docs.id"), index=True)
    pay_date: Mapped[date] = mapped_column(Date)
    amount: Mapped[int] = mapped_column(Integer)
    method: Mapped[str | None] = mapped_column(String(40))
    notes: Mapped[str | None] = mapped_column(Text)
    created_by: Mapped[int] = mapped_column(ForeignKey("users.id"))
    created_at: Mapped[datetime] = mapped_column(DateTime, default=now)
    __table_args__ = (CheckConstraint("amount > 0"),)


class CashMovement(Base):
    """Cash-movement log ONLY (not a double-entry ledger). Estimated donation
    values never appear here."""
    __tablename__ = "cash_movements"
    id: Mapped[int] = mapped_column(primary_key=True)
    move_date: Mapped[date] = mapped_column(Date, index=True)
    kind: Mapped[str] = mapped_column(String(20))  # supplier_payment | cash_donation
    amount: Mapped[int] = mapped_column(Integer)   # +in / -out
    ref_type: Mapped[str | None] = mapped_column(String(20))
    ref_id: Mapped[int | None] = mapped_column(Integer)
    donor_name: Mapped[str | None] = mapped_column(String(200))
    notes: Mapped[str | None] = mapped_column(Text)
    created_by: Mapped[int] = mapped_column(ForeignKey("users.id"))


# ---------------- Issues ----------------
class IssueDoc(Base):
    __tablename__ = "issue_docs"
    id: Mapped[int] = mapped_column(primary_key=True)
    number: Mapped[str] = mapped_column(String(30), unique=True)
    idempotency_key: Mapped[str | None] = mapped_column(String(64), unique=True)
    department_id: Mapped[int] = mapped_column(ForeignKey("departments.id"))
    recipient: Mapped[str | None] = mapped_column(String(120))
    issued_at: Mapped[datetime] = mapped_column(DateTime, default=now)
    reference: Mapped[str | None] = mapped_column(String(80))
    notes: Mapped[str | None] = mapped_column(Text)
    status: Mapped[str] = mapped_column(String(12), default="confirmed")
    created_by: Mapped[int] = mapped_column(ForeignKey("users.id"))
    total_cost: Mapped[int] = mapped_column(Integer, default=0)
    department: Mapped[Department] = relationship(lazy="selectin")
    lines: Mapped[list["IssueLine"]] = relationship(cascade="all, delete-orphan", lazy="selectin")


class IssueLine(Base):
    __tablename__ = "issue_lines"
    id: Mapped[int] = mapped_column(primary_key=True)
    doc_id: Mapped[int] = mapped_column(ForeignKey("issue_docs.id"))
    item_id: Mapped[int] = mapped_column(ForeignKey("items.id"))
    quantity: Mapped[int] = mapped_column(Integer)
    cost: Mapped[int] = mapped_column(Integer)
    item: Mapped[Item] = relationship(lazy="selectin")
    allocations: Mapped[list["IssueAllocation"]] = relationship(cascade="all, delete-orphan", lazy="selectin")
    __table_args__ = (CheckConstraint("quantity > 0"),)


class IssueAllocation(Base):
    __tablename__ = "issue_allocations"
    id: Mapped[int] = mapped_column(primary_key=True)
    line_id: Mapped[int] = mapped_column(ForeignKey("issue_lines.id"), index=True)
    batch_id: Mapped[int] = mapped_column(ForeignKey("batches.id"))
    quantity: Mapped[int] = mapped_column(Integer)
    unit_cost: Mapped[int] = mapped_column(Integer)
    returned_qty: Mapped[int] = mapped_column(Integer, default=0)
    __table_args__ = (CheckConstraint("quantity > 0"),
                      CheckConstraint("returned_qty >= 0 AND returned_qty <= quantity"))


# ---------------- Returns / damage ----------------
class ReturnRecord(Base):
    __tablename__ = "returns"
    id: Mapped[int] = mapped_column(primary_key=True)
    number: Mapped[str] = mapped_column(String(30), unique=True)
    issue_line_id: Mapped[int] = mapped_column(ForeignKey("issue_lines.id"))
    department_id: Mapped[int] = mapped_column(ForeignKey("departments.id"))
    item_id: Mapped[int] = mapped_column(ForeignKey("items.id"))
    quantity: Mapped[int] = mapped_column(Integer)
    condition: Mapped[str] = mapped_column(String(12))  # reusable | damaged
    reason: Mapped[str | None] = mapped_column(Text)
    status: Mapped[str] = mapped_column(String(12), default="pending")  # pending|approved|rejected
    return_date: Mapped[date] = mapped_column(Date)
    created_by: Mapped[int] = mapped_column(ForeignKey("users.id"))
    approved_by: Mapped[int | None] = mapped_column(ForeignKey("users.id"))
    cost: Mapped[int] = mapped_column(Integer, default=0)
    __table_args__ = (CheckConstraint("quantity > 0"),
                      CheckConstraint("condition IN ('reusable','damaged')"))


class DamageRecord(Base):
    __tablename__ = "damage_records"
    id: Mapped[int] = mapped_column(primary_key=True)
    item_id: Mapped[int] = mapped_column(ForeignKey("items.id"))
    batch_id: Mapped[int] = mapped_column(ForeignKey("batches.id"))
    quantity: Mapped[int] = mapped_column(Integer)
    reason_type: Mapped[str] = mapped_column(String(12))  # damaged|lost|expired|other
    reason: Mapped[str | None] = mapped_column(Text)
    event_date: Mapped[date] = mapped_column(Date)
    reported_by: Mapped[int] = mapped_column(ForeignKey("users.id"))
    approved_by: Mapped[int | None] = mapped_column(ForeignKey("users.id"))
    cost: Mapped[int] = mapped_column(Integer)
    __table_args__ = (CheckConstraint("quantity > 0"),)


# ---------------- Stocktaking ----------------
class StocktakeSession(Base):
    __tablename__ = "stocktake_sessions"
    id: Mapped[int] = mapped_column(primary_key=True)
    number: Mapped[str] = mapped_column(String(30), unique=True)
    status: Mapped[str] = mapped_column(String(12), default="open")  # open|submitted|approved|cancelled
    created_by: Mapped[int] = mapped_column(ForeignKey("users.id"))
    approved_by: Mapped[int | None] = mapped_column(ForeignKey("users.id"))
    created_at: Mapped[datetime] = mapped_column(DateTime, default=now)
    approved_at: Mapped[datetime | None] = mapped_column(DateTime)
    notes: Mapped[str | None] = mapped_column(Text)
    lines: Mapped[list["StocktakeLine"]] = relationship(cascade="all, delete-orphan", lazy="selectin")


class StocktakeLine(Base):
    __tablename__ = "stocktake_lines"
    id: Mapped[int] = mapped_column(primary_key=True)
    session_id: Mapped[int] = mapped_column(ForeignKey("stocktake_sessions.id"))
    item_id: Mapped[int] = mapped_column(ForeignKey("items.id"))
    book_qty: Mapped[int] = mapped_column(Integer)
    counted_qty: Mapped[int | None] = mapped_column(Integer)
    explanation: Mapped[str | None] = mapped_column(Text)
    cost_effect: Mapped[int | None] = mapped_column(Integer)  # set on approval
    __table_args__ = (UniqueConstraint("session_id", "item_id"),)


# ---------------- Alerts / audit / backups ----------------
class Alert(Base):
    __tablename__ = "alerts"
    id: Mapped[int] = mapped_column(primary_key=True)
    item_id: Mapped[int] = mapped_column(ForeignKey("items.id"), index=True)
    kind: Mapped[str] = mapped_column(String(8))     # low | out
    status: Mapped[str] = mapped_column(String(14), default="new")  # new|acknowledged|resolved
    qty_at_creation: Mapped[int] = mapped_column(Integer)
    min_at_creation: Mapped[int] = mapped_column(Integer)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=now)
    acknowledged_at: Mapped[datetime | None] = mapped_column(DateTime)
    acknowledged_by: Mapped[int | None] = mapped_column(ForeignKey("users.id"))
    resolved_at: Mapped[datetime | None] = mapped_column(DateTime)
    desktop_notified: Mapped[bool] = mapped_column(Boolean, default=False)
    item: Mapped[Item] = relationship(lazy="selectin")
    __table_args__ = (
        # at most ONE unresolved alert per item => no duplicates on refresh
        Index("ux_one_open_alert", "item_id", unique=True, sqlite_where=text("status != 'resolved'")),
    )


class AuditLog(Base):
    __tablename__ = "audit_log"
    id: Mapped[int] = mapped_column(primary_key=True)
    ts: Mapped[datetime] = mapped_column(DateTime, default=now, index=True)
    user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"))
    action: Mapped[str] = mapped_column(String(60))
    entity_type: Mapped[str] = mapped_column(String(40))
    entity_id: Mapped[str | None] = mapped_column(String(40))
    old_value: Mapped[str | None] = mapped_column(Text)
    new_value: Mapped[str | None] = mapped_column(Text)
    reason: Mapped[str | None] = mapped_column(Text)


class BackupMeta(Base):
    __tablename__ = "backup_meta"
    id: Mapped[int] = mapped_column(primary_key=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=now)
    path: Mapped[str] = mapped_column(Text)
    kind: Mapped[str] = mapped_column(String(12))  # manual|auto|safety
    status: Mapped[str] = mapped_column(String(12))  # ok|failed
    size_bytes: Mapped[int | None] = mapped_column(Integer)
    created_by: Mapped[int | None] = mapped_column(ForeignKey("users.id"))
