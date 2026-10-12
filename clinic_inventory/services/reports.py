"""Report queries. Every figure is computed from the immutable StockMovement ledger,
batches and documents. Each report returns (title_ar, headers_ar, rows).

Accounting definitions (documented):
 * Opening balance(item, D1) = SUM(qty_delta) of movements with move_date < D1.
 * Closing balance(item, D2) = SUM(qty_delta) of movements with move_date <= D2.
 * Inventory value at D     = SUM(value_delta) of movements with move_date <= D (exact FIFO cost).
 * Issue cost               = SUM(unit_cost * qty) of the batches actually consumed.
 * Donation value is an ESTIMATE and is never part of cash movement.
"""
from datetime import date
from sqlalchemy import select, func
from sqlalchemy.orm import Session
from ..models import (Batch, StockMovement as M, Item, Department, Supplier, IncomingDoc,
                      SupplierPayment, CashMovement, DamageRecord, Category, IssueDoc, IssueLine)
from ..money import fmt_egp
from .common import available_qty, onhand_qty
from .inventory import doc_total, paid_total, outstanding

E = fmt_egp


def stock_balances(s: Session, category_id=None, as_of: date | None = None):
    rows = []
    q = select(Item).where(Item.active.is_(True)).order_by(Item.name)
    if category_id:
        q = q.where(Item.category_id == category_id)
    for it in s.scalars(q):
        if as_of:
            qty, val = s.execute(select(func.coalesce(func.sum(M.qty_delta), 0),
                                        func.coalesce(func.sum(M.value_delta), 0))
                                 .where(M.item_id == it.id, M.move_date <= as_of)).one()
        else:
            qty = available_qty(s, it.id)
            val = s.scalar(select(func.coalesce(func.sum(Batch.remaining_qty * Batch.unit_cost), 0))
                           .where(Batch.item_id == it.id, Batch.status == "active"))
        state = "نفد المخزون" if qty <= 0 else ("مخزون منخفض" if it.min_stock and qty <= it.min_stock else "متوفر")
        rows.append([it.code, it.name, it.category.name if it.category else "", it.unit.name,
                     qty, it.min_stock, E(val), state])
    return ("أرصدة المخزون", ["الكود", "الصنف", "التصنيف", "الوحدة", "الكمية", "الحد الأدنى", "القيمة", "الحالة"], rows)


def inventory_value(s: Session, as_of: date | None = None) -> int:
    q = select(func.coalesce(func.sum(M.value_delta), 0))
    if as_of:
        q = q.where(M.move_date <= as_of)
    return s.scalar(q)


def batch_balances(s: Session):
    rows = []
    for b in s.scalars(select(Batch).where(Batch.status == "active", Batch.remaining_qty > 0)
                       .order_by(Batch.item_id, Batch.received_date, Batch.received_seq)):
        it = s.get(Item, b.item_id)
        rows.append([it.code, it.name, b.id, b.received_date.isoformat(), b.remaining_qty,
                     E(b.unit_cost), E(b.remaining_qty * b.unit_cost),
                     b.expiry_date.isoformat() if b.expiry_date else ""])
    return ("أرصدة الدفعات", ["الكود", "الصنف", "رقم الدفعة", "تاريخ الاستلام", "المتبقي",
                              "سعر الوحدة", "القيمة", "تاريخ الصلاحية"], rows)


def item_movement(s: Session, item_id: int, d1: date, d2: date):
    it = s.get(Item, item_id)
    def tot(kind_filter, lo=None, hi=None):
        q = select(func.coalesce(func.sum(M.qty_delta), 0)).where(M.item_id == item_id)
        if kind_filter: q = q.where(M.kind.in_(kind_filter))
        if lo: q = q.where(M.move_date >= lo)
        if hi: q = q.where(M.move_date <= hi)
        return s.scalar(q)
    opening = s.scalar(select(func.coalesce(func.sum(M.qty_delta), 0)).where(M.item_id == item_id, M.move_date < d1))
    inc = tot(["incoming"], d1, d2); iss = -tot(["issue"], d1, d2); ret = tot(["return"], d1, d2)
    other = tot(["damage", "adjustment", "incoming_reversal"], d1, d2)
    closing = opening + inc - iss + ret + other
    rows = [["الرصيد الافتتاحي", opening], ["الوارد", inc], ["المصروف", iss], ["المرتجع", ret],
            ["الهالك والتسويات", other], ["الرصيد الختامي", closing]]
    return (f"حركة الصنف: {it.name}", ["البند", "الكمية"], rows)


