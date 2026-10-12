"""Stock-changing operations. Each public function must run inside ONE
db.session_scope() transaction (BEGIN IMMEDIATE) and updates the immutable
StockMovement ledger, the batches, alerts and the audit log together."""
from datetime import date, datetime
from sqlalchemy import select, func, or_
from sqlalchemy.orm import Session
from ..errors import AppError, InsufficientStock, PermissionDenied
from ..models import (Batch, StockMovement, IncomingDoc, IncomingLine, SupplierPayment, CashMovement,
                      IssueDoc, IssueLine, IssueAllocation, ReturnRecord, DamageRecord,
                      StocktakeSession, StocktakeLine, Item, Supplier, Department, User, now)
from .common import require, audit, next_number, available_qty, onhand_qty
from . import alerts


def _move(s, *, item_id, batch, kind, qty_delta, doc_type, doc_id, user, move_date, dept_id=None):
    s.add(StockMovement(item_id=item_id, batch_id=batch.id, kind=kind, qty_delta=qty_delta,
                        unit_cost=batch.unit_cost, value_delta=qty_delta * batch.unit_cost,
                        doc_type=doc_type, doc_id=doc_id, user_id=user.id, move_date=move_date,
                        department_id=dept_id))


def _fifo_batches(s, item_id, include_expired=False, today=None):
    today = today or date.today()
    q = select(Batch).where(Batch.item_id == item_id, Batch.status == "active", Batch.remaining_qty > 0)
    if not include_expired:
        q = q.where((Batch.expiry_date.is_(None)) | (Batch.expiry_date >= today))
    return list(s.scalars(q.order_by(Batch.received_date, Batch.received_seq, Batch.id)))


def _consume(s, item_id, qty, *, kind, doc_type, doc_id, user, move_date, dept_id=None,
             include_expired=False):
    """Allocate `qty` from the oldest batches first. Returns [(batch, take, unit_cost)]."""
    batches = _fifo_batches(s, item_id, include_expired)
    total = sum(b.remaining_qty for b in batches)
    if qty > total:
        item = s.get(Item, item_id)
        raise InsufficientStock(f"الكمية المطلوبة من الصنف «{item.name}» ({qty}) أكبر من الرصيد المتاح ({total}).")
    out, need = [], qty
    for b in batches:
        if need == 0:
            break
        take = min(b.remaining_qty, need)
        b.remaining_qty -= take
        if b.remaining_qty == 0:
            b.status = "depleted"
        _move(s, item_id=item_id, batch=b, kind=kind, qty_delta=-take, doc_type=doc_type,
              doc_id=doc_id, user=user, move_date=move_date, dept_id=dept_id)
        out.append((b, take, b.unit_cost))
        need -= take
    s.flush()
    return out


def _new_batch(s, item_id, qty, unit_cost, received, expiry, line_id, kind, user, doc_type, doc_id):
    seq = (s.scalar(select(func.coalesce(func.max(Batch.received_seq), 0))) or 0) + 1
    b = Batch(item_id=item_id, received_date=received, received_seq=seq, original_qty=qty,
              remaining_qty=qty, unit_cost=unit_cost, source_line_id=line_id, source_kind=kind,
              expiry_date=expiry)
    s.add(b); s.flush()
    _move(s, item_id=item_id, batch=b, kind="incoming" if kind == "incoming" else "adjustment",
          qty_delta=qty, doc_type=doc_type, doc_id=doc_id, user=user, move_date=received)
    return b


# ------------------------------------------------------------------ incoming
def create_incoming(s: Session, actor: User, source_type: str, doc_date: date, lines: list[dict],
                    supplier_id=None, donor_name=None, reference=None, notes=None) -> IncomingDoc:
    """Creates a DRAFT. Drafts never affect stock."""
    require(actor, "incoming.create")
    if source_type == "purchase" and not supplier_id:
        raise AppError("يجب اختيار المورد لعمليات الشراء.")
    if not lines:
        raise AppError("يجب إضافة صنف واحد على الأقل.")
    doc = IncomingDoc(number=next_number(s, "incoming", "IN"), doc_date=doc_date, source_type=source_type,
                      supplier_id=supplier_id, donor_name=donor_name, reference=reference,
                      notes=notes, created_by=actor.id)
    for ln in lines:
        if ln["quantity"] <= 0:
            raise AppError("الكمية يجب أن تكون أكبر من صفر.")
        if ln.get("unit_cost", 0) < 0:
            raise AppError("سعر الوحدة لا يمكن أن يكون سالبًا.")
        doc.lines.append(IncomingLine(item_id=ln["item_id"], quantity=ln["quantity"],
                                      unit_cost=ln.get("unit_cost", 0), expiry_date=ln.get("expiry_date")))
    s.add(doc); s.flush()
    audit(s, actor, "create_incoming_draft", "incoming_doc", doc.id, new={"number": doc.number})
    return doc


