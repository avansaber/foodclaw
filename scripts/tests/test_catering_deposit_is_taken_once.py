"""A catering deposit is taken once.

Two operators (or one retried agent) must not take the client's money twice:
a call whose fresh draft is not the event's only draft, or no longer fits
under the cap as re-read after the draft was written, removes its own draft
through payments and refuses. An explicit ``--deposit-amount`` equal to a
deposit this customer already paid for the event is refused unless the caller
passes ``--further-deposit``.
"""
import argparse
import importlib.util
import json
import os
import sys
from decimal import Decimal

_TESTS_DIR = os.path.dirname(os.path.abspath(__file__))
if _TESTS_DIR not in sys.path:
    sys.path.insert(0, _TESTS_DIR)

from food_helpers import (  # noqa: E402
    call_action, ns, is_ok, is_error, load_db_query,
    seed_account, get_conn,
    delegate_selling_in_process,
)

from erpclaw_lib.query import Q, Table, P, line_order  # noqa: E402

_mod = load_db_query()
ACTIONS = _mod.ACTIONS

SCRIPTS_DIR = os.path.dirname(_TESTS_DIR)
SRC_DIR = os.path.dirname(os.path.dirname(SCRIPTS_DIR))


def _load_domain(domain):
    path = os.path.join(SRC_DIR, "erpclaw", "scripts", domain, "db_query.py")
    spec = importlib.util.spec_from_file_location("_food_once_%s" % domain.replace("-", "_"), path)
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
             deposit_date=DEPOSIT_DATE, cash_account_id=None,
             further_deposit=False, **extra):
    kw = dict(event_id=event_id, db_path=db_path)
    if customer_id is not None:
        kw["customer_id"] = customer_id
    if deposit_amount is not None:
        kw["deposit_amount"] = deposit_amount
    if deposit_date is not None:
        kw["deposit_date"] = deposit_date
    if cash_account_id is not None:
        kw["cash_account_id"] = cash_account_id
    if further_deposit:
        kw["further_deposit"] = True
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


def _delete_payment_audits(conn):
    t = Table("audit_log")
    return [dict(r) for r in conn.execute(
        Q.from_(t).select(t.star).where(t.action == P()).get_sql(),
        ("delete-payment",)).fetchall()]


def _all_rows(conn, table):
    t = Table(table)
    return [dict(r) for r in conn.execute(Q.from_(t).select(t.star).get_sql()).fetchall()]


def _balances(conn, account_id):
    t = Table("gl_entry")
    rows = conn.execute(
        Q.from_(t).select(t.debit, t.credit).where(t.account_id == P()).where(t.is_cancelled == P()).get_sql(),
        (account_id, 0)).fetchall()
    dr = sum((Decimal(str(dict(r)["debit"] or "0")) for r in rows), Decimal("0"))
    cr = sum((Decimal(str(dict(r)["credit"] or "0")) for r in rows), Decimal("0"))
    return dr, cr


def _pay_ns(**overrides):
    kw = dict(_PAY_DEFAULTS)
    kw.update(overrides)
    return argparse.Namespace(**kw)


def _add_competing_draft(db_path, company_id, customer_id, event_id,
                         receivable, cash, amount):
    fresh = get_conn(db_path)
    try:
        result = call_action(
            PAYMENTS.add_payment, fresh,
            _pay_ns(company_id=company_id, payment_type="receive",
                    posting_date=DEPOSIT_DATE, party_type="customer",
                    party_id=customer_id, paid_from_account=receivable,
                    paid_to_account=cash, paid_amount=amount,
                    reference_number="CATERING-DEPOSIT " + event_id,
                    reference_date=DEPOSIT_DATE))
    finally:
        try:
            fresh.close()
        except Exception:
            pass
    assert is_ok(result), result
    return result["payment_entry_id"]