def item_history(s: Session, item_id: int, d1: date, d2: date):
    labels = {"incoming": "وارد", "issue": "صرف", "return": "مرتجع", "damage": "هالك",
              "adjustment": "تسوية", "incoming_reversal": "إلغاء وارد"}
    rows = [[m.move_date.isoformat(), labels[m.kind], m.batch_id, m.qty_delta, E(m.unit_cost), E(m.value_delta)]
            for m in s.scalars(select(M).where(M.item_id == item_id, M.move_date.between(d1, d2)).order_by(M.id))]
    return ("سجل حركة الصنف", ["التاريخ", "النوع", "الدفعة", "الكمية", "سعر الوحدة", "القيمة"], rows)


def department_consumption(s: Session, d1: date, d2: date, department_id=None):
    q = (select(M.department_id, M.item_id, M.kind, func.sum(M.qty_delta), func.sum(M.value_delta))
         .where(M.kind.in_(["issue", "return"]), M.department_id.is_not(None), M.move_date.between(d1, d2))
         .group_by(M.department_id, M.item_id, M.kind))
    if department_id:
        q = q.where(M.department_id == department_id)
    agg: dict = {}
    for dep, item, kind, qty, val in s.execute(q):
        a = agg.setdefault((dep, item), {"iq": 0, "rq": 0, "cost": 0})
        if kind == "issue":
            a["iq"] += -qty; a["cost"] += -val
        else:
            a["rq"] += qty; a["cost"] -= val
    rows = []
    for (dep, item), a in sorted(agg.items()):
        it, d = s.get(Item, item), s.get(Department, dep)
        rows.append([d.name, it.code, it.name, a["iq"], a["rq"], a["iq"] - a["rq"], E(a["cost"])])
    return ("استهلاك العيادات والأقسام", ["العيادة/القسم", "الكود", "الصنف", "المصروف", "المرتجع",
                                          "الصافي", "التكلفة (FIFO)"], rows)


def supplier_balances(s: Session):
    out: dict = {}
    for d in s.scalars(select(IncomingDoc).where(IncomingDoc.source_type == "purchase",
                                                 IncomingDoc.status == "confirmed")):
        r = out.setdefault(d.supplier_id, [0, 0])
        r[0] += doc_total(d); r[1] += paid_total(s, d.id)
    rows = [[s.get(Supplier, sid).name, E(t), E(p), E(t - p)] for sid, (t, p) in out.items()]
    return ("أرصدة الموردين", ["المورد", "إجمالي المشتريات", "المدفوع", "المتبقي"], rows)


