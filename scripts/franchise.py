"""FoodClaw -- franchise domain module

Actions for the franchise domain (2 tables, 8 actions).
Handles franchise unit management and royalty entries with optional GL posting.
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
    from erpclaw_lib.query import Q, P, Table, Field, fn, Order, LiteralValue, insert_row, update_row, dynamic_update

    ENTITY_PREFIXES.setdefault("foodclaw_franchise_unit", "FUNIT-")
    ENTITY_PREFIXES.setdefault("foodclaw_royalty_entry", "ROYAL-")
except ImportError:
    pass

# GL posting -- optional integration (graceful degradation)
try:
    from erpclaw_lib.gl_posting import insert_gl_entries
    HAS_GL = True
except ImportError:
    HAS_GL = False

_now_iso = lambda: datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

VALID_UNIT_STATUSES = ("active", "inactive", "closed", "under_construction")
VALID_PAYMENT_STATUSES = ("pending", "paid", "overdue")


def _validate_company(conn, company_id):
    if not company_id:
        err("--company-id is required")
    row = conn.execute(Q.from_(Table("company")).select(Field("id")).where(Field("id") == P()).get_sql(), (company_id,)).fetchone()
    if not row:
        err(f"Company {company_id} not found")


def _validate_enum(value, valid_values, field_name):
    if value and value not in valid_values:
        err(f"Invalid {field_name}: {value}. Must be one of: {', '.join(valid_values)}")


def _validate_franchise_unit(conn, unit_id):
    if not unit_id:
        err("--franchise-unit-id is required")
    row = conn.execute(Q.from_(Table("foodclaw_franchise_unit")).select(Field("id")).where(Field("id") == P()).get_sql(), (unit_id,)).fetchone()
    if not row:
        err(f"Franchise unit {unit_id} not found")


# ---------------------------------------------------------------------------
# 1. add-franchise-unit
# ---------------------------------------------------------------------------
def add_franchise_unit(conn, args):
    _validate_company(conn, args.company_id)
    unit_name = getattr(args, "name", None)
    if not unit_name:
        err("--name is required")

    unit_id = str(uuid.uuid4())
    ns = get_next_name(conn, "foodclaw_franchise_unit", company_id=args.company_id)
    now = _now_iso()

    sql, _ = insert_row("foodclaw_franchise_unit", {"id": P(), "naming_series": P(), "company_id": P(), "unit_name": P(), "unit_code": P(), "address": P(), "city": P(), "state": P(), "zip_code": P(), "manager_name": P(), "phone": P(), "open_date": P(), "status": P(), "created_at": P(), "updated_at": P()})
    conn.execute(sql, (
        unit_id, ns, args.company_id, unit_name,
        getattr(args, "unit_code", None),
        getattr(args, "address", None),
        getattr(args, "city", None),
        getattr(args, "state", None),
        getattr(args, "zip_code", None),
        getattr(args, "manager_name", None),
        getattr(args, "phone", None),
        getattr(args, "open_date", None),
        "active",
        now, now,
    ))
    audit(conn, "foodclaw_franchise_unit", unit_id, "food-add-franchise-unit", args.company_id)
    conn.commit()
    ok({"id": unit_id, "naming_series": ns, "unit_name": unit_name, "status": "active"})


# ---------------------------------------------------------------------------
# 2. update-franchise-unit
# ---------------------------------------------------------------------------
def update_franchise_unit(conn, args):
    unit_id = getattr(args, "franchise_unit_id", None)
    _validate_franchise_unit(conn, unit_id)
    _validate_enum(getattr(args, "status", None), VALID_UNIT_STATUSES, "status")

    updates, params = [], []
    for field, col in [
        ("name", "unit_name"), ("unit_code", "unit_code"),
        ("address", "address"), ("city", "city"), ("state", "state"),
        ("zip_code", "zip_code"), ("manager_name", "manager_name"),
        ("phone", "phone"), ("open_date", "open_date"), ("status", "status"),
    ]:
        val = getattr(args, field, None)
        if val is not None:
            updates.append(f"{col} = ?")
            params.append(val)

    if not updates:
        err("No fields to update")

    updates.append("updated_at = ?")
    params.append(_now_iso())
    params.append(unit_id)

    conn.execute(
        f"UPDATE foodclaw_franchise_unit SET {', '.join(updates)} WHERE id = ?", params
    )
    audit(conn, "foodclaw_franchise_unit", unit_id, "food-update-franchise-unit", None)
    conn.commit()
    ok({"id": unit_id, "updated_fields": [u.split(" = ")[0] for u in updates if u != "updated_at = ?"]})


# ---------------------------------------------------------------------------
# 3. get-franchise-unit
# ---------------------------------------------------------------------------
def get_franchise_unit(conn, args):
    unit_id = getattr(args, "franchise_unit_id", None)
    _validate_franchise_unit(conn, unit_id)
    row = conn.execute(Q.from_(Table("foodclaw_franchise_unit")).select(Table("foodclaw_franchise_unit").star).where(Field("id") == P()).get_sql(), (unit_id,)).fetchone()
    data = row_to_dict(row)

    # Include royalty summary
    royalties = conn.execute("""
        SELECT COUNT(*) as entry_count,
               COALESCE(SUM(CAST(total_due AS REAL)), 0) as total_due,
               COALESCE(SUM(CAST(royalty_amount AS REAL)), 0) as total_royalties
        FROM foodclaw_royalty_entry
        WHERE franchise_unit_id = ?
    """, (unit_id,)).fetchone()
    data["royalty_entry_count"] = royalties[0]
    data["total_royalties_due"] = str(to_decimal(str(royalties[1])).quantize(Decimal("0.01")))
    data["total_royalty_amount"] = str(to_decimal(str(royalties[2])).quantize(Decimal("0.01")))

    ok(data)


# ---------------------------------------------------------------------------
# 4. list-franchise-units
# ---------------------------------------------------------------------------
def list_franchise_units(conn, args):
    where, params = ["1=1"], []
    if getattr(args, "company_id", None):
        where.append("company_id = ?")
        params.append(args.company_id)
    if getattr(args, "status", None):
        _validate_enum(args.status, VALID_UNIT_STATUSES, "status")
        where.append("status = ?")
        params.append(args.status)
    if getattr(args, "search", None):
        where.append("(unit_name LIKE ? OR unit_code LIKE ?)")
        params.extend([f"%{args.search}%", f"%{args.search}%"])

    total = conn.execute(
        f"SELECT COUNT(*) FROM foodclaw_franchise_unit WHERE {' AND '.join(where)}", params
    ).fetchone()[0]
    rows = conn.execute(
        f"SELECT * FROM foodclaw_franchise_unit WHERE {' AND '.join(where)} ORDER BY unit_name LIMIT ? OFFSET ?",
        params + [getattr(args, "limit", 50), getattr(args, "offset", 0)]
    ).fetchall()
    ok({"items": [row_to_dict(r) for r in rows], "total_count": total})


# ---------------------------------------------------------------------------
# 5. add-royalty-entry (with GL posting for royalty income recognition)
# ---------------------------------------------------------------------------
def add_royalty_entry(conn, args):
    """Record a royalty entry for a franchise unit with optional GL posting.

    GL pattern for franchise royalty income:
      DR: Franchise Receivable (royalty_receivable_account_id) for total_due
      CR: Royalty Income (royalty_income_account_id) for royalty_amount
      CR: Marketing Fee Income (marketing_expense_account_id) for marketing_fee
          (if marketing_fee > 0 and marketing account is configured)

    If marketing_expense_account_id is not provided but marketing_fee > 0,
    marketing_fee is rolled into the royalty income credit.

    GL posting is OPTIONAL. If GL accounts are not provided, the royalty entry
    is created without GL entries.
    """
    _validate_company(conn, args.company_id)
    franchise_unit_id = getattr(args, "franchise_unit_id", None)
    _validate_franchise_unit(conn, franchise_unit_id)

    period_start = getattr(args, "period_start", None) or getattr(args, "start_date", None)
    period_end = getattr(args, "period_end", None) or getattr(args, "end_date", None)
    if not period_start:
        err("--period-start (or --start-date) is required")
    if not period_end:
        err("--period-end (or --end-date) is required")

    gross_revenue = getattr(args, "gross_revenue", None) or "0.00"
    royalty_rate = getattr(args, "royalty_rate", None) or "0.00"
    marketing_fee = getattr(args, "marketing_fee", None) or "0.00"
    to_decimal(gross_revenue)
    to_decimal(royalty_rate)
    to_decimal(marketing_fee)

    # Calculate royalty amount if not explicitly provided
    royalty_amount = getattr(args, "royalty_amount", None)
    if royalty_amount:
        to_decimal(royalty_amount)
    else:
        rate = to_decimal(royalty_rate)
        revenue = to_decimal(gross_revenue)
        royalty_amount = str((revenue * rate / Decimal("100")).quantize(
            Decimal("0.01"), rounding=ROUND_HALF_UP
        ))

    total_due = str(
        (to_decimal(royalty_amount) + to_decimal(marketing_fee)).quantize(
            Decimal("0.01"), rounding=ROUND_HALF_UP
        )
    )

    entry_id = str(uuid.uuid4())
    ns = get_next_name(conn, "foodclaw_royalty_entry", company_id=args.company_id)
    now = _now_iso()

    # GL account configuration
    royalty_income_account_id = getattr(args, "royalty_income_account_id", None)
    royalty_receivable_account_id = getattr(args, "royalty_receivable_account_id", None)
    marketing_expense_account_id = getattr(args, "marketing_expense_account_id", None)
    cost_center_id = getattr(args, "cost_center_id", None)

    gl_entry_ids_str = None
    gl_posted = False

    # GL posting -- optional, requires at least income + receivable accounts + HAS_GL
    if HAS_GL and royalty_income_account_id and royalty_receivable_account_id:
        total_due_dec = to_decimal(total_due)
        royalty_amount_dec = to_decimal(royalty_amount)
        marketing_fee_dec = to_decimal(marketing_fee)

        if total_due_dec > Decimal("0"):
            entries = [
                {
                    "account_id": royalty_receivable_account_id,
                    "debit": str(total_due_dec),
                    "credit": "0",
                    "party_type": "customer",
                    "party_id": franchise_unit_id,
                },
            ]

            # Split credits: royalty income + marketing fee (if separate account)
            if marketing_fee_dec > Decimal("0") and marketing_expense_account_id:
                # Separate credit lines for royalty income and marketing fee income
                entries.append({
                    "account_id": royalty_income_account_id,
                    "debit": "0",
                    "credit": str(royalty_amount_dec),
                    "cost_center_id": cost_center_id,
                })
                entries.append({
                    "account_id": marketing_expense_account_id,
                    "debit": "0",
                    "credit": str(marketing_fee_dec),
                    "cost_center_id": cost_center_id,
                })
            else:
                # Single credit for total_due to royalty income account
                entries.append({
                    "account_id": royalty_income_account_id,
                    "debit": "0",
                    "credit": str(total_due_dec),
                    "cost_center_id": cost_center_id,
                })

            # Fetch franchise unit name for remarks
            unit_row = conn.execute(Q.from_(Table("foodclaw_franchise_unit")).select(Field("unit_name")).where(Field("id") == P()).get_sql(), (franchise_unit_id,)).fetchone()
            unit_name = unit_row[0] if unit_row else franchise_unit_id

            try:
                gl_ids = insert_gl_entries(
                    conn, entries,
                    voucher_type="Franchise Royalty",
                    voucher_id=entry_id,
                    posting_date=period_end,
                    company_id=args.company_id,
                    remarks=f"Royalty for {unit_name}: {period_start} to {period_end}",
                )
                gl_entry_ids_str = ",".join(gl_ids)
                gl_posted = True
            except (ValueError, Exception) as e:
                # GL posting failed -- log warning but still create the royalty entry
                import sys as _sys
                _sys.stderr.write(
                    f"[foodclaw] GL posting warning for royalty entry {entry_id}: {e}\n"
                )

    conn.execute("""
        INSERT INTO foodclaw_royalty_entry (id, naming_series, company_id, franchise_unit_id,
            period_start, period_end, gross_revenue, royalty_rate, royalty_amount,
            marketing_fee, total_due, payment_status,
            royalty_income_account_id, royalty_receivable_account_id,
            marketing_expense_account_id, cost_center_id, gl_entry_ids,
            notes, created_at)
        VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
    """, (
        entry_id, ns, args.company_id, franchise_unit_id,
        period_start, period_end, gross_revenue, royalty_rate, royalty_amount,
        marketing_fee, total_due, "pending",
        royalty_income_account_id, royalty_receivable_account_id,
        marketing_expense_account_id, cost_center_id, gl_entry_ids_str,
        getattr(args, "notes", None),
        now,
    ))
    audit(conn, "foodclaw_royalty_entry", entry_id, "food-add-royalty-entry", args.company_id)
    conn.commit()

    result = {
        "id": entry_id,
        "naming_series": ns,
        "franchise_unit_id": franchise_unit_id,
        "royalty_amount": royalty_amount,
        "marketing_fee": marketing_fee,
        "total_due": total_due,
        "payment_status": "pending",
        "gl_posted": gl_posted,
    }
    if gl_entry_ids_str:
        result["gl_entry_ids"] = gl_entry_ids_str
    ok(result)


# ---------------------------------------------------------------------------
# 6. list-royalty-entries
# ---------------------------------------------------------------------------
def list_royalty_entries(conn, args):
    where, params = ["1=1"], []
    if getattr(args, "company_id", None):
        where.append("re.company_id = ?")
        params.append(args.company_id)
    if getattr(args, "franchise_unit_id", None):
        where.append("re.franchise_unit_id = ?")
        params.append(args.franchise_unit_id)
    if getattr(args, "payment_status", None):
        _validate_enum(args.payment_status, VALID_PAYMENT_STATUSES, "payment-status")
        where.append("re.payment_status = ?")
        params.append(args.payment_status)

    where_sql = " AND ".join(where)
    total = conn.execute(
        f"""SELECT COUNT(*) FROM foodclaw_royalty_entry re
            LEFT JOIN foodclaw_franchise_unit fu ON re.franchise_unit_id = fu.id
            WHERE {where_sql}""", params
    ).fetchone()[0]
    rows = conn.execute(
        f"""SELECT re.*, fu.unit_name, fu.unit_code
            FROM foodclaw_royalty_entry re
            LEFT JOIN foodclaw_franchise_unit fu ON re.franchise_unit_id = fu.id
            WHERE {where_sql}
            ORDER BY re.period_end DESC LIMIT ? OFFSET ?""",
        params + [getattr(args, "limit", 50), getattr(args, "offset", 0)]
    ).fetchall()
    ok({"items": [row_to_dict(r) for r in rows], "total_count": total})


# ---------------------------------------------------------------------------
# 7. get-royalty-entry
# ---------------------------------------------------------------------------
def get_royalty_entry(conn, args):
    royalty_id = getattr(args, "royalty_id", None)
    if not royalty_id:
        err("--royalty-id is required")
    row = conn.execute(
        """SELECT re.*, fu.unit_name, fu.unit_code
           FROM foodclaw_royalty_entry re
           LEFT JOIN foodclaw_franchise_unit fu ON re.franchise_unit_id = fu.id
           WHERE re.id = ?""",
        (royalty_id,)
    ).fetchone()
    if not row:
        err(f"Royalty entry {royalty_id} not found")
    ok(row_to_dict(row))


# ---------------------------------------------------------------------------
# 8. update-royalty-payment-status
# ---------------------------------------------------------------------------
def update_royalty_payment_status(conn, args):
    """Mark a royalty entry as paid or overdue."""
    royalty_id = getattr(args, "royalty_id", None)
    if not royalty_id:
        err("--royalty-id is required")
    row = conn.execute(Q.from_(Table("foodclaw_royalty_entry")).select(Field("id"), Field("payment_status")).where(Field("id") == P()).get_sql(), (royalty_id,)).fetchone()
    if not row:
        err(f"Royalty entry {royalty_id} not found")

    payment_status = getattr(args, "payment_status", None)
    if not payment_status:
        err("--payment-status is required")
    _validate_enum(payment_status, VALID_PAYMENT_STATUSES, "payment-status")

    sql, upd_params = dynamic_update("foodclaw_royalty_entry", {"payment_status": payment_status}, where={"id": royalty_id})
    conn.execute(sql, upd_params)
    audit(conn, "foodclaw_royalty_entry", royalty_id, "food-update-royalty-status", None)
    conn.commit()
    ok({"id": royalty_id, "payment_status": payment_status})


# ---------------------------------------------------------------------------
# ACTIONS registry
# ---------------------------------------------------------------------------
ACTIONS = {
    "food-add-franchise-unit": add_franchise_unit,
    "food-update-franchise-unit": update_franchise_unit,
    "food-get-franchise-unit": get_franchise_unit,
    "food-list-franchise-units": list_franchise_units,
    "food-add-royalty-entry": add_royalty_entry,
    "food-list-royalty-entries": list_royalty_entries,
    "food-get-royalty-entry": get_royalty_entry,
    "food-update-royalty-status": update_royalty_payment_status,
}