def doc_total(doc: IncomingDoc) -> int:
    return sum(l.quantity * l.unit_cost for l in doc.lines)


def confirm_incoming(s: Session, actor: User, doc_id: int, paid_now: int = 0, pay_date: date | None = None):
    require(actor, "incoming.create")
    doc = s.get(IncomingDoc, doc_id)
    if doc.status != "draft":
        raise AppError("هذا المستند تم تأكيده أو إلغاؤه من قبل.")   # double-processing guard
    doc.status = "confirmed"; doc.confirmed_at = now()
    for l in doc.lines:
        _new_batch(s, l.item_id, l.quantity, l.unit_cost, doc.doc_date, l.expiry_date, l.id,
                   "incoming", actor, "incoming", doc.id)
    audit(s, actor, "confirm_incoming", "incoming_doc", doc.id, new={"total": doc_total(doc)})
    if paid_now:
        if doc.source_type != "purchase":
            raise AppError("لا توجد مدفوعات على التبرعات العينية.")
        record_payment(s, actor, doc.id, paid_now, pay_date or doc.doc_date)
    alerts.evaluate_items(s, [l.item_id for l in doc.lines])
    return doc


def cancel_incoming(s: Session, actor: User, doc_id: int, reason: str):
    require(actor, "incoming.cancel")
    if not reason or not reason.strip():
        raise AppError("سبب الإلغاء مطلوب.")
    doc = s.get(IncomingDoc, doc_id)
    if doc.status != "confirmed":
        raise AppError("يمكن إلغاء المستندات المؤكدة فقط.")
    if s.scalar(select(SupplierPayment.id).where(SupplierPayment.doc_id == doc.id).limit(1)):
        raise AppError("توجد مدفوعات مسجلة على هذا المستند؛ يجب معالجتها قبل الإلغاء.")
    batches = list(s.scalars(select(Batch).where(Batch.source_line_id.in_([l.id for l in doc.lines]))))
    for b in batches:
        if b.remaining_qty != b.original_qty:
            raise AppError("لا يمكن إلغاء المستند لأن جزءًا من كمياته صُرف أو تأثر بعملية أخرى.")
    for b in batches:
        _move(s, item_id=b.item_id, batch=b, kind="incoming_reversal", qty_delta=-b.remaining_qty,
              doc_type="incoming", doc_id=doc.id, user=actor, move_date=date.today())
        b.remaining_qty = 0; b.status = "cancelled"
    doc.status = "cancelled"; doc.cancel_reason = reason.strip()
    audit(s, actor, "cancel_incoming", "incoming_doc", doc.id, reason=reason)
    alerts.evaluate_items(s, [b.item_id for b in batches])


# ------------------------------------------------------------------ payments
def paid_total(s, doc_id) -> int:
    return s.scalar(select(func.coalesce(func.sum(SupplierPayment.amount), 0)).where(
        SupplierPayment.doc_id == doc_id)) or 0


def outstanding(s, doc: IncomingDoc) -> int:
    if doc.source_type != "purchase" or doc.status != "confirmed":
        return 0
    return doc_total(doc) - paid_total(s, doc.id)


