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
SRC_DIR = os.path.dirname(MODULE_DIR)              # source/
ERPCLAW_DIR = os.path.join(SRC_DIR, "erpclaw", "scripts", "erpclaw-setup")
INIT_SCHEMA_PATH = os.path.join(ERPCLAW_DIR, "init_schema.py")

# Make erpclaw_lib importable
# M54: bind erpclaw_lib to the tree under test, never the deployed
# ~/.openclaw/erpclaw/lib symlink — the last install to run wins that symlink,
# so with several worktrees in flight it resolves to a tree nobody is testing
# (and DANGLES once that worktree is removed). The deployed install stays as
# the fallback for a published module repo, which ships no source/erpclaw/.
_IN_TREE_LIB = os.path.join(SRC_DIR, "erpclaw", "scripts", "erpclaw-setup", "lib")
ERPCLAW_LIB = (_IN_TREE_LIB if os.path.isdir(os.path.join(_IN_TREE_LIB, "erpclaw_lib"))
               else os.path.join(os.path.expanduser(
                   os.environ.get("ERPCLAW_HOME", "~/.openclaw/erpclaw")), "lib"))
if ERPCLAW_LIB not in sys.path:
    if importlib.util.find_spec("erpclaw_lib") is None:
        sys.path.insert(0, ERPCLAW_LIB)

from erpclaw_lib.db import setup_pragmas

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
    setup_pragmas(conn)
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
        "customer_id": None,
        "cash_account_id": None,
        "deposit_date": None,
        "db_path": None,
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


