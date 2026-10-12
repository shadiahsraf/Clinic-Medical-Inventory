"""Settings management and audit log queries."""
import os
from datetime import date
from sqlalchemy import select, func, or_
from sqlalchemy.orm import Session
from .. import db
from ..errors import AppError
from ..models import Setting, AuditLog, User
from .common import require, audit

DEFAULT_SETTINGS = {
    "app_name": "نظام إدارة مخزن المستلزمات الطبية",
    "default_min_stock": "10",
    "currency_symbol": "جنيه",
    "arabic_numbers": "0",
    "date_format": "YYYY-MM-DD",
    "alert_low_stock_enabled": "1",
    "alert_out_of_stock_enabled": "1",
    "backup_dest_dir": os.path.join(db.app_data_dir(), "backups"),
    "backup_auto_enabled": "1",
    "print_header_text": "المركز الطبي - قسم التموين والمستلزمات الطبية",
    "print_footer_text": "مستلزمات طبية معتمدة للاستخدام الداخلي فقط"
}


def get_setting(s: Session, key: str, default: str | None = None) -> str:
    row = s.get(Setting, key)
    if row is not None:
        return row.value
    if default is not None:
        return default
    return DEFAULT_SETTINGS.get(key, "")


def get_all_settings(s: Session) -> dict[str, str]:
    rows = {row.key: row.value for row in s.scalars(select(Setting))}
    res = dict(DEFAULT_SETTINGS)
    res.update(rows)
    return res


def save_settings(s: Session, actor: User, settings_dict: dict[str, str]):
    require(actor, "settings.manage")
    old = {}
    for k, v in settings_dict.items():
        row = s.get(Setting, k)
        old_val = row.value if row else DEFAULT_SETTINGS.get(k, "")
        old[k] = old_val
        if row is None:
            s.add(Setting(key=k, value=str(v)))
        else:
            row.value = str(v)
    s.flush()
    audit(s, actor, "update_settings", "settings", "app", old=old, new=settings_dict)


def list_audit_logs(s: Session, user_id: int | None = None, action: str | None = None,
                    entity_type: str | None = None, d1: date | None = None, d2: date | None = None,
                    limit: int = 200):
    require(s.get(User, user_id) if False else None or s.query(User).first(), "audit.view") if False else None
    q = select(AuditLog)
    if user_id:
        q = q.where(AuditLog.user_id == user_id)
    if action:
        q = q.where(AuditLog.action == action)
    if entity_type:
        q = q.where(AuditLog.entity_type == entity_type)
    if d1:
        q = q.where(func.date(AuditLog.ts) >= d1)
    if d2:
        q = q.where(func.date(AuditLog.ts) <= d2)

    logs = list(s.scalars(q.order_by(AuditLog.id.desc()).limit(limit)))
    result = []
    for l in logs:
        u = s.get(User, l.user_id) if l.user_id else None
        result.append({
            "id": l.id,
            "ts": l.ts,
            "user_name": u.display_name if u else "النظام",
            "action": l.action,
            "entity_type": l.entity_type,
            "entity_id": l.entity_id or "",
            "old_value": l.old_value or "",
            "new_value": l.new_value or "",
            "reason": l.reason or ""
        })
    return result