def record_payment(s: Session, actor: User, doc_id: int, amount: int, pay_date: date,
                   method: str | None = None, notes: str | None = None) -> SupplierPayment:
    if not (actor.has("payments.manage") or actor.has("incoming.create")):
        raise PermissionDenied()
    doc = s.get(IncomingDoc, doc_id)
    if doc.source_type != "purchase" or doc.status != "confirmed":
        raise AppError("يمكن تسجيل المدفوعات على فواتير الشراء المؤكدة فقط.")
    if amount <= 0:
        raise AppError("مبلغ الدفعة يجب أن يكون أكبر من صفر.")
    if amount > outstanding(s, doc):
        raise AppError("مبلغ الدفعة أكبر من المتبقي على الفاتورة.")
    p = SupplierPayment(doc_id=doc.id, pay_date=pay_date, amount=amount, method=method,
                        notes=notes, created_by=actor.id)
    s.add(p); s.flush()
    s.add(CashMovement(move_date=pay_date, kind="supplier_payment", amount=-amount,
                       ref_type="incoming_doc", ref_id=doc.id, created_by=actor.id))
    audit(s, actor, "supplier_payment", "incoming_doc", doc.id, new={"amount": amount})
    return p


def record_cash_donation(s: Session, actor: User, amount: int, move_date: date, donor_name=None, notes=None):
    require(actor, "incoming.create")
    if amount <= 0:
        raise AppError("مبلغ التبرع يجب أن يكون أكبر من صفر.")
    c = CashMovement(move_date=move_date, kind="cash_donation", amount=amount, donor_name=donor_name,
                     notes=notes, created_by=actor.id)
    s.add(c); s.flush()
    audit(s, actor, "cash_donation", "cash_movement", c.id, new={"amount": amount})
    return c


# ------------------------------------------------------------------ issue
def create_issue(s: Session, actor: User, department_id: int, lines: list[dict], recipient=None,
                 reference=None, notes=None, idempotency_key: str | None = None) -> IssueDoc:
    """Confirm an issue atomically with FIFO allocation. Re-submitting the same
    idempotency_key returns the already-confirmed document (no double issue)."""
    require(actor, "issue.create")
    if idempotency_key:
        prev = s.scalar(select(IssueDoc).where(IssueDoc.idempotency_key == idempotency_key))
        if prev:
            return prev
    dept = s.get(Department, department_id)
    if dept is None or not dept.active:
        raise AppError("يجب اختيار عيادة أو قسم صحيح.")
    merged: dict[int, int] = {}
    for ln in lines:
        if ln["quantity"] <= 0:
            raise AppError("الكمية يجب أن تكون أكبر من صفر.")
        merged[ln["item_id"]] = merged.get(ln["item_id"], 0) + ln["quantity"]
    if not merged:
        raise AppError("يجب إضافة صنف واحد على الأقل.")
    doc = IssueDoc(number=next_number(s, "issue", "OUT"), idempotency_key=idempotency_key,
                   department_id=dept.id, recipient=recipient, reference=reference, notes=notes,
                   created_by=actor.id)
    s.add(doc); s.flush()
    total = 0
    for item_id, qty in merged.items():
        line = IssueLine(doc_id=doc.id, item_id=item_id, quantity=qty, cost=0)
        s.add(line); s.flush()
        allocs = _consume(s, item_id, qty, kind="issue", doc_type="issue", doc_id=doc.id, user=actor,
                          move_date=doc.issued_at.date(), dept_id=dept.id)
        for b, take, uc in allocs:
            s.add(IssueAllocation(line_id=line.id, batch_id=b.id, quantity=take, unit_cost=uc))
        line.cost = sum(t * uc for _, t, uc in allocs)
        total += line.cost
    doc.total_cost = total
    s.flush()
    audit(s, actor, "create_issue", "issue_doc", doc.id, new={"number": doc.number, "cost": total})
    alerts.evaluate_items(s, merged.keys())
    return doc


# ------------------------------------------------------------------ returns
def record_return(s: Session, actor: User, issue_line_id: int, quantity: int, condition: str,
                  reason: str | None = None, return_date: date | None = None) -> ReturnRecord:
    require(actor, "returns.create")
    line = s.get(IssueLine, issue_line_id)
    if quantity <= 0:
        raise AppError("الكمية يجب أن تكون أكبر من صفر.")
    already = s.scalar(select(func.coalesce(func.sum(ReturnRecord.quantity), 0)).where(
        ReturnRecord.issue_line_id == line.id, ReturnRecord.status.in_(["pending", "approved"])))
    if already + quantity > line.quantity:
        raise AppError("كمية المرتجع أكبر من الكمية المصروفة فعليًا في هذا السند.")
    doc = s.get(IssueDoc, line.doc_id)
    r = ReturnRecord(number=next_number(s, "return", "RET"), issue_line_id=line.id,
                     department_id=doc.department_id, item_id=line.item_id, quantity=quantity,
                     condition=condition, reason=reason, return_date=return_date or date.today(),
                     created_by=actor.id)
    s.add(r); s.flush()
    audit(s, actor, "record_return", "return", r.id, new={"qty": quantity, "condition": condition})
    return r


