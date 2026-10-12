from datetime import date
from sqlalchemy import select, or_, func
from sqlalchemy.orm import Session
from ..errors import AppError
from ..models import Item, Category, Unit, Supplier, Department, User, IncomingDoc, SupplierPayment, IssueDoc, ReturnRecord
from .common import require, audit, next_number


def get_or_create_category(s, actor, name):
    require(actor, "items.manage")
    c = s.scalar(select(Category).where(Category.name == name.strip()))
    if not c:
        c = Category(name=name.strip()); s.add(c); s.flush()
    return c


def get_or_create_unit(s, actor, name):
    require(actor, "items.manage")
    u = s.scalar(select(Unit).where(Unit.name == name.strip()))
    if not u:
        u = Unit(name=name.strip()); s.add(u); s.flush()
    return u


def create_item(s: Session, actor: User, name: str, unit_name: str, category_name: str | None = None,
                min_stock: int = 0, barcode: str | None = None, **extra) -> Item:
    require(actor, "items.manage")
    if not name.strip():
        raise AppError("اسم الصنف مطلوب.")
    if min_stock < 0:
        raise AppError("الحد الأدنى للمخزون لا يمكن أن يكون سالبًا.")
    barcode = (barcode or "").strip() or None
    if barcode and s.scalar(select(Item).where(Item.barcode == barcode)):
        raise AppError("هذا الباركود مسجل لصنف آخر.")
    unit = get_or_create_unit(s, actor, unit_name)
    cat = get_or_create_category(s, actor, category_name) if category_name else None
    code = next_number(s, "item_code", "IT", 5)   # permanent, never reused
    it = Item(code=code, name=name.strip(), unit_id=unit.id, category_id=cat.id if cat else None,
              min_stock=min_stock, barcode=barcode, **extra)
    s.add(it); s.flush()
    audit(s, actor, "create_item", "item", it.id, new={"code": code, "name": it.name})
    return it


def update_item(s: Session, actor: User, item_id: int, **changes) -> Item:
    require(actor, "items.manage")
    it = s.get(Item, item_id)
    if "code" in changes:
        raise AppError("لا يمكن تغيير كود الصنف بعد إنشائه.")
    old = {k: getattr(it, k) for k in changes}
    for k, v in changes.items():
        setattr(it, k, v)
    s.flush()
    audit(s, actor, "update_item", "item", it.id, old=old, new=changes)
    return it


def search_items(s: Session, text: str = "", category_id: int | None = None, active_only=True):
    q = select(Item)
    if text.strip():
        t = f"%{text.strip()}%"
        q = q.where(or_(Item.code.ilike(t), Item.name.ilike(t), Item.barcode == text.strip()))
    if category_id:
        q = q.where(Item.category_id == category_id)
    if active_only:
        q = q.where(Item.active.is_(True))
    return list(s.scalars(q.order_by(Item.name)))


def create_supplier(s, actor, name, **kw) -> Supplier:
    require(actor, "partners.manage")
    if not name.strip():
        raise AppError("اسم المورد مطلوب.")
    if s.scalar(select(Supplier).where(Supplier.name == name.strip())):
        raise AppError("المورد مسجل من قبل.")
    sup = Supplier(name=name.strip(), **kw); s.add(sup); s.flush()
    audit(s, actor, "create_supplier", "supplier", sup.id, new={"name": sup.name})
    return sup


def update_supplier(s: Session, actor: User, supplier_id: int, **changes) -> Supplier:
    require(actor, "partners.manage")
    sup = s.get(Supplier, supplier_id)
    if sup is None:
        raise AppError("المورد غير موجود.")
    if "name" in changes:
        new_name = changes["name"].strip()
        if not new_name:
            raise AppError("اسم المورد مطلوب.")
        existing = s.scalar(select(Supplier).where(Supplier.name == new_name, Supplier.id != supplier_id))
        if existing:
            raise AppError("يوجد مورد آخر مسجل بنفس الاسم.")
        changes["name"] = new_name
    old = {k: getattr(sup, k) for k in changes if hasattr(sup, k)}
    for k, v in changes.items():
        if hasattr(sup, k):
            setattr(sup, k, v)
    s.flush()
    audit(s, actor, "update_supplier", "supplier", sup.id, old=old, new=changes)
    return sup