def financial_summary(s: Session, d1: date, d2: date):
    docs = list(s.scalars(select(IncomingDoc).where(IncomingDoc.status == "confirmed",
                                                    IncomingDoc.doc_date.between(d1, d2))))
    purchases = sum(doc_total(d) for d in docs if d.source_type == "purchase")
    donations = sum(doc_total(d) for d in docs if d.source_type == "donation")
    pay = s.scalar(select(func.coalesce(func.sum(SupplierPayment.amount), 0)).where(SupplierPayment.pay_date.between(d1, d2)))
    cashdon = s.scalar(select(func.coalesce(func.sum(CashMovement.amount), 0)).where(
        CashMovement.kind == "cash_donation", CashMovement.move_date.between(d1, d2)))
    issue_cost = -s.scalar(select(func.coalesce(func.sum(M.value_delta), 0)).where(M.kind == "issue", M.move_date.between(d1, d2)))
    return_val = s.scalar(select(func.coalesce(func.sum(M.value_delta), 0)).where(M.kind == "return", M.move_date.between(d1, d2)))
    damage = s.scalar(select(func.coalesce(func.sum(DamageRecord.cost), 0)).where(DamageRecord.event_date.between(d1, d2)))
    adj = s.scalar(select(func.coalesce(func.sum(M.value_delta), 0)).where(M.kind == "adjustment", M.move_date.between(d1, d2)))
    rows = [["— حركة نقدية فعلية —", ""], ["مدفوعات الموردين (نقد خارج)", E(pay)], ["تبرعات نقدية (نقد داخل)", E(cashdon)],
            ["— التزامات —", ""], ["إجمالي المشتريات", E(purchases)], ["المستحق للموردين (المتبقي)", E(sum(outstanding(s, d) for d in docs))],
            ["— قيم تقديرية (ليست نقدًا) —", ""], ["القيمة التقديرية للتبرعات العينية", E(donations)],
            ["— تكلفة الاستهلاك —", ""], ["تكلفة المصروف (FIFO)", E(issue_cost)], ["قيمة المرتجعات المعادة للمخزون", E(return_val)],
            ["تكلفة الهالك والتالف", E(damage)], ["أثر تسويات الجرد", E(adj)],
            ["— قيمة المخزون —", ""], ["قيمة المخزون الحالية", E(inventory_value(s))]]
    return ("الملخص المالي", ["البند", "المبلغ"], rows)


def dashboard(s: Session, today: date | None = None) -> dict:
    today = today or date.today()
    m1 = today.replace(day=1)
    items = list(s.scalars(select(Item).where(Item.active.is_(True))))
    low = out = ok = 0
    for it in items:
        q = available_qty(s, it.id)
        if q <= 0: out += 1
        elif it.min_stock and q <= it.min_stock: low += 1
        else: ok += 1
    def sm(kind, field):
        return s.scalar(select(func.coalesce(func.sum(field), 0)).where(M.kind == kind, M.move_date.between(m1, today)))
    docs = list(s.scalars(select(IncomingDoc).where(IncomingDoc.status == "confirmed",
                                                    IncomingDoc.doc_date.between(m1, today))))
    from datetime import timedelta
    near = s.scalar(select(func.count(func.distinct(Batch.item_id))).where(
        Batch.status == "active", Batch.remaining_qty > 0, Batch.expiry_date.is_not(None),
        Batch.expiry_date.between(today, today + timedelta(days=60))))
    return {"total_items": len(items), "available": ok + low, "low": low, "out": out, "near_expiry": near,
            "inventory_value": inventory_value(s),
            "purchases_month": sum(doc_total(d) for d in docs if d.source_type == "purchase"),
            "donations_month": sum(doc_total(d) for d in docs if d.source_type == "donation"),
            "issue_cost_month": -sm("issue", M.value_delta),
            "incoming_qty_month": sm("incoming", M.qty_delta), "issued_qty_month": -sm("issue", M.qty_delta)}


def reconcile(s: Session) -> list[str]:
    """Integrity check: ledger must equal batch balances. Returns Arabic problem list."""
    problems = []
    for b in s.scalars(select(Batch)):
        led = s.scalar(select(func.coalesce(func.sum(M.qty_delta), 0)).where(M.batch_id == b.id))
        if led != b.remaining_qty:
            problems.append(f"الدفعة {b.id}: رصيد الدفعة {b.remaining_qty} لا يطابق السجل {led}")
    return problems


