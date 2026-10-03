"""Catering completion bills the customer through a submitted sales invoice.

Completing a catering event creates the debt as a selling document: FoodClaw
ensures the catering service item, creates a draft sales invoice through the
selling module's own ``create-sales-invoice`` action, records its link row,
and submits it through ``submit-sales-invoice``. FoodClaw writes no ledger
row; the event becomes ``completed`` only after the invoice is submitted. A
failed submit leaves the named draft and the event still confirmed, so
completing again finishes that same draft and never creates a second
invoice.

Every database read-back below goes through PyPika (``erpclaw_lib.query``)
over the shared ``conn`` fixture. Money compares exact ``Decimal`` strings,
never float. The selling/inventory calls run in-process through
``delegate_selling_in_process`` (real foundation functions, recording exactly
which action and flags the vertical sent).
"""
import argparse
import importlib.util
import io
import json
import os
import sys
from decimal import Decimal
from unittest.mock import patch

import pytest

_TESTS_DIR = os.path.dirname(os.path.abspath(__file__))
if _TESTS_DIR not in sys.path:
    sys.path.insert(0, _TESTS_DIR)

from food_helpers import (  # noqa: E402
    call_action, ns, is_ok, is_error, load_db_query,
    seed_account, seed_company, seed_fiscal_year,
    delegate_selling_in_process,
)

from erpclaw_lib.query import Q, Table, Field, P, line_order  # noqa: E402

_mod = load_db_query()
ACTIONS = _mod.ACTIONS

SCRIPTS_DIR = os.path.dirname(_TESTS_DIR)
SRC_DIR = os.path.dirname(os.path.dirname(SCRIPTS_DIR))