def approve_return(s: Session, actor: User, return_id: int, approve: bool = True):
    require(actor, "returns.approve")
    r = s.get(ReturnRecord, return_id)
    if r.status != "pending":
        raise AppError("تمت معالجة هذا المرتجع من قبل.")
    if not approve:
        r.status = "rejected"; r.approved_by = actor.id
        audit(s, actor, "reject_return", "return", r.id)
        return r
    r.status = "approved"; r.approved_by = actor.id
    if r.condition == "reusable":
        line = s.get(IssueLine, r.issue_line_id)
        need, cost = r.quantity, 0
        # return to the ORIGINAL batches (latest-consumed first), preserving unit cost
        for a in sorted(line.allocations, key=lambda x: -x.id):
            room = a.quantity - a.returned_qty
            if room <= 0 or need == 0:
                continue
            take = min(room, need)
            b = s.get(Batch, a.batch_id)
            if b.status == "cancelled":
                raise AppError("الدفعة الأصلية ملغاة؛ يلزم قرار إداري لتحديد دفعة بديلة.")
            a.returned_qty += take
            b.remaining_qty += take
            if b.status == "depleted":
                b.status = "active"
            _move(s, item_id=r.item_id, batch=b, kind="return", qty_delta=take, doc_type="return",
                  doc_id=r.id, user=actor, move_date=r.return_date, dept_id=r.department_id)
            cost += take * a.unit_cost
            need -= take
        r.cost = cost
        s.flush()
        alerts.evaluate_items(s, [r.item_id])
    audit(s, actor, "approve_return", "return", r.id, new={"condition": r.condition})
    return r


# ------------------------------------------------------------------ damage / loss / expiry
def record_damage(s: Session, actor: User, batch_id: int, quantity: int, reason_type: str,
                  reason: str | None = None, event_date: date | None = None) -> DamageRecord:
    require(actor, "damage.create")
    b = s.get(Batch, batch_id)
    if quantity <= 0 or quantity > b.remaining_qty:
        raise AppError("كمية الهالك أكبر من المتبقي في الدفعة أو غير صحيحة.")
    b.remaining_qty -= quantity
    if b.remaining_qty == 0:
        b.status = "depleted"
    ev = event_date or date.today()
    rec = DamageRecord(item_id=b.item_id, batch_id=b.id, quantity=quantity, reason_type=reason_type,
                       reason=reason, event_date=ev, reported_by=actor.id,
                       approved_by=actor.id if actor.has("stocktake.approve") else None,
                       cost=quantity * b.unit_cost)
    s.add(rec); s.flush()
    _move(s, item_id=b.item_id, batch=b, kind="damage", qty_delta=-quantity, doc_type="damage",
          doc_id=rec.id, user=actor, move_date=ev)
    audit(s, actor, "record_damage", "damage", rec.id, new={"qty": quantity, "type": reason_type})
    alerts.evaluate_items(s, [b.item_id])
    return rec


# ------------------------------------------------------------------ stocktaking
def start_stocktake(s: Session, actor: User, item_ids=None, notes=None) -> StocktakeSession:
    require(actor, "stocktake.manage")
    ids = item_ids or list(s.scalars(select(Item.id).where(Item.active.is_(True))))
    ss = StocktakeSession(number=next_number(s, "stocktake", "CNT"), created_by=actor.id, notes=notes)
    for i in ids:
        ss.lines.append(StocktakeLine(item_id=i, book_qty=onhand_qty(s, i)))
    s.add(ss); s.flush()
    audit(s, actor, "start_stocktake", "stocktake", ss.id)
    return ss


