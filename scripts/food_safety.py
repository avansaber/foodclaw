"""FoodClaw — food safety domain module

Actions for the food safety / HACCP domain (3 tables, 10 actions).
Imported by db_query.py (unified router).
"""
import json
import os
import sys
import uuid
from datetime import datetime, timezone
from decimal import Decimal

try:
    sys.path.insert(0, os.path.expanduser("~/.openclaw/erpclaw/lib"))
    from erpclaw_lib.db import get_connection
    from erpclaw_lib.decimal_utils import to_decimal
    from erpclaw_lib.naming import get_next_name, ENTITY_PREFIXES
    from erpclaw_lib.response import ok, err, row_to_dict
    from erpclaw_lib.audit import audit
    from erpclaw_lib.query import Q, P, Table, Field, fn, Order, insert_row, update_row

    ENTITY_PREFIXES.setdefault("foodclaw_inspection", "INSP-")
except ImportError:
    pass

_now_iso = lambda: datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

VALID_INSPECTION_TYPES = ("routine", "health_dept", "internal", "fire", "third_party", "other")
VALID_INSPECTION_STATUSES = ("scheduled", "in_progress", "completed", "failed", "follow_up")


def _validate_company(conn, company_id):
    if not company_id:
        err("--company-id is required")
    row = conn.execute(Q.from_(Table("company")).select(Field("id")).where(Field("id") == P()).get_sql(), (company_id,)).fetchone()
    if not row:
        err(f"Company {company_id} not found")


def _validate_enum(value, valid_values, field_name):
    if value and value not in valid_values:
        err(f"Invalid {field_name}: {value}. Must be one of: {', '.join(valid_values)}")


# ---------------------------------------------------------------------------
# 1. add-haccp-log
# ---------------------------------------------------------------------------
def add_haccp_log(conn, args):
    _validate_company(conn, args.company_id)
    ccp_name = getattr(args, "ccp_name", None)
    if not ccp_name:
        err("--ccp-name is required")
    log_date = getattr(args, "log_date", None)
    if not log_date:
        err("--log-date is required")

    hl_id = str(uuid.uuid4())

    measured = getattr(args, "measured_value", None)
    acceptable = getattr(args, "acceptable_range", None)
    is_within = 1
    if getattr(args, "is_within_range", None) is not None:
        is_within = int(args.is_within_range)

    conn.execute("""
        INSERT INTO foodclaw_haccp_log (id, company_id, ccp_name, log_date, log_time,
            monitored_by, parameter, measured_value, acceptable_range, is_within_range,
            corrective_action, notes, created_at)
        VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)
    """, (
        hl_id, args.company_id, ccp_name, log_date,
        getattr(args, "log_time", None),
        getattr(args, "monitored_by", None),
        getattr(args, "parameter", None),
        measured,
        acceptable,
        is_within,
        getattr(args, "corrective_action", None),
        getattr(args, "notes", None),
        _now_iso(),
    ))
    audit(conn, "foodclaw_haccp_log", hl_id, "food-add-haccp-log", args.company_id)
    conn.commit()
    ok({"id": hl_id, "ccp_name": ccp_name, "log_date": log_date, "is_within_range": is_within})


# ---------------------------------------------------------------------------
# 2. list-haccp-logs
# ---------------------------------------------------------------------------
def list_haccp_logs(conn, args):
    where, params = ["1=1"], []
    if getattr(args, "company_id", None):
        where.append("company_id = ?")
        params.append(args.company_id)
    if getattr(args, "ccp_name", None):
        where.append("ccp_name = ?")
        params.append(args.ccp_name)
    if getattr(args, "log_date", None):
        where.append("log_date = ?")
        params.append(args.log_date)

    total = conn.execute(
        f"SELECT COUNT(*) FROM foodclaw_haccp_log WHERE {' AND '.join(where)}", params
    ).fetchone()[0]
    rows = conn.execute(
        f"SELECT * FROM foodclaw_haccp_log WHERE {' AND '.join(where)} ORDER BY log_date DESC, log_time DESC LIMIT ? OFFSET ?",
        params + [getattr(args, "limit", 50), getattr(args, "offset", 0)]
    ).fetchall()
    ok({"items": [row_to_dict(r) for r in rows], "total_count": total})


