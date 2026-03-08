"""FoodClaw — catering domain module

Actions for the catering domain (3 tables, 10 actions).
Imported by db_query.py (unified router).
"""
import json
import os
import sys
import uuid
from datetime import datetime, timezone
from decimal import Decimal, ROUND_HALF_UP

try:
    sys.path.insert(0, os.path.expanduser("~/.openclaw/erpclaw/lib"))
    from erpclaw_lib.db import get_connection
    from erpclaw_lib.decimal_utils import to_decimal, round_currency
    from erpclaw_lib.naming import get_next_name, ENTITY_PREFIXES
    from erpclaw_lib.response import ok, err, row_to_dict
    from erpclaw_lib.audit import audit

    ENTITY_PREFIXES.setdefault("foodclaw_catering_event", "CATER-")
except ImportError:
    pass

_now_iso = lambda: datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

VALID_EVENT_STATUSES = ("inquiry", "quoted", "confirmed", "in_progress", "completed", "cancelled")


def _validate_company(conn, company_id):
    if not company_id:
        err("--company-id is required")
    row = conn.execute("SELECT id FROM company WHERE id = ?", (company_id,)).fetchone()
    if not row:
        err(f"Company {company_id} not found")


def _validate_enum(value, valid_values, field_name):
    if value and value not in valid_values:
        err(f"Invalid {field_name}: {value}. Must be one of: {', '.join(valid_values)}")


