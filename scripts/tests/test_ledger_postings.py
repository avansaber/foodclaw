"""FoodClaw ledger postings: registered voucher types, named customer, refuse-on-failure.

Catering completion and royalty entries either write the document and its
balanced voucher in one transaction, or write nothing and report why.
"""
import importlib.util
import os
import sys
from decimal import Decimal

_TESTS_DIR = os.path.dirname(os.path.abspath(__file__))
if _TESTS_DIR not in sys.path:
    sys.path.insert(0, _TESTS_DIR)

from food_helpers import (  # noqa: E402
    call_action, ns, is_ok, is_error, load_db_query,
    seed_account, seed_company, seed_cost_center,
    delegate_selling_in_process,
)

from erpclaw_lib.query import Q, Table, Field, P  # noqa: E402

_mod = load_db_query()
ACTIONS = _mod.ACTIONS

SCRIPTS_DIR = os.path.dirname(_TESTS_DIR)
SRC_DIR = os.path.dirname(os.path.dirname(SCRIPTS_DIR))
SELLING_QUERY = os.path.join(SRC_DIR, "erpclaw", "scripts", "erpclaw-selling", "db_query.py")
SETUP_QUERY = os.path.join(SRC_DIR, "erpclaw", "scripts", "erpclaw-setup", "db_query.py")


