#!/usr/bin/env python3
"""FoodClaw — db_query.py (unified router)

AI-native restaurant & food service management.
Routes all actions across 8 domain modules: menu, recipes, inventory, staff, catering, food_safety, franchise, reports.

Usage: python3 db_query.py --action <action-name> [--flags ...]
Output: JSON to stdout, exit 0 on success, exit 1 on error.
"""
import argparse
import json
import os
import sys

# Add shared lib to path
try:
    sys.path.insert(0, os.path.expanduser("~/.openclaw/erpclaw/lib"))
    from erpclaw_lib.db import get_connection, ensure_db_exists, DEFAULT_DB_PATH
    from erpclaw_lib.validation import check_input_lengths
    from erpclaw_lib.response import ok, err
    from erpclaw_lib.dependencies import check_required_tables
    from erpclaw_lib.args import SafeArgumentParser, check_unknown_args
except ImportError:
    import json as _json
    print(_json.dumps({
        "status": "error",
        "error": "ERPClaw foundation not installed. Install erpclaw-setup first: clawhub install erpclaw-setup",
        "suggestion": "clawhub install erpclaw-setup"
    }))
    sys.exit(1)

# Add this script's directory so domain modules can be imported
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from menu import ACTIONS as MENU_ACTIONS
from recipes import ACTIONS as RECIPES_ACTIONS
from inventory import ACTIONS as INVENTORY_ACTIONS
from staff import ACTIONS as STAFF_ACTIONS
from catering import ACTIONS as CATERING_ACTIONS
from food_safety import ACTIONS as FOOD_SAFETY_ACTIONS
from franchise import ACTIONS as FRANCHISE_ACTIONS
from reports import ACTIONS as REPORTS_ACTIONS

# ---------------------------------------------------------------------------
# Merge all domain actions into one router
# ---------------------------------------------------------------------------
SKILL = "foodclaw"
REQUIRED_TABLES = ["company", "foodclaw_menu"]

ACTIONS = {}
ACTIONS.update(MENU_ACTIONS)
ACTIONS.update(RECIPES_ACTIONS)
ACTIONS.update(INVENTORY_ACTIONS)
ACTIONS.update(STAFF_ACTIONS)
ACTIONS.update(CATERING_ACTIONS)
ACTIONS.update(FOOD_SAFETY_ACTIONS)
ACTIONS.update(FRANCHISE_ACTIONS)
ACTIONS.update(REPORTS_ACTIONS)
ACTIONS["status"] = lambda conn, args: ok({
    "skill": SKILL,
    "version": "1.1.0",
    "actions_available": len([k for k in ACTIONS if k != "status"]),
    "domains": ["menu", "recipes", "inventory", "staff", "catering", "food_safety", "franchise", "reports"],
    "database": DEFAULT_DB_PATH,
})