def record_count(s: Session, actor: User, session_id: int, item_id: int, counted: int, explanation=None):
    require(actor, "stocktake.manage")
    ss = s.get(StocktakeSession, session_id)
    if ss.status != "open":
        raise AppError("جلسة الجرد مغلقة.")
    if counted < 0:
        raise AppError("الكمية المعدودة لا يمكن أن تكون سالبة.")
    ln = next(l for l in ss.lines if l.item_id == item_id)
    ln.counted_qty = counted; ln.explanation = explanation


def submit_stocktake(s: Session, actor: User, session_id: int):
    require(actor, "stocktake.manage")
    ss = s.get(StocktakeSession, session_id)
    if ss.status != "open":
        raise AppError("جلسة الجرد مغلقة.")
    for l in ss.lines:
        if l.counted_qty is not None and l.counted_qty != l.book_qty and not (l.explanation or "").strip():
            raise AppError("يجب كتابة تفسير لكل فرق بين الرصيد الدفتري والفعلي.")
    ss.status = "submitted"
    audit(s, actor, "submit_stocktake", "stocktake", ss.id)


def approve_stocktake(s: Session, actor: User, session_id: int):
    require(actor, "stocktake.approve")
    ss = s.get(StocktakeSession, session_id)
    if ss.status != "submitted":
        raise AppError("يجب تقديم الجرد للاعتماد أولًا، أو تم اعتماده من قبل.")
    touched = []
    for l in ss.lines:
        if l.counted_qty is None:
            continue
        # Re-check the book quantity: if stock moved since the count started, block.
        if onhand_qty(s, l.item_id) != l.book_qty:
            raise AppError("تغير رصيد أحد الأصناف بعد بدء الجرد؛ يرجى إعادة الجرد لهذا الصنف.")
        diff = l.counted_qty - l.book_qty
        if diff < 0:
            allocs = _consume(s, l.item_id, -diff, kind="adjustment", doc_type="stocktake", doc_id=ss.id,
                              user=actor, move_date=date.today(), include_expired=True)
            l.cost_effect = -sum(t * uc for _, t, uc in allocs)     # FIFO cost of the shortage
        elif diff > 0:
            last = s.scalar(select(Batch).where(Batch.item_id == l.item_id)
                            .order_by(Batch.received_date.desc(), Batch.received_seq.desc()).limit(1))
            uc = last.unit_cost if last else 0      # documented: surplus valued at most recent batch cost
            _new_batch(s, l.item_id, diff, uc, date.today(), None, None, "adjustment", actor,
                       "stocktake", ss.id)
            l.cost_effect = diff * uc
        else:
            l.cost_effect = 0
        touched.append(l.item_id)
    ss.status = "approved"; ss.approved_by = actor.id; ss.approved_at = now()
    audit(s, actor, "approve_stocktake", "stocktake", ss.id)
    alerts.evaluate_items(s, touched)


def get_issue_docs_for_return(s: Session, search: str = ""):
    q = select(IssueDoc).where(IssueDoc.status == "confirmed")
    if search.strip():
        term = f"%{search.strip()}%"
        q = q.where(or_(IssueDoc.number.ilike(term), IssueDoc.recipient.ilike(term)))
    docs = list(s.scalars(q.order_by(IssueDoc.issued_at.desc()).limit(50)))
    result = []
    for doc in docs:
        lines_info = []
        for line in doc.lines:
            already = s.scalar(select(func.coalesce(func.sum(ReturnRecord.quantity), 0)).where(
                ReturnRecord.issue_line_id == line.id, ReturnRecord.status.in_(["pending", "approved"]))) or 0
            eligible = line.quantity - already
            if eligible > 0:
                lines_info.append({
                    "line_id": line.id,
                    "item_id": line.item_id,
                    "item_code": line.item.code,
                    "item_name": line.item.name,
                    "unit_name": line.item.unit.name if line.item.unit else "",
                    "issued_qty": line.quantity,
                    "returned_qty": already,
                    "eligible_qty": eligible,
                    "cost": line.cost
                })
        if lines_info:
            result.append({
                "doc_id": doc.id,
                "number": doc.number,
                "department_name": doc.department.name if doc.department else "",
                "department_id": doc.department_id,
                "recipient": doc.recipient or "",
                "issued_at": doc.issued_at,
                "lines": lines_info
            })
    return result


