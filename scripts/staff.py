"""FoodClaw — staff domain module

Actions for the staff scheduling domain (3 tables, 10 actions).
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

    ENTITY_PREFIXES.setdefault("foodclaw_employee", "FEMP-")
except ImportError:
    pass

_now_iso = lambda: datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

VALID_ROLES = ("manager", "chef", "sous_chef", "line_cook", "prep_cook", "server",
               "bartender", "host", "busser", "dishwasher", "delivery", "cashier", "staff", "other")
VALID_EMP_STATUSES = ("active", "inactive", "terminated")
VALID_SHIFT_STATUSES = ("scheduled", "clocked_in", "clocked_out", "no_show", "cancelled")


def _validate_company(conn, company_id):
    if not company_id:
        err("--company-id is required")
    row = conn.execute("SELECT id FROM company WHERE id = ?", (company_id,)).fetchone()
    if not row:
        err(f"Company {company_id} not found")


def _validate_enum(value, valid_values, field_name):
    if value and value not in valid_values:
        err(f"Invalid {field_name}: {value}. Must be one of: {', '.join(valid_values)}")


# ---------------------------------------------------------------------------
# 1. add-employee
# ---------------------------------------------------------------------------
def add_employee(conn, args):
    _validate_company(conn, args.company_id)
    first_name = getattr(args, "first_name", None)
    last_name = getattr(args, "last_name", None)
    if not first_name:
        err("--first-name is required")
    if not last_name:
        err("--last-name is required")
    _validate_enum(getattr(args, "role", None), VALID_ROLES, "role")

    emp_id = str(uuid.uuid4())
    ns = get_next_name(conn, "foodclaw_employee", company_id=args.company_id)
    now = _now_iso()
    full_name = f"{first_name} {last_name}"

    hourly_rate = getattr(args, "hourly_rate", None) or "0.00"
    to_decimal(hourly_rate)

    conn.execute("""
        INSERT INTO foodclaw_employee (id, naming_series, company_id, employee_id,
            first_name, last_name, full_name, role, hourly_rate, phone, email,
            hire_date, status, certifications, created_at, updated_at)
        VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
    """, (
        emp_id, ns, args.company_id,
        getattr(args, "employee_id", None),
        first_name, last_name, full_name,
        getattr(args, "role", None) or "staff",
        hourly_rate,
        getattr(args, "phone", None),
        getattr(args, "email", None),
        getattr(args, "hire_date", None),
        "active",
        getattr(args, "certifications", None),
        now, now,
    ))
    audit(conn, "foodclaw_employee", emp_id, "food-add-employee", args.company_id)
    conn.commit()
    ok({"id": emp_id, "naming_series": ns, "full_name": full_name, "role": getattr(args, "role", None) or "staff"})


# ---------------------------------------------------------------------------
# 2. update-employee
# ---------------------------------------------------------------------------
def update_employee(conn, args):
    emp_id = getattr(args, "foodclaw_employee_id", None)
    if not emp_id:
        err("--foodclaw-employee-id is required")
    row = conn.execute("SELECT id FROM foodclaw_employee WHERE id = ?", (emp_id,)).fetchone()
    if not row:
        err(f"Employee {emp_id} not found")
    _validate_enum(getattr(args, "role", None), VALID_ROLES, "role")
    _validate_enum(getattr(args, "emp_status", None), VALID_EMP_STATUSES, "status")

    updates, params = [], []
    for field, col in [
        ("first_name", "first_name"), ("last_name", "last_name"),
        ("role", "role"), ("phone", "phone"), ("email", "email"),
        ("hire_date", "hire_date"), ("certifications", "certifications"),
    ]:
        val = getattr(args, field, None)
        if val is not None:
            updates.append(f"{col} = ?")
            params.append(val)

    if getattr(args, "emp_status", None):
        updates.append("status = ?")
        params.append(args.emp_status)

    hr = getattr(args, "hourly_rate", None)
    if hr is not None:
        to_decimal(hr)
        updates.append("hourly_rate = ?")
        params.append(hr)

    # Recalculate full_name if first/last changed
    fn = getattr(args, "first_name", None)
    ln = getattr(args, "last_name", None)
    if fn or ln:
        cur = conn.execute("SELECT first_name, last_name FROM foodclaw_employee WHERE id = ?", (emp_id,)).fetchone()
        full = f"{fn or cur[0]} {ln or cur[1]}"
        updates.append("full_name = ?")
        params.append(full)

    if not updates:
        err("No fields to update")

    updates.append("updated_at = ?")
    params.append(_now_iso())
    params.append(emp_id)

    conn.execute(f"UPDATE foodclaw_employee SET {', '.join(updates)} WHERE id = ?", params)
    audit(conn, "foodclaw_employee", emp_id, "food-update-employee", None)
    conn.commit()
    ok({"id": emp_id, "updated_fields": [u.split(" = ")[0] for u in updates if u not in ("updated_at = ?", "full_name = ?")]})


# ---------------------------------------------------------------------------
# 3. list-employees
# ---------------------------------------------------------------------------
def list_employees(conn, args):
    where, params = ["1=1"], []
    if getattr(args, "company_id", None):
        where.append("company_id = ?")
        params.append(args.company_id)
    if getattr(args, "role", None):
        where.append("role = ?")
        params.append(args.role)
    if getattr(args, "emp_status", None):
        where.append("status = ?")
        params.append(args.emp_status)
    if getattr(args, "search", None):
        where.append("(first_name LIKE ? OR last_name LIKE ? OR full_name LIKE ?)")
        params.extend([f"%{args.search}%"] * 3)

    total = conn.execute(
        f"SELECT COUNT(*) FROM foodclaw_employee WHERE {' AND '.join(where)}", params
    ).fetchone()[0]
    rows = conn.execute(
        f"SELECT * FROM foodclaw_employee WHERE {' AND '.join(where)} ORDER BY full_name LIMIT ? OFFSET ?",
        params + [getattr(args, "limit", 50), getattr(args, "offset", 0)]
    ).fetchall()
    ok({"items": [row_to_dict(r) for r in rows], "total_count": total})


# ---------------------------------------------------------------------------
# 4. add-shift
# ---------------------------------------------------------------------------
def add_shift(conn, args):
    _validate_company(conn, args.company_id)
    emp_id = getattr(args, "foodclaw_employee_id", None)
    if not emp_id:
        err("--foodclaw-employee-id is required")
    row = conn.execute("SELECT id FROM foodclaw_employee WHERE id = ?", (emp_id,)).fetchone()
    if not row:
        err(f"Employee {emp_id} not found")

    shift_date = getattr(args, "shift_date", None)
    if not shift_date:
        err("--shift-date is required")
    start_time = getattr(args, "start_time", None)
    if not start_time:
        err("--start-time is required")

    shift_id = str(uuid.uuid4())
    now = _now_iso()

    conn.execute("""
        INSERT INTO foodclaw_shift (id, company_id, employee_id, shift_date,
            start_time, end_time, role_assigned, shift_status, notes, created_at, updated_at)
        VALUES (?,?,?,?,?,?,?,?,?,?,?)
    """, (
        shift_id, args.company_id, emp_id, shift_date,
        start_time,
        getattr(args, "end_time", None),
        getattr(args, "role_assigned", None),
        "scheduled",
        getattr(args, "notes", None),
        now, now,
    ))
    audit(conn, "foodclaw_shift", shift_id, "food-add-shift", args.company_id)
    conn.commit()
    ok({"id": shift_id, "employee_id": emp_id, "shift_date": shift_date, "shift_status": "scheduled"})


# ---------------------------------------------------------------------------
# 5. update-shift
# ---------------------------------------------------------------------------
def update_shift(conn, args):
    shift_id = getattr(args, "shift_id", None)
    if not shift_id:
        err("--shift-id is required")
    row = conn.execute("SELECT id FROM foodclaw_shift WHERE id = ?", (shift_id,)).fetchone()
    if not row:
        err(f"Shift {shift_id} not found")
    _validate_enum(getattr(args, "shift_status", None), VALID_SHIFT_STATUSES, "shift-status")

    updates, params = [], []
    for field, col in [
        ("shift_date", "shift_date"), ("start_time", "start_time"),
        ("end_time", "end_time"), ("role_assigned", "role_assigned"),
        ("shift_status", "shift_status"), ("notes", "notes"),
    ]:
        val = getattr(args, field, None)
        if val is not None:
            updates.append(f"{col} = ?")
            params.append(val)

    bm = getattr(args, "break_minutes", None)
    if bm is not None:
        updates.append("break_minutes = ?")
        params.append(int(bm))

    if not updates:
        err("No fields to update")

    updates.append("updated_at = ?")
    params.append(_now_iso())
    params.append(shift_id)

    conn.execute(f"UPDATE foodclaw_shift SET {', '.join(updates)} WHERE id = ?", params)
    audit(conn, "foodclaw_shift", shift_id, "food-update-shift", None)
    conn.commit()
    ok({"id": shift_id, "updated_fields": [u.split(" = ")[0] for u in updates if u != "updated_at = ?"]})


# ---------------------------------------------------------------------------
# 6. list-shifts
# ---------------------------------------------------------------------------
def list_shifts(conn, args):
    where, params = ["1=1"], []
    if getattr(args, "company_id", None):
        where.append("company_id = ?")
        params.append(args.company_id)
    if getattr(args, "foodclaw_employee_id", None):
        where.append("employee_id = ?")
        params.append(args.foodclaw_employee_id)
    if getattr(args, "shift_date", None):
        where.append("shift_date = ?")
        params.append(args.shift_date)
    if getattr(args, "shift_status", None):
        where.append("shift_status = ?")
        params.append(args.shift_status)

    total = conn.execute(
        f"SELECT COUNT(*) FROM foodclaw_shift WHERE {' AND '.join(where)}", params
    ).fetchone()[0]
    rows = conn.execute(
        f"SELECT * FROM foodclaw_shift WHERE {' AND '.join(where)} ORDER BY shift_date DESC, start_time LIMIT ? OFFSET ?",
        params + [getattr(args, "limit", 50), getattr(args, "offset", 0)]
    ).fetchall()
    ok({"items": [row_to_dict(r) for r in rows], "total_count": total})


# ---------------------------------------------------------------------------
# 7. clock-in
# ---------------------------------------------------------------------------
def clock_in(conn, args):
    shift_id = getattr(args, "shift_id", None)
    if not shift_id:
        err("--shift-id is required")
    row = conn.execute("SELECT id, shift_status FROM foodclaw_shift WHERE id = ?", (shift_id,)).fetchone()
    if not row:
        err(f"Shift {shift_id} not found")
    if row[1] != "scheduled":
        err(f"Cannot clock in: shift status is '{row[1]}', expected 'scheduled'")

    now = _now_iso()
    conn.execute(
        "UPDATE foodclaw_shift SET shift_status = 'clocked_in', clock_in_time = ?, updated_at = ? WHERE id = ?",
        (now, now, shift_id)
    )
    audit(conn, "foodclaw_shift", shift_id, "food-clock-in", None)
    conn.commit()
    ok({"id": shift_id, "shift_status": "clocked_in", "clock_in_time": now})


# ---------------------------------------------------------------------------
# 8. clock-out
# ---------------------------------------------------------------------------
def clock_out(conn, args):
    shift_id = getattr(args, "shift_id", None)
    if not shift_id:
        err("--shift-id is required")
    row = conn.execute("SELECT id, shift_status, clock_in_time, break_minutes FROM foodclaw_shift WHERE id = ?",
                       (shift_id,)).fetchone()
    if not row:
        err(f"Shift {shift_id} not found")
    if row[1] != "clocked_in":
        err(f"Cannot clock out: shift status is '{row[1]}', expected 'clocked_in'")

    now = _now_iso()

    # Calculate hours worked
    hours_worked = "0.00"
    try:
        cin = datetime.strptime(row[2], "%Y-%m-%dT%H:%M:%SZ")
        cout = datetime.strptime(now, "%Y-%m-%dT%H:%M:%SZ")
        diff_min = (cout - cin).total_seconds() / 60
        break_min = row[3] or 0
        net_min = max(0, diff_min - break_min)
        hours_worked = str(Decimal(str(net_min / 60)).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP))
    except (ValueError, TypeError):
        pass

    conn.execute(
        "UPDATE foodclaw_shift SET shift_status = 'clocked_out', clock_out_time = ?, hours_worked = ?, updated_at = ? WHERE id = ?",
        (now, hours_worked, now, shift_id)
    )
    audit(conn, "foodclaw_shift", shift_id, "food-clock-out", None)
    conn.commit()
    ok({"id": shift_id, "shift_status": "clocked_out", "clock_out_time": now, "hours_worked": hours_worked})


# ---------------------------------------------------------------------------
# 9. add-tip-distribution
# ---------------------------------------------------------------------------
def add_tip_distribution(conn, args):
    _validate_company(conn, args.company_id)
    emp_id = getattr(args, "foodclaw_employee_id", None)
    if not emp_id:
        err("--foodclaw-employee-id is required")
    row = conn.execute("SELECT id FROM foodclaw_employee WHERE id = ?", (emp_id,)).fetchone()
    if not row:
        err(f"Employee {emp_id} not found")

    tip_date = getattr(args, "tip_date", None)
    if not tip_date:
        err("--tip-date is required")

    cash_tips = getattr(args, "cash_tips", None) or "0.00"
    credit_tips = getattr(args, "credit_tips", None) or "0.00"
    tip_pool_share = getattr(args, "tip_pool_share", None) or "0.00"
    to_decimal(cash_tips)
    to_decimal(credit_tips)
    to_decimal(tip_pool_share)
    total_tips = str(to_decimal(cash_tips) + to_decimal(credit_tips) + to_decimal(tip_pool_share))

    tip_id = str(uuid.uuid4())

    conn.execute("""
        INSERT INTO foodclaw_tip_distribution (id, company_id, employee_id, shift_id,
            tip_date, cash_tips, credit_tips, tip_pool_share, total_tips, notes, created_at)
        VALUES (?,?,?,?,?,?,?,?,?,?,?)
    """, (
        tip_id, args.company_id, emp_id,
        getattr(args, "shift_id", None),
        tip_date, cash_tips, credit_tips, tip_pool_share, total_tips,
        getattr(args, "notes", None),
        _now_iso(),
    ))
    audit(conn, "foodclaw_tip_distribution", tip_id, "food-add-tip-distribution", args.company_id)
    conn.commit()
    ok({"id": tip_id, "employee_id": emp_id, "total_tips": total_tips})


# ---------------------------------------------------------------------------
# 10. list-tip-distributions
# ---------------------------------------------------------------------------
def list_tip_distributions(conn, args):
    where, params = ["1=1"], []
    if getattr(args, "company_id", None):
        where.append("company_id = ?")
        params.append(args.company_id)
    if getattr(args, "foodclaw_employee_id", None):
        where.append("employee_id = ?")
        params.append(args.foodclaw_employee_id)
    if getattr(args, "tip_date", None):
        where.append("tip_date = ?")
        params.append(args.tip_date)

    total = conn.execute(
        f"SELECT COUNT(*) FROM foodclaw_tip_distribution WHERE {' AND '.join(where)}", params
    ).fetchone()[0]
    rows = conn.execute(
        f"SELECT * FROM foodclaw_tip_distribution WHERE {' AND '.join(where)} ORDER BY tip_date DESC LIMIT ? OFFSET ?",
        params + [getattr(args, "limit", 50), getattr(args, "offset", 0)]
    ).fetchall()
    ok({"items": [row_to_dict(r) for r in rows], "total_count": total})


# ---------------------------------------------------------------------------
# ACTIONS registry
# ---------------------------------------------------------------------------
ACTIONS = {
    "food-add-employee": add_employee,
    "food-update-employee": update_employee,
    "food-list-employees": list_employees,
    "food-add-shift": add_shift,
    "food-update-shift": update_shift,
    "food-list-shifts": list_shifts,
    "food-clock-in": clock_in,
    "food-clock-out": clock_out,
    "food-add-tip-distribution": add_tip_distribution,
    "food-list-tip-distributions": list_tip_distributions,
}