def _validate_event(conn, event_id):
    if not event_id:
        err("--event-id is required")
    row = conn.execute("SELECT id FROM foodclaw_catering_event WHERE id = ?", (event_id,)).fetchone()
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

    conn.execute("""
        INSERT INTO foodclaw_catering_event (id, naming_series, company_id, event_name,
            client_name, client_phone, client_email, event_date, event_time, venue,
            guest_count, event_status, estimated_cost, quoted_price, deposit_amount,
            notes, created_at, updated_at)
        VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
    """, (
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
    audit(conn, "foodclaw_catering_event", event_id, "food-add-catering-event", args.company_id)
    conn.commit()
    ok({"id": event_id, "naming_series": ns, "event_name": event_name, "event_status": "inquiry"})


# ---------------------------------------------------------------------------
# 2. update-catering-event
# ---------------------------------------------------------------------------
def update_catering_event(conn, args):
    event_id = getattr(args, "event_id", None)
    _validate_event(conn, event_id)
    _validate_enum(getattr(args, "event_status", None), VALID_EVENT_STATUSES, "event-status")

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

    for field in ("estimated_cost", "quoted_price", "deposit_amount"):
        val = getattr(args, field, None)
        if val is not None:
            to_decimal(val)
            updates.append(f"{field} = ?")
            params.append(val)

    if not updates:
        err("No fields to update")

    updates.append("updated_at = ?")
    params.append(_now_iso())
    params.append(event_id)

    conn.execute(f"UPDATE foodclaw_catering_event SET {', '.join(updates)} WHERE id = ?", params)
    audit(conn, "foodclaw_catering_event", event_id, "food-update-catering-event", None)
    conn.commit()
    ok({"id": event_id, "updated_fields": [u.split(" = ")[0] for u in updates if u != "updated_at = ?"]})


# ---------------------------------------------------------------------------
# 3. get-catering-event
# ---------------------------------------------------------------------------
def get_catering_event(conn, args):
    event_id = getattr(args, "event_id", None)
    _validate_event(conn, event_id)
    row = conn.execute("SELECT * FROM foodclaw_catering_event WHERE id = ?", (event_id,)).fetchone()
    data = row_to_dict(row)

    # Get catering items
    items = conn.execute(
        "SELECT * FROM foodclaw_catering_item WHERE event_id = ?", (event_id,)
    ).fetchall()
    data["catering_items"] = [row_to_dict(r) for r in items]
    data["item_count"] = len(items)

    # Get dietary requirements
    diets = conn.execute(
        "SELECT * FROM foodclaw_dietary_requirement WHERE event_id = ?", (event_id,)
    ).fetchall()
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
        where.append("(event_name LIKE ? OR client_name LIKE ?)")
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

    conn.execute("""
        INSERT INTO foodclaw_catering_item (id, event_id, menu_item_id, item_name,
            quantity, unit_price, line_total, notes, created_at)
        VALUES (?,?,?,?,?,?,?,?,?)
    """, (
        ci_id, event_id,
        getattr(args, "menu_item_id", None),
        item_name, int(quantity), unit_price, line_total,
        getattr(args, "notes", None),
        _now_iso(),
    ))
    audit(conn, "foodclaw_catering_item", ci_id, "food-add-catering-item", None)
    conn.commit()
    ok({"id": ci_id, "item_name": item_name, "quantity": int(quantity), "unit_price": unit_price, "line_total": line_total})


# ---------------------------------------------------------------------------
# 6. list-catering-items
# ---------------------------------------------------------------------------
def list_catering_items(conn, args):
    event_id = getattr(args, "event_id", None)
    _validate_event(conn, event_id)

    rows = conn.execute(
        "SELECT * FROM foodclaw_catering_item WHERE event_id = ? ORDER BY created_at", (event_id,)
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

    conn.execute("""
        INSERT INTO foodclaw_dietary_requirement (id, event_id, requirement,
            guest_count, notes, created_at)
        VALUES (?,?,?,?,?,?)
    """, (
        dr_id, event_id, requirement,
        getattr(args, "guest_count", None) or 1,
        getattr(args, "notes", None),
        _now_iso(),
    ))
    audit(conn, "foodclaw_dietary_requirement", dr_id, "food-add-dietary-requirement", None)
    conn.commit()
    ok({"id": dr_id, "requirement": requirement, "guest_count": getattr(args, "guest_count", None) or 1})


# ---------------------------------------------------------------------------
# 8. list-dietary-requirements
# ---------------------------------------------------------------------------
def list_dietary_requirements(conn, args):
    event_id = getattr(args, "event_id", None)
    _validate_event(conn, event_id)

    rows = conn.execute(
        "SELECT * FROM foodclaw_dietary_requirement WHERE event_id = ?", (event_id,)
    ).fetchall()
    ok({"items": [row_to_dict(r) for r in rows], "total_count": len(rows)})


# ---------------------------------------------------------------------------
# 9. confirm-event
# ---------------------------------------------------------------------------
def confirm_event(conn, args):
    event_id = getattr(args, "event_id", None)
    _validate_event(conn, event_id)

    row = conn.execute("SELECT event_status FROM foodclaw_catering_event WHERE id = ?", (event_id,)).fetchone()
    if row[0] not in ("inquiry", "quoted"):
        err(f"Cannot confirm: event status is '{row[0]}', expected 'inquiry' or 'quoted'")

    now = _now_iso()
    conn.execute(
        "UPDATE foodclaw_catering_event SET event_status = 'confirmed', updated_at = ? WHERE id = ?",
        (now, event_id)
    )
    audit(conn, "foodclaw_catering_event", event_id, "food-confirm-event", None)
    conn.commit()
    ok({"id": event_id, "event_status": "confirmed"})


# ---------------------------------------------------------------------------
# 10. catering-cost-estimate
# ---------------------------------------------------------------------------
def catering_cost_estimate(conn, args):
    """Sum all catering items line_total for an event."""
    event_id = getattr(args, "event_id", None)
    _validate_event(conn, event_id)

    event = conn.execute("SELECT * FROM foodclaw_catering_event WHERE id = ?", (event_id,)).fetchone()
    event_data = row_to_dict(event)

    items = conn.execute(
        "SELECT * FROM foodclaw_catering_item WHERE event_id = ?", (event_id,)
    ).fetchall()

    total = Decimal("0.00")
    item_list = []
    for r in items:
        d = row_to_dict(r)
        lt = to_decimal(d.get("line_total", "0.00"))
        total += lt
        item_list.append({"item_name": d["item_name"], "quantity": d["quantity"], "unit_price": d.get("unit_price", "0.00"), "line_total": str(lt)})

    guest_count = event_data.get("guest_count", 0) or 0
    per_guest = "0.00"
    if guest_count > 0:
        per_guest = str((total / Decimal(str(guest_count))).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP))

    ok({
        "event_id": event_id,
        "event_name": event_data.get("event_name"),
        "guest_count": guest_count,
        "items": item_list,
        "total_cost": str(total),
        "cost_per_guest": per_guest,
    })


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
    "food-catering-cost-estimate": catering_cost_estimate,
}
