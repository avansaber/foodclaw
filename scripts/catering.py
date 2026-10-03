"""FoodClaw — catering domain module

Actions for the catering domain (3 tables, 11 actions).
Imported by db_query.py (unified router).
"""
import json
import os
import sys
import uuid
from datetime import datetime, timezone
from decimal import Decimal, ROUND_HALF_UP

try:
    import importlib.util
    if importlib.util.find_spec("erpclaw_lib") is None:
        sys.path.insert(0, os.path.join(os.path.expanduser(os.environ.get("ERPCLAW_HOME", "~/.openclaw/erpclaw")), "lib"))
    from erpclaw_lib.db import get_connection
    from erpclaw_lib.decimal_utils import to_decimal, round_currency
    from erpclaw_lib.naming import get_next_name, ENTITY_PREFIXES
    from erpclaw_lib.response import ok, err, row_to_dict
    from erpclaw_lib.audit import audit
    from erpclaw_lib.query import Q, P, Table, Field, fn, Order, insert_row, update_row, dynamic_update, line_order
    from erpclaw_lib.cross_skill import ensure_service_item, create_invoice, submit_invoice, CrossSkillError
    from erpclaw_lib import cross_skill

    ENTITY_PREFIXES.setdefault("foodclaw_catering_event", "CATER-")
except ImportError:
    pass

SKILL = "foodclaw"

CATERING_VOUCHER_TYPE = "food_catering_revenue"

CATERING_ITEM_CODE = "FOOD-CATERING"
CATERING_ITEM_NAME = "Catering service"

DEPOSIT_REFERENCE_PREFIX = "CATERING-DEPOSIT "


def _deposit_reference(event_id):
    return DEPOSIT_REFERENCE_PREFIX + event_id


def _event_deposits(conn, company_id, event_id, status):
    pe = Table("payment_entry")
    q = Q.from_(pe).select(pe.star).where(pe.company_id == P()).where(pe.payment_type == P()).where(pe.party_type == P()).where(pe.reference_number == P()).where(pe.status == P()).orderby(pe.posting_date, line_order(pe))
    rows = conn.execute(q.get_sql(), (company_id, "receive", "customer", _deposit_reference(event_id), status)).fetchall()
    return [row_to_dict(r) for r in rows]


def _company_receivable_account(conn, company_id):
    comp = Table("company")
    crow = conn.execute(Q.from_(comp).select(comp.default_receivable_account_id).where(comp.id == P()).get_sql(), (company_id,)).fetchone()
    if crow is not None:
        defaulted = row_to_dict(crow).get("default_receivable_account_id")
        if defaulted:
            return defaulted
    acct = Table("account")
    aq = Q.from_(acct).select(acct.id).where(acct.account_type == P()).where(acct.company_id == P()).where(acct.is_group == P()).limit(1)
    arow = conn.execute(aq.get_sql(), ("receivable", company_id, 0)).fetchone()
    if arow is not None:
        return dict(arow)["id"]
    return None


def _invoice_posted_receivable(conn, sales_invoice_id):
    ple = Table("payment_ledger_entry")
    rows = conn.execute(Q.from_(ple).select(ple.account_id).where(ple.voucher_type == P()).where(ple.voucher_id == P()).get_sql(), ("sales_invoice", sales_invoice_id)).fetchall()
    if not rows:
        return None
    return dict(rows[0])["account_id"]


def _deposit_unallocated(deposit):
    return to_decimal(deposit.get("unallocated_amount") or "0")

_now_iso = lambda: datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

VALID_EVENT_STATUSES = ("inquiry", "quoted", "confirmed", "in_progress", "completed", "cancelled")


def _validate_company(conn, company_id):
    if not company_id:
        err("--company-id is required")
    row = conn.execute(Q.from_(Table("company")).select(Field("id")).where(Field("id") == P()).get_sql(), (company_id,)).fetchone()
    if not row:
        err(f"Company {company_id} not found")


def _validate_enum(value, valid_values, field_name):
    if value and value not in valid_values:
        err(f"Invalid {field_name}: {value}. Must be one of: {', '.join(valid_values)}")


def _validate_event(conn, event_id):
    if not event_id:
        err("--event-id is required")
    row = conn.execute(Q.from_(Table("foodclaw_catering_event")).select(Field("id")).where(Field("id") == P()).get_sql(), (event_id,)).fetchone()
    if not row:
        err(f"Catering event {event_id} not found")


# ---------------------------------------------------------------------------
# 1. add-catering-event
# ---------------------------------------------------------------------------
def add_catering_event(conn, args):
    _validate_company(conn, args.company_id)
    event_name = getattr(args, "event_name", None)
    if not event_name:
        err("--event-name is required")
    client_name = getattr(args, "client_name", None)
    if not client_name:
        err("--client-name is required")
    event_date = getattr(args, "event_date", None)
    if not event_date:
        err("--event-date is required")

    for field in ("estimated_cost", "quoted_price", "deposit_amount"):
        val = getattr(args, field, None)
        if val:
            to_decimal(val)

    event_id = str(uuid.uuid4())
    ns = get_next_name(conn, "foodclaw_catering_event", company_id=args.company_id)
    now = _now_iso()

    sql, _ = insert_row("foodclaw_catering_event", {"id": P(), "naming_series": P(), "company_id": P(), "event_name": P(), "client_name": P(), "client_phone": P(), "client_email": P(), "event_date": P(), "event_time": P(), "venue": P(), "guest_count": P(), "event_status": P(), "estimated_cost": P(), "quoted_price": P(), "deposit_amount": P(), "notes": P(), "created_at": P(), "updated_at": P()})
    conn.execute(sql, (
        event_id, ns, args.company_id, event_name,
        client_name,
        getattr(args, "client_phone", None),
        getattr(args, "client_email", None),
        event_date,
        getattr(args, "event_time", None),
        getattr(args, "venue", None),
        getattr(args, "guest_count", None) or 0,
        "inquiry",
        getattr(args, "estimated_cost", None) or "0.00",
        getattr(args, "quoted_price", None) or "0.00",
        getattr(args, "deposit_amount", None) or "0.00",
        getattr(args, "notes", None),
        now, now,
    ))
    audit(conn, SKILL, "food-add-catering-event", "foodclaw_catering_event", event_id)
    conn.commit()
    ok({"id": event_id, "naming_series": ns, "event_name": event_name, "event_status": "inquiry"})


