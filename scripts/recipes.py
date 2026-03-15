"""FoodClaw — recipes domain module

Actions for the recipe domain (2 tables, 10 actions).
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

    ENTITY_PREFIXES.setdefault("foodclaw_recipe", "RCP-")
except ImportError:
    pass

_now_iso = lambda: datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _validate_company(conn, company_id):
    if not company_id:
        err("--company-id is required")
    row = conn.execute(Q.from_(Table("company")).select(Field("id")).where(Field("id") == P()).get_sql(), (company_id,)).fetchone()
    if not row:
        err(f"Company {company_id} not found")


# ---------------------------------------------------------------------------
# 1. add-recipe
# ---------------------------------------------------------------------------
def add_recipe(conn, args):
    _validate_company(conn, args.company_id)
    if not getattr(args, "name", None):
        err("--name is required")

    recipe_id = str(uuid.uuid4())
    ns = get_next_name(conn, "foodclaw_recipe", company_id=args.company_id)
    now = _now_iso()

    # Validate menu_item_id FK if provided
    mi_id = getattr(args, "menu_item_id", None)
    if mi_id:
        row = conn.execute(Q.from_(Table("foodclaw_menu_item")).select(Field("id")).where(Field("id") == P()).get_sql(), (mi_id,)).fetchone()
        if not row:
            err(f"Menu item {mi_id} not found")

    batch_size = getattr(args, "batch_size", None) or "1"
    yield_pct = getattr(args, "expected_yield_pct", None) or "100.00"
    to_decimal(batch_size)
    to_decimal(yield_pct)

    conn.execute("""
        INSERT INTO foodclaw_recipe (id, naming_series, company_id, name, product_name,
            description, category, batch_size, batch_unit, expected_yield_pct,
            total_cost, cost_per_portion, portions_per_batch,
            prep_time_min, cook_time_min, instructions, menu_item_id, status,
            created_at, updated_at)
        VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
    """, (
        recipe_id, ns, args.company_id, args.name,
        getattr(args, "product_name", None),
        getattr(args, "description", None),
        getattr(args, "category", None),
        batch_size,
        getattr(args, "batch_unit", None) or "portion",
        yield_pct,
        "0.00", "0.00",
        getattr(args, "portions_per_batch", None) or 1,
        getattr(args, "prep_time_min", None),
        getattr(args, "cook_time_min", None),
        getattr(args, "instructions", None),
        mi_id,
        "active",
        now, now,
    ))
    audit(conn, "foodclaw_recipe", recipe_id, "food-add-recipe", args.company_id)
    conn.commit()
    ok({"id": recipe_id, "naming_series": ns, "name": args.name})


# ---------------------------------------------------------------------------
# 2. update-recipe
# ---------------------------------------------------------------------------
def update_recipe(conn, args):
    recipe_id = getattr(args, "recipe_id", None)
    if not recipe_id:
        err("--recipe-id is required")
    row = conn.execute(Q.from_(Table("foodclaw_recipe")).select(Field("id")).where(Field("id") == P()).get_sql(), (recipe_id,)).fetchone()
    if not row:
        err(f"Recipe {recipe_id} not found")

    updates, params = [], []
    for field, col in [
        ("name", "name"), ("product_name", "product_name"), ("description", "description"),
        ("category", "category"), ("batch_unit", "batch_unit"),
        ("instructions", "instructions"), ("status", "status"),
    ]:
        val = getattr(args, field, None)
        if val is not None:
            updates.append(f"{col} = ?")
            params.append(val)

    for field, col in [("batch_size", "batch_size"), ("expected_yield_pct", "expected_yield_pct")]:
        val = getattr(args, field, None)
        if val is not None:
            to_decimal(val)
            updates.append(f"{col} = ?")
            params.append(val)

    ppb = getattr(args, "portions_per_batch", None)
    if ppb is not None:
        updates.append("portions_per_batch = ?")
        params.append(int(ppb))

    for field in ("prep_time_min", "cook_time_min"):
        val = getattr(args, field, None)
        if val is not None:
            updates.append(f"{field} = ?")
            params.append(int(val))

    if not updates:
        err("No fields to update")

    updates.append("updated_at = ?")
    params.append(_now_iso())
    params.append(recipe_id)

    conn.execute(f"UPDATE foodclaw_recipe SET {', '.join(updates)} WHERE id = ?", params)
    audit(conn, "foodclaw_recipe", recipe_id, "food-update-recipe", None)
    conn.commit()
    ok({"id": recipe_id, "updated_fields": [u.split(" = ")[0] for u in updates if u != "updated_at = ?"]})


# ---------------------------------------------------------------------------
# 3. get-recipe
# ---------------------------------------------------------------------------
def get_recipe(conn, args):
    recipe_id = getattr(args, "recipe_id", None)
    if not recipe_id:
        err("--recipe-id is required")
    row = conn.execute(Q.from_(Table("foodclaw_recipe")).select(Table("foodclaw_recipe").star).where(Field("id") == P()).get_sql(), (recipe_id,)).fetchone()
    if not row:
        err(f"Recipe {recipe_id} not found")
    data = row_to_dict(row)

    # Get ingredients
    ing_rows = conn.execute(
        "SELECT * FROM foodclaw_recipe_ingredient WHERE recipe_id = ? ORDER BY sort_order",
        (recipe_id,)
    ).fetchall()
    data["ingredients"] = [row_to_dict(r) for r in ing_rows]
    data["ingredient_count"] = len(ing_rows)
    ok(data)


# ---------------------------------------------------------------------------
# 4. list-recipes
# ---------------------------------------------------------------------------
def list_recipes(conn, args):
    where, params = ["1=1"], []
    if getattr(args, "company_id", None):
        where.append("company_id = ?")
        params.append(args.company_id)
    if getattr(args, "category", None):
        where.append("category = ?")
        params.append(args.category)
    if getattr(args, "status", None):
        where.append("status = ?")
        params.append(args.status)
    if getattr(args, "search", None):
        where.append("(name LIKE ? OR product_name LIKE ?)")
        params.extend([f"%{args.search}%", f"%{args.search}%"])

    total = conn.execute(
        f"SELECT COUNT(*) FROM foodclaw_recipe WHERE {' AND '.join(where)}", params
    ).fetchone()[0]
    rows = conn.execute(
        f"SELECT * FROM foodclaw_recipe WHERE {' AND '.join(where)} ORDER BY name LIMIT ? OFFSET ?",
        params + [getattr(args, "limit", 50), getattr(args, "offset", 0)]
    ).fetchall()
    ok({"items": [row_to_dict(r) for r in rows], "total_count": total})


# ---------------------------------------------------------------------------
# 5. add-recipe-ingredient
# ---------------------------------------------------------------------------
def add_recipe_ingredient(conn, args):
    recipe_id = getattr(args, "recipe_id", None)
    if not recipe_id:
        err("--recipe-id is required")
    row = conn.execute(Q.from_(Table("foodclaw_recipe")).select(Field("id")).where(Field("id") == P()).get_sql(), (recipe_id,)).fetchone()
    if not row:
        err(f"Recipe {recipe_id} not found")

    ingredient_name = getattr(args, "ingredient_name", None)
    if not ingredient_name:
        err("--ingredient-name is required")

    # Validate ingredient_id FK if provided
    ing_id = getattr(args, "ingredient_id", None)
    if ing_id:
        row = conn.execute(Q.from_(Table("foodclaw_ingredient")).select(Field("id")).where(Field("id") == P()).get_sql(), (ing_id,)).fetchone()
        if not row:
            err(f"Ingredient {ing_id} not found")

    qty = getattr(args, "quantity", None) or "0"
    unit_cost = getattr(args, "unit_cost", None)
    # Inherit cost from ingredient master if not explicitly provided
    if not unit_cost and ing_id:
        ing_row = conn.execute(Q.from_(Table("foodclaw_ingredient")).select(Field("unit_cost")).where(Field("id") == P()).get_sql(), (ing_id,)).fetchone()
        if ing_row and ing_row["unit_cost"]:
            unit_cost = ing_row["unit_cost"]
    if not unit_cost:
        unit_cost = "0.00"
    to_decimal(qty)
    to_decimal(unit_cost)
    line_cost = str(to_decimal(qty) * to_decimal(unit_cost))

    ri_id = str(uuid.uuid4())
    now = _now_iso()

    conn.execute("""
        INSERT INTO foodclaw_recipe_ingredient (id, recipe_id, ingredient_id, ingredient_name,
            quantity, unit, unit_cost, line_cost, notes, sort_order, created_at, updated_at)
        VALUES (?,?,?,?,?,?,?,?,?,?,?,?)
    """, (
        ri_id, recipe_id, ing_id, ingredient_name,
        qty,
        getattr(args, "unit", None) or "unit",
        unit_cost, line_cost,
        getattr(args, "notes", None),
        getattr(args, "sort_order", None) or 0,
        now, now,
    ))
    audit(conn, "foodclaw_recipe_ingredient", ri_id, "food-add-recipe-ingredient", None)
    conn.commit()
    ok({"id": ri_id, "ingredient_name": ingredient_name, "quantity": qty, "unit_cost": unit_cost, "line_cost": line_cost})


# ---------------------------------------------------------------------------
# 6. update-recipe-ingredient
# ---------------------------------------------------------------------------
def update_recipe_ingredient(conn, args):
    ri_id = getattr(args, "recipe_ingredient_id", None)
    if not ri_id:
        err("--recipe-ingredient-id is required")
    row = conn.execute(Q.from_(Table("foodclaw_recipe_ingredient")).select(Field("id")).where(Field("id") == P()).get_sql(), (ri_id,)).fetchone()
    if not row:
        err(f"Recipe ingredient {ri_id} not found")

    updates, params = [], []
    for field, col in [
        ("ingredient_name", "ingredient_name"), ("unit", "unit"), ("notes", "notes"),
    ]:
        val = getattr(args, field, None)
        if val is not None:
            updates.append(f"{col} = ?")
            params.append(val)

    for field, col in [("quantity", "quantity"), ("unit_cost", "unit_cost")]:
        val = getattr(args, field, None)
        if val is not None:
            to_decimal(val)
            updates.append(f"{col} = ?")
            params.append(val)

    if not updates:
        err("No fields to update")

    # Recalculate line_cost if quantity or unit_cost changed
    cur = conn.execute(Q.from_(Table("foodclaw_recipe_ingredient")).select(Field("quantity"), Field("unit_cost")).where(Field("id") == P()).get_sql(), (ri_id,)).fetchone()
    new_qty = None
    new_uc = None
    for field, val in [("quantity", getattr(args, "quantity", None)), ("unit_cost", getattr(args, "unit_cost", None))]:
        if field == "quantity" and val is not None:
            new_qty = val
        if field == "unit_cost" and val is not None:
            new_uc = val
    qty = to_decimal(new_qty or cur[0])
    uc = to_decimal(new_uc or cur[1])
    line_cost = str(qty * uc)
    updates.append("line_cost = ?")
    params.append(line_cost)

    updates.append("updated_at = ?")
    params.append(_now_iso())
    params.append(ri_id)

    conn.execute(f"UPDATE foodclaw_recipe_ingredient SET {', '.join(updates)} WHERE id = ?", params)
    audit(conn, "foodclaw_recipe_ingredient", ri_id, "food-update-recipe-ingredient", None)
    conn.commit()
    ok({"id": ri_id, "line_cost": line_cost, "updated_fields": [u.split(" = ")[0] for u in updates if u not in ("updated_at = ?", "line_cost = ?")]})


# ---------------------------------------------------------------------------
# 7. list-recipe-ingredients
# ---------------------------------------------------------------------------
def list_recipe_ingredients(conn, args):
    recipe_id = getattr(args, "recipe_id", None)
    if not recipe_id:
        err("--recipe-id is required")

    rows = conn.execute(
        "SELECT * FROM foodclaw_recipe_ingredient WHERE recipe_id = ? ORDER BY sort_order",
        (recipe_id,)
    ).fetchall()
    ok({"items": [row_to_dict(r) for r in rows], "total_count": len(rows)})


# ---------------------------------------------------------------------------
# 8. calculate-recipe-cost
# ---------------------------------------------------------------------------
def calculate_recipe_cost(conn, args):
    recipe_id = getattr(args, "recipe_id", None)
    if not recipe_id:
        err("--recipe-id is required")
    recipe = conn.execute(Q.from_(Table("foodclaw_recipe")).select(Table("foodclaw_recipe").star).where(Field("id") == P()).get_sql(), (recipe_id,)).fetchone()
    if not recipe:
        err(f"Recipe {recipe_id} not found")
    recipe_data = row_to_dict(recipe)

    rows = conn.execute(Q.from_(Table("foodclaw_recipe_ingredient")).select(Table("foodclaw_recipe_ingredient").star).where(Field("recipe_id") == P()).get_sql(), (recipe_id,)).fetchall()

    total = Decimal("0.00")
    ingredients = []
    for r in rows:
        d = row_to_dict(r)
        qty = to_decimal(d.get("quantity", "0"))
        uc = to_decimal(d.get("unit_cost", "0.00"))
        lc = qty * uc
        # Update line_cost in DB
        conn.execute("UPDATE foodclaw_recipe_ingredient SET line_cost = ? WHERE id = ?", (str(lc), d["id"]))
        total += lc
        ingredients.append({"ingredient_name": d["ingredient_name"], "quantity": str(qty), "unit_cost": str(uc), "line_cost": str(lc)})

    ppb = int(recipe_data.get("portions_per_batch", 1) or 1)
    cost_per_portion = str((total / Decimal(str(ppb))).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)) if ppb > 0 else "0.00"

    # Update recipe totals
    conn.execute(
        "UPDATE foodclaw_recipe SET total_cost = ?, cost_per_portion = ?, updated_at = ? WHERE id = ?",
        (str(total), cost_per_portion, _now_iso(), recipe_id)
    )
    conn.commit()

    ok({
        "recipe_id": recipe_id,
        "recipe_name": recipe_data.get("name"),
        "ingredients": ingredients,
        "total_cost": str(total),
        "portions_per_batch": ppb,
        "cost_per_portion": cost_per_portion,
    })


# ---------------------------------------------------------------------------
# 9. cost-analysis
# ---------------------------------------------------------------------------
def cost_analysis(conn, args):
    """Food cost % = cost / price for menu items linked to recipes."""
    where, params = ["r.status = 'active'"], []
    if getattr(args, "company_id", None):
        where.append("r.company_id = ?")
        params.append(args.company_id)

    rows = conn.execute(f"""
        SELECT r.id as recipe_id, r.name as recipe_name, r.total_cost, r.cost_per_portion,
               mi.id as menu_item_id, mi.name as item_name, mi.price
        FROM foodclaw_recipe r
        LEFT JOIN foodclaw_menu_item mi ON r.menu_item_id = mi.id
        WHERE {' AND '.join(where)}
        ORDER BY r.name
    """, params).fetchall()

    analysis = []
    for r in rows:
        d = row_to_dict(r)
        cost = to_decimal(d.get("cost_per_portion", "0.00"))
        price = to_decimal(d.get("price", "0.00"))
        food_cost_pct = "0.00"
        if price > 0:
            food_cost_pct = str((cost / price * Decimal("100")).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP))
        analysis.append({
            "recipe_id": d["recipe_id"],
            "recipe_name": d["recipe_name"],
            "cost_per_portion": str(cost),
            "menu_price": str(price),
            "food_cost_pct": food_cost_pct,
            "menu_item_name": d.get("item_name"),
        })

    ok({"items": analysis, "total_count": len(analysis)})


# ---------------------------------------------------------------------------
# 10. recipe-scaling
# ---------------------------------------------------------------------------
def recipe_scaling(conn, args):
    """Scale ingredients for different batch sizes."""
    recipe_id = getattr(args, "recipe_id", None)
    if not recipe_id:
        err("--recipe-id is required")
    target_portions = getattr(args, "target_portions", None)
    if not target_portions:
        err("--target-portions is required")

    recipe = conn.execute(Q.from_(Table("foodclaw_recipe")).select(Table("foodclaw_recipe").star).where(Field("id") == P()).get_sql(), (recipe_id,)).fetchone()
    if not recipe:
        err(f"Recipe {recipe_id} not found")
    recipe_data = row_to_dict(recipe)

    orig_portions = int(recipe_data.get("portions_per_batch", 1) or 1)
    target = int(target_portions)
    if orig_portions <= 0:
        err("Original portions_per_batch must be > 0")

    scale_factor = Decimal(str(target)) / Decimal(str(orig_portions))

    rows = conn.execute(
        "SELECT * FROM foodclaw_recipe_ingredient WHERE recipe_id = ? ORDER BY sort_order",
        (recipe_id,)
    ).fetchall()

    scaled = []
    total_cost = Decimal("0.00")
    for r in rows:
        d = row_to_dict(r)
        orig_qty = to_decimal(d.get("quantity", "0"))
        scaled_qty = (orig_qty * scale_factor).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
        uc = to_decimal(d.get("unit_cost", "0.00"))
        lc = (scaled_qty * uc).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
        total_cost += lc
        scaled.append({
            "ingredient_name": d["ingredient_name"],
            "original_quantity": str(orig_qty),
            "scaled_quantity": str(scaled_qty),
            "unit": d.get("unit", "unit"),
            "unit_cost": str(uc),
            "line_cost": str(lc),
        })

    ok({
        "recipe_id": recipe_id,
        "recipe_name": recipe_data.get("name"),
        "original_portions": orig_portions,
        "target_portions": target,
        "scale_factor": str(scale_factor.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)),
        "ingredients": scaled,
        "total_cost": str(total_cost),
    })


# ---------------------------------------------------------------------------
# ACTIONS registry
# ---------------------------------------------------------------------------
ACTIONS = {
    "food-add-recipe": add_recipe,
    "food-update-recipe": update_recipe,
    "food-get-recipe": get_recipe,
    "food-list-recipes": list_recipes,
    "food-add-recipe-ingredient": add_recipe_ingredient,
    "food-update-recipe-ingredient": update_recipe_ingredient,
    "food-list-recipe-ingredients": list_recipe_ingredients,
    "food-calculate-recipe-cost": calculate_recipe_cost,
    "food-cost-analysis": cost_analysis,
    "food-recipe-scaling": recipe_scaling,
}
