"""Shared helper functions for FoodClaw L1 unit tests.

Provides:
  - DB bootstrap via init_schema.init_db() + init_foodclaw_schema()
  - load_db_query() for explicit module loading (avoids sys.path collisions)
  - call_action() / ns() / is_error() / is_ok()
  - Seed functions for company, employee, supplier, naming_series
  - build_env() for a complete food service test environment
"""
import argparse
import importlib.util
import io
import json
import os
import sqlite3
import sys
import uuid
from datetime import datetime, timezone
from decimal import Decimal
from unittest.mock import patch

# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------

TESTS_DIR = os.path.dirname(os.path.abspath(__file__))
SCRIPTS_DIR = os.path.dirname(TESTS_DIR)          # foodclaw/scripts/
MODULE_DIR = os.path.dirname(SCRIPTS_DIR)          # foodclaw/
INIT_DB_PATH = os.path.join(MODULE_DIR, "init_db.py")

# Foundation init_schema.py (erpclaw-setup)
SRC_DIR = os.path.dirname(MODULE_DIR)              # src/
ERPCLAW_DIR = os.path.join(SRC_DIR, "erpclaw", "scripts", "erpclaw-setup")
INIT_SCHEMA_PATH = os.path.join(ERPCLAW_DIR, "init_schema.py")

# Make erpclaw_lib importable
ERPCLAW_LIB = os.path.expanduser("~/.openclaw/erpclaw/lib")
if ERPCLAW_LIB not in sys.path:
    sys.path.insert(0, ERPCLAW_LIB)

# Make scripts dir importable so domain modules (menu, recipes, ...) resolve
if SCRIPTS_DIR not in sys.path:
    sys.path.insert(0, SCRIPTS_DIR)