# ---------------------------------------------------------------------------
# 2. update-catering-event
# ---------------------------------------------------------------------------
def update_catering_event(conn, args):
    event_id = getattr(args, "event_id", None)
    _validate_event(conn, event_id)
    _validate_enum(getattr(args, "event_status", None), VALID_EVENT_STATUSES, "event-status")

    if getattr(args, "event_status", None) == "completed":
        err("Cannot set event_status to completed with food-update-catering-event; use food-complete-catering-event to complete (and bill) an event")

    if getattr(args, "event_status", None) == "cancelled":
        ev_row = conn.execute(Q.from_(Table("foodclaw_catering_event")).select(Field("company_id")).where(Field("id") == P()).get_sql(), (event_id,)).fetchone()
        ev_company = dict(ev_row)["company_id"] if ev_row is not None else None
        if ev_company is not None:
            for s in _event_deposits(conn, ev_company, event_id, "submitted"):
                left = _deposit_unallocated(s)
                if left > Decimal("0"):
                    err(f"Catering event {event_id} has an unapplied deposit of {round_currency(left)} (payment {s['id']}); apply it to an invoice through payments, or cancel the payment with cancel-payment if the money was returned, before cancelling")

    row = conn.execute(Q.from_(Table("foodclaw_catering_event")).select(Field("event_status")).where(Field("id") == P()).get_sql(), (event_id,)).fetchone()
    current_status = row[0] if row is not None else None
    if current_status == "completed":
        frozen = ("estimated_cost", "quoted_price", "deposit_amount", "final_amount", "revenue_account_id", "receivable_account_id", "cost_center_id", "event_status")
        passed = [f for f in frozen if getattr(args, f, None) is not None]
        if passed:
            err(f"Cannot change {', '.join(passed)} on a completed event: a completed event is billed and its amounts and accounts cannot change")

    updates, params = [], []
    for field, col in [
        ("event_name", "event_name"), ("client_name", "client_name"),
        ("client_phone", "client_phone"), ("client_email", "client_email"),
        ("event_date", "event_date"), ("event_time", "event_time"),
        ("venue", "venue"), ("event_status", "event_status"), ("notes", "notes"),
    ]:
        val = getattr(args, field, None)
        if val is not None:
            updates.append(f"{col} = ?")
            params.append(val)

    gc = getattr(args, "guest_count", None)
    if gc is not None:
        updates.append("guest_count = ?")
        params.append(int(gc))

    for field in ("estimated_cost", "quoted_price", "deposit_amount", "final_amount"):
        val = getattr(args, field, None)
        if val is not None:
            to_decimal(val)
            updates.append(f"{field} = ?")
            params.append(val)

    # GL account configuration fields
    for field in ("revenue_account_id", "receivable_account_id", "cost_center_id"):
        val = getattr(args, field, None)
        if val is not None:
            updates.append(f"{field} = ?")
            params.append(val)

    if not updates:
        err("No fields to update")

    updates.append("updated_at = ?")
    params.append(_now_iso())
    params.append(event_id)

    conn.execute(f"UPDATE foodclaw_catering_event SET {', '.join(updates)} WHERE id = ?", params)
    audit(conn, SKILL, "food-update-catering-event", "foodclaw_catering_event", event_id)
    conn.commit()
    ok({"id": event_id, "updated_fields": [u.split(" = ")[0] for u in updates if u != "updated_at = ?"]})


# ---------------------------------------------------------------------------
# 3. get-catering-event
# ---------------------------------------------------------------------------
def get_catering_event(conn, args):
    event_id = getattr(args, "event_id", None)
    _validate_event(conn, event_id)
    row = conn.execute(Q.from_(Table("foodclaw_catering_event")).select(Table("foodclaw_catering_event").star).where(Field("id") == P()).get_sql(), (event_id,)).fetchone()
    data = row_to_dict(row)

    # Get catering items
    items = conn.execute(Q.from_(Table("foodclaw_catering_item")).select(Table("foodclaw_catering_item").star).where(Field("event_id") == P()).get_sql(), (event_id,)).fetchall()
    data["catering_items"] = [row_to_dict(r) for r in items]
    data["item_count"] = len(items)

    # Get dietary requirements
    diets = conn.execute(Q.from_(Table("foodclaw_dietary_requirement")).select(Table("foodclaw_dietary_requirement").star).where(Field("event_id") == P()).get_sql(), (event_id,)).fetchall()
    data["dietary_requirements"] = [row_to_dict(r) for r in diets]

    ok(data)