def set_supplier_active(s: Session, actor: User, supplier_id: int, active: bool) -> Supplier:
    require(actor, "partners.manage")
    sup = s.get(Supplier, supplier_id)
    if sup is None:
        raise AppError("المورد غير موجود.")
    old = sup.active
    sup.active = active
    s.flush()
    audit(s, actor, "set_supplier_active", "supplier", sup.id, old={"active": old}, new={"active": active})
    return sup


def delete_supplier(s: Session, actor: User, supplier_id: int):
    require(actor, "partners.manage")
    sup = s.get(Supplier, supplier_id)
    if sup is None:
        raise AppError("المورد غير موجود.")
    has_tx = s.scalar(select(IncomingDoc.id).where(IncomingDoc.supplier_id == supplier_id).limit(1))
    if has_tx:
        raise AppError("لا يمكن حذف المورد لوجود فواتير أو حركات شراء مرتبطة به. يمكنك تعطيل حسابه بدلاً من ذلك.")
    s.delete(sup)
    s.flush()
    audit(s, actor, "delete_supplier", "supplier", supplier_id, old={"name": sup.name})


def search_suppliers(s: Session, text: str = "", active_only: bool = False):
    q = select(Supplier)
    if text.strip():
        t = f"%{text.strip()}%"
        q = q.where(or_(Supplier.name.ilike(t), Supplier.phone.ilike(t), Supplier.contact_person.ilike(t)))
    if active_only:
        q = q.where(Supplier.active.is_(True))
    return list(s.scalars(q.order_by(Supplier.name)))


def get_supplier_history(s: Session, supplier_id: int):
    docs = list(s.scalars(select(IncomingDoc).where(
        IncomingDoc.supplier_id == supplier_id,
        IncomingDoc.source_type == "purchase"
    ).order_by(IncomingDoc.doc_date.desc(), IncomingDoc.id.desc())))
    history = []
    for d in docs:
        total = sum(l.quantity * l.unit_cost for l in d.lines)
        paid = s.scalar(select(func.coalesce(func.sum(SupplierPayment.amount), 0)).where(SupplierPayment.doc_id == d.id)) or 0
        rem = total - paid if d.status == "confirmed" else 0
        history.append({
            "id": d.id,
            "number": d.number,
            "doc_date": d.doc_date,
            "reference": d.reference or "",
            "status": d.status,
            "total_cost": total,
            "paid": paid,
            "outstanding": rem,
        })
    return history


def create_department(s, actor, name, **kw) -> Department:
    require(actor, "partners.manage")
    if not name.strip():
        raise AppError("اسم العيادة أو القسم مطلوب.")
    if s.scalar(select(Department).where(Department.name == name.strip())):
        raise AppError("العيادة أو القسم مسجل من قبل.")
    d = Department(name=name.strip(), **kw); s.add(d); s.flush()
    audit(s, actor, "create_department", "department", d.id, new={"name": d.name})
    return d


def update_department(s: Session, actor: User, dept_id: int, **changes) -> Department:
    require(actor, "partners.manage")
    d = s.get(Department, dept_id)
    if d is None:
        raise AppError("القسم أو العيادة غير موجودة.")
    if "name" in changes:
        new_name = changes["name"].strip()
        if not new_name:
            raise AppError("اسم العيادة أو القسم مطلوب.")
        existing = s.scalar(select(Department).where(Department.name == new_name, Department.id != dept_id))
        if existing:
            raise AppError("توجد عيادة أو قسم آخر مسجل بنفس الاسم.")
        changes["name"] = new_name
    old = {k: getattr(d, k) for k in changes if hasattr(d, k)}
    for k, v in changes.items():
        if hasattr(d, k):
            setattr(d, k, v)
    s.flush()
    audit(s, actor, "update_department", "department", d.id, old=old, new=changes)
    return d