def main():
    parser = SafeArgumentParser(description="foodclaw")
    parser.add_argument("--action", required=True, choices=sorted(ACTIONS.keys()))
    parser.add_argument("--db-path", default=None)

    # -- Shared IDs --
    parser.add_argument("--company-id")

    # -- Shared --
    parser.add_argument("--search")
    parser.add_argument("--limit", type=int, default=50)
    parser.add_argument("--offset", type=int, default=0)
    parser.add_argument("--notes")
    parser.add_argument("--status")
    parser.add_argument("--description")
    parser.add_argument("--name")

    # ── MENU domain ───────────────────────────────────────────────
    parser.add_argument("--menu-id")
    parser.add_argument("--menu-type")
    parser.add_argument("--effective-date")
    parser.add_argument("--end-date")
    parser.add_argument("--is-active")
    parser.add_argument("--menu-item-id")
    parser.add_argument("--category")
    parser.add_argument("--price")
    parser.add_argument("--cost")
    parser.add_argument("--allergens")
    parser.add_argument("--nutrition-info")
    parser.add_argument("--is-vegetarian")
    parser.add_argument("--is-vegan")
    parser.add_argument("--is-gluten-free")
    parser.add_argument("--prep-time-min")
    parser.add_argument("--calories")
    parser.add_argument("--sort-order")
    parser.add_argument("--is-available")
    parser.add_argument("--modifier-group-id")
    parser.add_argument("--min-selections")
    parser.add_argument("--max-selections")
    parser.add_argument("--is-required")
    parser.add_argument("--price-adjustment")
    parser.add_argument("--is-default")

    # ── RECIPES domain ────────────────────────────────────────────
    parser.add_argument("--recipe-id")
    parser.add_argument("--product-name")
    parser.add_argument("--batch-size")
    parser.add_argument("--batch-unit")
    parser.add_argument("--expected-yield-pct")
    parser.add_argument("--portions-per-batch")
    parser.add_argument("--cook-time-min")
    parser.add_argument("--instructions")
    parser.add_argument("--recipe-ingredient-id")
    parser.add_argument("--ingredient-id")
    parser.add_argument("--ingredient-name")
    parser.add_argument("--quantity")
    parser.add_argument("--unit")
    parser.add_argument("--unit-cost")
    parser.add_argument("--target-portions")

    # ── INVENTORY domain ──────────────────────────────────────────
    parser.add_argument("--ingredient-category")
    parser.add_argument("--ingredient-status")
    parser.add_argument("--par-level")
    parser.add_argument("--current-stock")
    parser.add_argument("--supplier")
    parser.add_argument("--supplier-id")
    parser.add_argument("--is-perishable")
    parser.add_argument("--expiry-date")
    parser.add_argument("--reorder-point")
    parser.add_argument("--storage-location")
    parser.add_argument("--count-date")
    parser.add_argument("--counted-qty")
    parser.add_argument("--counted-by")
    parser.add_argument("--item-name")
    parser.add_argument("--waste-date")
    parser.add_argument("--waste-reason")
    parser.add_argument("--waste-cost")
    parser.add_argument("--logged-by")
    parser.add_argument("--order-date")
    parser.add_argument("--expected-date")
    parser.add_argument("--total-amount")
    parser.add_argument("--order-status")
    parser.add_argument("--items-json")

    # ── STAFF domain ──────────────────────────────────────────────
    # foodclaw_employee is an extension table — name/email/phone/hire_date
    # come from the core employee table via JOIN
    parser.add_argument("--foodclaw-employee-id")
    parser.add_argument("--employee-id")
    parser.add_argument("--role")
    parser.add_argument("--hourly-rate")
    parser.add_argument("--emp-status")
    parser.add_argument("--certifications")
    parser.add_argument("--shift-id")
    parser.add_argument("--shift-date")
    parser.add_argument("--start-time")
    parser.add_argument("--end-time")
    parser.add_argument("--role-assigned")
    parser.add_argument("--shift-status")
    parser.add_argument("--break-minutes")
    parser.add_argument("--tip-date")
    parser.add_argument("--cash-tips")
    parser.add_argument("--credit-tips")
    parser.add_argument("--tip-pool-share")

    # ── CATERING domain ──────────────────────────────────────────
    parser.add_argument("--event-id")
    parser.add_argument("--event-name")
    parser.add_argument("--client-name")
    parser.add_argument("--client-phone")
    parser.add_argument("--client-email")
    parser.add_argument("--event-date")
    parser.add_argument("--event-time")
    parser.add_argument("--venue")
    parser.add_argument("--guest-count")
    parser.add_argument("--event-status")
    parser.add_argument("--estimated-cost")
    parser.add_argument("--quoted-price")
    parser.add_argument("--deposit-amount")
    parser.add_argument("--final-amount")
    parser.add_argument("--unit-price")
    parser.add_argument("--requirement")
    # GL account configuration (catering + franchise)
    parser.add_argument("--revenue-account-id")
    parser.add_argument("--receivable-account-id")
    parser.add_argument("--cost-center-id")

    # ── FOOD SAFETY domain ───────────────────────────────────────
    parser.add_argument("--ccp-name")
    parser.add_argument("--log-date")
    parser.add_argument("--log-time")
    parser.add_argument("--monitored-by")
    parser.add_argument("--parameter")
    parser.add_argument("--measured-value")
    parser.add_argument("--acceptable-range")
    parser.add_argument("--is-within-range")
    parser.add_argument("--corrective-action")
    parser.add_argument("--equipment-name")
    parser.add_argument("--location")
    parser.add_argument("--reading-date")
    parser.add_argument("--reading-time")
    parser.add_argument("--temperature")
    parser.add_argument("--temp-unit")
    parser.add_argument("--safe-min")
    parser.add_argument("--safe-max")
    parser.add_argument("--recorded-by")
    parser.add_argument("--inspection-id")
    parser.add_argument("--inspection-type")
    parser.add_argument("--inspector-name")
    parser.add_argument("--inspection-date")
    parser.add_argument("--score")
    parser.add_argument("--max-score")
    parser.add_argument("--grade")
    parser.add_argument("--findings")
    parser.add_argument("--corrective-actions")
    parser.add_argument("--follow-up-date")
    parser.add_argument("--inspection-status")

    # ── FRANCHISE domain ────────────────────────────────────────
    parser.add_argument("--franchise-unit-id")
    parser.add_argument("--unit-code")
    parser.add_argument("--address")
    parser.add_argument("--city")
    parser.add_argument("--state")
    parser.add_argument("--zip-code")
    parser.add_argument("--manager-name")
    parser.add_argument("--phone")
    parser.add_argument("--open-date")
    parser.add_argument("--royalty-id")
    parser.add_argument("--period-start")
    parser.add_argument("--period-end")
    parser.add_argument("--gross-revenue")
    parser.add_argument("--royalty-rate")
    parser.add_argument("--royalty-amount")
    parser.add_argument("--marketing-fee")
    parser.add_argument("--payment-status")
    parser.add_argument("--royalty-income-account-id")
    parser.add_argument("--royalty-receivable-account-id")
    parser.add_argument("--marketing-expense-account-id")

    # ── REPORTS domain ───────────────────────────────────────────
    parser.add_argument("--start-date")
    parser.add_argument("--summary-date")

    args, unknown = parser.parse_known_args()
    check_unknown_args(parser, unknown)
    check_input_lengths(args)

    db_path = args.db_path or DEFAULT_DB_PATH
    ensure_db_exists(db_path)
    conn = get_connection(db_path)

    _dep = check_required_tables(conn, REQUIRED_TABLES)
    if _dep:
        _dep["suggestion"] = "clawhub install erpclaw-setup && clawhub install foodclaw"
        print(json.dumps(_dep, indent=2))
        conn.close()
        sys.exit(1)

    try:
        ACTIONS[args.action](conn, args)
    except Exception as e:
        conn.rollback()
        sys.stderr.write(f"[{SKILL}] {e}\n")
        err(str(e))
    finally:
        conn.close()


if __name__ == "__main__":
    main()
