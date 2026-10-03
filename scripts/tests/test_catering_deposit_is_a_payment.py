"""A catering deposit is a real customer payment through the payments module.

Receiving a deposit records a submitted ``receive`` payment (an open customer
advance) linked by ``CATERING-DEPOSIT <event id>`` reference, plus one audit
row. ``--deposit-amount`` on add/update stays the deposit asked for.
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
    seed_account, seed_company, seed_fiscal_year, seed_cost_center,
    seed_naming_series, get_conn,
    delegate_selling_in_process,
)

from erpclaw_lib.query import Q, Table, Field, P, line_order  # noqa: E402

_mod = load_db_query()
ACTIONS = _mod.ACTIONS

SCRIPTS_DIR = os.path.dirname(_TESTS_DIR)
SRC_DIR = os.path.dirname(os.path.dirname(SCRIPTS_DIR))


def _load_domain(domain):
    path = os.path.join(SRC_DIR, "erpclaw", "scripts", domain, "db_query.py")
    spec = importlib.util.spec_from_file_location("_food_dep_%s" % domain.replace("-", "_"), path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


SELLING = _load_domain("erpclaw-selling")
PAYMENTS = _load_domain("erpclaw-payments")

EVENT_DATE = "2026-10-10"
DEPOSIT_DATE = "2026-10-01"
QUOTED = "3300.00"
DEPOSIT = "500.00"

SNAPSHOT_TABLES = (
    "foodclaw_catering_event",
    "payment_entry",
    "gl_entry",
    "payment_ledger_entry",
    "audit_log",
)


class _AnyArgs:
    def __init__(self, **kw):
        self.__dict__.update(kw)

    def __getattr__(self, name):
        return None


def _add_customer(conn, company_id, name="Marlow Wedding Party"):
    result = call_action(
        SELLING.add_customer, conn,
        _AnyArgs(name=name, company_id=company_id),
    )
    assert is_ok(result), result
    return result["customer_id"]


def _setup_cash(conn, env):
    cash = seed_account(conn, env["company_id"], "Cash", "asset", "cash", "1000")
    t = Table("company")
    conn.execute(
        Q.update(t).set("default_receivable_account_id", P()).where(t.id == P()).get_sql(),
        (env["ar_account_id"], env["company_id"]))
    conn.execute(
        Q.update(t).set("default_income_account_id", P()).where(t.id == P()).get_sql(),
        (env["revenue_account_id"], env["company_id"]))
    conn.execute(
        Q.update(t).set("default_cash_account_id", P()).where(t.id == P()).get_sql(),
        (cash, env["company_id"]))
    conn.commit()
    return cash


def _make_event(conn, env, name="Marlow Wedding", client="Marlow Wedding Party",
                date=EVENT_DATE, quoted=QUOTED, deposit=DEPOSIT):
    result = call_action(
        ACTIONS["food-add-catering-event"], conn,
        ns(company_id=env["company_id"], event_name=name,
           client_name=client, event_date=date, venue="Lakeview Hall",
           guest_count=60, quoted_price=quoted, deposit_amount=deposit),
    )
    assert is_ok(result), result
    eid = result["id"]
    r1 = call_action(
        ACTIONS["food-add-catering-item"], conn,
        ns(event_id=eid, item_name="Chicken entree", quantity=60, unit_price="45.00"))
    assert is_ok(r1), r1
    r2 = call_action(
        ACTIONS["food-add-catering-item"], conn,
        ns(event_id=eid, item_name="Dessert", quantity=60, unit_price="10.00"))
    assert is_ok(r2), r2
    return eid


def _confirm(conn, event_id):
    result = call_action(
        ACTIONS["food-confirm-event"], conn, ns(event_id=event_id))
    assert is_ok(result), result


def _receive(conn, db_path, event_id, customer_id=None, deposit_amount=None,
             deposit_date=DEPOSIT_DATE, cash_account_id=None, **extra):
    kw = dict(event_id=event_id, db_path=db_path)
    if customer_id is not None:
        kw["customer_id"] = customer_id
    if deposit_amount is not None:
        kw["deposit_amount"] = deposit_amount
    if deposit_date is not None:
        kw["deposit_date"] = deposit_date
    if cash_account_id is not None:
        kw["cash_account_id"] = cash_account_id
    kw.update(extra)
    return call_action(
        ACTIONS["food-receive-catering-deposit"], conn, ns(**kw))


def _calls(captured, action):
    return [c for c in captured["calls"] if c["action"] == action]


def snapshot_tables(conn):
    snap = {}
    for name in SNAPSHOT_TABLES:
        t = Table(name)
        rows = conn.execute(Q.from_(t).select(t.star).get_sql()).fetchall()
        snap[name] = sorted(repr(dict(r)) for r in rows)
    return snap


def _row(conn, table, rid):
    t = Table(table)
    row = conn.execute(
        Q.from_(t).select(t.star).where(t.id == P()).get_sql(), (rid,)).fetchone()
    return dict(row) if row is not None else None


def _event(conn, event_id):
    return _row(conn, "foodclaw_catering_event", event_id)


def _payments_by_ref(conn, company_id, event_id, status=None):
    t = Table("payment_entry")
    ref = "CATERING-DEPOSIT " + event_id
    q = Q.from_(t).select(t.star).where(t.company_id == P()).where(t.payment_type == P()).where(t.party_type == P()).where(t.reference_number == P())
    params = [company_id, "receive", "customer", ref]
    if status is not None:
        q = q.where(t.status == P())
        params.append(status)
    q = q.orderby(t.posting_date, line_order(t))
    return [dict(r) for r in conn.execute(q.get_sql(), tuple(params)).fetchall()]


def _gl_for_payment(conn, pe_id):
    t = Table("gl_entry")
    return [dict(r) for r in conn.execute(
        Q.from_(t).select(t.star).where(t.voucher_id == P()).get_sql(), (pe_id,)).fetchall()]


def _ple_for_payment(conn, pe_id):
    t = Table("payment_ledger_entry")
    return [dict(r) for r in conn.execute(
        Q.from_(t).select(t.star).where(t.voucher_id == P()).get_sql(), (pe_id,)).fetchall()]


def _audit_for_event(conn, event_id):
    t = Table("audit_log")
    return [dict(r) for r in conn.execute(
        Q.from_(t).select(t.star).where(t.entity_id == P()).where(t.action == P()).get_sql(),
        (event_id, "food-receive-catering-deposit")).fetchall()]


def _balances(conn, account_id):
    t = Table("gl_entry")
    rows = conn.execute(
        Q.from_(t).select(t.debit, t.credit).where(t.account_id == P()).where(t.is_cancelled == P()).get_sql(),
        (account_id, 0)).fetchall()
    dr = sum((Decimal(str(dict(r)["debit"] or "0")) for r in rows), Decimal("0"))
    cr = sum((Decimal(str(dict(r)["credit"] or "0")) for r in rows), Decimal("0"))
    return dr, cr


def test_deposit_is_a_submitted_customer_receipt(conn, env, db_path, monkeypatch):
    cash = _setup_cash(conn, env)
    customer_id = _add_customer(conn, env["company_id"])
    event_id = _make_event(conn, env)
    _confirm(conn, event_id)
    event_before = _event(conn, event_id)
    captured = delegate_selling_in_process(conn, monkeypatch)
    result = _receive(conn, db_path, event_id, customer_id, deposit_amount="500.00")
    assert is_ok(result), result
    assert result["event_id"] == event_id
    assert result["customer_id"] == customer_id
    assert result["amount"] == "500.00"
    assert result["deposit_date"] == DEPOSIT_DATE
    assert result["deposits_received"] == "500.00"
    assert result["resumed"] is False
    pe_id = result["payment_entry_id"]
    assert pe_id

    pes = _payments_by_ref(conn, env["company_id"], event_id)
    assert len(pes) == 1
    pe = pes[0]
    assert pe["id"] == pe_id
    assert pe["status"] == "submitted"
    assert pe["payment_type"] == "receive"
    assert (pe["party_type"], pe["party_id"]) == ("customer", customer_id)
    assert pe["paid_amount"] == "500.00"
    assert pe["unallocated_amount"] == "500.00"
    assert pe["posting_date"] == DEPOSIT_DATE
    assert pe["reference_number"] == "CATERING-DEPOSIT " + event_id

    legs = _gl_for_payment(conn, pe_id)
    assert len(legs) == 2, legs
    by_account = {leg["account_id"]: leg for leg in legs}
    cash_leg = by_account[cash]
    assert cash_leg["debit"] == "500.00"
    recv_leg = by_account[env["ar_account_id"]]
    assert recv_leg["credit"] == "500.00"
    assert (recv_leg["party_type"], recv_leg["party_id"]) == ("customer", customer_id)

    audits = _audit_for_event(conn, event_id)
    assert len(audits) == 1
    assert pe_id in (audits[0].get("new_values") or "")

    assert _event(conn, event_id) == event_before


def test_deposit_through_the_advance_account(conn, env, db_path, monkeypatch):
    cash = _setup_cash(conn, env)
    adv = seed_account(conn, env["company_id"], "Customer Advances", "liability", "other", "2400")
    t = Table("company")
    conn.execute(
        Q.update(t).set("advance_from_customer_account_id", P()).where(t.id == P()).get_sql(),
        (adv, env["company_id"]))
    conn.commit()
    customer_id = _add_customer(conn, env["company_id"])
    event_id = _make_event(conn, env)
    _confirm(conn, event_id)
    captured = delegate_selling_in_process(conn, monkeypatch)
    result = _receive(conn, db_path, event_id, customer_id, deposit_amount="500.00")
    assert is_ok(result), result
    pe_id = result["payment_entry_id"]
    legs = _gl_for_payment(conn, pe_id)
    assert len(legs) == 2, legs
    by_account = {leg["account_id"]: leg for leg in legs}
    assert by_account[cash]["debit"] == "500.00"
    assert by_account[adv]["credit"] == "500.00"
    assert env["ar_account_id"] not in by_account
    t2 = Table("gl_entry")
    assert conn.execute(
        Q.from_(t2).select(t2.id).where(t2.account_id == P()).get_sql(),
        (env["ar_account_id"],)).fetchall() == []


def test_deposit_refusals_write_nothing(conn, env, db_path, monkeypatch):
    cash = _setup_cash(conn, env)
    customer_id = _add_customer(conn, env["company_id"])

    def _fresh_event(**kw):
        eid = _make_event(conn, env, **kw)
        return eid

    # no customer
    eid = _fresh_event()
    _confirm(conn, eid)
    cap = delegate_selling_in_process(conn, monkeypatch)
    before = snapshot_tables(conn)
    r = _receive(conn, db_path, eid, None, deposit_amount="500.00")
    assert is_error(r)
    assert r["message"] == "--customer-id is required to receive a catering deposit: the payment must name the customer who paid it"
    assert snapshot_tables(conn) == before
    assert cap["calls"] == []

    # customer of another company
    other_company = seed_company(conn)
    seed_naming_series(conn, other_company)
    other_cust = _add_customer(conn, other_company)
    eid2 = _fresh_event()
    _confirm(conn, eid2)
    cap = delegate_selling_in_process(conn, monkeypatch)
    before = snapshot_tables(conn)
    r = _receive(conn, db_path, eid2, other_cust, deposit_amount="500.00")
    assert is_error(r)
    assert r["message"] == "Customer %s not found in company %s" % (other_cust, env["company_id"])
    assert snapshot_tables(conn) == before
    assert cap["calls"] == []

    # amount 0
    eid3 = _fresh_event()
    _confirm(conn, eid3)
    cap = delegate_selling_in_process(conn, monkeypatch)
    before = snapshot_tables(conn)
    r = _receive(conn, db_path, eid3, customer_id, deposit_amount="0")
    assert is_error(r)
    assert r["message"] == "Deposit amount must be greater than 0"
    assert snapshot_tables(conn) == before
    assert cap["calls"] == []

    # amount 3300.01
    eid4 = _fresh_event()
    _confirm(conn, eid4)
    cap = delegate_selling_in_process(conn, monkeypatch)
    before = snapshot_tables(conn)
    r = _receive(conn, db_path, eid4, customer_id, deposit_amount="3300.01")
    assert is_error(r)
    assert r["message"] == "Deposit 3300.01 is more than the event's 3300.00 less deposits already received (0.00)"
    assert snapshot_tables(conn) == before
    assert cap["calls"] == []

    # after a 500 deposit, 2800.01
    eid5 = _fresh_event()
    _confirm(conn, eid5)
    cap = delegate_selling_in_process(conn, monkeypatch)
    ok1 = _receive(conn, db_path, eid5, customer_id, deposit_amount="500.00")
    assert is_ok(ok1), ok1
    cap2 = delegate_selling_in_process(conn, monkeypatch)
    before = snapshot_tables(conn)
    r = _receive(conn, db_path, eid5, customer_id, deposit_amount="2800.01")
    assert is_error(r)
    assert r["message"] == "Deposit 2800.01 is more than the event's 3300.00 less deposits already received (500.00)"
    assert snapshot_tables(conn) == before
    assert cap2["calls"] == []

    # event inquiry (not yet updated)
    eid6 = _fresh_event()
    cap = delegate_selling_in_process(conn, monkeypatch)
    before = snapshot_tables(conn)
    r = _receive(conn, db_path, eid6, customer_id, deposit_amount="500.00")
    assert is_error(r)
    assert r["message"] == "Cannot receive a deposit: event status is 'inquiry', expected 'quoted', 'confirmed' or 'in_progress'"
    assert snapshot_tables(conn) == before
    assert cap["calls"] == []

    # event completed
    eid7 = _fresh_event()
    _confirm(conn, eid7)
    t = Table("foodclaw_catering_event")
    conn.execute(
        Q.update(t).set("event_status", P()).where(t.id == P()).get_sql(), ("completed", eid7))
    conn.commit()
    cap = delegate_selling_in_process(conn, monkeypatch)
    before = snapshot_tables(conn)
    r = _receive(conn, db_path, eid7, customer_id, deposit_amount="500.00")
    assert is_error(r)
    assert r["message"] == "Cannot receive a deposit: event status is 'completed', expected 'quoted', 'confirmed' or 'in_progress'"
    assert snapshot_tables(conn) == before
    assert cap["calls"] == []

    # event cancelled
    eid8 = _fresh_event()
    _confirm(conn, eid8)
    conn.execute(
        Q.update(t).set("event_status", P()).where(t.id == P()).get_sql(), ("cancelled", eid8))
    conn.commit()
    cap = delegate_selling_in_process(conn, monkeypatch)
    before = snapshot_tables(conn)
    r = _receive(conn, db_path, eid8, customer_id, deposit_amount="500.00")
    assert is_error(r)
    assert r["message"] == "Cannot receive a deposit: event status is 'cancelled', expected 'quoted', 'confirmed' or 'in_progress'"
    assert snapshot_tables(conn) == before
    assert cap["calls"] == []

    # no cash or bank account
    eid9 = _fresh_event()
    _confirm(conn, eid9)
    tc = Table("company")
    conn.execute(
        Q.update(tc).set("default_cash_account_id", P()).where(tc.id == P()).get_sql(), (None, env["company_id"]))
    conn.execute(
        Q.update(tc).set("default_bank_account_id", P()).where(tc.id == P()).get_sql(), (None, env["company_id"]))
    conn.commit()
    cap = delegate_selling_in_process(conn, monkeypatch)
    before = snapshot_tables(conn)
    r = _receive(conn, db_path, eid9, customer_id, deposit_amount="500.00")
    assert is_error(r)
    assert r["message"] == "No account to receive the deposit into: pass --cash-account-id or set the company's default cash or bank account"
    assert snapshot_tables(conn) == before
    assert cap["calls"] == []
    conn.execute(
        Q.update(tc).set("default_cash_account_id", P()).where(tc.id == P()).get_sql(), (cash, env["company_id"]))
    conn.commit()

    # cash account of another company
    other_cash = seed_account(conn, other_company, "Other Cash", "asset", "cash", "1010")
    eid10 = _fresh_event()
    _confirm(conn, eid10)
    cap = delegate_selling_in_process(conn, monkeypatch)
    before = snapshot_tables(conn)
    r = _receive(conn, db_path, eid10, customer_id, deposit_amount="500.00", cash_account_id=other_cash)
    assert is_error(r)
    assert r["message"] == "Account %s cannot receive a deposit for company %s (not found, another company's, or a group account)" % (other_cash, env["company_id"])
    assert snapshot_tables(conn) == before
    assert cap["calls"] == []

    # deposit date with no fiscal year
    eid11 = _fresh_event()
    _confirm(conn, eid11)
    cap = delegate_selling_in_process(conn, monkeypatch)
    before = snapshot_tables(conn)
    r = _receive(conn, db_path, eid11, customer_id, deposit_amount="500.00", deposit_date="2027-03-01")
    assert is_error(r)
    assert r["message"] == "Deposit cannot be recorded: no open fiscal year covers 2027-03-01"
    assert snapshot_tables(conn) == before
    assert cap["calls"] == []

    # second customer after first customer's deposit
    eid12 = _fresh_event()
    _confirm(conn, eid12)
    cap = delegate_selling_in_process(conn, monkeypatch)
    ok2 = _receive(conn, db_path, eid12, customer_id, deposit_amount="500.00")
    assert is_ok(ok2), ok2
    pe_first = ok2["payment_entry_id"]
    other_party = _add_customer(conn, env["company_id"], "Second Party")
    cap2 = delegate_selling_in_process(conn, monkeypatch)
    before = snapshot_tables(conn)
    r = _receive(conn, db_path, eid12, other_party, deposit_amount="100.00")
    assert is_error(r)
    assert r["message"] == "Catering event %s already has a deposit from customer %s (payment %s)" % (eid12, customer_id, pe_first)
    assert snapshot_tables(conn) == before
    assert cap2["calls"] == []

    # no receivable account (second company)
    cid2 = seed_company(conn)
    seed_naming_series(conn, cid2)
    seed_fiscal_year(conn, cid2)
    seed_cost_center(conn, cid2)
    cash2 = seed_account(conn, cid2, "Cash 2", "asset", "cash", "1000")
    tc2 = Table("company")
    conn.execute(
        Q.update(tc2).set("default_cash_account_id", P()).where(tc2.id == P()).get_sql(), (cash2, cid2))
    conn.commit()
    cust2 = _add_customer(conn, cid2, "Second Co Customer")
    res = call_action(
        ACTIONS["food-add-catering-event"], conn,
        ns(company_id=cid2, event_name="Second Co Event", client_name="Second Co Customer",
           event_date=EVENT_DATE, quoted_price="1000.00", deposit_amount="100.00"))
    assert is_ok(res), res
    eid13 = res["id"]
    call_action(ACTIONS["food-confirm-event"], conn, ns(event_id=eid13))
    cap = delegate_selling_in_process(conn, monkeypatch)
    before = snapshot_tables(conn)
    r = _receive(conn, db_path, eid13, cust2, deposit_amount="100.00")
    assert is_error(r)
    assert r["message"] == "No receivable account for company %s: set its default receivable account" % cid2
    assert snapshot_tables(conn) == before
    assert cap["calls"] == []


def test_failed_deposit_submit_resumes_the_same_payment(conn, env, db_path, monkeypatch):
    cash = _setup_cash(conn, env)
    customer_id = _add_customer(conn, env["company_id"])
    event_id = _make_event(conn, env)
    _confirm(conn, event_id)
    cap1 = delegate_selling_in_process(conn, monkeypatch, payment_behaviour="fail")
    refused = _receive(conn, db_path, event_id, customer_id, deposit_amount="500.00")
    assert is_error(refused), refused
    drafts = _payments_by_ref(conn, env["company_id"], event_id, status="draft")
    assert len(drafts) == 1
    pe_id = drafts[0]["id"]
    assert refused["message"].startswith(
        "Deposit payment %s was created for catering event %s but could not be submitted:" % (pe_id, event_id))
    assert _gl_for_payment(conn, pe_id) == []

    cap2 = delegate_selling_in_process(conn, monkeypatch)
    result = _receive(conn, db_path, event_id, customer_id, deposit_amount="500.00")
    assert is_ok(result), result
    assert result["payment_entry_id"] == pe_id
    assert result["resumed"] is True
    assert _row(conn, "payment_entry", pe_id)["status"] == "submitted"
    assert len(_calls(cap1, "add-payment") + _calls(cap2, "add-payment")) == 1

    # second event, draft mismatch on cash account
    cash2 = seed_account(conn, env["company_id"], "Cash 2", "asset", "cash", "1010")
    event2 = _make_event(conn, env, name="Second Wedding")
    _confirm(conn, event2)
    cap3 = delegate_selling_in_process(conn, monkeypatch, payment_behaviour="fail")
    refused2 = _receive(conn, db_path, event2, customer_id, deposit_amount="500.00")
    assert is_error(refused2), refused2
    drafts2 = _payments_by_ref(conn, env["company_id"], event2, status="draft")
    assert len(drafts2) == 1
    pe2 = drafts2[0]["id"]
    cap4 = delegate_selling_in_process(conn, monkeypatch)
    before = snapshot_tables(conn)
    r = _receive(conn, db_path, event2, customer_id, deposit_amount="500.00", cash_account_id=cash2)
    assert is_error(r)
    assert r["message"] == "A draft deposit payment %s for catering event %s exists (customer %s, amount 500.00); submit or delete it through payments first" % (pe2, event2, customer_id)
    assert snapshot_tables(conn) == before
    assert cap4["calls"] == []


def test_lost_submit_reply_is_a_success(conn, env, db_path, monkeypatch):
    cash = _setup_cash(conn, env)
    customer_id = _add_customer(conn, env["company_id"])
    event_id = _make_event(conn, env)
    _confirm(conn, event_id)
    cap = delegate_selling_in_process(conn, monkeypatch, payment_behaviour="submit_then_fail")
    result = _receive(conn, db_path, event_id, customer_id, deposit_amount="500.00")
    assert is_ok(result), result
    pe_id = result["payment_entry_id"]
    assert _row(conn, "payment_entry", pe_id)["status"] == "submitted"
    assert len(_calls(cap, "add-payment")) == 1
    assert len(_calls(cap, "submit-payment")) == 1
    assert len(_audit_for_event(conn, event_id)) == 1
    cap2 = delegate_selling_in_process(conn, monkeypatch)
    before = snapshot_tables(conn)
    r = call_action(
        ACTIONS["food-receive-catering-deposit"], conn,
        ns(event_id=event_id, customer_id=customer_id, deposit_date=DEPOSIT_DATE, db_path=db_path))
    assert is_error(r)
    assert r["message"] == "Deposit amount must be greater than 0"
    assert snapshot_tables(conn) == before
    assert cap2["calls"] == []


def test_more_than_one_draft_is_refused(conn, env, db_path, monkeypatch):
    cash = _setup_cash(conn, env)
    customer_id = _add_customer(conn, env["company_id"])
    event_id = _make_event(conn, env)
    _confirm(conn, event_id)
    ref = "CATERING-DEPOSIT " + event_id
    for amt in ("100.00", "200.00"):
        fresh = get_conn(db_path)
        try:
            res = call_action(
                PAYMENTS.add_payment, fresh,
                _AnyArgs(company_id=env["company_id"], payment_type="receive",
                         posting_date=DEPOSIT_DATE, party_type="customer", party_id=customer_id,
                         paid_from_account=env["ar_account_id"], paid_to_account=cash,
                         paid_amount=amt, reference_number=ref, reference_date=DEPOSIT_DATE))
            assert is_ok(res), res
        finally:
            try:
                fresh.close()
            except Exception:
                pass
    drafts = _payments_by_ref(conn, env["company_id"], event_id, status="draft")
    assert len(drafts) == 2
    pe_a, pe_b = drafts[0]["id"], drafts[1]["id"]
    cap = delegate_selling_in_process(conn, monkeypatch)
    before = snapshot_tables(conn)
    r = _receive(conn, db_path, event_id, customer_id, deposit_amount="500.00")
    assert is_error(r)
    assert r["message"] == "Catering event %s has more than one draft deposit payment (%s, %s); delete the extra ones through payments first" % (event_id, pe_a, pe_b)
    assert snapshot_tables(conn) == before
    assert cap["calls"] == []


def test_ledger_check_by_install_phase(conn, env, db_path, monkeypatch):
    from erpclaw_lib.db import get_connection as lib_get_connection
    from erpclaw_lib import authority_gate
    cash = _setup_cash(conn, env)
    customer_id = _add_customer(conn, env["company_id"])
    event_id = _make_event(conn, env)
    _confirm(conn, event_id)
    delegate_selling_in_process(conn, monkeypatch, connect=lib_get_connection)
    probe = lib_get_connection(db_path)
    try:
        assert authority_gate.install_phase(probe)[0] == "STAGED"
    finally:
        try:
            probe.close()
        except Exception:
            pass
    result = _receive(conn, db_path, event_id, customer_id, deposit_amount="500.00")
    assert is_ok(result), result

    event2 = _make_event(conn, env, name="Second Wedding")
    _confirm(conn, event2)
    customer2 = customer_id
    probe2 = lib_get_connection(db_path)
    try:
        try:
            n = probe2.execute("SELECT COUNT(*) FROM authority_install").fetchone()[0]
        except Exception:
            n = 0
        assert n == 1, "expected exactly one authority_install row, found %s" % n
    finally:
        try:
            probe2.close()
        except Exception:
            pass
    flipper = lib_get_connection(db_path)
    try:
        flipper.execute(
            Q.update(Table("authority_install")).set(Field("phase"), P()).get_sql(), ("ACTIVE",))
        flipper.commit()
    finally:
        try:
            flipper.close()
        except Exception:
            pass
    vconn = lib_get_connection(db_path)
    delegate_selling_in_process(vconn, monkeypatch, connect=lib_get_connection)
    try:
        refused = call_action(
            ACTIONS["food-receive-catering-deposit"], vconn,
            ns(event_id=event2, customer_id=customer2, deposit_amount="500.00",
               deposit_date=DEPOSIT_DATE, db_path=db_path))
    finally:
        try:
            vconn.close()
        except Exception:
            pass
    assert is_error(refused), refused
    assert "AUTHORITY_NOT_READY" in refused["message"]
    assert refused["message"].startswith("Deposit payment ")
    reader = lib_get_connection(db_path)
    try:
        pes = [dict(r) for r in reader.execute(
            Q.from_(Table("payment_entry")).select(Table("payment_entry").star).where(Field("reference_number") == P()).get_sql(),
            ("CATERING-DEPOSIT " + event2,)).fetchall()]
        assert len(pes) == 1
        pe2 = pes[0]["id"]
        assert pes[0]["status"] == "draft"
        assert reader.execute(
            Q.from_(Table("gl_entry")).select(Field("id")).where(Field("voucher_id") == P()).get_sql(),
            (pe2,)).fetchall() == []
        assert reader.execute(
            Q.from_(Table("payment_ledger_entry")).select(Field("id")).where(Field("voucher_id") == P()).get_sql(),
            (pe2,)).fetchall() == []
    finally:
        try:
            reader.close()
        except Exception:
            pass
    flipper = lib_get_connection(db_path)
    try:
        flipper.execute(
            Q.update(Table("authority_install")).set(Field("phase"), P()).get_sql(), ("STAGED",))
        flipper.commit()
    finally:
        try:
            flipper.close()
        except Exception:
            pass
    vconn2 = lib_get_connection(db_path)
    delegate_selling_in_process(vconn2, monkeypatch, connect=lib_get_connection)
    try:
        ok2 = call_action(
            ACTIONS["food-receive-catering-deposit"], vconn2,
            ns(event_id=event2, customer_id=customer2, deposit_amount="500.00",
               deposit_date=DEPOSIT_DATE, db_path=db_path))
    finally:
        try:
            vconn2.close()
        except Exception:
            pass
    assert is_ok(ok2), ok2
    assert ok2["resumed"] is True
    assert ok2["payment_entry_id"] == pe2


def test_deposit_is_a_confirmed_action(conn, env, db_path, monkeypatch):
    cash = _setup_cash(conn, env)
    customer_id = _add_customer(conn, env["company_id"])
    event_id = _make_event(conn, env)
    _confirm(conn, event_id)
    captured = delegate_selling_in_process(conn, monkeypatch)
    result = _receive(conn, db_path, event_id, customer_id, deposit_amount="500.00")
    assert is_ok(result), result
    router_path = os.path.join(SRC_DIR, "erpclaw", "scripts", "db_query.py")
    spec = importlib.util.spec_from_file_location("_food_dep_gate_router", router_path)
    router = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(router)
    assert "food-receive-catering-deposit" in router.DANGEROUS_ACTIONS
    submits = [c for c in captured["calls"] if c["action"] == "submit-payment"]
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
    with patch.object(sys, "argv", stripped), patch("sys.stdout", buf), pytest.raises(SystemExit) as exc:
        router._gate_dangerous_action(recorded["action"])
    assert exc.value.code == 2
    assert json.loads(buf.getvalue())["error"] == "user_confirmation_required"