# ---------------------------------------------------------------------------
# 3. add-temp-reading
# ---------------------------------------------------------------------------
def add_temp_reading(conn, args):
    _validate_company(conn, args.company_id)
    equipment_name = getattr(args, "equipment_name", None)
    if not equipment_name:
        err("--equipment-name is required")
    reading_date = getattr(args, "reading_date", None)
    if not reading_date:
        err("--reading-date is required")
    temperature = getattr(args, "temperature", None)
    if not temperature:
        err("--temperature is required")

    temp_unit = getattr(args, "temp_unit", None) or "F"
    if temp_unit not in ("F", "C"):
        err("Invalid temp-unit: must be F or C")

    # Determine if safe
    safe_min = getattr(args, "safe_min", None)
    safe_max = getattr(args, "safe_max", None)
    is_safe = 1
    temp_val = to_decimal(temperature)
    if safe_min and safe_max:
        if temp_val < to_decimal(safe_min) or temp_val > to_decimal(safe_max):
            is_safe = 0
    elif safe_min:
        if temp_val < to_decimal(safe_min):
            is_safe = 0
    elif safe_max:
        if temp_val > to_decimal(safe_max):
            is_safe = 0

    tr_id = str(uuid.uuid4())

    conn.execute("""
        INSERT INTO foodclaw_temp_reading (id, company_id, equipment_name, location,
            reading_date, reading_time, temperature, temp_unit, safe_min, safe_max,
            is_safe, recorded_by, corrective_action, created_at)
        VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)
    """, (
        tr_id, args.company_id, equipment_name,
        getattr(args, "location", None),
        reading_date,
        getattr(args, "reading_time", None),
        temperature, temp_unit,
        safe_min, safe_max, is_safe,
        getattr(args, "recorded_by", None),
        getattr(args, "corrective_action", None),
        _now_iso(),
    ))
    audit(conn, "foodclaw_temp_reading", tr_id, "food-add-temp-reading", args.company_id)
    conn.commit()
    ok({"id": tr_id, "equipment_name": equipment_name, "temperature": temperature, "is_safe": is_safe})


# ---------------------------------------------------------------------------
# 4. list-temp-readings
# ---------------------------------------------------------------------------
def list_temp_readings(conn, args):
    where, params = ["1=1"], []
    if getattr(args, "company_id", None):
        where.append("company_id = ?")
        params.append(args.company_id)
    if getattr(args, "equipment_name", None):
        where.append("equipment_name = ?")
        params.append(args.equipment_name)
    if getattr(args, "reading_date", None):
        where.append("reading_date = ?")
        params.append(args.reading_date)

    total = conn.execute(
        f"SELECT COUNT(*) FROM foodclaw_temp_reading WHERE {' AND '.join(where)}", params
    ).fetchone()[0]
    rows = conn.execute(
        f"SELECT * FROM foodclaw_temp_reading WHERE {' AND '.join(where)} ORDER BY reading_date DESC, reading_time DESC LIMIT ? OFFSET ?",
        params + [getattr(args, "limit", 50), getattr(args, "offset", 0)]
    ).fetchall()
    ok({"items": [row_to_dict(r) for r in rows], "total_count": total})


# ---------------------------------------------------------------------------
# 5. add-inspection
# ---------------------------------------------------------------------------
def add_inspection(conn, args):
    _validate_company(conn, args.company_id)
    inspection_date = getattr(args, "inspection_date", None)
    if not inspection_date:
        err("--inspection-date is required")
    _validate_enum(getattr(args, "inspection_type", None), VALID_INSPECTION_TYPES, "inspection-type")

    for field in ("score", "max_score"):
        val = getattr(args, field, None)
        if val:
            to_decimal(val)

    insp_id = str(uuid.uuid4())
    ns = get_next_name(conn, "foodclaw_inspection", company_id=args.company_id)
    now = _now_iso()

    conn.execute("""
        INSERT INTO foodclaw_inspection (id, naming_series, company_id, inspection_type,
            inspector_name, inspection_date, score, max_score, grade, findings,
            corrective_actions, follow_up_date, inspection_status, notes,
            created_at, updated_at)
        VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
    """, (
        insp_id, ns, args.company_id,
        getattr(args, "inspection_type", None) or "routine",
        getattr(args, "inspector_name", None),
        inspection_date,
        getattr(args, "score", None),
        getattr(args, "max_score", None) or "100",
        getattr(args, "grade", None),
        getattr(args, "findings", None),
        getattr(args, "corrective_actions", None),
        getattr(args, "follow_up_date", None),
        "scheduled",
        getattr(args, "notes", None),
        now, now,
    ))
    audit(conn, "foodclaw_inspection", insp_id, "food-add-inspection", args.company_id)
    conn.commit()
    ok({"id": insp_id, "naming_series": ns, "inspection_type": getattr(args, "inspection_type", None) or "routine", "inspection_status": "scheduled"})


