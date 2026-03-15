"""FoodClaw — inventory domain module

Actions for the F&B inventory domain (4 tables, 12 actions).
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
    from erpclaw_lib.query import Q, P, Table, Field, fn, Order, insert_row, update_row

    ENTITY_PREFIXES.setdefault("foodclaw_ingredient", "ING-")
    ENTITY_PREFIXES.setdefault("foodclaw_purchase_order", "FPO-")
except ImportError:
    pass

_now_iso = lambda: datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

VALID_INGREDIENT_CATEGORIES = ("produce", "protein", "dairy", "dry_goods", "frozen", "beverage", "spice", "oil", "other")
VALID_INGREDIENT_STATUSES = ("active", "inactive", "discontinued")
VALID_WASTE_REASONS = ("expired", "spoiled", "overproduction", "damaged", "prep_waste", "plate_waste", "other")
VALID_PO_STATUSES = ("draft", "sent", "received", "partial", "cancelled")


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
# 1. add-ingredient
# ---------------------------------------------------------------------------
def add_ingredient(conn, args):
    _validate_company(conn, args.company_id)
    if not getattr(args, "name", None):
        err("--name is required")
    _validate_enum(getattr(args, "ingredient_category", None), VALID_INGREDIENT_CATEGORIES, "category")

    ing_id = str(uuid.uuid4())
    ns = get_next_name(conn, "foodclaw_ingredient", company_id=args.company_id)
    now = _now_iso()

    unit_cost = getattr(args, "unit_cost", None) or "0.00"
    par_level = getattr(args, "par_level", None) or "0"
    current_stock = getattr(args, "current_stock", None) or "0"
    to_decimal(unit_cost)
    to_decimal(par_level)
    to_decimal(current_stock)

    conn.execute("""
        INSERT INTO foodclaw_ingredient (id, naming_series, company_id, name, category,
            unit, par_level, current_stock, unit_cost, supplier, is_perishable,
            expiry_date, reorder_point, storage_location, status, created_at, updated_at)
        VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
    """, (
        ing_id, ns, args.company_id, args.name,
        getattr(args, "ingredient_category", None) or "other",
        getattr(args, "unit", None) or "unit",
        par_level, current_stock, unit_cost,
        getattr(args, "supplier", None),
        int(getattr(args, "is_perishable", None) or 0),
        getattr(args, "expiry_date", None),
        getattr(args, "reorder_point", None) or "0",
        getattr(args, "storage_location", None),
        "active",
        now, now,
    ))
    audit(conn, "foodclaw_ingredient", ing_id, "food-add-ingredient", args.company_id)
    conn.commit()
    ok({"id": ing_id, "naming_series": ns, "name": args.name, "unit_cost": unit_cost})


# ---------------------------------------------------------------------------
# 2. update-ingredient
# ---------------------------------------------------------------------------
def update_ingredient(conn, args):
    ing_id = getattr(args, "ingredient_id", None)
    if not ing_id:
        err("--ingredient-id is required")
    row = conn.execute(Q.from_(Table("foodclaw_ingredient")).select(Field("id"), Field("company_id")).where(Field("id") == P()).get_sql(), (ing_id,)).fetchone()
    if not row:
        err(f"Ingredient {ing_id} not found")
    _validate_enum(getattr(args, "ingredient_category", None), VALID_INGREDIENT_CATEGORIES, "category")
    _validate_enum(getattr(args, "ingredient_status", None), VALID_INGREDIENT_STATUSES, "status")

    updates, params = [], []
    for field, col in [
        ("name", "name"), ("unit", "unit"), ("supplier", "supplier"),
        ("expiry_date", "expiry_date"), ("storage_location", "storage_location"),
    ]:
        val = getattr(args, field, None)
        if val is not None:
            updates.append(f"{col} = ?")
            params.append(val)

    if getattr(args, "ingredient_category", None):
        updates.append("category = ?")
        params.append(args.ingredient_category)

    if getattr(args, "ingredient_status", None):
        updates.append("status = ?")
        params.append(args.ingredient_status)

    for field, col in [("unit_cost", "unit_cost"), ("par_level", "par_level"),
                       ("current_stock", "current_stock"), ("reorder_point", "reorder_point")]:
        val = getattr(args, field, None)
        if val is not None:
            to_decimal(val)
            updates.append(f"{col} = ?")
            params.append(val)

    is_per = getattr(args, "is_perishable", None)
    if is_per is not None:
        updates.append("is_perishable = ?")
        params.append(int(is_per))

    if not updates:
        err("No fields to update")

    updates.append("updated_at = ?")
    params.append(_now_iso())
    params.append(ing_id)

    conn.execute(f"UPDATE foodclaw_ingredient SET {', '.join(updates)} WHERE id = ?", params)
    audit(conn, "foodclaw_ingredient", ing_id, "food-update-ingredient", row["company_id"])
    conn.commit()
    ok({"id": ing_id, "updated_fields": [u.split(" = ")[0] for u in updates if u != "updated_at = ?"]})


# ---------------------------------------------------------------------------
# 3. get-ingredient
# ---------------------------------------------------------------------------
def get_ingredient(conn, args):
    ing_id = getattr(args, "ingredient_id", None)
    if not ing_id:
        err("--ingredient-id is required")
    row = conn.execute(Q.from_(Table("foodclaw_ingredient")).select(Table("foodclaw_ingredient").star).where(Field("id") == P()).get_sql(), (ing_id,)).fetchone()
    if not row:
        err(f"Ingredient {ing_id} not found")
    ok(row_to_dict(row))


# ---------------------------------------------------------------------------
# 4. list-ingredients
# ---------------------------------------------------------------------------
def list_ingredients(conn, args):
    where, params = ["1=1"], []
    if getattr(args, "company_id", None):
        where.append("company_id = ?")
        params.append(args.company_id)
    if getattr(args, "ingredient_category", None):
        where.append("category = ?")
        params.append(args.ingredient_category)
    if getattr(args, "ingredient_status", None):
        where.append("status = ?")
        params.append(args.ingredient_status)
    if getattr(args, "search", None):
        where.append("name LIKE ?")
        params.append(f"%{args.search}%")

    total = conn.execute(
        f"SELECT COUNT(*) FROM foodclaw_ingredient WHERE {' AND '.join(where)}", params
    ).fetchone()[0]
    rows = conn.execute(
        f"SELECT * FROM foodclaw_ingredient WHERE {' AND '.join(where)} ORDER BY name LIMIT ? OFFSET ?",
        params + [getattr(args, "limit", 50), getattr(args, "offset", 0)]
    ).fetchall()
    ok({"items": [row_to_dict(r) for r in rows], "total_count": total})


# ---------------------------------------------------------------------------
# 5. add-stock-count
# ---------------------------------------------------------------------------
def add_stock_count(conn, args):
    _validate_company(conn, args.company_id)
    ing_id = getattr(args, "ingredient_id", None)
    if not ing_id:
        err("--ingredient-id is required")
    row = conn.execute(Q.from_(Table("foodclaw_ingredient")).select(Field("id"), Field("current_stock")).where(Field("id") == P()).get_sql(), (ing_id,)).fetchone()
    if not row:
        err(f"Ingredient {ing_id} not found")

    count_date = getattr(args, "count_date", None)
    if not count_date:
        err("--count-date is required")

    counted_qty = getattr(args, "counted_qty", None) or "0"
    to_decimal(counted_qty)
    system_qty = row[1] or "0"
    variance = str(to_decimal(counted_qty) - to_decimal(system_qty))

    sc_id = str(uuid.uuid4())

    conn.execute("""
        INSERT INTO foodclaw_stock_count (id, company_id, ingredient_id, count_date,
            counted_qty, system_qty, variance, counted_by, notes, created_at)
        VALUES (?,?,?,?,?,?,?,?,?,?)
    """, (
        sc_id, args.company_id, ing_id, count_date,
        counted_qty, system_qty, variance,
        getattr(args, "counted_by", None),
        getattr(args, "notes", None),
        _now_iso(),
    ))

    # Update current stock to match count
    conn.execute("UPDATE foodclaw_ingredient SET current_stock = ?, updated_at = ? WHERE id = ?",
                 (counted_qty, _now_iso(), ing_id))
    audit(conn, "foodclaw_stock_count", sc_id, "food-add-stock-count", args.company_id)
    conn.commit()
    ok({"id": sc_id, "ingredient_id": ing_id, "counted_qty": counted_qty, "system_qty": system_qty, "variance": variance})


# ---------------------------------------------------------------------------
# 6. list-stock-counts
# ---------------------------------------------------------------------------
def list_stock_counts(conn, args):
    where, params = ["1=1"], []
    if getattr(args, "company_id", None):
        where.append("company_id = ?")
        params.append(args.company_id)
    if getattr(args, "ingredient_id", None):
        where.append("ingredient_id = ?")
        params.append(args.ingredient_id)

    total = conn.execute(
        f"SELECT COUNT(*) FROM foodclaw_stock_count WHERE {' AND '.join(where)}", params
    ).fetchone()[0]
    rows = conn.execute(
        f"SELECT * FROM foodclaw_stock_count WHERE {' AND '.join(where)} ORDER BY count_date DESC LIMIT ? OFFSET ?",
        params + [getattr(args, "limit", 50), getattr(args, "offset", 0)]
    ).fetchall()
    ok({"items": [row_to_dict(r) for r in rows], "total_count": total})


# ---------------------------------------------------------------------------
# 7. add-waste-log
# ---------------------------------------------------------------------------
def add_waste_log(conn, args):
    _validate_company(conn, args.company_id)
    item_name = getattr(args, "item_name", None)
    if not item_name:
        err("--item-name is required")
    waste_date = getattr(args, "waste_date", None)
    if not waste_date:
        err("--waste-date is required")
    _validate_enum(getattr(args, "waste_reason", None), VALID_WASTE_REASONS, "reason")

    quantity = getattr(args, "quantity", None) or "0"
    waste_cost = getattr(args, "waste_cost", None) or "0.00"
    to_decimal(quantity)
    to_decimal(waste_cost)

    # Validate ingredient_id FK if provided
    ing_id = getattr(args, "ingredient_id", None)
    if ing_id:
        row = conn.execute(Q.from_(Table("foodclaw_ingredient")).select(Field("id")).where(Field("id") == P()).get_sql(), (ing_id,)).fetchone()
        if not row:
            err(f"Ingredient {ing_id} not found")

    wl_id = str(uuid.uuid4())

    conn.execute("""
        INSERT INTO foodclaw_waste_log (id, company_id, ingredient_id, item_name,
            waste_date, quantity, unit, reason, cost, logged_by, notes, created_at)
        VALUES (?,?,?,?,?,?,?,?,?,?,?,?)
    """, (
        wl_id, args.company_id, ing_id, item_name,
        waste_date, quantity,
        getattr(args, "unit", None) or "unit",
        getattr(args, "waste_reason", None) or "other",
        waste_cost,
        getattr(args, "logged_by", None),
        getattr(args, "notes", None),
        _now_iso(),
    ))
    audit(conn, "foodclaw_waste_log", wl_id, "food-add-waste-log", args.company_id)
    conn.commit()
    ok({"id": wl_id, "item_name": item_name, "quantity": quantity, "cost": waste_cost})


# ---------------------------------------------------------------------------
# 8. list-waste-logs
# ---------------------------------------------------------------------------
def list_waste_logs(conn, args):
    where, params = ["1=1"], []
    if getattr(args, "company_id", None):
        where.append("company_id = ?")
        params.append(args.company_id)
    if getattr(args, "ingredient_id", None):
        where.append("ingredient_id = ?")
        params.append(args.ingredient_id)
    if getattr(args, "waste_reason", None):
        where.append("reason = ?")
        params.append(args.waste_reason)

    total = conn.execute(
        f"SELECT COUNT(*) FROM foodclaw_waste_log WHERE {' AND '.join(where)}", params
    ).fetchone()[0]
    rows = conn.execute(
        f"SELECT * FROM foodclaw_waste_log WHERE {' AND '.join(where)} ORDER BY waste_date DESC LIMIT ? OFFSET ?",
        params + [getattr(args, "limit", 50), getattr(args, "offset", 0)]
    ).fetchall()
    ok({"items": [row_to_dict(r) for r in rows], "total_count": total})


# ---------------------------------------------------------------------------
# 9. add-purchase-order
# ---------------------------------------------------------------------------
def add_purchase_order(conn, args):
    _validate_company(conn, args.company_id)
    supplier_id = getattr(args, "supplier_id", None)
    if not supplier_id:
        err("--supplier-id is required")
    # Validate supplier FK against core supplier table
    sup_row = conn.execute(Q.from_(Table("supplier")).select(Field("id"), Field("name")).where(Field("id") == P()).get_sql(), (supplier_id,)).fetchone()
    if not sup_row:
        err(f"Supplier {supplier_id} not found in core supplier table")
    order_date = getattr(args, "order_date", None)
    if not order_date:
        err("--order-date is required")

    total_amount = getattr(args, "total_amount", None) or "0.00"
    to_decimal(total_amount)

    po_id = str(uuid.uuid4())
    ns = get_next_name(conn, "foodclaw_purchase_order", company_id=args.company_id)
    now = _now_iso()

    conn.execute("""
        INSERT INTO foodclaw_purchase_order (id, naming_series, company_id, supplier_id,
            order_date, expected_date, total_amount, order_status, notes, items_json,
            created_at, updated_at)
        VALUES (?,?,?,?,?,?,?,?,?,?,?,?)
    """, (
        po_id, ns, args.company_id, supplier_id,
        order_date,
        getattr(args, "expected_date", None),
        total_amount,
        "draft",
        getattr(args, "notes", None),
        getattr(args, "items_json", None),
        now, now,
    ))
    audit(conn, "foodclaw_purchase_order", po_id, "food-add-purchase-order", args.company_id)
    conn.commit()
    ok({"id": po_id, "naming_series": ns, "supplier_id": supplier_id, "supplier_name": sup_row[1], "order_status": "draft", "total_amount": total_amount})


# ---------------------------------------------------------------------------
# 10. list-purchase-orders
# ---------------------------------------------------------------------------
def list_purchase_orders(conn, args):
    where, params = ["1=1"], []
    if getattr(args, "company_id", None):
        where.append("po.company_id = ?")
        params.append(args.company_id)
    if getattr(args, "order_status", None):
        _validate_enum(args.order_status, VALID_PO_STATUSES, "order-status")
        where.append("po.order_status = ?")
        params.append(args.order_status)
    if getattr(args, "search", None):
        where.append("s.name LIKE ?")
        params.append(f"%{args.search}%")

    where_sql = " AND ".join(where)
    total = conn.execute(
        f"SELECT COUNT(*) FROM foodclaw_purchase_order po LEFT JOIN supplier s ON po.supplier_id = s.id WHERE {where_sql}", params
    ).fetchone()[0]
    rows = conn.execute(
        f"""SELECT po.*, s.name AS supplier_name
            FROM foodclaw_purchase_order po
            LEFT JOIN supplier s ON po.supplier_id = s.id
            WHERE {where_sql}
            ORDER BY po.order_date DESC LIMIT ? OFFSET ?""",
        params + [getattr(args, "limit", 50), getattr(args, "offset", 0)]
    ).fetchall()
    ok({"items": [row_to_dict(r) for r in rows], "total_count": total})


# ---------------------------------------------------------------------------
# 11. par-level-alert
# ---------------------------------------------------------------------------
def par_level_alert(conn, args):
    """Items where current_stock < par_level."""
    where, params = ["CAST(current_stock AS REAL) < CAST(par_level AS REAL)", "CAST(par_level AS REAL) > 0", "status = 'active'"], []
    if getattr(args, "company_id", None):
        where.append("company_id = ?")
        params.append(args.company_id)

    rows = conn.execute(
        f"SELECT * FROM foodclaw_ingredient WHERE {' AND '.join(where)} ORDER BY name",
        params
    ).fetchall()

    alerts = []
    for r in rows:
        d = row_to_dict(r)
        deficit = str(to_decimal(d["par_level"]) - to_decimal(d["current_stock"]))
        d["deficit"] = deficit
        alerts.append(d)

    ok({"items": alerts, "total_count": len(alerts)})


# ---------------------------------------------------------------------------
# 12. inventory-valuation
# ---------------------------------------------------------------------------
def inventory_valuation(conn, args):
    """Total inventory value = sum(current_stock * unit_cost)."""
    where, params = ["status = 'active'"], []
    if getattr(args, "company_id", None):
        where.append("company_id = ?")
        params.append(args.company_id)

    rows = conn.execute(
        f"SELECT * FROM foodclaw_ingredient WHERE {' AND '.join(where)} ORDER BY name",
        params
    ).fetchall()

    items = []
    total_value = Decimal("0.00")
    for r in rows:
        d = row_to_dict(r)
        stock = to_decimal(d.get("current_stock", "0"))
        cost = to_decimal(d.get("unit_cost", "0.00"))
        value = (stock * cost).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
        total_value += value
        items.append({
            "ingredient_id": d["id"],
            "name": d["name"],
            "current_stock": str(stock),
            "unit_cost": str(cost),
            "value": str(value),
        })

    ok({"items": items, "total_count": len(items), "total_value": str(total_value)})


# ---------------------------------------------------------------------------
# ACTIONS registry
# ---------------------------------------------------------------------------
ACTIONS = {
    "food-add-ingredient": add_ingredient,
    "food-update-ingredient": update_ingredient,
    "food-get-ingredient": get_ingredient,
    "food-list-ingredients": list_ingredients,
    "food-add-stock-count": add_stock_count,
    "food-list-stock-counts": list_stock_counts,
    "food-add-waste-log": add_waste_log,
    "food-list-waste-logs": list_waste_logs,
    "food-add-purchase-order": add_purchase_order,
    "food-list-purchase-orders": list_purchase_orders,
    "food-par-level-alert": par_level_alert,
    "food-inventory-valuation": inventory_valuation,
}