def _load_selling():
    path = os.path.join(SRC_DIR, "erpclaw", "scripts", "erpclaw-selling", "db_query.py")
    spec = importlib.util.spec_from_file_location("_food_sell_selling", path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


SELLING = _load_selling()

EVENT_DATE = "2026-11-01"
QUOTED = "1500.00"

SNAPSHOT_TABLES = (
    "foodclaw_catering_event",
    "foodclaw_catering_invoice",
    "sales_invoice",
    "sales_invoice_item",
    "gl_entry",
    "audit_log",
)


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


def _make_event(conn, env, quoted=QUOTED, name="Gala Dinner",
                client="Acme Inc", date=EVENT_DATE):
    result = call_action(
        ACTIONS["food-add-catering-event"], conn,
        ns(company_id=env["company_id"], event_name=name,
           client_name=client, event_date=date, quoted_price=quoted),
    )
    assert is_ok(result), result
    return result["id"]


def _confirm(conn, event_id):
    result = call_action(
        ACTIONS["food-confirm-event"], conn, ns(event_id=event_id))
    assert is_ok(result), result


def _add_item(conn, event_id, item_name, quantity, unit_price):
    result = call_action(
        ACTIONS["food-add-catering-item"], conn,
        ns(event_id=event_id, item_name=item_name, quantity=quantity,
           unit_price=unit_price),
    )
    assert is_ok(result), result
    return result["id"]


def _complete(conn, db_path, event_id, customer_id=None, final_amount=None,
              **extra):
    kw = dict(event_id=event_id, db_path=db_path)
    if customer_id is not None:
        kw["customer_id"] = customer_id
    if final_amount is not None:
        kw["final_amount"] = final_amount
    kw.update(extra)
    return call_action(
        ACTIONS["food-complete-catering-event"], conn, ns(**kw))


def _row(conn, table, rid):
    t = Table(table)
    row = conn.execute(
        Q.from_(t).select(t.star).where(t.id == P()).get_sql(), (rid,)).fetchone()
    return dict(row) if row is not None else None


def _event(conn, event_id):
    return _row(conn, "foodclaw_catering_event", event_id)


def _link_for_event(conn, event_id):
    t = Table("foodclaw_catering_invoice")
    row = conn.execute(
        Q.from_(t).select(t.star).where(t.event_id == P()).get_sql(),
        (event_id,)).fetchone()
    return dict(row) if row is not None else None


def _invoices_for_customer(conn, customer_id):
    t = Table("sales_invoice")
    return [dict(r) for r in conn.execute(
        Q.from_(t).select(t.star).where(t.customer_id == P()).get_sql(),
        (customer_id,)).fetchall()]


def _lines(conn, sales_invoice_id):
    t = Table("sales_invoice_item")
    return [dict(r) for r in conn.execute(
        Q.from_(t).select(t.star).where(t.sales_invoice_id == P())
        .orderby(line_order(t)).get_sql(), (sales_invoice_id,)).fetchall()]


def _gl_for_voucher(conn, voucher_type, voucher_id):
    t = Table("gl_entry")
    return [dict(r) for r in conn.execute(
        Q.from_(t).select(t.star)
        .where(t.voucher_type == P()).where(t.voucher_id == P()).get_sql(),
        (voucher_type, voucher_id,)).fetchall()]


def _item(conn, item_id):
    return _row(conn, "item", item_id)


def _calls(captured, action):
    return [c for c in captured["calls"] if c["action"] == action]


def snapshot_tables(conn):
    snap = {}
    for name in SNAPSHOT_TABLES:
        t = Table(name)
        rows = conn.execute(Q.from_(t).select(t.star).get_sql()).fetchall()
        snap[name] = sorted(repr(dict(r)) for r in rows)
    return snap


def test_completion_bills_a_submitted_sales_invoice(conn, env, db_path,
                                                    monkeypatch):
    customer_id = _add_customer(conn, env["company_id"])
    event_id = _make_event(conn, env)
    _confirm(conn, event_id)
    captured = delegate_selling_in_process(conn, monkeypatch)
    result = _complete(conn, db_path, event_id, customer_id)
    assert is_ok(result), result
    si_id = result["sales_invoice_id"]
    assert result["resumed"] is False

    invoices = _invoices_for_customer(conn, customer_id)
    assert len(invoices) == 1
    si = invoices[0]
    assert si["id"] == si_id
    assert si["status"] == "submitted"
    assert si["posting_date"] == EVENT_DATE
    assert si["grand_total"] == "1500.00"
    assert si["outstanding_amount"] == "1500.00"

    lines = _lines(conn, si_id)
    assert len(lines) == 1
    assert (lines[0]["quantity"], lines[0]["rate"],
            lines[0]["amount"]) == ("1.00", "1500.00", "1500.00")
    assert _item(conn, lines[0]["item_id"])["item_code"] == "FOOD-CATERING"

    legs = _gl_for_voucher(conn, "sales_invoice", si_id)
    assert len(legs) == 2, legs
    assert {leg["account_id"] for leg in legs} == {
        env["ar_account_id"], env["revenue_account_id"]}
    by_account = {leg["account_id"]: leg for leg in legs}
    receivable = by_account[env["ar_account_id"]]
    assert (receivable["debit"], receivable["credit"]) == ("1500.00", "0.00")
    assert (receivable["party_type"], receivable["party_id"]) == (
        "customer", customer_id)
    revenue = by_account[env["revenue_account_id"]]
    assert (revenue["debit"], revenue["credit"]) == ("0.00", "1500.00")
    t = Table("gl_entry")
    assert conn.execute(
        Q.from_(t).select(t.id).where(t.voucher_id == P()).get_sql(),
        (event_id,)).fetchall() == []

    link = _link_for_event(conn, event_id)
    assert link is not None
    assert (link["event_id"], link["sales_invoice_id"], link["customer_id"],
            link["amount"], link["company_id"]) == (
                event_id, si_id, customer_id, "1500.00", env["company_id"])

    event = _event(conn, event_id)
    assert event["event_status"] == "completed"
    assert event["final_amount"] == "1500.00"
    assert event["gl_entry_ids"] is None

    for leg in legs:
        assert leg["posting_date"] == EVENT_DATE
    assert revenue["cost_center_id"] == env["cost_center_id"]
    assert revenue["party_type"] is None
    assert revenue["party_id"] is None
    assert (sum(Decimal(leg["debit"]) for leg in legs)
            == sum(Decimal(leg["credit"]) for leg in legs)
            == Decimal("1500.00"))
    assert _calls(captured, "create-sales-invoice")
    assert _calls(captured, "submit-sales-invoice")


def test_items_bill_one_line_each(conn, env, db_path, monkeypatch):
    customer_id = _add_customer(conn, env["company_id"])
    event_id = _make_event(conn, env, quoted="0.00")
    _confirm(conn, event_id)
    _add_item(conn, event_id, "Chicken", 100, "20.00")
    _add_item(conn, event_id, "Dessert", 100, "8.00")
    delegate_selling_in_process(conn, monkeypatch)
    result = _complete(conn, db_path, event_id, customer_id)
    assert is_ok(result), result
    assert result["final_amount"] == "2800.00"
    assert result["resumed"] is False
    si = _row(conn, "sales_invoice", result["sales_invoice_id"])
    assert si["grand_total"] == "2800.00"
    lines = _lines(conn, result["sales_invoice_id"])
    assert len(lines) == 2
    assert (lines[0]["quantity"], lines[0]["rate"],
            lines[0]["amount"]) == ("100.00", "20.00", "2000.00")
    assert (lines[1]["quantity"], lines[1]["rate"],
            lines[1]["amount"]) == ("100.00", "8.00", "800.00")


def test_items_not_matching_the_total_bill_one_line(conn, env, db_path,
                                                    monkeypatch):
    customer_id = _add_customer(conn, env["company_id"])
    event_id = _make_event(conn, env, quoted="0.00")
    _confirm(conn, event_id)
    _add_item(conn, event_id, "Chicken", 100, "20.00")
    _add_item(conn, event_id, "Dessert", 100, "8.00")
    delegate_selling_in_process(conn, monkeypatch)
    result = _complete(conn, db_path, event_id, customer_id,
                       final_amount="3000.00")
    assert is_ok(result), result
    assert result["final_amount"] == "3000.00"
    si = _row(conn, "sales_invoice", result["sales_invoice_id"])
    assert si["grand_total"] == "3000.00"
    lines = _lines(conn, result["sales_invoice_id"])
    assert len(lines) == 1
    assert (lines[0]["quantity"], lines[0]["rate"]) == ("1.00", "3000.00")


def test_customer_required(conn, env, db_path, monkeypatch):
    event_id = _make_event(conn, env)
    _confirm(conn, event_id)
    captured = delegate_selling_in_process(conn, monkeypatch)
    before = snapshot_tables(conn)
    result = _complete(conn, db_path, event_id)
    assert is_error(result)
    assert result["message"] == (
        "--customer-id is required to complete a catering event: the sales "
        "invoice must name the customer who owes it")
    assert snapshot_tables(conn) == before
    assert captured["calls"] == []


def test_customer_of_another_company_refused(conn, env, db_path, monkeypatch):
    other_company = seed_company(conn)
    foreign_customer = _add_customer(conn, other_company)
    event_id = _make_event(conn, env)
    _confirm(conn, event_id)
    captured = delegate_selling_in_process(conn, monkeypatch)
    before = snapshot_tables(conn)
    result = _complete(conn, db_path, event_id, foreign_customer)
    assert is_error(result)
    assert result["message"] == (
        f"Customer {foreign_customer} not found in company {env['company_id']}")
    assert snapshot_tables(conn) == before
    assert captured["calls"] == []


def test_failed_submit_leaves_a_named_draft_and_retry_finishes_it(
        conn, env, db_path, monkeypatch):
    customer_id = _add_customer(conn, env["company_id"])
    event_id = _make_event(conn, env)
    _confirm(conn, event_id)
    captured_first = delegate_selling_in_process(
        conn, monkeypatch, submit_behaviour="fail")
    refused = _complete(conn, db_path, event_id, customer_id)
    assert is_error(refused), refused
    link = _link_for_event(conn, event_id)
    assert link is not None
    si_id = link["sales_invoice_id"]
    assert refused["message"].startswith(
        f"Sales invoice {si_id} was created for catering event {event_id} "
        "but could not be submitted:")
    assert _event(conn, event_id)["event_status"] == "confirmed"
    assert _row(conn, "sales_invoice", si_id)["status"] == "draft"
    assert _gl_for_voucher(conn, "sales_invoice", si_id) == []

    captured_second = delegate_selling_in_process(conn, monkeypatch)
    result = _complete(conn, db_path, event_id, customer_id)
    assert is_ok(result), result
    assert result["sales_invoice_id"] == si_id
    assert result["resumed"] is True
    assert len(_invoices_for_customer(conn, customer_id)) == 1
    assert _row(conn, "sales_invoice", si_id)["status"] == "submitted"
    assert len(_calls(captured_first, "create-sales-invoice")
               + _calls(captured_second, "create-sales-invoice")) == 1
    assert _event(conn, event_id)["event_status"] == "completed"


def test_submitted_invoice_on_retry_just_completes(conn, env, db_path,
                                                   monkeypatch):
    customer_id = _add_customer(conn, env["company_id"])
    event_id = _make_event(conn, env)
    _confirm(conn, event_id)
    delegate_selling_in_process(conn, monkeypatch, submit_behaviour="lost_reply")
    refused = _complete(conn, db_path, event_id, customer_id)
    assert is_error(refused), refused
    link = _link_for_event(conn, event_id)
    assert link is not None
    si_id = link["sales_invoice_id"]
    assert refused["message"].startswith(
        f"Sales invoice {si_id} was created for catering event {event_id} "
        "but could not be submitted:")
    assert _row(conn, "sales_invoice", si_id)["status"] == "submitted"
    assert len(_gl_for_voucher(conn, "sales_invoice", si_id)) == 2
    assert _event(conn, event_id)["event_status"] == "confirmed"

    captured = delegate_selling_in_process(conn, monkeypatch)
    result = _complete(conn, db_path, event_id, customer_id)
    assert is_ok(result), result
    assert result["sales_invoice_id"] == si_id
    assert result["resumed"] is True
    assert captured["calls"] == []
    assert len(_gl_for_voucher(conn, "sales_invoice", si_id)) == 2
    assert _event(conn, event_id)["event_status"] == "completed"


def test_retry_with_another_customer_refused(conn, env, db_path, monkeypatch):
    customer_id = _add_customer(conn, env["company_id"])
    event_id = _make_event(conn, env)
    _confirm(conn, event_id)
    delegate_selling_in_process(conn, monkeypatch, submit_behaviour="fail")
    refused = _complete(conn, db_path, event_id, customer_id)
    assert is_error(refused), refused
    si_id = _link_for_event(conn, event_id)["sales_invoice_id"]
    other = _add_customer(conn, env["company_id"], "Other Diner")
    captured = delegate_selling_in_process(conn, monkeypatch)
    before = snapshot_tables(conn)
    result = _complete(conn, db_path, event_id, other)
    assert is_error(result)
    assert result["message"] == (
        f"Catering event {event_id} is already billed to customer "
        f"{customer_id} (sales invoice {si_id})")
    assert snapshot_tables(conn) == before
    assert captured["calls"] == []


def test_retry_with_another_amount_refused(conn, env, db_path, monkeypatch):
    customer_id = _add_customer(conn, env["company_id"])
    event_id = _make_event(conn, env)
    _confirm(conn, event_id)
    delegate_selling_in_process(conn, monkeypatch, submit_behaviour="fail")
    refused = _complete(conn, db_path, event_id, customer_id)
    assert is_error(refused), refused
    si_id = _link_for_event(conn, event_id)["sales_invoice_id"]
    captured = delegate_selling_in_process(conn, monkeypatch)
    before = snapshot_tables(conn)
    result = _complete(conn, db_path, event_id, customer_id,
                       final_amount="1600.00")
    assert is_error(result)
    assert result["message"] == (
        f"Catering event {event_id} is already billed for 1500.00 "
        f"(sales invoice {si_id}); the amount cannot change")
    assert snapshot_tables(conn) == before
    assert captured["calls"] == []


def test_completed_event_refused(conn, env, db_path, monkeypatch):
    customer_id = _add_customer(conn, env["company_id"])
    event_id = _make_event(conn, env)
    _confirm(conn, event_id)
    captured = delegate_selling_in_process(conn, monkeypatch)
    first = _complete(conn, db_path, event_id, customer_id)
    assert is_ok(first), first
    assert first["sales_invoice_id"]
    calls_before = len(captured["calls"])
    before = snapshot_tables(conn)
    result = _complete(conn, db_path, event_id, customer_id)
    assert is_error(result)
    assert result["message"] == (
        "Cannot complete: event status is 'completed', expected 'confirmed' "
        "or 'in_progress'")
    assert len(captured["calls"]) == calls_before
    assert snapshot_tables(conn) == before


def test_account_arguments_are_not_posting_inputs(conn, env, db_path,
                                                  monkeypatch):
    other_income = seed_account(conn, env["company_id"], "Catering Revenue",
                                "income", "revenue", "4200")
    t = Table("company")
    conn.execute(
        Q.update(t).set("default_income_account_id", P())
        .where(t.id == P()).get_sql(),
        (env["revenue_account_id"], env["company_id"]))
    conn.commit()
    customer_id = _add_customer(conn, env["company_id"])
    event_id = _make_event(conn, env)
    _confirm(conn, event_id)
    stored_before = _event(conn, event_id)
    delegate_selling_in_process(conn, monkeypatch)
    result = _complete(conn, db_path, event_id, customer_id,
                       revenue_account_id=other_income,
                       receivable_account_id=env["ar_account_id"])
    assert is_ok(result), result
    legs = _gl_for_voucher(conn, "sales_invoice", result["sales_invoice_id"])
    assert len(legs) == 2, legs
    by_account = {leg["account_id"]: leg for leg in legs}
    assert by_account[env["revenue_account_id"]]["credit"] == "1500.00"
    assert _gl_for_voucher(conn, "sales_invoice", other_income) == []
    t = Table("gl_entry")
    assert conn.execute(
        Q.from_(t).select(t.id).where(t.account_id == P()).get_sql(),
        (other_income,)).fetchall() == []
    stored_after = _event(conn, event_id)
    for column in ("revenue_account_id", "receivable_account_id",
                   "cost_center_id", "gl_entry_ids"):
        assert stored_after[column] == stored_before[column]


def test_complete_is_a_confirmed_action(conn, env, db_path, monkeypatch):
    customer_id = _add_customer(conn, env["company_id"])
    event_id = _make_event(conn, env)
    _confirm(conn, event_id)
    captured = delegate_selling_in_process(conn, monkeypatch)
    result = _complete(conn, db_path, event_id, customer_id)
    assert is_ok(result), result

    router_path = os.path.join(SRC_DIR, "erpclaw", "scripts", "db_query.py")
    spec = importlib.util.spec_from_file_location("_food_sell_gate_router",
                                                  router_path)
    router = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(router)
    assert "food-complete-catering-event" in router.DANGEROUS_ACTIONS

    submits = [c for c in captured["calls"]
               if c["action"] == "submit-sales-invoice"]
    assert submits
    recorded = submits[0]
    argv = ["db_query.py", "--action", recorded["action"]]
    for key, value in recorded["args"].items():
        argv.append(key)
        if value is not None:
            argv.append(str(value))

    with patch.object(sys, "argv", argv):
        router._gate_dangerous_action(recorded["action"])

    stripped = [a for a in argv if a != "--user-confirmed"]
    buf = io.StringIO()
    with patch.object(sys, "argv", stripped), \
            patch("sys.stdout", buf), pytest.raises(SystemExit) as exc:
        router._gate_dangerous_action(recorded["action"])
    assert exc.value.code == 2
    assert json.loads(buf.getvalue())["error"] == "user_confirmation_required"


def test_real_submit_refusal_leaves_a_named_draft(conn, env, db_path,
                                                  monkeypatch):
    customer_id = _add_customer(conn, env["company_id"])
    event_id = _make_event(conn, env, date="2027-03-01")
    _confirm(conn, event_id)
    delegate_selling_in_process(conn, monkeypatch)
    refused = _complete(conn, db_path, event_id, customer_id)
    assert is_error(refused), refused
    link = _link_for_event(conn, event_id)
    assert link is not None
    si_id = link["sales_invoice_id"]
    assert refused["message"].startswith(
        f"Sales invoice {si_id} was created for catering event {event_id} "
        "but could not be submitted:")
    assert "GL Validation Step 9 Failed" in refused["message"]
    assert _event(conn, event_id)["event_status"] == "confirmed"
    assert _row(conn, "sales_invoice", si_id)["status"] == "draft"
    assert _gl_for_voucher(conn, "sales_invoice", si_id) == []

    seed_fiscal_year(conn, env["company_id"], "2027-01-01", "2027-12-31")
    delegate_selling_in_process(conn, monkeypatch)
    result = _complete(conn, db_path, event_id, customer_id)
    assert is_ok(result), result
    assert result["sales_invoice_id"] == si_id
    assert result["resumed"] is True
    assert _row(conn, "sales_invoice", si_id)["status"] == "submitted"
    legs = _gl_for_voucher(conn, "sales_invoice", si_id)
    assert len(legs) == 2, legs
    for leg in legs:
        assert leg["posting_date"] == "2027-03-01"


def test_create_refusal_writes_nothing(conn, env, db_path, monkeypatch):
    customer_id = _add_customer(conn, env["company_id"])
    event_id = _make_event(conn, env)
    _confirm(conn, event_id)
    captured = delegate_selling_in_process(conn, monkeypatch,
                                           create_behaviour="fail")
    before = snapshot_tables(conn)
    result = _complete(conn, db_path, event_id, customer_id)
    assert is_error(result)
    assert result["message"] == (
        "Catering invoice could not be created: simulated create failure")
    after = snapshot_tables(conn)
    for table in SNAPSHOT_TABLES:
        if table == "audit_log":
            continue
        assert after[table] == before[table]
    audit_before = [r for r in before["audit_log"]
                    if "'action': 'add-item'" not in r]
    audit_after = [r for r in after["audit_log"]
                   if "'action': 'add-item'" not in r]
    assert audit_after == audit_before
    added = [r for r in after["audit_log"]
             if "'action': 'add-item'" in r]
    assert len(added) == 1 and "FOOD-CATERING" in added[0]
    assert _calls(captured, "submit-sales-invoice") == []


def test_invoice_total_must_match(conn, env, db_path, monkeypatch):
    customer_id = _add_customer(conn, env["company_id"])
    event_id = _make_event(conn, env)
    _confirm(conn, event_id)
    delegate_selling_in_process(conn, monkeypatch, create_behaviour="reprice")
    refused = _complete(conn, db_path, event_id, customer_id)
    assert is_error(refused), refused
    t = Table("sales_invoice")
    drafts = [dict(r) for r in conn.execute(
        Q.from_(t).select(t.star).get_sql()).fetchall()]
    assert len(drafts) == 1
    si_id = drafts[0]["id"]
    assert drafts[0]["status"] == "draft"
    assert refused["message"] == (
        f"Sales invoice {si_id} totals 1400.00, not 1500.00, for catering "
        f"event {event_id} (a selling price rule changed a line); it is an "
        "unlinked draft: delete it through selling, then complete again")
    assert _link_for_event(conn, event_id) is None
    assert _event(conn, event_id)["event_status"] == "confirmed"

    customer_b = _add_customer(conn, env["company_id"], "Second Diner")
    event_b = _make_event(conn, env)
    _confirm(conn, event_b)
    delegate_selling_in_process(conn, monkeypatch, submit_behaviour="fail")
    refused_b = _complete(conn, db_path, event_b, customer_b)
    assert is_error(refused_b), refused_b
    si_b = _link_for_event(conn, event_b)["sales_invoice_id"]
    item_id = _lines(conn, si_b)[0]["item_id"]
    updated = call_action(
        SELLING.update_sales_invoice, conn,
        argparse.Namespace(
            sales_invoice_id=si_b, due_date=None,
            items=json.dumps([{"item_id": item_id, "qty": "1",
                               "rate": "1400.00"}]),
            dimensions=None, dimension_key=None, dimension_value=None))
    assert is_ok(updated), updated
    captured = delegate_selling_in_process(conn, monkeypatch)
    before = snapshot_tables(conn)
    retry = _complete(conn, db_path, event_b, customer_b)
    assert is_error(retry)
    assert retry["message"] == (
        f"Sales invoice {si_b} for catering event {event_b} no longer "
        f"matches its link (customer {customer_b}, total 1400.00; the link "
        f"says {customer_b}, 1500.00)")
    assert _calls(captured, "submit-sales-invoice") == []
    assert snapshot_tables(conn) == before
    assert _event(conn, event_b)["event_status"] == "confirmed"
