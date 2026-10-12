from argon2 import PasswordHasher
from argon2.exceptions import VerifyMismatchError, InvalidHashError
from sqlalchemy import select
from sqlalchemy.orm import Session
from ..errors import AppError
from ..models import User, Role, RolePermission
from ..permissions import DEFAULT_ROLES, PERMISSIONS, ROLE_ADMIN
from .common import require, audit

_ph = PasswordHasher()


def seed_roles(s: Session):
    for name, perms in DEFAULT_ROLES.items():
        if s.scalar(select(Role).where(Role.name == name)) is None:
            r = Role(name=name)
            r.permissions = [RolePermission(permission=p) for p in perms]
            s.add(r)
    s.flush()


def create_user(s: Session, actor: User | None, username: str, display_name: str,
                password: str, role_name: str) -> User:
    first_user = s.scalar(select(User.id).limit(1)) is None
    if not first_user:
        require(actor, "users.manage")
    username = username.strip()
    if not username or len(password) < 6:
        raise AppError("اسم المستخدم مطلوب وكلمة المرور يجب ألا تقل عن 6 أحرف.")
    if s.scalar(select(User).where(User.username == username)):
        raise AppError("اسم المستخدم مستخدم من قبل.")
    role = s.scalar(select(Role).where(Role.name == role_name))
    if role is None:
        raise AppError("الدور المحدد غير موجود.")
    u = User(username=username, display_name=display_name, role_id=role.id,
             password_hash=_ph.hash(password))
    s.add(u); s.flush()
    audit(s, actor or u, "create_user", "user", u.id, new={"username": username, "role": role_name})
    return u


def login(s: Session, username: str, password: str) -> User:
    u = s.scalar(select(User).where(User.username == username.strip()))
    try:
        if u is None or not u.active:
            raise VerifyMismatchError()
        _ph.verify(u.password_hash, password)
    except (VerifyMismatchError, InvalidHashError):
        raise AppError("اسم المستخدم أو كلمة المرور غير صحيحة.")
    return u


def change_role_permissions(s: Session, actor: User, role_name: str, perms: list[str]):
    require(actor, "users.manage")
    if role_name == ROLE_ADMIN:
        raise AppError("لا يمكن تعديل صلاحيات مدير النظام.")
    if any(p not in PERMISSIONS for p in perms):
        raise AppError("صلاحية غير معروفة.")
    role = s.scalar(select(Role).where(Role.name == role_name))
    old = sorted(p.permission for p in role.permissions)
    role.permissions = [RolePermission(role_id=role.id, permission=p) for p in perms]
    s.flush()
    audit(s, actor, "change_permissions", "role", role.id, old=old, new=sorted(perms))


def set_user_active(s: Session, actor: User, user_id: int, active: bool):
    require(actor, "users.manage")
    u = s.get(User, user_id)
    if u.id == actor.id and not active:
        raise AppError("لا يمكنك تعطيل حسابك الحالي.")
    audit(s, actor, "set_user_active", "user", u.id, old={"active": u.active}, new={"active": active})
    u.active = active


def change_password(s: Session, actor: User, user_id: int, new_password: str):
    if actor.id != user_id and not actor.has("users.manage"):
        raise PermissionDenied()
    if len(new_password) < 6:
        raise AppError("كلمة المرور يجب ألا تقل عن 6 أحرف.")
    u = s.get(User, user_id)
    if u is None:
        raise AppError("المستخدم غير موجود.")
    u.password_hash = _ph.hash(new_password)
    s.flush()
    audit(s, actor, "change_password", "user", u.id)


def update_user_role(s: Session, actor: User, user_id: int, role_name: str):
    require(actor, "users.manage")
    if actor.id == user_id and actor.role.name != ROLE_ADMIN:
        raise AppError("لا يمكنك تعديل صلاحيات أو دور حسابك بنفسك.")
    if role_name == ROLE_ADMIN and actor.role.name != ROLE_ADMIN:
        raise AppError("لا يمكن لمستخدم عادي ترقية نفسه أو غيره إلى رتبة مدير النظام.")
    u = s.get(User, user_id)
    if u is None:
        raise AppError("المستخدم غير موجود.")
    role = s.scalar(select(Role).where(Role.name == role_name))
    if role is None:
        raise AppError("الدور المحدد غير موجود.")
    old_role = u.role.name
    u.role_id = role.id
    s.flush()
    audit(s, actor, "update_user_role", "user", u.id, old={"role": old_role}, new={"role": role_name})


def list_users(s: Session):
    return list(s.scalars(select(User).order_by(User.id)))


def list_roles(s: Session):
    return list(s.scalars(select(Role).order_by(Role.id)))


def get_user_audit_trail(s: Session, user_id: int):
    from ..models import AuditLog
    q = select(AuditLog).where(
        (AuditLog.user_id == user_id) |
        ((AuditLog.entity_type == "user") & (AuditLog.entity_id == str(user_id)))
    ).order_by(AuditLog.id.desc()).limit(100)
    return list(s.scalars(q))