# ---------------------------------------------------------------------------
# 4. list-catering-events
# ---------------------------------------------------------------------------
def list_catering_events(conn, args):
    where, params = ["1=1"], []
    if getattr(args, "company_id", None):
        where.append("company_id = ?")
        params.append(args.company_id)
    if getattr(args, "event_status", None):
        _validate_enum(args.event_status, VALID_EVENT_STATUSES, "event-status")
        where.append("event_status = ?")
        params.append(args.event_status)
    if getattr(args, "search", None):
        where.append("(LOWER(event_name) LIKE LOWER(?) OR LOWER(client_name) LIKE LOWER(?))")
        params.extend([f"%{args.search}%", f"%{args.search}%"])

    total = conn.execute(
        f"SELECT COUNT(*) FROM foodclaw_catering_event WHERE {' AND '.join(where)}", params
    ).fetchone()[0]
    rows = conn.execute(
        f"SELECT * FROM foodclaw_catering_event WHERE {' AND '.join(where)} ORDER BY event_date DESC LIMIT ? OFFSET ?",
        params + [getattr(args, "limit", 50), getattr(args, "offset", 0)]
    ).fetchall()
    ok({"items": [row_to_dict(r) for r in rows], "total_count": total})


# ---------------------------------------------------------------------------
# 5. add-catering-item
# ---------------------------------------------------------------------------
def add_catering_item(conn, args):
    event_id = getattr(args, "event_id", None)
    _validate_event(conn, event_id)
    item_name = getattr(args, "item_name", None)
    if not item_name:
        err("--item-name is required")

    quantity = getattr(args, "quantity", None) or 1
    unit_price = getattr(args, "unit_price", None) or "0.00"
    to_decimal(unit_price)
    line_total = str(to_decimal(unit_price) * Decimal(str(quantity)))

    ci_id = str(uuid.uuid4())

    sql, _ = insert_row("foodclaw_catering_item", {"id": P(), "event_id": P(), "menu_item_id": P(), "item_name": P(), "quantity": P(), "unit_price": P(), "line_total": P(), "notes": P(), "created_at": P()})
    conn.execute(sql, (
        ci_id, event_id,
        getattr(args, "menu_item_id", None),
        item_name, int(quantity), unit_price, line_total,
        getattr(args, "notes", None),
        _now_iso(),
    ))
    audit(conn, SKILL, "food-add-catering-item", "foodclaw_catering_item", ci_id)
    conn.commit()
    ok({"id": ci_id, "item_name": item_name, "quantity": int(quantity), "unit_price": unit_price, "line_total": line_total})


# ---------------------------------------------------------------------------
# 6. list-catering-items
# ---------------------------------------------------------------------------
def list_catering_items(conn, args):
    event_id = getattr(args, "event_id", None)
    _validate_event(conn, event_id)

    ci = Table("foodclaw_catering_item")
    rows = conn.execute(
        Q.from_(ci).select(ci.star).where(ci.event_id == P()).orderby(ci.created_at).get_sql(), (event_id,)
    ).fetchall()
    ok({"items": [row_to_dict(r) for r in rows], "total_count": len(rows)})


# ---------------------------------------------------------------------------
# 7. add-dietary-requirement
# ---------------------------------------------------------------------------
def add_dietary_requirement(conn, args):
    event_id = getattr(args, "event_id", None)
    _validate_event(conn, event_id)
    requirement = getattr(args, "requirement", None)
    if not requirement:
        err("--requirement is required")

    dr_id = str(uuid.uuid4())

    sql, _ = insert_row("foodclaw_dietary_requirement", {"id": P(), "event_id": P(), "requirement": P(), "guest_count": P(), "notes": P(), "created_at": P()})
    conn.execute(sql, (
        dr_id, event_id, requirement,
        getattr(args, "guest_count", None) or 1,
        getattr(args, "notes", None),
        _now_iso(),
    ))
    audit(conn, SKILL, "food-add-dietary-requirement", "foodclaw_dietary_requirement", dr_id)
    conn.commit()
    ok({"id": dr_id, "requirement": requirement, "guest_count": getattr(args, "guest_count", None) or 1})


# ---------------------------------------------------------------------------
# 8. list-dietary-requirements
# ---------------------------------------------------------------------------
def list_dietary_requirements(conn, args):
    event_id = getattr(args, "event_id", None)
    _validate_event(conn, event_id)

    rows = conn.execute(Q.from_(Table("foodclaw_dietary_requirement")).select(Table("foodclaw_dietary_requirement").star).where(Field("event_id") == P()).get_sql(), (event_id,)).fetchall()
    ok({"items": [row_to_dict(r) for r in rows], "total_count": len(rows)})


# ---------------------------------------------------------------------------
# 9. confirm-event
# ---------------------------------------------------------------------------
def confirm_event(conn, args):
    event_id = getattr(args, "event_id", None)
    _validate_event(conn, event_id)

    row = conn.execute(Q.from_(Table("foodclaw_catering_event")).select(Field("event_status")).where(Field("id") == P()).get_sql(), (event_id,)).fetchone()
    if row[0] not in ("inquiry", "quoted"):
        err(f"Cannot confirm: event status is '{row[0]}', expected 'inquiry' or 'quoted'")

    now = _now_iso()
    sql, upd_params = dynamic_update("foodclaw_catering_event", {
        "event_status": "confirmed",
        "updated_at": now,
    }, where={"id": event_id})
    conn.execute(sql, upd_params)
    audit(conn, SKILL, "food-confirm-event", "foodclaw_catering_event", event_id)
    conn.commit()
    ok({"id": event_id, "event_status": "confirmed"})