def set_department_active(s: Session, actor: User, dept_id: int, active: bool) -> Department:
    require(actor, "partners.manage")
    d = s.get(Department, dept_id)
    if d is None:
        raise AppError("القسم أو العيادة غير موجودة.")
    old = d.active
    d.active = active
    s.flush()
    audit(s, actor, "set_department_active", "department", d.id, old={"active": old}, new={"active": active})
    return d


def delete_department(s: Session, actor: User, dept_id: int):
    require(actor, "partners.manage")
    d = s.get(Department, dept_id)
    if d is None:
        raise AppError("القسم أو العيادة غير موجودة.")
    has_issue = s.scalar(select(IssueDoc.id).where(IssueDoc.department_id == dept_id).limit(1))
    has_ret = s.scalar(select(ReturnRecord.id).where(ReturnRecord.department_id == dept_id).limit(1))
    if has_issue or has_ret:
        raise AppError("لا يمكن حذف العيادة أو القسم لوجود حركات صرف أو مرتجعات مرتبطة به. يمكنك تعطيل حسابه بدلاً من ذلك.")
    s.delete(d)
    s.flush()
    audit(s, actor, "delete_department", "department", dept_id, old={"name": d.name})


def search_departments(s: Session, text: str = "", active_only: bool = False):
    q = select(Department)
    if text.strip():
        t = f"%{text.strip()}%"
        q = q.where(or_(Department.name.ilike(t), Department.dept_type.ilike(t), Department.doctor.ilike(t)))
    if active_only:
        q = q.where(Department.active.is_(True))
    return list(s.scalars(q.order_by(Department.name)))


def get_department_issue_history(s: Session, dept_id: int, d1: date | None = None, d2: date | None = None):
    q = select(IssueDoc).where(IssueDoc.department_id == dept_id)
    if d1:
        q = q.where(func.date(IssueDoc.issued_at) >= d1)
    if d2:
        q = q.where(func.date(IssueDoc.issued_at) <= d2)
    docs = list(s.scalars(q.order_by(IssueDoc.issued_at.desc(), IssueDoc.id.desc())))
    history = []
    for doc in docs:
        items_summary = ", ".join(f"{line.item.name} ({line.quantity})" for line in doc.lines)
        total_qty = sum(line.quantity for line in doc.lines)
        history.append({
            "id": doc.id,
            "number": doc.number,
            "issued_at": doc.issued_at,
            "recipient": doc.recipient or "",
            "total_cost": doc.total_cost,
            "total_qty": total_qty,
            "items_summary": items_summary,
            "status": doc.status
        })
    return history


def get_department_consumption_summary(s: Session, dept_id: int, d1: date, d2: date):
    from ..models import StockMovement as M
    issued_qty = - (s.scalar(select(func.coalesce(func.sum(M.qty_delta), 0)).where(
        M.department_id == dept_id, M.kind == "issue", M.move_date.between(d1, d2))) or 0)
    returned_qty = s.scalar(select(func.coalesce(func.sum(M.qty_delta), 0)).where(
        M.department_id == dept_id, M.kind == "return", M.move_date.between(d1, d2))) or 0
    net_qty = issued_qty - returned_qty
    issue_cost = - (s.scalar(select(func.coalesce(func.sum(M.value_delta), 0)).where(
        M.department_id == dept_id, M.kind == "issue", M.move_date.between(d1, d2))) or 0)
    return_val = s.scalar(select(func.coalesce(func.sum(M.value_delta), 0)).where(
        M.department_id == dept_id, M.kind == "return", M.move_date.between(d1, d2))) or 0
    net_cost = issue_cost - return_val
    return {
        "issued_qty": issued_qty,
        "returned_qty": returned_qty,
        "net_qty": net_qty,
        "issue_cost": issue_cost,
        "net_cost": net_cost
    }