def load_db_query():
    """Load foodclaw db_query.py explicitly to avoid sys.path collisions."""
    db_query_path = os.path.join(SCRIPTS_DIR, "db_query.py")
    spec = importlib.util.spec_from_file_location("db_query_food", db_query_path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


# ---------------------------------------------------------------------------
# DB helpers
# ---------------------------------------------------------------------------

def init_all_tables(db_path: str):
    """Create foundation tables + foodclaw extension tables.

    1. Runs erpclaw-setup init_schema.init_db()  (core tables)
    2. Runs foodclaw init_db.init_foodclaw_schema()
    """
    # Step 1: Foundation schema
    spec = importlib.util.spec_from_file_location("init_schema", INIT_SCHEMA_PATH)
    schema_mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(schema_mod)
    schema_mod.init_db(db_path)

    # Step 2: FoodClaw extension tables
    spec2 = importlib.util.spec_from_file_location("food_init_db", INIT_DB_PATH)
    food_mod = importlib.util.module_from_spec(spec2)
    spec2.loader.exec_module(food_mod)
    food_mod.init_foodclaw_schema(db_path)


class _ConnWrapper:
    """Thin wrapper so conn.company_id works (some actions set it)."""
    def __init__(self, real_conn):
        self._conn = real_conn
        self.company_id = None

    def __getattr__(self, name):
        return getattr(self._conn, name)

    def execute(self, *a, **kw):
        return self._conn.execute(*a, **kw)

    def executemany(self, *a, **kw):
        return self._conn.executemany(*a, **kw)

    def executescript(self, *a, **kw):
        return self._conn.executescript(*a, **kw)

    def commit(self):
        return self._conn.commit()

    def rollback(self):
        return self._conn.rollback()

    def close(self):
        return self._conn.close()

    @property
    def row_factory(self):
        return self._conn.row_factory

    @row_factory.setter
    def row_factory(self, value):
        self._conn.row_factory = value


class _DecimalSum:
    """Custom SQLite aggregate: SUM using Python Decimal for precision."""
    def __init__(self):
        self.total = Decimal("0")

    def step(self, value):
        if value is not None:
            self.total += Decimal(str(value))

    def finalize(self):
        return str(self.total)


def get_conn(db_path: str):
    """Return a wrapped sqlite3.Connection with FK enabled and Row factory."""
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    conn.execute("PRAGMA busy_timeout = 5000")
    conn.create_aggregate("decimal_sum", 1, _DecimalSum)
    return _ConnWrapper(conn)


# ---------------------------------------------------------------------------
# Action invocation helpers
# ---------------------------------------------------------------------------

def call_action(fn, conn, args) -> dict:
    """Invoke a domain function, capture stdout JSON, return parsed dict."""
    buf = io.StringIO()

    def _fake_exit(code=0):
        raise SystemExit(code)

    try:
        with patch("sys.stdout", buf), patch("sys.exit", side_effect=_fake_exit):
            fn(conn, args)
    except SystemExit:
        pass

    output = buf.getvalue().strip()
    if not output:
        return {"status": "error", "message": "no output captured"}
    return json.loads(output)


def ns(**kwargs) -> argparse.Namespace:
    """Build an argparse.Namespace from keyword args (mimics CLI flags)."""
    defaults = {
        "limit": 50,
        "offset": 0,
        "company_id": None,
        "search": None,
        "notes": None,
        "status": None,
        "description": None,
        "name": None,
        # Menu domain
        "menu_id": None,
        "menu_type": None,
        "effective_date": None,
        "end_date": None,
        "is_active": None,
        "menu_item_id": None,
        "category": None,
        "price": None,
        "cost": None,
        "allergens": None,
        "nutrition_info": None,
        "is_vegetarian": None,
        "is_vegan": None,
        "is_gluten_free": None,
        "prep_time_min": None,
        "calories": None,
        "sort_order": None,
        "is_available": None,
        "modifier_group_id": None,
        "min_selections": None,
        "max_selections": None,
        "is_required": None,
        "price_adjustment": None,
        "is_default": None,
        # Recipe domain
        "recipe_id": None,
        "product_name": None,
        "batch_size": None,
        "batch_unit": None,
        "expected_yield_pct": None,
        "portions_per_batch": None,
        "cook_time_min": None,
        "instructions": None,
        "recipe_ingredient_id": None,
        "ingredient_id": None,
        "ingredient_name": None,
        "quantity": None,
        "unit": None,
        "unit_cost": None,
        "target_portions": None,
        # Inventory domain
        "ingredient_category": None,
        "ingredient_status": None,
        "par_level": None,
        "current_stock": None,
        "supplier": None,
        "supplier_id": None,
        "is_perishable": None,
        "expiry_date": None,
        "reorder_point": None,
        "storage_location": None,
        "count_date": None,
        "counted_qty": None,
        "counted_by": None,
        "item_name": None,
        "waste_date": None,
        "waste_reason": None,
        "waste_cost": None,
        "logged_by": None,
        "order_date": None,
        "expected_date": None,
        "total_amount": None,
        "order_status": None,
        "items_json": None,
        # Staff domain
        "foodclaw_employee_id": None,
        "employee_id": None,
        "role": None,
        "hourly_rate": None,
        "emp_status": None,
        "certifications": None,
        "shift_id": None,
        "shift_date": None,
        "start_time": None,
        "end_time": None,
        "role_assigned": None,
        "shift_status": None,
        "break_minutes": None,
        "tip_date": None,
        "cash_tips": None,
        "credit_tips": None,
        "tip_pool_share": None,
        # Catering domain
        "event_id": None,
        "event_name": None,
        "client_name": None,
        "client_phone": None,
        "client_email": None,
        "event_date": None,
        "event_time": None,
        "venue": None,
        "guest_count": None,
        "event_status": None,
        "estimated_cost": None,
        "quoted_price": None,
        "deposit_amount": None,
        "final_amount": None,
        "unit_price": None,
        "requirement": None,
        "revenue_account_id": None,
        "receivable_account_id": None,
        "cost_center_id": None,
        # Food safety domain
        "ccp_name": None,
        "log_date": None,
        "log_time": None,
        "monitored_by": None,
        "parameter": None,
        "measured_value": None,
        "acceptable_range": None,
        "is_within_range": None,
        "corrective_action": None,
        "equipment_name": None,
        "location": None,
        "reading_date": None,
        "reading_time": None,
        "temperature": None,
        "temp_unit": None,
        "safe_min": None,
        "safe_max": None,
        "recorded_by": None,
        "inspection_id": None,
        "inspection_type": None,
        "inspector_name": None,
        "inspection_date": None,
        "score": None,
        "max_score": None,
        "grade": None,
        "findings": None,
        "corrective_actions": None,
        "follow_up_date": None,
        "inspection_status": None,
        # Franchise domain
        "franchise_unit_id": None,
        "unit_code": None,
        "address": None,
        "city": None,
        "state": None,
        "zip_code": None,
        "manager_name": None,
        "phone": None,
        "open_date": None,
        "royalty_id": None,
        "period_start": None,
        "period_end": None,
        "gross_revenue": None,
        "royalty_rate": None,
        "royalty_amount": None,
        "marketing_fee": None,
        "payment_status": None,
        "royalty_income_account_id": None,
        "royalty_receivable_account_id": None,
        "marketing_expense_account_id": None,
        # Reports domain
        "start_date": None,
        "summary_date": None,
    }
    defaults.update(kwargs)
    return argparse.Namespace(**defaults)


def is_error(result: dict) -> bool:
    return result.get("status") == "error"


def is_ok(result: dict) -> bool:
    return result.get("status") == "ok"


# ---------------------------------------------------------------------------
# Utility
# ---------------------------------------------------------------------------

def _uuid() -> str:
    return str(uuid.uuid4())


def _now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


# ---------------------------------------------------------------------------
# Seed helpers
# ---------------------------------------------------------------------------

def seed_company(conn, name="Food Service Co", abbr="FS") -> str:
    """Insert a test company and return its ID."""
    cid = _uuid()
    conn.execute(
        """INSERT INTO company (id, name, abbr, default_currency, country,
           fiscal_year_start_month)
           VALUES (?, ?, ?, 'USD', 'United States', 1)""",
        (cid, f"{name} {cid[:6]}", f"{abbr}{cid[:4]}")
    )
    conn.commit()
    return cid


def seed_naming_series(conn, company_id: str):
    """Seed naming series for foodclaw entity types."""
    series = [
        ("foodclaw_menu", "MENU-", 0),
        ("foodclaw_menu_item", "MI-", 0),
        ("foodclaw_recipe", "RCP-", 0),
        ("foodclaw_ingredient", "ING-", 0),
        ("foodclaw_purchase_order", "FPO-", 0),
        ("foodclaw_employee", "FEMP-", 0),
        ("foodclaw_catering_event", "CATER-", 0),
        ("foodclaw_inspection", "INSP-", 0),
        ("foodclaw_franchise_unit", "FUNIT-", 0),
        ("foodclaw_royalty_entry", "ROYAL-", 0),
    ]
    for entity_type, prefix, current in series:
        conn.execute(
            """INSERT OR IGNORE INTO naming_series
               (id, entity_type, prefix, current_value, company_id)
               VALUES (?, ?, ?, ?, ?)""",
            (_uuid(), entity_type, prefix, current, company_id)
        )
    conn.commit()


def seed_employee(conn, company_id: str, first_name="Jane",
                  last_name="Cook") -> str:
    """Insert a core employee and return its ID."""
    eid = _uuid()
    now = _now()
    conn.execute(
        """INSERT INTO employee (id, first_name, last_name, full_name,
           company_id, status, date_of_joining, created_at, updated_at)
           VALUES (?, ?, ?, ?, ?, 'active', '2026-01-15', ?, ?)""",
        (eid, first_name, last_name, f"{first_name} {last_name}",
         company_id, now, now)
    )
    conn.commit()
    return eid


def seed_supplier(conn, company_id: str, name="Fresh Foods Inc") -> str:
    """Insert a core supplier and return its ID."""
    sid = _uuid()
    conn.execute(
        """INSERT INTO supplier (id, name, company_id)
           VALUES (?, ?, ?)""",
        (sid, name, company_id)
    )
    conn.commit()
    return sid


def seed_account(conn, company_id: str, name="Test Account",
                 root_type="asset", account_type=None,
                 account_number=None) -> str:
    """Insert a GL account and return its ID."""
    aid = _uuid()
    direction = "debit_normal" if root_type in ("asset", "expense") else "credit_normal"
    conn.execute(
        """INSERT INTO account (id, name, account_number, root_type, account_type,
           balance_direction, company_id, depth)
           VALUES (?, ?, ?, ?, ?, ?, ?, 0)""",
        (aid, name, account_number or f"ACC-{aid[:6]}", root_type,
         account_type, direction, company_id)
    )
    conn.commit()
    return aid


def seed_fiscal_year(conn, company_id: str,
                     start="2026-01-01", end="2026-12-31") -> str:
    """Insert a fiscal year and return its ID."""
    fid = _uuid()
    conn.execute(
        """INSERT INTO fiscal_year (id, name, start_date, end_date, company_id)
           VALUES (?, ?, ?, ?, ?)""",
        (fid, f"FY-{fid[:6]}", start, end, company_id)
    )
    conn.commit()
    return fid


def seed_cost_center(conn, company_id: str, name="Main CC") -> str:
    """Insert a cost center and return its ID."""
    ccid = _uuid()
    conn.execute(
        """INSERT INTO cost_center (id, name, company_id, is_group)
           VALUES (?, ?, ?, 0)""",
        (ccid, name, company_id)
    )
    conn.commit()
    return ccid


def build_env(conn) -> dict:
    """Create a complete food service test environment.

    Returns dict with all IDs needed for tests.
    """
    cid = seed_company(conn)
    seed_naming_series(conn, cid)
    fyid = seed_fiscal_year(conn, cid)
    ccid = seed_cost_center(conn, cid)

    # GL accounts
    ar = seed_account(conn, cid, "Accounts Receivable", "asset", "receivable", "1100")
    revenue = seed_account(conn, cid, "Food Revenue", "income", "revenue", "4000")

    # Core employee (for staff domain)
    emp1 = seed_employee(conn, cid, "Jane", "Cook")
    emp2 = seed_employee(conn, cid, "Bob", "Server")

    # Core supplier (for purchase orders)
    supplier = seed_supplier(conn, cid, "Fresh Foods Inc")

    return {
        "company_id": cid,
        "fiscal_year_id": fyid,
        "cost_center_id": ccid,
        "ar_account_id": ar,
        "revenue_account_id": revenue,
        "employee_id_1": emp1,
        "employee_id_2": emp2,
        "supplier_id": supplier,
    }
