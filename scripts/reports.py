"""FoodClaw — reports domain module

Actions for the reports + status domain (7 actions).
Imported by db_query.py (unified router).
"""
import json
import os
import sys
from datetime import datetime, timezone
from decimal import Decimal, ROUND_HALF_UP

try:
    sys.path.insert(0, os.path.expanduser("~/.openclaw/erpclaw/lib"))
    from erpclaw_lib.db import get_connection, DEFAULT_DB_PATH
    from erpclaw_lib.decimal_utils import to_decimal
    from erpclaw_lib.response import ok, err, row_to_dict
except ImportError:
    DEFAULT_DB_PATH = "~/.openclaw/erpclaw/data.sqlite"
    pass

_now_iso = lambda: datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


# ---------------------------------------------------------------------------
# 1. food-cost-report
# ---------------------------------------------------------------------------
def food_cost_report(conn, args):
    """Food cost vs revenue by category.
    Uses recipe total_cost for cost and menu_item price for revenue proxy.
    """
    where, params = ["r.status = 'active'"], []
    if getattr(args, "company_id", None):
        where.append("r.company_id = ?")
        params.append(args.company_id)

    rows = conn.execute(f"""
        SELECT mi.category,
               COUNT(*) as item_count,
               SUM(CAST(r.cost_per_portion AS REAL)) as total_cost,
               SUM(CAST(mi.price AS REAL)) as total_revenue
        FROM foodclaw_recipe r
        JOIN foodclaw_menu_item mi ON r.menu_item_id = mi.id
        WHERE {' AND '.join(where)}
        GROUP BY mi.category
        ORDER BY mi.category
    """, params).fetchall()

    categories = []
    grand_cost = Decimal("0.00")
    grand_revenue = Decimal("0.00")
    for r in rows:
        cat_cost = to_decimal(str(r[2] or 0))
        cat_rev = to_decimal(str(r[3] or 0))
        pct = "0.00"
        if cat_rev > 0:
            pct = str((cat_cost / cat_rev * Decimal("100")).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP))
        grand_cost += cat_cost
        grand_revenue += cat_rev
        categories.append({
            "category": r[0],
            "item_count": r[1],
            "total_cost": str(cat_cost.quantize(Decimal("0.01"))),
            "total_revenue": str(cat_rev.quantize(Decimal("0.01"))),
            "food_cost_pct": pct,
        })

    overall_pct = "0.00"
    if grand_revenue > 0:
        overall_pct = str((grand_cost / grand_revenue * Decimal("100")).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP))

    ok({
        "categories": categories,
        "grand_total_cost": str(grand_cost.quantize(Decimal("0.01"))),
        "grand_total_revenue": str(grand_revenue.quantize(Decimal("0.01"))),
        "overall_food_cost_pct": overall_pct,
    })


# ---------------------------------------------------------------------------
# 2. labor-report
# ---------------------------------------------------------------------------
def labor_report(conn, args):
    """Labor cost by role for a date range. Sums hours_worked * hourly_rate."""
    where_s, params_s = ["s.shift_status = 'clocked_out'"], []
    if getattr(args, "company_id", None):
        where_s.append("s.company_id = ?")
        params_s.append(args.company_id)
    if getattr(args, "start_date", None):
        where_s.append("s.shift_date >= ?")
        params_s.append(args.start_date)
    if getattr(args, "end_date", None):
        where_s.append("s.shift_date <= ?")
        params_s.append(args.end_date)

    rows = conn.execute(f"""
        SELECT e.role,
               COUNT(DISTINCT e.id) as employee_count,
               SUM(CAST(s.hours_worked AS REAL)) as total_hours,
               SUM(CAST(s.hours_worked AS REAL) * CAST(e.hourly_rate AS REAL)) as total_cost
        FROM foodclaw_shift s
        JOIN foodclaw_employee e ON s.employee_id = e.id
        WHERE {' AND '.join(where_s)}
        GROUP BY e.role
        ORDER BY total_cost DESC
    """, params_s).fetchall()

    roles = []
    grand_hours = Decimal("0.00")
    grand_cost = Decimal("0.00")
    for r in rows:
        hrs = to_decimal(str(r[2] or 0))
        cost = to_decimal(str(r[3] or 0)).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
        grand_hours += hrs
        grand_cost += cost
        roles.append({
            "role": r[0],
            "employee_count": r[1],
            "total_hours": str(hrs.quantize(Decimal("0.01"))),
            "total_cost": str(cost),
        })

    ok({
        "roles": roles,
        "grand_total_hours": str(grand_hours.quantize(Decimal("0.01"))),
        "grand_total_cost": str(grand_cost.quantize(Decimal("0.01"))),
    })