def _submit_competitor(db_path, pe_id):
    fresh = get_conn(db_path)
    try:
        result = call_action(
            PAYMENTS.submit_payment, fresh,
            _pay_ns(payment_entry_id=pe_id))
    finally:
        try:
            fresh.close()
        except Exception:
            pass
    assert is_ok(result), result


def test_concurrent_draft_makes_the_later_call_step_back(conn, env, db_path, monkeypatch):
    cash = _setup_cash(conn, env)
    customer_id = _add_customer(conn, env["company_id"])
    event_id = _make_event(conn, env)
    _confirm(conn, event_id)
    holder = {}

    def after_add(path, own_id):
        holder["own"] = own_id
        holder["other"] = _add_competing_draft(
            path, env["company_id"], customer_id, event_id,
            env["ar_account_id"], cash, "500.00")

    captured = delegate_selling_in_process(conn, monkeypatch, after_add=after_add)
    refused = _receive(conn, db_path, event_id, customer_id, deposit_amount="500.00")
    assert is_error(refused), refused
    assert refused["message"] == (
        "Another deposit for catering event %s is being recorded "
        "(payment %s); try again once it has finished" % (event_id, holder["other"]))
    remaining = _payments_by_ref(conn, env["company_id"], event_id)
    assert len(remaining) == 1
    assert remaining[0]["id"] == holder["other"]
    assert remaining[0]["status"] == "draft"
    assert _all_rows(conn, "gl_entry") == []
    assert _all_rows(conn, "payment_ledger_entry") == []
    assert _audit_for_event(conn, event_id) == []
    deletes = _delete_payment_audits(conn)
    assert len(deletes) == 1
    assert holder["own"] in (deletes[0].get("entity_id") or "")
    assert len(_calls(captured, "delete-payment")) == 1


def test_concurrent_submitted_deposit_counts_against_the_cap(conn, env, db_path, monkeypatch):
    cash = _setup_cash(conn, env)
    customer_id = _add_customer(conn, env["company_id"])
    event_id = _make_event(conn, env)
    _confirm(conn, event_id)
    holder = {}

    def after_add(path, own_id):
        holder["own"] = own_id
        holder["other"] = _add_competing_draft(
            path, env["company_id"], customer_id, event_id,
            env["ar_account_id"], cash, "3000.00")
        _submit_competitor(path, holder["other"])

    captured = delegate_selling_in_process(conn, monkeypatch, after_add=after_add)
    refused = _receive(conn, db_path, event_id, customer_id, deposit_amount="500.00")
    assert is_error(refused), refused
    assert refused["message"] == (
        "Deposit 500.00 is more than the event's 3300.00 "
        "less deposits already received (3000.00)")
    remaining = _payments_by_ref(conn, env["company_id"], event_id)
    assert len(remaining) == 1
    assert remaining[0]["id"] == holder["other"]
    assert remaining[0]["status"] == "submitted"
    assert remaining[0]["paid_amount"] == "3000.00"
    assert _gl_for_payment(conn, holder["own"]) == []
    assert _ple_for_payment(conn, holder["own"]) == []
    legs = _gl_for_payment(conn, holder["other"])
    assert len(legs) == 2
    assert _balances(conn, cash) == (Decimal("3000.00"), Decimal("0"))
    assert _balances(conn, env["ar_account_id"]) == (Decimal("0"), Decimal("3000.00"))
    assert _audit_for_event(conn, event_id) == []
    assert len(_calls(captured, "delete-payment")) == 1


def test_explicit_retry_after_a_lost_reply_is_refused(conn, env, db_path, monkeypatch):
    cash = _setup_cash(conn, env)
    customer_id = _add_customer(conn, env["company_id"])
    event_id = _make_event(conn, env)
    _confirm(conn, event_id)
    delegate_selling_in_process(conn, monkeypatch)
    first = _receive(conn, db_path, event_id, customer_id, deposit_amount="500.00")
    assert is_ok(first), first
    first_pe = first["payment_entry_id"]
    before = snapshot_tables(conn)
    captured = delegate_selling_in_process(conn, monkeypatch)
    refused = _receive(conn, db_path, event_id, customer_id, deposit_amount="500.00")
    assert is_error(refused), refused
    assert refused["message"] == (
        "Catering event %s already has a deposit of 500.00 from customer %s "
        "(payment %s, posted 2026-10-01); if this is a further deposit, "
        "pass --further-deposit" % (event_id, customer_id, first_pe))
    assert snapshot_tables(conn) == before
    assert captured["calls"] == []