def list_returns(s: Session, status: str = None):
    q = select(ReturnRecord)
    if status:
        q = q.where(ReturnRecord.status == status)
    returns = list(s.scalars(q.order_by(ReturnRecord.id.desc())))
    result = []
    for r in returns:
        item = s.get(Item, r.item_id)
        dept = s.get(Department, r.department_id)
        creator = s.get(User, r.created_by)
        approver = s.get(User, r.approved_by) if r.approved_by else None
        result.append({
            "id": r.id,
            "number": r.number,
            "return_date": r.return_date,
            "item_name": item.name if item else "",
            "item_code": item.code if item else "",
            "dept_name": dept.name if dept else "",
            "quantity": r.quantity,
            "condition": r.condition,
            "reason": r.reason or "",
            "status": r.status,
            "cost": r.cost,
            "creator_name": creator.display_name if creator else "",
            "approver_name": approver.display_name if approver else ""
        })
    return result


def list_batches_for_damage(s: Session, item_id: int):
    batches = list(s.scalars(select(Batch).where(
        Batch.item_id == item_id,
        Batch.status == "active",
        Batch.remaining_qty > 0
    ).order_by(Batch.received_date, Batch.received_seq)))
    return [{
        "id": b.id,
        "received_date": b.received_date,
        "remaining_qty": b.remaining_qty,
        "unit_cost": b.unit_cost,
        "expiry_date": b.expiry_date
    } for b in batches]


def list_damage_records(s: Session):
    records = list(s.scalars(select(DamageRecord).order_by(DamageRecord.id.desc())))
    result = []
    for rec in records:
        item = s.get(Item, rec.item_id)
        reporter = s.get(User, rec.reported_by)
        approver = s.get(User, rec.approved_by) if rec.approved_by else None
        result.append({
            "id": rec.id,
            "item_name": item.name if item else "",
            "item_code": item.code if item else "",
            "batch_id": rec.batch_id,
            "quantity": rec.quantity,
            "reason_type": rec.reason_type,
            "reason": rec.reason or "",
            "cost": rec.cost,
            "event_date": rec.event_date,
            "reporter_name": reporter.display_name if reporter else "",
            "approver_name": approver.display_name if approver else ""
        })
    return result


def list_stocktake_sessions(s: Session):
    sessions = list(s.scalars(select(StocktakeSession).order_by(StocktakeSession.id.desc())))
    result = []
    for ss in sessions:
        creator = s.get(User, ss.created_by)
        approver = s.get(User, ss.approved_by) if ss.approved_by else None
        total_items = len(ss.lines)
        counted_items = sum(1 for l in ss.lines if l.counted_qty is not None)
        has_diff = any(l.counted_qty is not None and l.counted_qty != l.book_qty for l in ss.lines)
        result.append({
            "id": ss.id,
            "number": ss.number,
            "status": ss.status,
            "created_at": ss.created_at,
            "approved_at": ss.approved_at,
            "creator_name": creator.display_name if creator else "",
            "approver_name": approver.display_name if approver else "",
            "total_items": total_items,
            "counted_items": counted_items,
            "has_diff": has_diff,
            "notes": ss.notes or ""
        })
    return result


def get_stocktake_details(s: Session, session_id: int):
    ss = s.get(StocktakeSession, session_id)
    if not ss:
        raise AppError("جلسة الجرد غير موجودة.")
    lines = []
    for l in ss.lines:
        item = s.get(Item, l.item_id)
        diff = (l.counted_qty - l.book_qty) if l.counted_qty is not None else None
        lines.append({
            "id": l.id,
            "item_id": l.item_id,
            "item_code": item.code if item else "",
            "item_name": item.name if item else "",
            "unit_name": item.unit.name if item and item.unit else "",
            "book_qty": l.book_qty,
            "counted_qty": l.counted_qty,
            "diff": diff,
            "explanation": l.explanation or "",
            "cost_effect": l.cost_effect
        })
    return {
        "id": ss.id,
        "number": ss.number,
        "status": ss.status,
        "created_at": ss.created_at,
        "approved_at": ss.approved_at,
        "notes": ss.notes or "",
        "lines": lines
    }