# ---------------------------------------------------------------------------
# 3. waste-report
# ---------------------------------------------------------------------------
def waste_report(conn, args):
    """Waste by reason for a date range."""
    where, params = ["1=1"], []
    if getattr(args, "company_id", None):
        where.append("company_id = ?")
        params.append(args.company_id)
    if getattr(args, "start_date", None):
        where.append("waste_date >= ?")
        params.append(args.start_date)
    if getattr(args, "end_date", None):
        where.append("waste_date <= ?")
        params.append(args.end_date)

    rows = conn.execute(f"""
        SELECT reason,
               COUNT(*) as log_count,
               SUM(CAST(quantity AS REAL)) as total_qty,
               SUM(CAST(cost AS REAL)) as total_cost
        FROM foodclaw_waste_log
        WHERE {' AND '.join(where)}
        GROUP BY reason
        ORDER BY total_cost DESC
    """, params).fetchall()

    reasons = []
    grand_cost = Decimal("0.00")
    for r in rows:
        cost = to_decimal(str(r[3] or 0)).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
        grand_cost += cost
        reasons.append({
            "reason": r[0],
            "log_count": r[1],
            "total_quantity": str(to_decimal(str(r[2] or 0)).quantize(Decimal("0.01"))),
            "total_cost": str(cost),
        })

    ok({
        "reasons": reasons,
        "grand_total_cost": str(grand_cost.quantize(Decimal("0.01"))),
    })


# ---------------------------------------------------------------------------
# 4. menu-performance
# ---------------------------------------------------------------------------
def menu_performance(conn, args):
    """Menu item performance: price, cost, contribution margin."""
    where, params = ["1=1"], []
    if getattr(args, "company_id", None):
        where.append("mi.company_id = ?")
        params.append(args.company_id)
    if getattr(args, "category", None):
        where.append("mi.category = ?")
        params.append(args.category)

    rows = conn.execute(f"""
        SELECT mi.id, mi.name, mi.category, mi.price, mi.cost,
               r.total_cost as recipe_cost, r.cost_per_portion
        FROM foodclaw_menu_item mi
        LEFT JOIN foodclaw_recipe r ON r.menu_item_id = mi.id
        WHERE {' AND '.join(where)}
        ORDER BY mi.category, mi.name
    """, params).fetchall()

    items = []
    for r in rows:
        d = row_to_dict(r)
        price = to_decimal(d.get("price", "0.00"))
        cost = to_decimal(d.get("cost_per_portion") or d.get("cost", "0.00"))
        margin = price - cost
        margin_pct = "0.00"
        if price > 0:
            margin_pct = str((margin / price * Decimal("100")).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP))
        items.append({
            "menu_item_id": d.get("id"),
            "name": d.get("name"),
            "category": d.get("category"),
            "price": str(price),
            "cost": str(cost),
            "contribution_margin": str(margin.quantize(Decimal("0.01"))),
            "margin_pct": margin_pct,
        })

    ok({"items": items, "total_count": len(items)})