def test_further_deposit_flag_takes_a_second_deposit(conn, env, db_path, monkeypatch):
    cash = _setup_cash(conn, env)
    customer_id = _add_customer(conn, env["company_id"])
    event_id = _make_event(conn, env)
    _confirm(conn, event_id)
    delegate_selling_in_process(conn, monkeypatch)
    first = _receive(conn, db_path, event_id, customer_id, deposit_amount="500.00")
    assert is_ok(first), first
    delegate_selling_in_process(conn, monkeypatch)
    refused = _receive(conn, db_path, event_id, customer_id, deposit_amount="500.00")
    assert is_error(refused), refused
    delegate_selling_in_process(conn, monkeypatch)
    second = _receive(conn, db_path, event_id, customer_id, deposit_amount="500.00",
                      further_deposit=True)
    assert is_ok(second), second
    assert second["deposits_received"] == "1000.00"
    submitted = _payments_by_ref(conn, env["company_id"], event_id, status="submitted")
    assert len(submitted) == 2
    assert sorted(p["paid_amount"] for p in submitted) == ["500.00", "500.00"]
    audits = _audit_for_event(conn, event_id)
    assert len(audits) == 2
    by_payment = {}
    for audit_row in audits:
        new_values = json.loads(audit_row["new_values"])
        by_payment[new_values["payment_entry_id"]] = new_values
    assert "further_deposit" not in by_payment[first["payment_entry_id"]]
    assert by_payment[second["payment_entry_id"]]["further_deposit"] is True


def test_further_deposit_still_respects_the_cap(conn, env, db_path, monkeypatch):
    cash = _setup_cash(conn, env)
    customer_id = _add_customer(conn, env["company_id"])
    event_id = _make_event(conn, env)
    _confirm(conn, event_id)
    delegate_selling_in_process(conn, monkeypatch)
    first = _receive(conn, db_path, event_id, customer_id, deposit_amount="3000.00")
    assert is_ok(first), first
    before = snapshot_tables(conn)
    captured = delegate_selling_in_process(conn, monkeypatch)
    refused = _receive(conn, db_path, event_id, customer_id, deposit_amount="3000.00",
                       further_deposit=True)
    assert is_error(refused), refused
    assert refused["message"] == (
        "Deposit 3000.00 is more than the event's 3300.00 "
        "less deposits already received (3000.00)")
    assert snapshot_tables(conn) == before
    assert captured["calls"] == []


def test_different_explicit_amount_is_not_a_duplicate(conn, env, db_path, monkeypatch):
    cash = _setup_cash(conn, env)
    customer_id = _add_customer(conn, env["company_id"])
    event_id = _make_event(conn, env)
    _confirm(conn, event_id)
    delegate_selling_in_process(conn, monkeypatch)
    first = _receive(conn, db_path, event_id, customer_id, deposit_amount="500.00")
    assert is_ok(first), first
    delegate_selling_in_process(conn, monkeypatch)
    second = _receive(conn, db_path, event_id, customer_id, deposit_amount="300.00")
    assert is_ok(second), second
    assert second["deposits_received"] == "800.00"