def cancel_stocktake(s: Session, actor: User, session_id: int, reason: str = ""):
    require(actor, "stocktake.manage")
    ss = s.get(StocktakeSession, session_id)
    if not ss:
        raise AppError("جلسة الجرد غير موجودة.")
    if ss.status == "approved":
        raise AppError("لا يمكن إلغاء جلسة جرد تم اعتمادها وتطبيق تسوياتها.")
    ss.status = "cancelled"
    audit(s, actor, "cancel_stocktake", "stocktake", ss.id, reason=reason)


def get_unpaid_purchase_docs(s: Session, supplier_id: int | None = None):
    q = select(IncomingDoc).where(
        IncomingDoc.source_type == "purchase",
        IncomingDoc.status == "confirmed"
    )
    if supplier_id:
        q = q.where(IncomingDoc.supplier_id == supplier_id)
    docs = list(s.scalars(q.order_by(IncomingDoc.doc_date.desc(), IncomingDoc.id.desc())))
    unpaid = []
    for d in docs:
        tot = doc_total(d)
        paid = paid_total(s, d.id)
        rem = tot - paid
        if rem > 0:
            supplier = s.get(Supplier, d.supplier_id)
            unpaid.append({
                "doc_id": d.id,
                "number": d.number,
                "doc_date": d.doc_date,
                "supplier_id": d.supplier_id,
                "supplier_name": supplier.name if supplier else "",
                "reference": d.reference or "",
                "total_cost": tot,
                "paid": paid,
                "outstanding": rem
            })
    return unpaid


def list_supplier_payments(s: Session, supplier_id: int | None = None, d1: date | None = None, d2: date | None = None):
    q = select(SupplierPayment).order_by(SupplierPayment.pay_date.desc(), SupplierPayment.id.desc())
    if d1:
        q = q.where(SupplierPayment.pay_date >= d1)
    if d2:
        q = q.where(SupplierPayment.pay_date <= d2)
    payments = list(s.scalars(q))
    result = []
    for p in payments:
        doc = s.get(IncomingDoc, p.doc_id)
        if not doc:
            continue
        if supplier_id and doc.supplier_id != supplier_id:
            continue
        supplier = s.get(Supplier, doc.supplier_id)
        creator = s.get(User, p.created_by)
        tot = doc_total(doc)
        paid_so_far = paid_total(s, doc.id)
        rem = tot - paid_so_far
        result.append({
            "id": p.id,
            "pay_date": p.pay_date,
            "doc_number": doc.number,
            "doc_id": doc.id,
            "supplier_name": supplier.name if supplier else "",
            "supplier_id": doc.supplier_id,
            "amount": p.amount,
            "method": p.method or "",
            "notes": p.notes or "",
            "doc_total": tot,
            "remaining": rem,
            "creator_name": creator.display_name if creator else ""
        })
    return result


def list_inkind_donations(s: Session):
    docs = list(s.scalars(select(IncomingDoc).where(
        IncomingDoc.source_type == "donation"
    ).order_by(IncomingDoc.doc_date.desc(), IncomingDoc.id.desc())))
    result = []
    for d in docs:
        creator = s.get(User, d.created_by)
        items_summary = ", ".join(
            f"{(s.get(Item, l.item_id).name if s.get(Item, l.item_id) else '')} ({l.quantity})"
            for l in d.lines
        )
        tot = sum(l.quantity * l.unit_cost for l in d.lines)
        result.append({
            "id": d.id,
            "number": d.number,
            "doc_date": d.doc_date,
            "donor_name": d.donor_name or "فاعل خير",
            "reference": d.reference or "",
            "status": d.status,
            "items_summary": items_summary,
            "estimated_value": tot,
            "creator_name": creator.display_name if creator else "",
            "notes": d.notes or ""
        })
    return result


def list_cash_donations(s: Session):
    moves = list(s.scalars(select(CashMovement).where(
        CashMovement.kind == "cash_donation"
    ).order_by(CashMovement.move_date.desc(), CashMovement.id.desc())))
    result = []
    for m in moves:
        creator = s.get(User, m.created_by)
        result.append({
            "id": m.id,
            "move_date": m.move_date,
            "donor_name": m.donor_name or "فاعل خير",
            "amount": m.amount,
            "creator_name": creator.display_name if creator else "",
            "notes": m.notes or ""
        })
    return result