def delegate_selling_in_process(conn, monkeypatch, submit_behaviour=None,
                                create_behaviour=None, payment_behaviour=None,
                                allocate_behaviour=None, connect=None, *,
                                delete_behaviour=None, after_add=None):
    """Redirect cross_skill.call_skill_action to the REAL foundation functions.

    Copied from educlaw's ``test_fee_invoice_bills_through_selling.py`` (the
    ``add-customer`` branch is dropped: customers are seeded directly through
    selling ``add_customer``). Keeps every assertion real (item resolution,
    totals, GL postings) while recording exactly which action and flags the
    vertical sent through the shared library.

    ``submit_behaviour`` controls ``submit-sales-invoice``: None runs it;
    "fail" raises CrossSkillError without running it; "lost_reply" runs it
    and then raises CrossSkillError. ``create_behaviour`` controls
    ``create-sales-invoice``: "fail" raises CrossSkillError without running
    it; "reprice" sets the first line's rate to "1400.00" before calling
    selling (simulates a price rule). ``payment_behaviour`` controls ``submit-payment``: None runs it;
    "fail" raises CrossSkillError without running it; "submit_then_fail"
    runs it and then raises CrossSkillError("simulated lost reply").
    ``allocate_behaviour`` controls ``allocate-payment``: None runs it;
    "fail_once" raises CrossSkillError("simulated allocation failure") for the
    first ``allocate-payment`` only, without running it.
    ``delete_behaviour`` controls ``delete-payment``: None runs it;
    "fail" raises CrossSkillError without running it; "submit_then_fail"
    first submits the named payment through the real ``submit_payment`` on a
    fresh connection (once), then raises CrossSkillError without deleting.
    ``after_add`` is an optional callable ``after_add(db_path,
    payment_entry_id)`` run after a successful real ``add-payment`` returns
    and before the branch returns, so a test can write a competing payment
    through payments on its own fresh connection.
    ``connect`` builds fresh child connections on the call's ``db_path``
    (default the raw ``get_conn``); the payments branches never run on the
    test's ``conn``.
    """
    def _load_domain(domain):
        path = os.path.join(SRC_DIR, "erpclaw", "scripts", domain, "db_query.py")
        spec = importlib.util.spec_from_file_location(
            "_food_sell_%s" % domain.replace("-", "_"), path)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        return module

    selling = _load_domain("erpclaw-selling")
    inventory = _load_domain("erpclaw-inventory")
    payments = _load_domain("erpclaw-payments")
    from erpclaw_lib import cross_skill as _cs
    _cs._SERVICE_ITEM_CACHE.clear()
    captured = {"calls": []}

    def _run(fn, args_ns):
        buf = io.StringIO()

        def _fake_exit(code=0):
            raise SystemExit(code)

        try:
            with patch("sys.stdout", buf), patch("sys.exit", side_effect=_fake_exit):
                fn(conn, args_ns)
        except SystemExit:
            pass
        return json.loads(buf.getvalue().strip())

    connect_fn = connect if connect is not None else get_conn

    _PAY_DEFAULTS = {
        "payment_entry_id": None, "company_id": None, "company_name": None,
        "payment_type": None, "posting_date": None, "party_type": None,
        "party_id": None, "paid_from_account": None, "paid_to_account": None,
        "paid_amount": None, "payment_currency": "USD", "exchange_rate": "1",
        "reference_number": None, "reference_date": None, "allocations": None,
        "deductions": None, "dimensions": None, "dimension_key": None,
        "dimension_value": None, "voucher_type": None, "voucher_id": None,
        "allocated_amount": None, "ple_amount": None, "account_id": None,
        "against_voucher_type": None, "against_voucher_id": None,
        "write_off_amount": None, "write_off_account_id": None, "reason": None,
        "cost_center_id": None, "bank_account_id": None, "pe_status": None,
        "from_date": None, "to_date": None, "limit": "20", "offset": "0",
    }

    def _run_fresh(fn, args_ns, fresh):
        buf = io.StringIO()

        def _fake_exit(code=0):
            raise SystemExit(code)

        try:
            with patch("sys.stdout", buf), patch("sys.exit", side_effect=_fake_exit):
                fn(fresh, args_ns)
        except SystemExit:
            pass
        out = buf.getvalue().strip()
        if not out:
            return {"status": "error", "message": "no output captured"}
        return json.loads(out)

    def _in_process(skill_name, action, args=None, db_path=None, timeout=30):
        assert not conn.in_transaction, (
            "FoodClaw holds an uncommitted write across a cross-skill call")
        flags = dict(args or {})
        captured["calls"].append(
            {"skill": skill_name, "action": action, "args": flags})
        if action == "add-item":
            result = _run(inventory.add_item, argparse.Namespace(
                item_code=flags.get("--item-code"),
                item_name=flags.get("--item-name"),
                item_type=flags.get("--item-type"),
                valuation_method=None, item_group=None, stock_uom=None,
                has_batch=None, has_serial=None, standard_rate=None,
                custom_fields=None))
        elif action == "list-items":
            result = _run(inventory.list_items, argparse.Namespace(
                item_group=None, item_type=None, search=flags.get("--search"),
                limit="20", offset="0", warehouse_id=None, company_id=None))
        elif action == "create-sales-invoice":
            if create_behaviour == "fail":
                raise _cs.CrossSkillError("simulated create failure")
            items_json = flags.get("--items")
            if create_behaviour == "reprice":
                lines = json.loads(items_json)
                lines[0]["rate"] = "1400.00"
                items_json = json.dumps(lines)
            result = _run(selling.create_sales_invoice, argparse.Namespace(
                company_id=flags.get("--company-id"),
                customer_id=flags.get("--customer-id"),
                tax_template_id=None, sales_order_id=None,
                delivery_note_id=None,
                posting_date=flags.get("--posting-date"),
                due_date=flags.get("--due-date"),
                items=items_json, payment_terms_id=None))
        elif action == "submit-sales-invoice":
            if submit_behaviour == "fail":
                raise _cs.CrossSkillError("simulated submit failure")
            result = _run(selling.submit_sales_invoice, argparse.Namespace(
                sales_invoice_id=flags.get("--sales-invoice-id")))
            if submit_behaviour == "lost_reply":
                raise _cs.CrossSkillError("simulated lost reply")
        elif action == "add-payment":
            pay_ns = argparse.Namespace(**{**_PAY_DEFAULTS,
                "company_id": flags.get("--company-id"),
                "payment_type": flags.get("--payment-type"),
                "posting_date": flags.get("--posting-date"),
                "party_type": flags.get("--party-type"),
                "party_id": flags.get("--party-id"),
                "paid_from_account": flags.get("--paid-from-account"),
                "paid_to_account": flags.get("--paid-to-account"),
                "paid_amount": flags.get("--paid-amount"),
                "reference_number": flags.get("--reference-number"),
                "reference_date": flags.get("--reference-date"),
                "allocations": flags.get("--allocations"),
                "deductions": flags.get("--deductions"),
            })
            target = db_path if db_path is not None else os.environ.get("ERPCLAW_DB_PATH")
            fresh = connect_fn(target)
            try:
                try:
                    result = _run_fresh(payments.add_payment, pay_ns, fresh)
                except _cs.CrossSkillError:
                    raise
                except Exception as exc:
                    try:
                        fresh.rollback()
                    except Exception:
                        pass
                    raise _cs.CrossSkillError(str(exc) if str(exc) else "add-payment failed")
            except _cs.CrossSkillError:
                try:
                    fresh.close()
                except Exception:
                    pass
                raise
            if result.get("status") == "error":
                try:
                    fresh.rollback()
                except Exception:
                    pass
                try:
                    fresh.close()
                except Exception:
                    pass
                raise _cs.CrossSkillError(result.get("message", "add-payment failed"))
            try:
                fresh.close()
            except Exception:
                pass
            if after_add is not None:
                after_add(target, result.get("payment_entry_id"))
            return result
        elif action == "submit-payment":
            if payment_behaviour == "fail":
                raise _cs.CrossSkillError("simulated payment submit failure")
            pay_ns = argparse.Namespace(**{**_PAY_DEFAULTS,
                "payment_entry_id": flags.get("--payment-entry-id"),
            })
            target = db_path if db_path is not None else os.environ.get("ERPCLAW_DB_PATH")
            fresh = connect_fn(target)
            try:
                try:
                    result = _run_fresh(payments.submit_payment, pay_ns, fresh)
                except _cs.CrossSkillError:
                    raise
                except Exception as exc:
                    try:
                        fresh.rollback()
                    except Exception:
                        pass
                    raise _cs.CrossSkillError(str(exc) if str(exc) else "submit-payment failed")
            except _cs.CrossSkillError:
                try:
                    fresh.close()
                except Exception:
                    pass
                raise
            if result.get("status") == "error":
                try:
                    fresh.rollback()
                except Exception:
                    pass
                try:
                    fresh.close()
                except Exception:
                    pass
                raise _cs.CrossSkillError(result.get("message", "submit-payment failed"))
            try:
                fresh.close()
            except Exception:
                pass
            if payment_behaviour == "submit_then_fail":
                raise _cs.CrossSkillError("simulated lost reply")
            return result
        elif action == "delete-payment":
            if delete_behaviour == "fail":
                raise _cs.CrossSkillError("simulated delete failure")
            if delete_behaviour == "submit_then_fail" and not captured.get("delete_submitted"):
                captured["delete_submitted"] = True
                sub_ns = argparse.Namespace(**{**_PAY_DEFAULTS,
                    "payment_entry_id": flags.get("--payment-entry-id"),
                })
                sub_target = db_path if db_path is not None else os.environ.get("ERPCLAW_DB_PATH")
                sub_fresh = connect_fn(sub_target)
                try:
                    _run_fresh(payments.submit_payment, sub_ns, sub_fresh)
                finally:
                    try:
                        sub_fresh.close()
                    except Exception:
                        pass
                raise _cs.CrossSkillError("simulated delete failure")
            pay_ns = argparse.Namespace(**{**_PAY_DEFAULTS,
                "payment_entry_id": flags.get("--payment-entry-id"),
            })
            target = db_path if db_path is not None else os.environ.get("ERPCLAW_DB_PATH")
            fresh = connect_fn(target)
            try:
                try:
                    result = _run_fresh(payments.delete_payment, pay_ns, fresh)
                except _cs.CrossSkillError:
                    raise
                except Exception as exc:
                    try:
                        fresh.rollback()
                    except Exception:
                        pass
                    raise _cs.CrossSkillError(str(exc) if str(exc) else "delete-payment failed")
            except _cs.CrossSkillError:
                try:
                    fresh.close()
                except Exception:
                    pass
                raise
            if result.get("status") == "error":
                try:
                    fresh.rollback()
                except Exception:
                    pass
                try:
                    fresh.close()
                except Exception:
                    pass
                raise _cs.CrossSkillError(result.get("message", "delete-payment failed"))
            try:
                fresh.close()
            except Exception:
                pass
            return result
        elif action == "allocate-payment":
            if allocate_behaviour == "fail_once" and not captured.get("allocate_failed"):
                captured["allocate_failed"] = True
                raise _cs.CrossSkillError("simulated allocation failure")
            pay_ns = argparse.Namespace(**{**_PAY_DEFAULTS,
                "payment_entry_id": flags.get("--payment-entry-id"),
                "voucher_type": flags.get("--voucher-type"),
                "voucher_id": flags.get("--voucher-id"),
                "allocated_amount": flags.get("--allocated-amount"),
            })
            target = db_path if db_path is not None else os.environ.get("ERPCLAW_DB_PATH")
            fresh = connect_fn(target)
            try:
                try:
                    result = _run_fresh(payments.allocate_payment, pay_ns, fresh)
                except _cs.CrossSkillError:
                    raise
                except Exception as exc:
                    try:
                        fresh.rollback()
                    except Exception:
                        pass
                    raise _cs.CrossSkillError(str(exc) if str(exc) else "allocate-payment failed")
            except _cs.CrossSkillError:
                try:
                    fresh.close()
                except Exception:
                    pass
                raise
            if result.get("status") == "error":
                try:
                    fresh.rollback()
                except Exception:
                    pass
                try:
                    fresh.close()
                except Exception:
                    pass
                raise _cs.CrossSkillError(result.get("message", "allocate-payment failed"))
            try:
                fresh.close()
            except Exception:
                pass
            return result
        else:
            raise AssertionError("unexpected cross-skill action %s" % action)
        if result.get("status") == "error":
            conn.rollback()
            raise _cs.CrossSkillError(
                result.get("message", "%s failed" % action))
        return result

    monkeypatch.setattr(_cs, "call_skill_action", _in_process)
    return captured
