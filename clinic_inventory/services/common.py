import json
from datetime import date, datetime
from sqlalchemy import select, func
from sqlalchemy.orm import Session
from ..errors import PermissionDenied, AppError
from ..models import AuditLog, Counter, Batch, User


def require(user: User, perm: str):
    if user is None or not user.has(perm):
        raise PermissionDenied()


def next_number(s: Session, name: str, prefix: str, width: int = 6) -> str:
    """Monotonic, never reused (even if the document is cancelled)."""
    c = s.get(Counter, name)
    if c is None:
        c = Counter(name=name, value=0)
        s.add(c)
    c.value += 1
    s.flush()
    return f"{prefix}-{c.value:0{width}d}"


def _ser(v):
    return json.dumps(v, ensure_ascii=False, default=str) if v is not None else None


def audit(s: Session, user: User | None, action: str, entity_type: str, entity_id=None,
          old=None, new=None, reason: str | None = None):
    s.add(AuditLog(user_id=user.id if user else None, action=action, entity_type=entity_type,
                   entity_id=str(entity_id) if entity_id is not None else None,
                   old_value=_ser(old), new_value=_ser(new), reason=reason))


def available_qty(s: Session, item_id: int, today: date | None = None) -> int:
    """USABLE quantity: active batches that are not expired."""
    today = today or date.today()
    return s.scalar(select(func.coalesce(func.sum(Batch.remaining_qty), 0)).where(
        Batch.item_id == item_id, Batch.status == "active",
        (Batch.expiry_date.is_(None)) | (Batch.expiry_date >= today))) or 0


def onhand_qty(s: Session, item_id: int) -> int:
    """Physical quantity on shelf (usable + expired-but-not-yet-written-off)."""
    return s.scalar(select(func.coalesce(func.sum(Batch.remaining_qty), 0)).where(
        Batch.item_id == item_id, Batch.status == "active")) or 0
