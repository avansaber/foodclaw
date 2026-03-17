"""FoodClaw — menu domain module

Actions for the menu domain (4 tables, 12 actions).
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
    from erpclaw_lib.decimal_utils import to_decimal, round_currency
    from erpclaw_lib.naming import get_next_name, ENTITY_PREFIXES
    from erpclaw_lib.response import ok, err, row_to_dict
    from erpclaw_lib.audit import audit
    from erpclaw_lib.query import Q, P, Table, Field, fn, Order, insert_row, update_row, dynamic_update

    ENTITY_PREFIXES.setdefault("foodclaw_menu", "MENU-")
    ENTITY_PREFIXES.setdefault("foodclaw_menu_item", "MI-")
except ImportError:
    pass

_now_iso = lambda: datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

# ---------------------------------------------------------------------------
# Validation constants
# ---------------------------------------------------------------------------
VALID_MENU_TYPES = ("regular", "brunch", "lunch", "dinner", "happy_hour", "seasonal", "catering", "kids", "other")
VALID_ITEM_CATEGORIES = ("appetizer", "entree", "dessert", "beverage", "side", "soup", "salad", "other")


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
# 1. add-menu
# ---------------------------------------------------------------------------
def add_menu(conn, args):
    _validate_company(conn, args.company_id)
    if not getattr(args, "name", None):
        err("--name is required")
    _validate_enum(getattr(args, "menu_type", None), VALID_MENU_TYPES, "menu-type")

    menu_id = str(uuid.uuid4())
    ns = get_next_name(conn, "foodclaw_menu", company_id=args.company_id)
    now = _now_iso()

    sql, _ = insert_row("foodclaw_menu", {"id": P(), "naming_series": P(), "company_id": P(), "name": P(), "description": P(), "menu_type": P(), "is_active": P(), "effective_date": P(), "end_date": P(), "created_at": P(), "updated_at": P()})
    conn.execute(sql, (
        menu_id, ns, args.company_id, args.name,
        getattr(args, "description", None),
        getattr(args, "menu_type", None) or "regular",
        1,
        getattr(args, "effective_date", None),
        getattr(args, "end_date", None),
        now, now,
    ))
    audit(conn, "foodclaw_menu", menu_id, "food-add-menu", args.company_id)
    conn.commit()
    ok({"id": menu_id, "naming_series": ns, "name": args.name})


# ---------------------------------------------------------------------------
# 2. update-menu
# ---------------------------------------------------------------------------
def update_menu(conn, args):
    menu_id = getattr(args, "menu_id", None)
    if not menu_id:
        err("--menu-id is required")
    row = conn.execute(Q.from_(Table("foodclaw_menu")).select(Field("id")).where(Field("id") == P()).get_sql(), (menu_id,)).fetchone()
    if not row:
        err(f"Menu {menu_id} not found")

    _validate_enum(getattr(args, "menu_type", None), VALID_MENU_TYPES, "menu-type")

    data, changed = {}, []
    for field, col in [
        ("name", "name"), ("description", "description"), ("menu_type", "menu_type"),
        ("effective_date", "effective_date"), ("end_date", "end_date"),
    ]:
        val = getattr(args, field, None)
        if val is not None:
            data[col] = val
            changed.append(col)

    is_active = getattr(args, "is_active", None)
    if is_active is not None:
        data["is_active"] = int(is_active)
        changed.append("is_active")

    if not data:
        err("No fields to update")

    data["updated_at"] = _now_iso()
    sql, params = dynamic_update("foodclaw_menu", data, where={"id": menu_id})
    conn.execute(sql, params)
    audit(conn, "foodclaw_menu", menu_id, "food-update-menu", None)
    conn.commit()
    ok({"id": menu_id, "updated_fields": changed})


# ---------------------------------------------------------------------------
# 3. get-menu
# ---------------------------------------------------------------------------
def get_menu(conn, args):
    menu_id = getattr(args, "menu_id", None)
    if not menu_id:
        err("--menu-id is required")
    row = conn.execute(Q.from_(Table("foodclaw_menu")).select(Table("foodclaw_menu").star).where(Field("id") == P()).get_sql(), (menu_id,)).fetchone()
    if not row:
        err(f"Menu {menu_id} not found")
    data = row_to_dict(row)
    # Get item count
    cnt = conn.execute(Q.from_(Table("foodclaw_menu_item")).select(fn.Count("*")).where(Field("menu_id") == P()).get_sql(), (menu_id,)).fetchone()[0]
    data["item_count"] = cnt
    ok(data)


# ---------------------------------------------------------------------------
# 4. list-menus
# ---------------------------------------------------------------------------
def list_menus(conn, args):
    where, params = ["1=1"], []
    if getattr(args, "company_id", None):
        where.append("company_id = ?")
        params.append(args.company_id)
    if getattr(args, "menu_type", None):
        where.append("menu_type = ?")
        params.append(args.menu_type)
    if getattr(args, "search", None):
        where.append("(LOWER(name) LIKE LOWER(?) OR LOWER(description) LIKE LOWER(?))")
        params.extend([f"%{args.search}%", f"%{args.search}%"])

    total = conn.execute(
        f"SELECT COUNT(*) FROM foodclaw_menu WHERE {' AND '.join(where)}", params
    ).fetchone()[0]
    rows = conn.execute(
        f"SELECT * FROM foodclaw_menu WHERE {' AND '.join(where)} ORDER BY created_at DESC LIMIT ? OFFSET ?",
        params + [getattr(args, "limit", 50), getattr(args, "offset", 0)]
    ).fetchall()
    ok({"items": [row_to_dict(r) for r in rows], "total_count": total})


# ---------------------------------------------------------------------------
# 5. add-menu-item
# ---------------------------------------------------------------------------
def add_menu_item(conn, args):
    _validate_company(conn, args.company_id)
    if not getattr(args, "name", None):
        err("--name is required")
    _validate_enum(getattr(args, "category", None), VALID_ITEM_CATEGORIES, "category")

    # Validate menu if provided
    menu_id = getattr(args, "menu_id", None)
    if menu_id:
        row = conn.execute(Q.from_(Table("foodclaw_menu")).select(Field("id")).where(Field("id") == P()).get_sql(), (menu_id,)).fetchone()
        if not row:
            err(f"Menu {menu_id} not found")

    item_id = str(uuid.uuid4())
    ns = get_next_name(conn, "foodclaw_menu_item", company_id=args.company_id)
    now = _now_iso()

    price = getattr(args, "price", None) or "0.00"
    cost = getattr(args, "cost", None) or "0.00"
    # Validate Decimal
    to_decimal(price)
    to_decimal(cost)

    sql, _ = insert_row("foodclaw_menu_item", {"id": P(), "naming_series": P(), "company_id": P(), "menu_id": P(), "name": P(), "description": P(), "category": P(), "price": P(), "cost": P(), "allergens": P(), "nutrition_info": P(), "is_available": P(), "is_vegetarian": P(), "is_vegan": P(), "is_gluten_free": P(), "prep_time_min": P(), "calories": P(), "sort_order": P(), "created_at": P(), "updated_at": P()})
    conn.execute(sql, (
        item_id, ns, args.company_id, menu_id, args.name,
        getattr(args, "description", None),
        getattr(args, "category", None) or "other",
        price, cost,
        getattr(args, "allergens", None),
        getattr(args, "nutrition_info", None),
        1,
        int(getattr(args, "is_vegetarian", None) or 0),
        int(getattr(args, "is_vegan", None) or 0),
        int(getattr(args, "is_gluten_free", None) or 0),
        getattr(args, "prep_time_min", None),
        getattr(args, "calories", None),
        getattr(args, "sort_order", None) or 0,
        now, now,
    ))
    audit(conn, "foodclaw_menu_item", item_id, "food-add-menu-item", args.company_id)
    conn.commit()
    ok({"id": item_id, "naming_series": ns, "name": args.name, "price": price, "cost": cost})


# ---------------------------------------------------------------------------
# 6. update-menu-item
# ---------------------------------------------------------------------------
def update_menu_item(conn, args):
    item_id = getattr(args, "menu_item_id", None)
    if not item_id:
        err("--menu-item-id is required")
    row = conn.execute(Q.from_(Table("foodclaw_menu_item")).select(Field("id")).where(Field("id") == P()).get_sql(), (item_id,)).fetchone()
    if not row:
        err(f"Menu item {item_id} not found")
    _validate_enum(getattr(args, "category", None), VALID_ITEM_CATEGORIES, "category")

    data, changed = {}, []
    for field, col in [
        ("name", "name"), ("description", "description"), ("category", "category"),
        ("allergens", "allergens"), ("nutrition_info", "nutrition_info"),
    ]:
        val = getattr(args, field, None)
        if val is not None:
            data[col] = val
            changed.append(col)

    for field, col in [("price", "price"), ("cost", "cost")]:
        val = getattr(args, field, None)
        if val is not None:
            to_decimal(val)
            data[col] = val
            changed.append(col)

    for field, col in [("is_available", "is_available"), ("is_vegetarian", "is_vegetarian"),
                       ("is_vegan", "is_vegan"), ("is_gluten_free", "is_gluten_free")]:
        val = getattr(args, field, None)
        if val is not None:
            data[col] = int(val)
            changed.append(col)

    if not data:
        err("No fields to update")

    data["updated_at"] = _now_iso()
    sql, params = dynamic_update("foodclaw_menu_item", data, where={"id": item_id})
    conn.execute(sql, params)
    audit(conn, "foodclaw_menu_item", item_id, "food-update-menu-item", None)
    conn.commit()
    ok({"id": item_id, "updated_fields": changed})


# ---------------------------------------------------------------------------
# 7. get-menu-item
# ---------------------------------------------------------------------------
def get_menu_item(conn, args):
    item_id = getattr(args, "menu_item_id", None)
    if not item_id:
        err("--menu-item-id is required")
    row = conn.execute(Q.from_(Table("foodclaw_menu_item")).select(Table("foodclaw_menu_item").star).where(Field("id") == P()).get_sql(), (item_id,)).fetchone()
    if not row:
        err(f"Menu item {item_id} not found")
    data = row_to_dict(row)
    # Parse nutrition_info JSON if present
    if data.get("nutrition_info"):
        try:
            data["nutrition_info"] = json.loads(data["nutrition_info"])
        except (json.JSONDecodeError, TypeError):
            pass
    ok(data)


# ---------------------------------------------------------------------------
# 8. list-menu-items
# ---------------------------------------------------------------------------
def list_menu_items(conn, args):
    where, params = ["1=1"], []
    if getattr(args, "company_id", None):
        where.append("company_id = ?")
        params.append(args.company_id)
    if getattr(args, "menu_id", None):
        where.append("menu_id = ?")
        params.append(args.menu_id)
    if getattr(args, "category", None):
        where.append("category = ?")
        params.append(args.category)
    if getattr(args, "search", None):
        where.append("(LOWER(name) LIKE LOWER(?) OR LOWER(description) LIKE LOWER(?))")
        params.extend([f"%{args.search}%", f"%{args.search}%"])

    total = conn.execute(
        f"SELECT COUNT(*) FROM foodclaw_menu_item WHERE {' AND '.join(where)}", params
    ).fetchone()[0]
    rows = conn.execute(
        f"SELECT * FROM foodclaw_menu_item WHERE {' AND '.join(where)} ORDER BY sort_order, name LIMIT ? OFFSET ?",
        params + [getattr(args, "limit", 50), getattr(args, "offset", 0)]
    ).fetchall()
    ok({"items": [row_to_dict(r) for r in rows], "total_count": total})


# ---------------------------------------------------------------------------
# 9. add-modifier-group
# ---------------------------------------------------------------------------
def add_modifier_group(conn, args):
    _validate_company(conn, args.company_id)
    if not getattr(args, "name", None):
        err("--name is required")

    group_id = str(uuid.uuid4())
    now = _now_iso()

    sql, _ = insert_row("foodclaw_modifier_group", {"id": P(), "company_id": P(), "name": P(), "description": P(), "min_selections": P(), "max_selections": P(), "is_required": P(), "menu_item_id": P(), "created_at": P(), "updated_at": P()})
    conn.execute(sql, (
        group_id, args.company_id, args.name,
        getattr(args, "description", None),
        getattr(args, "min_selections", None) or 0,
        getattr(args, "max_selections", None) or 1,
        int(getattr(args, "is_required", None) or 0),
        getattr(args, "menu_item_id", None),
        now, now,
    ))
    audit(conn, "foodclaw_modifier_group", group_id, "food-add-modifier-group", args.company_id)
    conn.commit()
    ok({"id": group_id, "name": args.name})


# ---------------------------------------------------------------------------
# 10. list-modifier-groups
# ---------------------------------------------------------------------------
def list_modifier_groups(conn, args):
    where, params = ["1=1"], []
    if getattr(args, "company_id", None):
        where.append("company_id = ?")
        params.append(args.company_id)
    if getattr(args, "menu_item_id", None):
        where.append("menu_item_id = ?")
        params.append(args.menu_item_id)

    total = conn.execute(
        f"SELECT COUNT(*) FROM foodclaw_modifier_group WHERE {' AND '.join(where)}", params
    ).fetchone()[0]
    rows = conn.execute(
        f"SELECT * FROM foodclaw_modifier_group WHERE {' AND '.join(where)} ORDER BY name LIMIT ? OFFSET ?",
        params + [getattr(args, "limit", 50), getattr(args, "offset", 0)]
    ).fetchall()
    ok({"items": [row_to_dict(r) for r in rows], "total_count": total})


# ---------------------------------------------------------------------------
# 11. add-modifier
# ---------------------------------------------------------------------------
def add_modifier(conn, args):
    _validate_company(conn, args.company_id)
    mg_id = getattr(args, "modifier_group_id", None)
    if not mg_id:
        err("--modifier-group-id is required")
    row = conn.execute(Q.from_(Table("foodclaw_modifier_group")).select(Field("id")).where(Field("id") == P()).get_sql(), (mg_id,)).fetchone()
    if not row:
        err(f"Modifier group {mg_id} not found")
    if not getattr(args, "name", None):
        err("--name is required")

    price_adj = getattr(args, "price_adjustment", None) or "0.00"
    to_decimal(price_adj)

    mod_id = str(uuid.uuid4())
    now = _now_iso()

    sql, _ = insert_row("foodclaw_modifier", {"id": P(), "company_id": P(), "modifier_group_id": P(), "name": P(), "price_adjustment": P(), "is_default": P(), "is_available": P(), "sort_order": P(), "created_at": P(), "updated_at": P()})
    conn.execute(sql, (
        mod_id, args.company_id, mg_id, args.name,
        price_adj,
        int(getattr(args, "is_default", None) or 0),
        1,
        getattr(args, "sort_order", None) or 0,
        now, now,
    ))
    audit(conn, "foodclaw_modifier", mod_id, "food-add-modifier", args.company_id)
    conn.commit()
    ok({"id": mod_id, "name": args.name, "price_adjustment": price_adj})


# ---------------------------------------------------------------------------
# 12. list-modifiers
# ---------------------------------------------------------------------------
def list_modifiers(conn, args):
    where, params = ["1=1"], []
    if getattr(args, "modifier_group_id", None):
        where.append("modifier_group_id = ?")
        params.append(args.modifier_group_id)
    if getattr(args, "company_id", None):
        where.append("company_id = ?")
        params.append(args.company_id)

    total = conn.execute(
        f"SELECT COUNT(*) FROM foodclaw_modifier WHERE {' AND '.join(where)}", params
    ).fetchone()[0]
    rows = conn.execute(
        f"SELECT * FROM foodclaw_modifier WHERE {' AND '.join(where)} ORDER BY sort_order, name LIMIT ? OFFSET ?",
        params + [getattr(args, "limit", 50), getattr(args, "offset", 0)]
    ).fetchall()
    ok({"items": [row_to_dict(r) for r in rows], "total_count": total})


# ---------------------------------------------------------------------------
# ACTIONS registry
# ---------------------------------------------------------------------------
ACTIONS = {
    "food-add-menu": add_menu,
    "food-update-menu": update_menu,
    "food-get-menu": get_menu,
    "food-list-menus": list_menus,
    "food-add-menu-item": add_menu_item,
    "food-update-menu-item": update_menu_item,
    "food-get-menu-item": get_menu_item,
    "food-list-menu-items": list_menu_items,
    "food-add-modifier-group": add_modifier_group,
    "food-list-modifier-groups": list_modifier_groups,
    "food-add-modifier": add_modifier,
    "food-list-modifiers": list_modifiers,
}