def _load(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


SELLING = _load("db_query_selling_for_foodclaw_ledger_tests", SELLING_QUERY)
SETUP = _load("db_query_setup_for_foodclaw_ledger_tests", SETUP_QUERY)
CATERING_MOD = _load("catering_for_foodclaw_ledger_tests", os.path.join(SCRIPTS_DIR, "catering.py"))
FRANCHISE_MOD = _load("franchise_for_foodclaw_ledger_tests", os.path.join(SCRIPTS_DIR, "franchise.py"))

EVENT_DATE = "2026-11-01"
QUOTED = "1500.00"
PERIOD_START = "2026-01-01"
PERIOD_END = "2026-01-31"


class _AnyArgs:
    """Args object whose unset attributes read None (for cross-module actions)."""

    def __init__(self, **kw):
        self.__dict__.update(kw)

    def __getattr__(self, name):
        return None


def _add_customer(conn, company_id, name="Diner Corp"):
    result = call_action(
        SELLING.add_customer, conn,
        _AnyArgs(name=name, company_id=company_id),
    )
    assert is_ok(result), result
    return result["customer_id"]


def _make_event(conn, env):
    result = call_action(
        ACTIONS["food-add-catering-event"], conn,
        ns(company_id=env["company_id"], event_name="Gala Dinner",
           client_name="Acme Inc", event_date=EVENT_DATE,
           quoted_price=QUOTED),
    )
    assert is_ok(result), result
    return result["id"]


def _confirm(conn, event_id):
    result = call_action(
        ACTIONS["food-confirm-event"], conn, ns(event_id=event_id))
    assert is_ok(result), result


def _event_row(conn, event_id):
    t = Table("foodclaw_catering_event")
    q = (Q.from_(t).select(t.id, t.event_status, t.final_amount, t.gl_entry_ids)
         .where(t.id == P()))
    row = conn.execute(q.get_sql(), (event_id,)).fetchone()
    return dict(row) if row else None


def _gl_for_voucher(conn, voucher_id):
    t = Table("gl_entry")
    q = (Q.from_(t).select(t.id, t.voucher_type, t.voucher_id, t.posting_date,
                           t.account_id, t.debit, t.credit, t.party_type,
                           t.party_id, t.cost_center_id)
         .where(t.voucher_id == P()))
    return [dict(r) for r in conn.execute(q.get_sql(), (voucher_id,)).fetchall()]


def _make_unit(conn, company_id, name="Royal Unit"):
    result = call_action(
        ACTIONS["food-add-franchise-unit"], conn,
        ns(company_id=company_id, name=name),
    )
    assert is_ok(result), result
    return result["id"]


def _royalty_rows(conn, unit_id):
    t = Table("foodclaw_royalty_entry")
    q = (Q.from_(t).select(t.star).where(t.franchise_unit_id == P()))
    return [dict(r) for r in conn.execute(q.get_sql(), (unit_id,)).fetchall()]


def _series_value(conn, company_id):
    t = Table("naming_series")
    q = (Q.from_(t).select(t.current_value)
         .where(t.entity_type == P()).where(t.company_id == P()))
    row = conn.execute(
        q.get_sql(), ("foodclaw_royalty_entry", company_id)).fetchone()
    return row[0] if row else None


def _deactivate(conn, voucher_type):
    result = call_action(
        SETUP.deactivate_voucher_type, conn,
        _AnyArgs(voucher_type=voucher_type, target_table="gl_entry"),
    )
    assert is_ok(result), result


class TestCateringPosting:
    def test_catering_refuses_without_customer(self, conn, env, db_path,
                                               monkeypatch):
        delegate_selling_in_process(conn, monkeypatch)
        event_id = _make_event(conn, env)
        _confirm(conn, event_id)
        result = call_action(
            ACTIONS["food-complete-catering-event"], conn,
            ns(event_id=event_id,
               revenue_account_id=env["revenue_account_id"],
               receivable_account_id=env["ar_account_id"],
               cost_center_id=env["cost_center_id"],
               db_path=db_path),
        )
        assert is_error(result)
        assert result["message"] == (
            "--customer-id is required to complete a catering event: the sales "
            "invoice must name the customer who owes it")
        event = _event_row(conn, event_id)
        assert event["event_status"] == "confirmed"
        assert event["gl_entry_ids"] is None
        assert _gl_for_voucher(conn, event_id) == []

    def test_catering_refuses_customer_of_another_company(self, conn, env, db_path,
                                                          monkeypatch):
        delegate_selling_in_process(conn, monkeypatch)
        other_company = seed_company(conn)
        foreign_customer = _add_customer(conn, other_company)
        event_id = _make_event(conn, env)
        _confirm(conn, event_id)
        result = call_action(
            ACTIONS["food-complete-catering-event"], conn,
            ns(event_id=event_id,
               revenue_account_id=env["revenue_account_id"],
               receivable_account_id=env["ar_account_id"],
               cost_center_id=env["cost_center_id"],
               customer_id=foreign_customer,
               db_path=db_path),
        )
        assert is_error(result)
        assert result["message"] == (
            f"Customer {foreign_customer} not found in company {env['company_id']}")
        event = _event_row(conn, event_id)
        assert event["event_status"] == "confirmed"
        assert event["gl_entry_ids"] is None
        assert _gl_for_voucher(conn, event_id) == []

class TestRoyaltyPosting:
    def _income_accounts(self, conn, company_id):
        income = seed_account(conn, company_id, "Royalty Income", "income",
                              "revenue", "4100")
        marketing = seed_account(conn, company_id, "Marketing Fee Income",
                                 "income", "revenue", "4110")
        return income, marketing

    def _add_entry(self, conn, env, unit_id, customer_id, income, marketing,
                   with_marketing=True, with_cost_center=True):
        kwargs = dict(company_id=env["company_id"], franchise_unit_id=unit_id,
                      period_start=PERIOD_START, period_end=PERIOD_END,
                      gross_revenue="100000.00", royalty_rate="5",
                      marketing_fee="1000.00",
                      royalty_income_account_id=income,
                      royalty_receivable_account_id=env["ar_account_id"],
                      customer_id=customer_id)
        if with_marketing:
            kwargs["marketing_expense_account_id"] = marketing
        if with_cost_center:
            kwargs["cost_center_id"] = env["cost_center_id"]
        return call_action(ACTIONS["food-add-royalty-entry"], conn, ns(**kwargs))

    def test_royalty_posts_three_balanced_legs(self, conn, env):
        customer_id = _add_customer(conn, env["company_id"])
        unit_id = _make_unit(conn, env["company_id"])
        income, marketing = self._income_accounts(conn, env["company_id"])
        result = self._add_entry(conn, env, unit_id, customer_id, income, marketing)
        assert is_ok(result), result
        assert result["gl_posted"] is True
        rows = _gl_for_voucher(conn, result["id"])
        assert len(rows) == 3
        for row in rows:
            assert row["voucher_type"] == "food_franchise_royalty"
            assert row["posting_date"] == PERIOD_END
        by_account = {r["account_id"]: r for r in rows}
        receivable = by_account[env["ar_account_id"]]
        assert receivable["debit"] == "6000.00"
        assert (receivable["party_type"], receivable["party_id"]) == ("customer", customer_id)
        royalty_leg = by_account[income]
        assert royalty_leg["credit"] == "5000.00"
        assert royalty_leg["cost_center_id"] == env["cost_center_id"]
        marketing_leg = by_account[marketing]
        assert marketing_leg["credit"] == "1000.00"
        assert marketing_leg["cost_center_id"] == env["cost_center_id"]
        assert (sum(Decimal(r["debit"]) for r in rows)
                == sum(Decimal(r["credit"]) for r in rows) == Decimal("6000.00"))
        stored = _royalty_rows(conn, unit_id)
        assert len(stored) == 1
        assert stored[0]["gl_entry_ids"] == result["gl_entry_ids"]

    def test_royalty_without_marketing_account_single_credit(self, conn, env):
        customer_id = _add_customer(conn, env["company_id"])
        unit_id = _make_unit(conn, env["company_id"])
        income, marketing = self._income_accounts(conn, env["company_id"])
        result = self._add_entry(conn, env, unit_id, customer_id, income,
                                 marketing, with_marketing=False)
        assert is_ok(result), result
        rows = _gl_for_voucher(conn, result["id"])
        assert len(rows) == 2
        assert sorted(r["debit"] for r in rows) == ["0.00", "6000.00"]
        assert sorted(r["credit"] for r in rows) == ["0.00", "6000.00"]

    def test_royalty_refuses_without_customer(self, conn, env):
        unit_id = _make_unit(conn, env["company_id"])
        income, marketing = self._income_accounts(conn, env["company_id"])
        before = _series_value(conn, env["company_id"])
        result = self._add_entry(conn, env, unit_id, None, income, marketing)
        assert is_error(result)
        assert result["message"] == (
            "--customer-id is required to post a royalty entry: the receivable "
            "leg must name the franchisee's customer record")
        assert _royalty_rows(conn, unit_id) == []
        t = Table("gl_entry")
        q = (Q.from_(t).select(t.id)
             .where(t.voucher_type == P()))
        assert conn.execute(q.get_sql(), ("food_franchise_royalty",)).fetchall() == []
        assert _series_value(conn, env["company_id"]) == before

    def test_royalty_refuses_one_account(self, conn, env):
        customer_id = _add_customer(conn, env["company_id"])
        unit_id = _make_unit(conn, env["company_id"])
        before = _series_value(conn, env["company_id"])
        result = call_action(
            ACTIONS["food-add-royalty-entry"], conn,
            ns(company_id=env["company_id"], franchise_unit_id=unit_id,
               period_start=PERIOD_START, period_end=PERIOD_END,
               gross_revenue="100000.00", royalty_rate="5",
               marketing_fee="1000.00",
               royalty_income_account_id=seed_account(
                   conn, env["company_id"], "Royalty Income", "income",
                   "revenue", "4100"),
               customer_id=customer_id),
        )
        assert is_error(result)
        assert result["message"] == (
            "Cannot post a royalty entry: --royalty-income-account-id and "
            "--royalty-receivable-account-id must both be given to post to "
            "the ledger")
        assert _royalty_rows(conn, unit_id) == []
        assert _series_value(conn, env["company_id"]) == before

    def test_royalty_ledger_failure_writes_nothing(self, conn, env):
        customer_id = _add_customer(conn, env["company_id"])
        unit_id = _make_unit(conn, env["company_id"])
        income, marketing = self._income_accounts(conn, env["company_id"])
        result = self._add_entry(conn, env, unit_id, customer_id, income,
                                 marketing, with_cost_center=False)
        assert is_error(result)
        assert result["message"].startswith(
            "Royalty entry was not recorded: the ledger posting was refused: "
            "GL Validation Step 6 Failed:")
        assert _royalty_rows(conn, unit_id) == []
        t = Table("gl_entry")
        q = (Q.from_(t).select(t.id)
             .where(t.voucher_type == P()))
        assert conn.execute(q.get_sql(), ("food_franchise_royalty",)).fetchall() == []


class TestVoucherTypesRegistered:
    def test_voucher_types_registered_for_foodclaw(self, conn, env):
        assert CATERING_MOD.CATERING_VOUCHER_TYPE == "food_catering_revenue"
        assert FRANCHISE_MOD.ROYALTY_VOUCHER_TYPE == "food_franchise_royalty"
        for voucher_type in ("food_catering_revenue", "food_franchise_royalty"):
            t = Table("voucher_type_registry")
            q = (Q.from_(t).select(t.voucher_type, t.skill_name, t.is_active)
                 .where(t.voucher_type == P())
                 .where(t.target_table == P()))
            rows = [dict(r) for r in
                    conn.execute(q.get_sql(), (voucher_type, "gl_entry")).fetchall()]
            assert len(rows) == 1
            assert rows[0]["skill_name"] == "foodclaw"
            assert rows[0]["is_active"] == 1