# ---------------------------------------------------------------------------
# 5. franchise-comparison
# ---------------------------------------------------------------------------
def franchise_comparison(conn, args):
    """Compare franchise units by royalty revenue."""
    where, params = ["1=1"], []
    if getattr(args, "company_id", None):
        where.append("fu.company_id = ?")
        params.append(args.company_id)

    rows = conn.execute(f"""
        SELECT fu.id, fu.unit_name, fu.unit_code, fu.status,
               COUNT(re.id) as entry_count,
               SUM(CAST(re.gross_revenue AS REAL)) as total_revenue,
               SUM(CAST(re.royalty_amount AS REAL)) as total_royalties,
               SUM(CAST(re.total_due AS REAL)) as total_due
        FROM foodclaw_franchise_unit fu
        LEFT JOIN foodclaw_royalty_entry re ON re.franchise_unit_id = fu.id
        WHERE {' AND '.join(where)}
        GROUP BY fu.id, fu.unit_name, fu.unit_code, fu.status
        ORDER BY total_revenue DESC
    """, params).fetchall()

    units = []
    for r in rows:
        units.append({
            "unit_id": r[0],
            "unit_name": r[1],
            "unit_code": r[2],
            "unit_status": r[3],
            "entry_count": r[4],
            "total_revenue": str(to_decimal(str(r[5] or 0)).quantize(Decimal("0.01"))),
            "total_royalties": str(to_decimal(str(r[6] or 0)).quantize(Decimal("0.01"))),
            "total_due": str(to_decimal(str(r[7] or 0)).quantize(Decimal("0.01"))),
        })

    ok({"units": units, "total_count": len(units)})


# ---------------------------------------------------------------------------
# 6. daily-sales-summary
# ---------------------------------------------------------------------------
def daily_sales_summary(conn, args):
    """Summary of menu items, catering events, and staff for a date."""
    summary_date = getattr(args, "summary_date", None)
    if not summary_date:
        err("--summary-date is required")

    where_co = []
    params_co = []
    if getattr(args, "company_id", None):
        where_co.append("company_id = ?")
        params_co.append(args.company_id)
    co_clause = (" AND " + " AND ".join(where_co)) if where_co else ""

    # Active menu items count
    menu_count = conn.execute(
        f"SELECT COUNT(*) FROM foodclaw_menu_item WHERE is_available = 1{co_clause}", params_co
    ).fetchone()[0]

    # Catering events on this date
    cat_count = conn.execute(
        f"SELECT COUNT(*) FROM foodclaw_catering_event WHERE event_date = ?{co_clause}",
        [summary_date] + params_co
    ).fetchone()[0]

    # Shifts on this date
    shift_count = conn.execute(
        f"SELECT COUNT(*) FROM foodclaw_shift WHERE shift_date = ?{co_clause}",
        [summary_date] + params_co
    ).fetchone()[0]

    # Waste on this date
    waste_total = conn.execute(
        f"SELECT COALESCE(SUM(CAST(cost AS REAL)), 0) FROM foodclaw_waste_log WHERE waste_date = ?{co_clause}",
        [summary_date] + params_co
    ).fetchone()[0]

    # Temp violations on this date
    violations = conn.execute(
        f"SELECT COUNT(*) FROM foodclaw_temp_reading WHERE reading_date = ? AND is_safe = 0{co_clause}",
        [summary_date] + params_co
    ).fetchone()[0]

    ok({
        "summary_date": summary_date,
        "active_menu_items": menu_count,
        "catering_events": cat_count,
        "scheduled_shifts": shift_count,
        "waste_cost": str(to_decimal(str(waste_total)).quantize(Decimal("0.01"))),
        "temp_violations": violations,
    })


# ---------------------------------------------------------------------------
# ACTIONS registry
# ---------------------------------------------------------------------------
ACTIONS = {
    "food-cost-report": food_cost_report,
    "food-labor-report": labor_report,
    "food-waste-report": waste_report,
    "food-menu-performance": menu_performance,
    "food-franchise-comparison": franchise_comparison,
    "food-daily-sales-summary": daily_sales_summary,
    # "status" is added in db_query.py
}