# ---------------------------------------------------------------------------
# 10. complete-catering-event (with GL posting for revenue recognition)
# ---------------------------------------------------------------------------
def complete_catering_event(conn, args):
    """Complete a catering event by billing a submitted sales invoice.

    The customer is billed through the selling module's own actions: FoodClaw
    ensures the catering service item, creates a draft sales invoice, records
    its link row, and submits the invoice. The event becomes completed only
    after the invoice is submitted. A failed submit leaves the named draft and
    the link behind while the event stays confirmed, so completing again
    finishes that same draft and never creates a second invoice.
    """
    event_id = getattr(args, "event_id", None)
    _validate_event(conn, event_id)

    row = conn.execute(Q.from_(Table("foodclaw_catering_event")).select(Table("foodclaw_catering_event").star).where(Field("id") == P()).get_sql(), (event_id,)).fetchone()
    event = row_to_dict(row)

    if event["event_status"] not in ("confirmed", "in_progress"):
        err(f"Cannot complete: event status is '{event['event_status']}', "
            "expected 'confirmed' or 'in_progress'")

    ci = Table("foodclaw_catering_item")
    item_rows = conn.execute(
        Q.from_(ci).select(ci.star).where(ci.event_id == P()).orderby(ci.created_at, line_order(ci)).get_sql(), (event_id,)).fetchall()
    items = [row_to_dict(r) for r in item_rows]

    final_amount_arg = getattr(args, "final_amount", None)
    if final_amount_arg:
        to_decimal(final_amount_arg)
        total_raw = final_amount_arg
    elif event.get("final_amount") and to_decimal(event["final_amount"]) > Decimal("0"):
        total_raw = event["final_amount"]
    elif event.get("quoted_price") and to_decimal(event["quoted_price"]) > Decimal("0"):
        total_raw = event["quoted_price"]
    else:
        items_sum = Decimal("0")
        for d in items:
            items_sum += round_currency(Decimal(int(d.get("quantity") or 0)) * to_decimal(d.get("unit_price")))
        total_raw = str(items_sum)
    total = round_currency(to_decimal(total_raw))
    if total <= Decimal("0"):
        err("Cannot complete event with zero or negative revenue amount")

    customer_id = getattr(args, "customer_id", None)
    if not customer_id:
        err("--customer-id is required to complete a catering event: the sales invoice must name the customer who owes it")
    found = conn.execute(
        Q.from_(Table("customer")).select(Field("id"))
        .where(Field("id") == P()).where(Field("company_id") == P()).get_sql(),
        (customer_id, event["company_id"])).fetchone()
    if not found:
        err(f"Customer {customer_id} not found in company {event['company_id']}")

    company_id = event["company_id"]
    db_path = getattr(args, "db_path", None)

    submitted_deposits = _event_deposits(conn, company_id, event_id, "submitted")
    for s in submitted_deposits:
        if s["party_id"] != customer_id:
            err(f"Catering event {event_id} has a deposit from customer {s['party_id']} (payment {s['id']}); complete it for that customer")
    draft_deposits = _event_deposits(conn, company_id, event_id, "draft")
    if draft_deposits:
        err(f"Catering event {event_id} has an unfinished deposit payment {draft_deposits[0]['id']}; receive the deposit again to finish it, or delete it through payments, before completing")
    preview_table = Table("foodclaw_catering_invoice")
    preview_row = conn.execute(
        Q.from_(preview_table).select(preview_table.star).where(preview_table.event_id == P()).get_sql(), (event_id,)).fetchone()
    expected_receivable = None
    if preview_row is None:
        expected_receivable = _company_receivable_account(conn, company_id)
    else:
        preview_link = row_to_dict(preview_row)
        preview_si = conn.execute(
            Q.from_(Table("sales_invoice")).select(Field("status")).where(Field("id") == P()).get_sql(), (preview_link["sales_invoice_id"],)).fetchone()
        if preview_si is not None:
            preview_status = row_to_dict(preview_si)["status"]
            if preview_status != "cancelled":
                if preview_status == "draft":
                    expected_receivable = _company_receivable_account(conn, company_id)
                else:
                    expected_receivable = _invoice_posted_receivable(conn, preview_link["sales_invoice_id"])
                    if expected_receivable is None:
                        expected_receivable = _company_receivable_account(conn, company_id)
    if expected_receivable is not None:
        for s in submitted_deposits:
            if _deposit_unallocated(s) > Decimal("0") and s.get("paid_from_account") != expected_receivable:
                err(f"Deposit {s['id']} was received to receivable {s.get('paid_from_account')}, but the invoice for catering event {event_id} posts to {expected_receivable}; apply it through payments")

    link_table = Table("foodclaw_catering_invoice")
    link_row = conn.execute(
        Q.from_(link_table).select(link_table.star).where(link_table.event_id == P()).get_sql(), (event_id,)).fetchone()
    if link_row is not None:
        link = row_to_dict(link_row)
        link_customer = link["customer_id"]
        link_si = link["sales_invoice_id"]
        link_amount = link["amount"]
        if customer_id != link_customer:
            err(f"Catering event {event_id} is already billed to customer {link_customer} (sales invoice {link_si})")
        if final_amount_arg and round_currency(to_decimal(final_amount_arg)) != round_currency(to_decimal(link_amount)):
            err(f"Catering event {event_id} is already billed for {link_amount} (sales invoice {link_si}); the amount cannot change")
        si_table = Table("sales_invoice")
        si_row = conn.execute(
            Q.from_(si_table).select(Field("status"), Field("customer_id"), Field("total_amount")).where(Field("id") == P()).get_sql(), (link_si,)).fetchone()
        if si_row is None:
            err(f"Sales invoice {link_si} linked to catering event {event_id} was not found")
        si = row_to_dict(si_row)
        if si["status"] == "cancelled":
            err(f"Sales invoice {link_si} for catering event {event_id} is cancelled")
        si_total = round_currency(to_decimal(si["total_amount"]))
        if si["customer_id"] != link_customer or si_total != round_currency(to_decimal(link_amount)):
            err(f"Sales invoice {link_si} for catering event {event_id} no longer matches its link (customer {si['customer_id']}, total {si_total}; the link says {link_customer}, {link_amount})")
        if si["status"] == "draft":
            try:
                submit_invoice(link_si, db_path=db_path)
            except CrossSkillError as e:
                err(f"Sales invoice {link_si} was created for catering event {event_id} but could not be submitted: {e}")
        total = round_currency(to_decimal(link_amount))
        si_id = link_si
        billed_customer = link_customer
        resumed = True
    else:
        try:
            item_id = ensure_service_item(company_id, db_path, item_code=CATERING_ITEM_CODE, item_name=CATERING_ITEM_NAME)
            items_sum = Decimal("0")
            per_item = []
            items_usable = len(items) > 0
            for d in items:
                qty = int(d.get("quantity") or 0)
                price = to_decimal(d.get("unit_price"))
                if qty < 1 or price < Decimal("0"):
                    items_usable = False
                billed = round_currency(Decimal(qty) * price)
                items_sum += billed
                per_item.append({"item_id": item_id, "qty": str(qty), "rate": str(price), "description": d.get("item_name")})
            if items_usable and items_sum == total:
                lines = per_item
            else:
                lines = [{"item_id": item_id, "qty": "1", "rate": str(total), "description": event.get("event_name")}]
            created = create_invoice(customer_id=customer_id, items=lines, company_id=company_id, posting_date=event.get("event_date"), db_path=db_path)
        except CrossSkillError as e:
            err(f"Catering invoice could not be created: {e}")
        si_id = (created or {}).get("sales_invoice_id")
        if not si_id:
            err("Catering invoice could not be created: sales invoice creation returned no id")
        billed = round_currency(to_decimal(created.get("total_amount")))
        if billed != total:
            err(f"Sales invoice {si_id} totals {billed}, not {total}, for catering event {event_id} (a selling price rule changed a line); it is an unlinked draft: delete it through selling, then complete again")
        link_id = str(uuid.uuid4())
        now = _now_iso()
        sql, _ = insert_row("foodclaw_catering_invoice", {"id": P(), "event_id": P(), "sales_invoice_id": P(), "customer_id": P(), "amount": P(), "company_id": P(), "created_at": P()})
        conn.execute(sql, (link_id, event_id, si_id, customer_id, str(total), company_id, now))
        audit(conn, SKILL, "food-complete-catering-event", "foodclaw_catering_invoice", link_id,
              new_values={"event_id": event_id, "sales_invoice_id": si_id, "customer_id": customer_id, "amount": str(total)})
        conn.commit()
        try:
            submit_invoice(si_id, db_path=db_path)
        except CrossSkillError as e:
            err(f"Sales invoice {si_id} was created for catering event {event_id} but could not be submitted: {e}")
        billed_customer = customer_id
        resumed = False

    si_table = Table("sales_invoice")
    pe_table = Table("payment_entry")
    si_out = conn.execute(Q.from_(si_table).select(Field("outstanding_amount")).where(Field("id") == P()).get_sql(), (si_id,)).fetchone()
    current_outstanding = to_decimal(dict(si_out)["outstanding_amount"])
    deposits_applied = []
    for dep in _event_deposits(conn, company_id, event_id, "submitted"):
        pe_id = dep["id"]
        pe_row = conn.execute(Q.from_(pe_table).select(Field("unallocated_amount")).where(Field("id") == P()).get_sql(), (pe_id,)).fetchone()
        if pe_row is None:
            continue
        unallocated = to_decimal(dict(pe_row)["unallocated_amount"])
        if unallocated <= Decimal("0"):
            continue
        si_row = conn.execute(Q.from_(si_table).select(Field("outstanding_amount")).where(Field("id") == P()).get_sql(), (si_id,)).fetchone()
        current_outstanding = to_decimal(dict(si_row)["outstanding_amount"])
        if current_outstanding <= Decimal("0"):
            break
        take = min(unallocated, current_outstanding)
        take_str = str(round_currency(take))
        try:
            cross_skill.call_skill_action("erpclaw", "allocate-payment", {"--payment-entry-id": pe_id, "--voucher-type": "sales_invoice", "--voucher-id": si_id, "--allocated-amount": take_str}, db_path=db_path)
        except cross_skill.CrossSkillError as e:
            err(f"Deposit {pe_id} could not be applied to sales invoice {si_id} for catering event {event_id}: {e}; complete the event again to finish")
        si_after = conn.execute(Q.from_(si_table).select(Field("outstanding_amount")).where(Field("id") == P()).get_sql(), (si_id,)).fetchone()
        current_outstanding = to_decimal(dict(si_after)["outstanding_amount"])
        deposits_applied.append({"payment_entry_id": pe_id, "allocated_amount": take_str})
    si_final = conn.execute(Q.from_(si_table).select(Field("outstanding_amount")).where(Field("id") == P()).get_sql(), (si_id,)).fetchone()
    final_outstanding_str = dict(si_final)["outstanding_amount"]
    remainder = Decimal("0")
    for dep in _event_deposits(conn, company_id, event_id, "submitted"):
        pe_row = conn.execute(Q.from_(pe_table).select(Field("unallocated_amount")).where(Field("id") == P()).get_sql(), (dep["id"],)).fetchone()
        if pe_row is not None:
            left = to_decimal(dict(pe_row)["unallocated_amount"])
            if left > Decimal("0"):
                remainder += left
    deposit_unapplied_str = str(round_currency(remainder))

    now = _now_iso()
    sql, upd_params = dynamic_update("foodclaw_catering_event", {
        "event_status": "completed",
        "final_amount": str(total),
        "updated_at": now,
    }, where={"id": event_id})
    conn.execute(sql, upd_params)
    audit(conn, SKILL, "food-complete-catering-event", "foodclaw_catering_event", event_id,
          new_values={"event_status": "completed", "final_amount": str(total), "sales_invoice_id": si_id, "deposits_applied": deposits_applied, "deposit_unapplied": deposit_unapplied_str})
    conn.commit()

    ok({"id": event_id, "event_status": "completed", "final_amount": str(total),
        "sales_invoice_id": si_id, "customer_id": billed_customer, "resumed": resumed,
        "deposits_applied": deposits_applied, "outstanding_amount": final_outstanding_str, "deposit_unapplied": deposit_unapplied_str})

