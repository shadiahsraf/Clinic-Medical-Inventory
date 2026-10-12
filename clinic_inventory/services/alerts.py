"""Low/out-of-stock alert lifecycle: new -> acknowledged -> resolved (history kept)."""
from datetime import datetime
from sqlalchemy import select
from sqlalchemy.orm import Session
from ..models import Alert, Item, Batch, User, now
from .common import available_qty, require, audit


def _state(qty: int, min_stock: int):
    if qty <= 0:
        return "out"
    if min_stock > 0 and qty <= min_stock:
        return "low"
    return None


def evaluate_item(s: Session, item_id: int) -> Alert | None:
    """Idempotent: safe to call after every stock change and on every timer tick."""
    item = s.get(Item, item_id)
    if not item.active:
        return None
    has_history = s.scalar(select(Batch.id).where(Batch.item_id == item_id).limit(1)) is not None
    qty = available_qty(s, item_id)
    state = _state(qty, item.min_stock) if has_history else None
    open_alert = s.scalar(select(Alert).where(Alert.item_id == item_id, Alert.status != "resolved"))
    if open_alert and open_alert.kind == state:
        return open_alert                       # same unresolved condition: no duplicate
    if open_alert:                              # condition ended or changed severity
        open_alert.status = "resolved"; open_alert.resolved_at = now()
        s.flush()
    if state is None:
        return None
    a = Alert(item_id=item_id, kind=state, qty_at_creation=qty, min_at_creation=item.min_stock)
    s.add(a); s.flush()
    return a


def evaluate_items(s: Session, item_ids):
    for i in set(item_ids):
        evaluate_item(s, i)


def scan_all(s: Session):
    """Periodic safety-net scan (also catches expiry-driven and threshold-edit changes)."""
    evaluate_items(s, s.scalars(select(Item.id).where(Item.active.is_(True))).all())


def pending_desktop_notifications(s: Session) -> list[Alert]:
    return list(s.scalars(select(Alert).where(Alert.desktop_notified.is_(False),
                                              Alert.status == "new").order_by(Alert.id)))


def mark_notified(s: Session, alert_ids):
    for a in s.scalars(select(Alert).where(Alert.id.in_(list(alert_ids)))):
        a.desktop_notified = True


def acknowledge(s: Session, actor: User, alert_id: int):
    require(actor, "alerts.manage")
    a = s.get(Alert, alert_id)
    if a.status == "new":
        a.status = "acknowledged"; a.acknowledged_at = now(); a.acknowledged_by = actor.id
        audit(s, actor, "ack_alert", "alert", a.id)


def list_alerts(s: Session, kind=None, status=None, item_id=None):
    q = select(Alert)
    if kind: q = q.where(Alert.kind == kind)
    if status: q = q.where(Alert.status == status)
    if item_id: q = q.where(Alert.item_id == item_id)
    return list(s.scalars(q.order_by(Alert.id.desc())))


def badge_count(s: Session) -> int:
    return len(list(s.scalars(select(Alert.id).where(Alert.status == "new"))))


def notification_text_ar(a: Alert) -> tuple[str, str]:
    """(title, body) for the Windows toast, entirely Arabic."""
    if a.kind == "out":
        return ("تنبيه نفاد المخزون", f"الصنف: {a.item.name}\nالرصيد الحالي: صفر")
    return ("تنبيه انخفاض المخزون",
            f"الصنف: {a.item.name}\nالرصيد الحالي: {a.qty_at_creation}\nالحد الأدنى: {a.min_at_creation}")