def query_movement_history(s: Session, item_id: int | None = None, department_id: int | None = None,
                           kind: str | None = None, d1: date | None = None, d2: date | None = None,
                           search: str | None = None, limit: int = 500):
    from ..models import User, ReturnRecord, DamageRecord, StocktakeSession
    labels = {
        "incoming": "وارد إلى المخزن",
        "issue": "صرف إلى قسم",
        "return": "مرتجع من قسم",
        "damage": "استبعاد هالك/تالف",
        "adjustment": "تسوية جرد",
        "incoming_reversal": "إلغاء وارد"
    }
    q = select(M)
    if item_id:
        q = q.where(M.item_id == item_id)
    if department_id:
        q = q.where(M.department_id == department_id)
    if kind:
        q = q.where(M.kind == kind)
    if d1:
        q = q.where(M.move_date >= d1)
    if d2:
        q = q.where(M.move_date <= d2)

    movements = list(s.scalars(q.order_by(M.ts.desc(), M.id.desc()).limit(limit)))
    result = []
    for m in movements:
        it = s.get(Item, m.item_id)
        u = s.get(User, m.user_id) if m.user_id else None

        partner_str = ""
        ref_doc_str = f"{m.doc_type} #{m.doc_id}"
        if m.department_id:
            dept = s.get(Department, m.department_id)
            partner_str = dept.name if dept else ""

        if m.doc_type == "incoming":
            inc_doc = s.get(IncomingDoc, m.doc_id)
            if inc_doc:
                ref_doc_str = inc_doc.number
                if not partner_str:
                    if inc_doc.supplier_id:
                        sup = s.get(Supplier, inc_doc.supplier_id)
                        partner_str = f"مورد: {sup.name}" if sup else ""
                    elif inc_doc.donor_name:
                        partner_str = f"متبرع: {inc_doc.donor_name}"
        elif m.doc_type == "issue":
            iss_doc = s.get(IssueDoc, m.doc_id)
            if iss_doc:
                ref_doc_str = iss_doc.number
                if not partner_str and iss_doc.department:
                    partner_str = iss_doc.department.name
        elif m.doc_type == "return":
            ret_doc = s.get(ReturnRecord, m.doc_id)
            if ret_doc:
                ref_doc_str = ret_doc.number
        elif m.doc_type == "damage":
            dam_doc = s.get(DamageRecord, m.doc_id)
            if dam_doc:
                ref_doc_str = f"هالك #{dam_doc.id}"
        elif m.doc_type == "stocktake":
            st_sess = s.get(StocktakeSession, m.doc_id)
            if st_sess:
                ref_doc_str = st_sess.number

        result.append({
            "id": m.id,
            "ts": m.ts,
            "move_date": m.move_date,
            "item_code": it.code if it else "",
            "item_name": it.name if it else "",
            "kind": m.kind,
            "kind_ar": labels.get(m.kind, m.kind),
            "qty_delta": m.qty_delta,
            "batch_id": m.batch_id,
            "unit_cost": m.unit_cost,
            "value_delta": m.value_delta,
            "partner": partner_str,
            "ref_doc": ref_doc_str,
            "user_name": u.display_name if u else ""
        })

    if search and search.strip():
        term = search.strip().lower()
        result = [r for r in result if term in r["ref_doc"].lower() or term in r["partner"].lower()
                  or term in r["item_name"].lower() or term in r["item_code"].lower()
                  or term in r["user_name"].lower()]

    return result


def get_issue_voucher_data(s: Session, doc_id: int):
    from ..models import User
    doc = s.get(IssueDoc, doc_id)
    if not doc:
        from ..errors import AppError
        raise AppError("سند الصرف غير موجود.")
    user = s.get(User, doc.created_by) if doc.created_by else None
    lines_data = []
    for line in doc.lines:
        lines_data.append({
            "item_code": line.item.code,
            "item_name": line.item.name,
            "unit_name": line.item.unit.name if line.item.unit else "",
            "quantity": line.quantity,
            "cost": line.cost,
            "unit_cost": line.cost // line.quantity if line.quantity else 0
        })
    return {
        "id": doc.id,
        "number": doc.number,
        "issued_at": doc.issued_at,
        "department_name": doc.department.name if doc.department else "",
        "recipient": doc.recipient or "",
        "reference": doc.reference or "",
        "notes": doc.notes or "",
        "total_cost": doc.total_cost,
        "created_by_name": user.display_name if user else "",
        "lines": lines_data
    }