# ---------------------------------------------------------------------------
# 11. catering-cost-estimate
# ---------------------------------------------------------------------------
def catering_cost_estimate(conn, args):
    """Estimate cost vs selling price for a catering event."""
    event_id = getattr(args, "event_id", None)
    _validate_event(conn, event_id)

    event = conn.execute(Q.from_(Table("foodclaw_catering_event")).select(Table("foodclaw_catering_event").star).where(Field("id") == P()).get_sql(), (event_id,)).fetchone()
    event_data = row_to_dict(event)

    items = conn.execute(Q.from_(Table("foodclaw_catering_item")).select(Table("foodclaw_catering_item").star).where(Field("event_id") == P()).get_sql(), (event_id,)).fetchall()

    cent = Decimal("0.01")
    estimated_dec = to_decimal(event_data.get("estimated_cost") or "0.00")
    estimated_str = str(estimated_dec.quantize(cent, rounding=ROUND_HALF_UP))

    total_price_dec = Decimal("0.00")
    rows = []
    for r in items:
        d = row_to_dict(r)
        total_price_dec += to_decimal(d.get("line_total") or "0.00")
        rows.append(d)

    linked_ids = sorted({d.get("menu_item_id") for d in rows if d.get("menu_item_id")})
    cost_by_id = {}
    if linked_ids:
        menu = Table("foodclaw_menu_item")
        query = Q.from_(menu).select(Field("id"), Field("cost")).where(Field("id").isin([P() for _ in linked_ids]))
        for mrow in conn.execute(query.get_sql(), tuple(linked_ids)).fetchall():
            md = row_to_dict(mrow)
            cost_by_id[md["id"]] = to_decimal(md.get("cost") or "0.00")

    item_list = []
    menu_cost_dec = Decimal("0.00")
    linked_count = 0
    for d in rows:
        quantity = d.get("quantity") or 0
        unit_price_str = str(to_decimal(d.get("unit_price") or "0.00").quantize(cent, rounding=ROUND_HALF_UP))
        line_total_str = str(to_decimal(d.get("line_total") or "0.00").quantize(cent, rounding=ROUND_HALF_UP))
        menu_item_id = d.get("menu_item_id")
        if menu_item_id and menu_item_id in cost_by_id:
            unit_cost_dec = cost_by_id[menu_item_id]
            unit_cost_str = str(unit_cost_dec.quantize(cent, rounding=ROUND_HALF_UP))
            line_cost_dec = (unit_cost_dec * Decimal(str(int(quantity)))).quantize(cent, rounding=ROUND_HALF_UP)
            line_cost_str = str(line_cost_dec)
            menu_cost_dec += line_cost_dec
            linked_count += 1
        else:
            unit_cost_str = None
            line_cost_str = None
        item_list.append({"item_name": d["item_name"], "quantity": d["quantity"], "unit_price": unit_price_str, "line_total": line_total_str, "unit_cost": unit_cost_str, "line_cost": line_cost_str})

    menu_cost_str = str(menu_cost_dec.quantize(cent, rounding=ROUND_HALF_UP))
    unlinked_count = len(item_list) - linked_count

    total_price_str = str(total_price_dec.quantize(cent, rounding=ROUND_HALF_UP))

    guest_count = event_data.get("guest_count", 0) or 0
    price_per_guest = "0.00"
    if guest_count and int(guest_count) > 0:
        price_per_guest = str((total_price_dec / Decimal(str(int(guest_count)))).quantize(cent, rounding=ROUND_HALF_UP))

    if estimated_dec > Decimal("0"):
        total_cost_str = estimated_str
        cost_source = "event_estimate"
    elif linked_count > 0:
        total_cost_str = menu_cost_str
        cost_source = "menu_item_cost"
    else:
        total_cost_str = "0.00"
        cost_source = "none"

    total_cost_dec = to_decimal(total_cost_str)
    cost_per_guest = "0.00"
    if guest_count and int(guest_count) > 0:
        cost_per_guest = str((total_cost_dec / Decimal(str(int(guest_count)))).quantize(cent, rounding=ROUND_HALF_UP))

    if cost_source == "none":
        estimated_margin = None
    else:
        estimated_margin = str((total_price_dec - total_cost_dec).quantize(cent, rounding=ROUND_HALF_UP))

    ok({
        "event_id": event_id,
        "event_name": event_data.get("event_name"),
        "guest_count": guest_count,
        "items": item_list,
        "total_price": total_price_str,
        "price_per_guest": price_per_guest,
        "estimated_cost": estimated_str,
        "menu_cost": menu_cost_str,
        "unlinked_item_count": unlinked_count,
        "total_cost": total_cost_str,
        "cost_source": cost_source,
        "cost_per_guest": cost_per_guest,
        "estimated_margin": estimated_margin,
    })