# ---------------------------------------------------------------------------
# 6. update-inspection
# ---------------------------------------------------------------------------
def update_inspection(conn, args):
    insp_id = getattr(args, "inspection_id", None)
    if not insp_id:
        err("--inspection-id is required")
    row = conn.execute(Q.from_(Table("foodclaw_inspection")).select(Field("id")).where(Field("id") == P()).get_sql(), (insp_id,)).fetchone()
    if not row:
        err(f"Inspection {insp_id} not found")
    _validate_enum(getattr(args, "inspection_type", None), VALID_INSPECTION_TYPES, "inspection-type")
    _validate_enum(getattr(args, "inspection_status", None), VALID_INSPECTION_STATUSES, "inspection-status")

    updates, params = [], []
    for field, col in [
        ("inspection_type", "inspection_type"), ("inspector_name", "inspector_name"),
        ("inspection_date", "inspection_date"), ("grade", "grade"),
        ("findings", "findings"), ("corrective_actions", "corrective_actions"),
        ("follow_up_date", "follow_up_date"), ("inspection_status", "inspection_status"),
        ("notes", "notes"),
    ]:
        val = getattr(args, field, None)
        if val is not None:
            updates.append(f"{col} = ?")
            params.append(val)

    for field in ("score", "max_score"):
        val = getattr(args, field, None)
        if val is not None:
            to_decimal(val)
            updates.append(f"{field} = ?")
            params.append(val)

    if not updates:
        err("No fields to update")

    updates.append("updated_at = ?")
    params.append(_now_iso())
    params.append(insp_id)

    conn.execute(f"UPDATE foodclaw_inspection SET {', '.join(updates)} WHERE id = ?", params)
    audit(conn, "foodclaw_inspection", insp_id, "food-update-inspection", None)
    conn.commit()
    ok({"id": insp_id, "updated_fields": [u.split(" = ")[0] for u in updates if u != "updated_at = ?"]})


# ---------------------------------------------------------------------------
# 7. list-inspections
# ---------------------------------------------------------------------------
def list_inspections(conn, args):
    where, params = ["1=1"], []
    if getattr(args, "company_id", None):
        where.append("company_id = ?")
        params.append(args.company_id)
    if getattr(args, "inspection_type", None):
        where.append("inspection_type = ?")
        params.append(args.inspection_type)
    if getattr(args, "inspection_status", None):
        where.append("inspection_status = ?")
        params.append(args.inspection_status)

    total = conn.execute(
        f"SELECT COUNT(*) FROM foodclaw_inspection WHERE {' AND '.join(where)}", params
    ).fetchone()[0]
    rows = conn.execute(
        f"SELECT * FROM foodclaw_inspection WHERE {' AND '.join(where)} ORDER BY inspection_date DESC LIMIT ? OFFSET ?",
        params + [getattr(args, "limit", 50), getattr(args, "offset", 0)]
    ).fetchall()
    ok({"items": [row_to_dict(r) for r in rows], "total_count": total})