def test_failed_draft_removal_is_reported(conn, env, db_path, monkeypatch):
    cash = _setup_cash(conn, env)
    customer_id = _add_customer(conn, env["company_id"])
    event_id = _make_event(conn, env)
    _confirm(conn, event_id)
    holder = {}

    def after_add(path, own_id):
        holder["own"] = own_id
        holder["other"] = _add_competing_draft(
            path, env["company_id"], customer_id, event_id,
            env["ar_account_id"], cash, "500.00")

    captured = delegate_selling_in_process(
        conn, monkeypatch, delete_behaviour="fail", after_add=after_add)
    refused = _receive(conn, db_path, event_id, customer_id, deposit_amount="500.00")
    assert is_error(refused), refused
    drafts = _payments_by_ref(conn, env["company_id"], event_id, status="draft")
    assert len(drafts) == 2
    own = [d for d in drafts if d["id"] != holder["other"]]
    assert len(own) == 1
    assert own[0]["id"] == holder["own"]
    assert refused["message"] == (
        "Deposit payment %s for catering event %s was not submitted and "
        "could not be removed: simulated delete failure; delete it through "
        "payments" % (holder["own"], event_id))
    assert _all_rows(conn, "gl_entry") == []
    assert _all_rows(conn, "payment_ledger_entry") == []
    assert len(_calls(captured, "delete-payment")) == 1


def test_single_caller_is_unchanged(conn, env, db_path, monkeypatch):
    cash = _setup_cash(conn, env)
    customer_id = _add_customer(conn, env["company_id"])
    event_id = _make_event(conn, env)
    _confirm(conn, event_id)
    captured = delegate_selling_in_process(conn, monkeypatch)
    result = _receive(conn, db_path, event_id, customer_id, deposit_amount="500.00")
    assert is_ok(result), result
    submitted = _payments_by_ref(conn, env["company_id"], event_id, status="submitted")
    assert len(submitted) == 1
    assert submitted[0]["id"] == result["payment_entry_id"]
    assert _calls(captured, "delete-payment") == []
    audits = _audit_for_event(conn, event_id)
    assert len(audits) == 1
    assert json.loads(audits[0]["new_values"]) == {
        "payment_entry_id": result["payment_entry_id"],
        "customer_id": customer_id,
        "amount": "500.00",
    }


def test_own_draft_submitted_by_another_caller_is_a_success(conn, env, db_path, monkeypatch):
    cash = _setup_cash(conn, env)
    customer_id = _add_customer(conn, env["company_id"])
    event_id = _make_event(conn, env, quoted="500.00", deposit="500.00")
    _confirm(conn, event_id)

    def after_add(path, own_id):
        _submit_competitor(path, own_id)

    captured = delegate_selling_in_process(conn, monkeypatch, after_add=after_add)
    result = _receive(conn, db_path, event_id, customer_id, deposit_amount="500.00")
    assert is_ok(result), result
    assert result["deposits_received"] == "500.00"
    submitted = _payments_by_ref(conn, env["company_id"], event_id, status="submitted")
    assert len(submitted) == 1
    assert submitted[0]["paid_amount"] == "500.00"
    assert _calls(captured, "delete-payment") == []
    assert len(_audit_for_event(conn, event_id)) == 1


def test_draft_submitted_by_another_call_while_stepping_back_is_reported(
        conn, env, db_path, monkeypatch):
    cash = _setup_cash(conn, env)
    customer_id = _add_customer(conn, env["company_id"])
    event_id = _make_event(conn, env)
    _confirm(conn, event_id)
    holder = {}

    def after_add(path, own_id):
        holder["own"] = own_id
        holder["other"] = _add_competing_draft(
            path, env["company_id"], customer_id, event_id,
            env["ar_account_id"], cash, "500.00")

    captured = delegate_selling_in_process(
        conn, monkeypatch, delete_behaviour="submit_then_fail", after_add=after_add)
    refused = _receive(conn, db_path, event_id, customer_id, deposit_amount="500.00")
    assert is_error(refused), refused
    assert refused["message"] == (
        "Deposit payment %s for catering event %s was submitted by another "
        "call while this one stepped back; check the event's deposits before "
        "receiving again" % (holder["own"], event_id))
    assert _row(conn, "payment_entry", holder["own"])["status"] == "submitted"
    assert _audit_for_event(conn, event_id) == []
    assert len(_calls(captured, "delete-payment")) == 1