# ---------------------------------------------------------------------------
# 12. receive-catering-deposit
# ---------------------------------------------------------------------------
def receive_catering_deposit(conn, args):
    event_id = getattr(args, "event_id", None)
    _validate_event(conn, event_id)
    row = conn.execute(Q.from_(Table("foodclaw_catering_event")).select(Table("foodclaw_catering_event").star).where(Field("id") == P()).get_sql(), (event_id,)).fetchone()
    event = row_to_dict(row)
    if event["event_status"] not in ("quoted", "confirmed", "in_progress"):
        err(f"Cannot receive a deposit: event status is '{event['event_status']}', expected 'quoted', 'confirmed' or 'in_progress'")
    customer_id = getattr(args, "customer_id", None)
    if not customer_id:
        err("--customer-id is required to receive a catering deposit: the payment must name the customer who paid it")
    company_id = event["company_id"]
    found = conn.execute(Q.from_(Table("customer")).select(Field("id")).where(Field("id") == P()).where(Field("company_id") == P()).get_sql(), (customer_id, company_id)).fetchone()
    if not found:
        err(f"Customer {customer_id} not found in company {company_id}")
    submitted = _event_deposits(conn, company_id, event_id, "submitted")
    for s in submitted:
        if s["party_id"] != customer_id:
            err(f"Catering event {event_id} already has a deposit from customer {s['party_id']} (payment {s['id']})")
    received_sum = sum((to_decimal(r.get("paid_amount") or "0") for r in submitted), Decimal("0"))
    received = round_currency(received_sum)
    deposit_amount_arg = getattr(args, "deposit_amount", None)
    if deposit_amount_arg:
        amount = round_currency(to_decimal(deposit_amount_arg))
    else:
        stored = to_decimal(event.get("deposit_amount") or "0.00")
        amount = round_currency(stored - received)
    if amount <= Decimal("0"):
        err("Deposit amount must be greater than 0")
    further_deposit = getattr(args, "further_deposit", False)
    if deposit_amount_arg and not further_deposit:
        for prior in submitted:
            if prior.get("party_id") == customer_id and round_currency(to_decimal(prior.get("paid_amount") or "0")) == amount:
                err(f"Catering event {event_id} already has a deposit of {amount} from customer {customer_id} (payment {prior['id']}, posted {prior.get('posting_date')}); if this is a further deposit, pass --further-deposit")
    ci = Table("foodclaw_catering_item")
    item_rows = conn.execute(Q.from_(ci).select(ci.star).where(ci.event_id == P()).orderby(ci.created_at, line_order(ci)).get_sql(), (event_id,)).fetchall()
    items = [row_to_dict(r) for r in item_rows]
    if event.get("final_amount") and to_decimal(event["final_amount"]) > Decimal("0"):
        total = round_currency(to_decimal(event["final_amount"]))
    elif event.get("quoted_price") and to_decimal(event["quoted_price"]) > Decimal("0"):
        total = round_currency(to_decimal(event["quoted_price"]))
    else:
        items_sum = Decimal("0")
        for d in items:
            items_sum += round_currency(Decimal(int(d.get("quantity") or 0)) * to_decimal(d.get("unit_price")))
        total = round_currency(items_sum)
    if total <= Decimal("0"):
        err("Set the event\'s quoted price or items before receiving a deposit")
    remaining = round_currency(total - received)
    if amount > remaining:
        err(f"Deposit {amount} is more than the event\'s {total} less deposits already received ({received})")
    comp = Table("company")
    crow = conn.execute(Q.from_(comp).select(comp.default_receivable_account_id, comp.default_cash_account_id, comp.default_bank_account_id).where(comp.id == P()).get_sql(), (company_id,)).fetchone()
    crow_d = row_to_dict(crow) if crow is not None else {}
    receivable = crow_d.get("default_receivable_account_id")
    if not receivable:
        acct = Table("account")
        aq = Q.from_(acct).select(acct.id).where(acct.account_type == P()).where(acct.company_id == P()).where(acct.is_group == P()).limit(1)
        arow = conn.execute(aq.get_sql(), ("receivable", company_id, 0)).fetchone()
        if arow is not None:
            receivable = dict(arow)["id"]
    if not receivable:
        err(f"No receivable account for company {company_id}: set its default receivable account")
    cash_arg = getattr(args, "cash_account_id", None)
    if cash_arg:
        cash_id = cash_arg
    else:
        cash_id = crow_d.get("default_cash_account_id") or crow_d.get("default_bank_account_id")
    if not cash_id:
        err("No account to receive the deposit into: pass --cash-account-id or set the company\'s default cash or bank account")
    acct2 = Table("account")
    acct_row = conn.execute(Q.from_(acct2).select(acct2.id, acct2.company_id, acct2.is_group).where(acct2.id == P()).get_sql(), (cash_id,)).fetchone()
    if acct_row is None:
        err(f"Account {cash_id} cannot receive a deposit for company {company_id} (not found, another company\'s, or a group account)")
    acct_d = dict(acct_row)
    try:
        is_group_val = int(acct_d.get("is_group") or 0)
    except (TypeError, ValueError):
        is_group_val = 0
    if acct_d.get("company_id") != company_id or is_group_val != 0:
        err(f"Account {cash_id} cannot receive a deposit for company {company_id} (not found, another company\'s, or a group account)")
    deposit_date_arg = getattr(args, "deposit_date", None)
    if deposit_date_arg:
        deposit_date = deposit_date_arg
    else:
        deposit_date = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    fy = Table("fiscal_year")
    fyq = Q.from_(fy).select(fy.id).where(fy.company_id == P()).where(fy.start_date <= P()).where(fy.end_date >= P()).where(fy.is_closed == P())
    fy_row = conn.execute(fyq.get_sql(), (company_id, deposit_date, deposit_date, 0)).fetchone()
    if fy_row is None:
        err(f"Deposit cannot be recorded: no open fiscal year covers {deposit_date}")
    db_path = getattr(args, "db_path", None)
    drafts = _event_deposits(conn, company_id, event_id, "draft")
    resumed = False
    pe = None
    if len(drafts) > 1:
        err(f"Catering event {event_id} has more than one draft deposit payment ({drafts[0]['id']}, {drafts[1]['id']}); delete the extra ones through payments first")
    if len(drafts) == 1:
        draft = drafts[0]
        draft_amount = round_currency(to_decimal(draft.get("paid_amount") or "0"))
        if draft.get("party_id") == customer_id and draft_amount == amount and draft.get("paid_from_account") == receivable and draft.get("paid_to_account") == cash_id:
            pe = draft["id"]
            try:
                cross_skill.call_skill_action("erpclaw", "submit-payment", {"--payment-entry-id": pe, "--user-confirmed": None}, db_path=db_path)
            except cross_skill.CrossSkillError as e:
                pe_row = conn.execute(Q.from_(Table("payment_entry")).select(Field("status")).where(Field("id") == P()).get_sql(), (pe,)).fetchone()
                pe_status = dict(pe_row)["status"] if pe_row is not None else None
                if pe_status == "submitted":
                    pass
                else:
                    err(f"Deposit payment {pe} was created for catering event {event_id} but could not be submitted: {e}; receive the deposit again to finish it")
            resumed = True
        else:
            err(f"A draft deposit payment {draft['id']} for catering event {event_id} exists (customer {draft.get('party_id')}, amount {draft_amount}); submit or delete it through payments first")
    if pe is None:
        try:
            made = cross_skill.call_skill_action("erpclaw", "add-payment", {"--company-id": company_id, "--payment-type": "receive", "--party-type": "customer", "--party-id": customer_id, "--posting-date": deposit_date, "--paid-from-account": receivable, "--paid-to-account": cash_id, "--paid-amount": str(amount), "--reference-number": _deposit_reference(event_id), "--reference-date": deposit_date}, db_path=db_path)
        except cross_skill.CrossSkillError as e:
            err(f"Catering deposit could not be recorded: {e}")
        pe = (made or {}).get("payment_entry_id")
        if not pe:
            err("Catering deposit could not be recorded: payment creation returned no id")
        def _remove_own_draft(payment_id):
            try:
                cross_skill.call_skill_action("erpclaw", "delete-payment", {"--payment-entry-id": payment_id, "--user-confirmed": None}, db_path=db_path)
            except cross_skill.CrossSkillError as e:
                own_row = conn.execute(Q.from_(Table("payment_entry")).select(Field("status")).where(Field("id") == P()).get_sql(), (payment_id,)).fetchone()
                own_status = dict(own_row)["status"] if own_row is not None else None
                if own_status == "submitted":
                    err(f"Deposit payment {payment_id} for catering event {event_id} was submitted by another call while this one stepped back; check the event's deposits before receiving again")
                err(f"Deposit payment {payment_id} for catering event {event_id} was not submitted and could not be removed: {e}; delete it through payments")
        conn.rollback()
        pe_row = conn.execute(Q.from_(Table("payment_entry")).select(Field("status")).where(Field("id") == P()).get_sql(), (pe,)).fetchone()
        pe_status = dict(pe_row)["status"] if pe_row is not None else None
        if pe_status != "submitted":
            fresh_drafts = _event_deposits(conn, company_id, event_id, "draft")
            others = [d for d in fresh_drafts if d["id"] != pe]
            if others:
                _remove_own_draft(pe)
                err(f"Another deposit for catering event {event_id} is being recorded (payment {others[0]['id']}); try again once it has finished")
            fresh_submitted = [s for s in _event_deposits(conn, company_id, event_id, "submitted") if s["id"] != pe]
            fresh_sum = sum((to_decimal(r.get("paid_amount") or "0") for r in fresh_submitted), Decimal("0"))
            fresh_received = round_currency(fresh_sum)
            fresh_remaining = round_currency(total - fresh_received)
            if amount > fresh_remaining:
                _remove_own_draft(pe)
                err(f"Deposit {amount} is more than the event's {total} less deposits already received ({fresh_received})")
        try:
            cross_skill.call_skill_action("erpclaw", "submit-payment", {"--payment-entry-id": pe, "--user-confirmed": None}, db_path=db_path)
        except cross_skill.CrossSkillError as e:
            pe_row = conn.execute(Q.from_(Table("payment_entry")).select(Field("status")).where(Field("id") == P()).get_sql(), (pe,)).fetchone()
            pe_status = dict(pe_row)["status"] if pe_row is not None else None
            if pe_status == "submitted":
                pass
            else:
                err(f"Deposit payment {pe} was created for catering event {event_id} but could not be submitted: {e}; receive the deposit again to finish it")
        resumed = False
    _deposit_values = {"payment_entry_id": pe, "customer_id": customer_id, "amount": str(amount)}
    if getattr(args, "further_deposit", False):
        _deposit_values["further_deposit"] = True
    audit(conn, SKILL, "food-receive-catering-deposit", "foodclaw_catering_event", event_id, new_values=_deposit_values)
    conn.commit()
    submitted_after = _event_deposits(conn, company_id, event_id, "submitted")
    after_sum = sum((to_decimal(r.get("paid_amount") or "0") for r in submitted_after), Decimal("0"))
    deposits_received = round_currency(after_sum)
    ok({"event_id": event_id, "payment_entry_id": pe, "customer_id": customer_id, "amount": str(amount), "deposit_date": deposit_date, "deposits_received": str(deposits_received), "resumed": resumed})


# ---------------------------------------------------------------------------
# ACTIONS registry
# ---------------------------------------------------------------------------
ACTIONS = {
    "food-add-catering-event": add_catering_event,
    "food-update-catering-event": update_catering_event,
    "food-get-catering-event": get_catering_event,
    "food-list-catering-events": list_catering_events,
    "food-add-catering-item": add_catering_item,
    "food-list-catering-items": list_catering_items,
    "food-add-dietary-requirement": add_dietary_requirement,
    "food-list-dietary-requirements": list_dietary_requirements,
    "food-confirm-event": confirm_event,
    "food-complete-catering-event": complete_catering_event,
    "food-receive-catering-deposit": receive_catering_deposit,
    "food-catering-cost-estimate": catering_cost_estimate,
}