# ---------------------------------------------------------------------------
# 8. complete-inspection
# ---------------------------------------------------------------------------
def complete_inspection(conn, args):
    insp_id = getattr(args, "inspection_id", None)
    if not insp_id:
        err("--inspection-id is required")
    row = conn.execute(Q.from_(Table("foodclaw_inspection")).select(Field("id"), Field("inspection_status")).where(Field("id") == P()).get_sql(), (insp_id,)).fetchone()
    if not row:
        err(f"Inspection {insp_id} not found")
    if row[1] in ("completed", "failed"):
        err(f"Inspection already '{row[1]}'")

    score = getattr(args, "score", None)
    grade = getattr(args, "grade", None)

    now = _now_iso()
    updates = ["inspection_status = 'completed'", "updated_at = ?"]
    params = [now]

    if score is not None:
        to_decimal(score)
        updates.insert(0, "score = ?")
        params.insert(0, score)
    if grade is not None:
        updates.insert(0, "grade = ?")
        params.insert(0, grade)

    params.append(insp_id)
    conn.execute(f"UPDATE foodclaw_inspection SET {', '.join(updates)} WHERE id = ?", params)
    audit(conn, "foodclaw_inspection", insp_id, "food-complete-inspection", None)
    conn.commit()
    ok({"id": insp_id, "inspection_status": "completed", "score": score, "grade": grade})


# ---------------------------------------------------------------------------
# 9. temp-violation-alert
# ---------------------------------------------------------------------------
def temp_violation_alert(conn, args):
    """Return all temperature readings flagged as unsafe."""
    where, params = ["is_safe = 0"], []
    if getattr(args, "company_id", None):
        where.append("company_id = ?")
        params.append(args.company_id)
    if getattr(args, "reading_date", None):
        where.append("reading_date = ?")
        params.append(args.reading_date)

    rows = conn.execute(
        f"SELECT * FROM foodclaw_temp_reading WHERE {' AND '.join(where)} ORDER BY reading_date DESC, reading_time DESC",
        params
    ).fetchall()
    ok({"items": [row_to_dict(r) for r in rows], "total_count": len(rows)})


# ---------------------------------------------------------------------------
# 10. haccp-compliance-report
# ---------------------------------------------------------------------------
def haccp_compliance_report(conn, args):
    """HACCP compliance summary: total logs, within/out of range counts."""
    where, params = ["1=1"], []
    if getattr(args, "company_id", None):
        where.append("company_id = ?")
        params.append(args.company_id)
    if getattr(args, "start_date", None):
        where.append("log_date >= ?")
        params.append(args.start_date)
    if getattr(args, "end_date", None):
        where.append("log_date <= ?")
        params.append(args.end_date)

    total = conn.execute(
        f"SELECT COUNT(*) FROM foodclaw_haccp_log WHERE {' AND '.join(where)}", params
    ).fetchone()[0]
    within = conn.execute(
        f"SELECT COUNT(*) FROM foodclaw_haccp_log WHERE {' AND '.join(where)} AND is_within_range = 1", params
    ).fetchone()[0]
    out_of_range = total - within

    compliance_pct = "0.00"
    if total > 0:
        compliance_pct = str(
            (Decimal(str(within)) / Decimal(str(total)) * Decimal("100")).quantize(
                Decimal("0.01")
            )
        )

    # Get CCP breakdown
    ccp_rows = conn.execute(f"""
        SELECT ccp_name,
               COUNT(*) as total,
               SUM(CASE WHEN is_within_range = 1 THEN 1 ELSE 0 END) as within_count
        FROM foodclaw_haccp_log
        WHERE {' AND '.join(where)}
        GROUP BY ccp_name
        ORDER BY ccp_name
    """, params).fetchall()

    ccps = []
    for r in ccp_rows:
        ccps.append({
            "ccp_name": r[0],
            "total_logs": r[1],
            "within_range": r[2],
            "out_of_range": r[1] - r[2],
        })

    ok({
        "total_logs": total,
        "within_range": within,
        "out_of_range": out_of_range,
        "compliance_pct": compliance_pct,
        "ccp_breakdown": ccps,
    })


# ---------------------------------------------------------------------------
# ACTIONS registry
# ---------------------------------------------------------------------------
ACTIONS = {
    "food-add-haccp-log": add_haccp_log,
    "food-list-haccp-logs": list_haccp_logs,
    "food-add-temp-reading": add_temp_reading,
    "food-list-temp-readings": list_temp_readings,
    "food-add-inspection": add_inspection,
    "food-update-inspection": update_inspection,
    "food-list-inspections": list_inspections,
    "food-complete-inspection": complete_inspection,
    "food-temp-violation-alert": temp_violation_alert,
    "food-haccp-compliance-report": haccp_compliance_report,
}
