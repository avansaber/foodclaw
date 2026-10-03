"""Completing a catering event applies its deposits to the invoice.

Completion bills the event through a submitted sales invoice and then applies
each received deposit (``CATERING-DEPOSIT <event id>``) to that invoice through
the payments module's ``allocate-payment``, so the invoice chases only what the
client still owes. A remainder stays an open customer advance.
"""
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
    seed_account, seed_company, seed_naming_series, get_conn,
    delegate_selling_in_process,
)

from erpclaw_lib.query import Q, Table, Field, P, line_order  # noqa: E402

_mod = load_db_query()
ACTIONS = _mod.ACTIONS

SCRIPTS_DIR = os.path.dirname(_TESTS_DIR)
SRC_DIR = os.path.dirname(os.path.dirname(SCRIPTS_DIR))


def _load_domain(domain):
    path = os.path.join(SRC_DIR, "erpclaw", "scripts", domain, "db_query.py")
    spec = importlib.util.spec_from_file_location(
        "_food_net_%s" % domain.replace("-", "_"), path)
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
    "foodclaw_catering_invoice",
    "payment_entry",
    "payment_allocation",
    "sales_invoice",
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


def _update(conn, event_id, **kw):
    return call_action(
        ACTIONS["food-update-catering-event"], conn,
        ns(event_id=event_id, **kw))


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


def _link_for_event(conn, event_id):
    t = Table("foodclaw_catering_invoice")
    row = conn.execute(
        Q.from_(t).select(t.star).where(t.event_id == P()).get_sql(),
        (event_id,)).fetchone()
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


def _allocations_for_payment(conn, pe_id):
    t = Table("payment_allocation")
    return [dict(r) for r in conn.execute(
        Q.from_(t).select(t.star).where(t.payment_entry_id == P()).get_sql(),
        (pe_id,)).fetchall()]


def _all_allocations(conn):
    t = Table("payment_allocation")
    return [dict(r) for r in conn.execute(
        Q.from_(t).select(t.star).get_sql()).fetchall()]


def _gl_sums(conn, account_id):
    t = Table("gl_entry")
    rows = conn.execute(
        Q.from_(t).select(t.debit, t.credit).where(t.account_id == P()).where(t.is_cancelled == P()).get_sql(),
        (account_id, 0)).fetchall()
    dr = sum((Decimal(str(dict(r)["debit"] or "0")) for r in rows), Decimal("0"))
    cr = sum((Decimal(str(dict(r)["credit"] or "0")) for r in rows), Decimal("0"))
    return dr, cr


def _ple_balance(conn, customer_id):
    from erpclaw_lib.party_ledger import LIVE_ROW_SQL
    rows = conn.execute(
        "SELECT amount FROM payment_ledger_entry WHERE party_type = ? "
        "AND party_id = ? AND " + LIVE_ROW_SQL,
        ("customer", customer_id)).fetchall()
    return sum((Decimal(str(dict(r)["amount"])) for r in rows), Decimal("0"))


def _completion_audits(conn, event_id):
    t = Table("audit_log")
    return [dict(r) for r in conn.execute(
        Q.from_(t).select(t.star).where(t.action == P()).where(t.entity_type == P()).where(t.entity_id == P()).get_sql(),
        ("food-complete-catering-event", "foodclaw_catering_event", event_id)).fetchall()]


def _set_default_receivable(conn, company_id, account_id):
    t = Table("company")
    conn.execute(
        Q.update(t).set("default_receivable_account_id", P()).where(t.id == P()).get_sql(),
        (account_id, company_id))
    conn.commit()


def test_completion_nets_the_deposit(conn, env, db_path, monkeypatch):
    cash = _setup_cash(conn, env)
    customer_id = _add_customer(conn, env["company_id"])
    event_id = _make_event(conn, env)
    _confirm(conn, event_id)
    captured = delegate_selling_in_process(conn, monkeypatch)
    rec = _receive(conn, db_path, event_id, customer_id, deposit_amount="500.00")
    assert is_ok(rec), rec
    pe_id = rec["payment_entry_id"]
    result = _complete(conn, db_path, event_id, customer_id)
    assert is_ok(result), result
    si_id = result["sales_invoice_id"]
    assert result["resumed"] is False

    allocs = _allocations_for_payment(conn, pe_id)
    assert len(allocs) == 1
    assert allocs[0]["voucher_id"] == si_id
    assert allocs[0]["allocated_amount"] == "500.00"

    si = _row(conn, "sales_invoice", si_id)
    assert si["grand_total"] == "3300.00"
    assert si["outstanding_amount"] == "2800.00"
    assert si["status"] == "partially_paid"

    assert _row(conn, "payment_entry", pe_id)["unallocated_amount"] == "0.00"

    dr, cr = _gl_sums(conn, env["ar_account_id"])
    assert (dr, cr) == (Decimal("3300.00"), Decimal("500.00"))
    assert dr - cr == Decimal("2800.00")
    dr, cr = _gl_sums(conn, cash)
    assert (dr, cr) == (Decimal("500.00"), Decimal("0"))
    dr, cr = _gl_sums(conn, env["revenue_account_id"])
    assert (dr, cr) == (Decimal("0"), Decimal("3300.00"))

    assert _ple_balance(conn, customer_id) == Decimal("2800.00")

    assert result["deposits_applied"] == [
        {"payment_entry_id": pe_id, "allocated_amount": "500.00"}]
    assert result["outstanding_amount"] == "2800.00"
    assert result["deposit_unapplied"] == "0.00"

    assert _event(conn, event_id)["event_status"] == "completed"

    audits = _completion_audits(conn, event_id)
    assert len(audits) == 1
    new_values = json.loads(audits[0]["new_values"])
    assert new_values["event_status"] == "completed"
    assert new_values["final_amount"] == "3300.00"
    assert new_values["sales_invoice_id"] == si_id
    assert new_values["deposits_applied"] == [
        {"payment_entry_id": pe_id, "allocated_amount": "500.00"}]
    assert new_values["deposit_unapplied"] == "0.00"
    assert _calls(captured, "allocate-payment")


def test_completion_nets_a_deposit_recorded_through_payments(conn, env, db_path, monkeypatch):
    cash = _setup_cash(conn, env)
    customer_id = _add_customer(conn, env["company_id"])
    event_id = _make_event(conn, env)
    _confirm(conn, event_id)
    captured = delegate_selling_in_process(conn, monkeypatch)
    ref = "CATERING-DEPOSIT " + event_id
    fresh = get_conn(db_path)
    try:
        made = call_action(
            PAYMENTS.add_payment, fresh,
            _AnyArgs(company_id=env["company_id"], payment_type="receive",
                     posting_date=DEPOSIT_DATE, party_type="customer", party_id=customer_id,
                     paid_from_account=env["ar_account_id"], paid_to_account=cash,
                     paid_amount="500.00", reference_number=ref, reference_date=DEPOSIT_DATE))
        assert is_ok(made), made
        pe_id = made["payment_entry_id"]
    finally:
        try:
            fresh.close()
        except Exception:
            pass
    fresh2 = get_conn(db_path)
    try:
        sub = call_action(
            PAYMENTS.submit_payment, fresh2,
            _AnyArgs(payment_entry_id=pe_id))
        assert is_ok(sub), sub
    finally:
        try:
            fresh2.close()
        except Exception:
            pass
    result = _complete(conn, db_path, event_id, customer_id)
    assert is_ok(result), result
    si_id = result["sales_invoice_id"]
    si = _row(conn, "sales_invoice", si_id)
    assert si["outstanding_amount"] == "2800.00"
    allocs = _allocations_for_payment(conn, pe_id)
    assert len(allocs) == 1
    assert allocs[0]["allocated_amount"] == "500.00"
    assert si["grand_total"] == "3300.00"
    assert si["status"] == "partially_paid"
    assert _row(conn, "payment_entry", pe_id)["unallocated_amount"] == "0.00"
    assert result["deposits_applied"] == [
        {"payment_entry_id": pe_id, "allocated_amount": "500.00"}]
    assert result["outstanding_amount"] == "2800.00"
    assert result["deposit_unapplied"] == "0.00"
    assert _event(conn, event_id)["event_status"] == "completed"


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
    delegate_selling_in_process(conn, monkeypatch)
    rec = _receive(conn, db_path, event_id, customer_id, deposit_amount="500.00")
    assert is_ok(rec), rec
    result = _complete(conn, db_path, event_id, customer_id)
    assert is_ok(result), result
    dr, cr = _gl_sums(conn, adv)
    assert dr - cr == Decimal("0.00")
    assert (dr, cr) == (Decimal("500.00"), Decimal("500.00"))
    dr, cr = _gl_sums(conn, env["ar_account_id"])
    assert dr - cr == Decimal("2800.00")
    dr, cr = _gl_sums(conn, cash)
    assert (dr, cr) == (Decimal("500.00"), Decimal("0"))


def test_completion_refusals_write_nothing(conn, env, db_path, monkeypatch):
    cash = _setup_cash(conn, env)
    customer_id = _add_customer(conn, env["company_id"])
    other_id = _add_customer(conn, env["company_id"], "Second Party")

    event_id = _make_event(conn, env)
    _confirm(conn, event_id)
    cap = delegate_selling_in_process(conn, monkeypatch)
    rec = _receive(conn, db_path, event_id, customer_id, deposit_amount="500.00")
    assert is_ok(rec), rec
    pe_id = rec["payment_entry_id"]
    cap2 = delegate_selling_in_process(conn, monkeypatch)
    before = snapshot_tables(conn)
    r = _complete(conn, db_path, event_id, other_id)
    assert is_error(r), r
    assert r["message"] == (
        "Catering event %s has a deposit from customer %s (payment %s); "
        "complete it for that customer" % (event_id, customer_id, pe_id))
    assert snapshot_tables(conn) == before
    assert cap2["calls"] == []

    event_b = _make_event(conn, env, name="Second Wedding")
    _confirm(conn, event_b)
    cap3 = delegate_selling_in_process(conn, monkeypatch, payment_behaviour="fail")
    refused = _receive(conn, db_path, event_b, customer_id, deposit_amount="500.00")
    assert is_error(refused), refused
    drafts = _payments_by_ref(conn, env["company_id"], event_b, status="draft")
    assert len(drafts) == 1
    draft_id = drafts[0]["id"]
    cap4 = delegate_selling_in_process(conn, monkeypatch)
    before = snapshot_tables(conn)
    r = _complete(conn, db_path, event_b, customer_id)
    assert is_error(r), r
    assert r["message"] == (
        "Catering event %s has an unfinished deposit payment %s; receive the "
        "deposit again to finish it, or delete it through payments, before "
        "completing" % (event_b, draft_id))
    assert snapshot_tables(conn) == before
    assert cap4["calls"] == []

    event_c = _make_event(conn, env, name="Third Wedding")
    _confirm(conn, event_c)
    cap5 = delegate_selling_in_process(conn, monkeypatch)
    rec_c = _receive(conn, db_path, event_c, customer_id, deposit_amount="500.00")
    assert is_ok(rec_c), rec_c
    pe_c = rec_c["payment_entry_id"]
    second_ar = seed_account(conn, env["company_id"], "Receivable 2", "asset", "receivable", "1150")
    _set_default_receivable(conn, env["company_id"], second_ar)
    cap6 = delegate_selling_in_process(conn, monkeypatch)
    before = snapshot_tables(conn)
    r = _complete(conn, db_path, event_c, customer_id)
    assert is_error(r), r
    assert r["message"] == (
        "Deposit %s was received to receivable %s, but the invoice for catering "
        "event %s posts to %s; apply it through payments"
        % (pe_c, env["ar_account_id"], event_c, second_ar))
    assert snapshot_tables(conn) == before
    assert cap6["calls"] == []
    _set_default_receivable(conn, env["company_id"], env["ar_account_id"])


def test_deposit_larger_than_the_bill_stays_an_advance(conn, env, db_path, monkeypatch):
    cash = _setup_cash(conn, env)
    customer_id = _add_customer(conn, env["company_id"])
    event_id = _make_event(conn, env)
    _confirm(conn, event_id)
    delegate_selling_in_process(conn, monkeypatch)
    rec = _receive(conn, db_path, event_id, customer_id, deposit_amount="500.00")
    assert is_ok(rec), rec
    pe_id = rec["payment_entry_id"]
    result = _complete(conn, db_path, event_id, customer_id, final_amount="400.00")
    assert is_ok(result), result
    si_id = result["sales_invoice_id"]
    allocs = _allocations_for_payment(conn, pe_id)
    assert len(allocs) == 1
    assert allocs[0]["allocated_amount"] == "400.00"
    si = _row(conn, "sales_invoice", si_id)
    assert si["outstanding_amount"] == "0"
    assert si["status"] == "paid"
    assert _row(conn, "payment_entry", pe_id)["unallocated_amount"] == "100.00"
    assert result["deposit_unapplied"] == "100.00"
    assert result["outstanding_amount"] == "0"
    before = snapshot_tables(conn)
    r = _update(conn, event_id, event_status="cancelled")
    assert is_error(r), r
    assert r["message"] == (
        "Catering event %s has an unapplied deposit of 100.00 (payment %s); "
        "apply it to an invoice through payments, or cancel the payment with "
        "cancel-payment if the money was returned, before cancelling"
        % (event_id, pe_id))
    assert snapshot_tables(conn) == before


def test_failed_allocation_is_finished_by_completing_again(conn, env, db_path, monkeypatch):
    cash = _setup_cash(conn, env)
    customer_id = _add_customer(conn, env["company_id"])
    event_id = _make_event(conn, env)
    _confirm(conn, event_id)
    captured = delegate_selling_in_process(conn, monkeypatch, allocate_behaviour="fail_once")
    rec = _receive(conn, db_path, event_id, customer_id, deposit_amount="500.00")
    assert is_ok(rec), rec
    pe_id = rec["payment_entry_id"]
    refused = _complete(conn, db_path, event_id, customer_id)
    assert is_error(refused), refused
    link = _link_for_event(conn, event_id)
    assert link is not None
    si_id = link["sales_invoice_id"]
    assert refused["message"] == (
        "Deposit %s could not be applied to sales invoice %s for catering event "
        "%s: simulated allocation failure; complete the event again to finish"
        % (pe_id, si_id, event_id))
    si = _row(conn, "sales_invoice", si_id)
    assert si["status"] == "submitted"
    assert si["outstanding_amount"] == "3300.00"
    assert _event(conn, event_id)["event_status"] == "confirmed"
    assert _all_allocations(conn) == []
    result = _complete(conn, db_path, event_id, customer_id)
    assert is_ok(result), result
    assert result["resumed"] is True
    assert result["sales_invoice_id"] == si_id
    allocs = _allocations_for_payment(conn, pe_id)
    assert len(allocs) == 1
    assert allocs[0]["allocated_amount"] == "500.00"
    assert _row(conn, "sales_invoice", si_id)["outstanding_amount"] == "2800.00"
    assert len(_calls(captured, "create-sales-invoice")) == 1


def test_cancelling_an_event_with_a_deposit_is_refused(conn, env, db_path, monkeypatch):
    cash = _setup_cash(conn, env)
    customer_id = _add_customer(conn, env["company_id"])
    event_id = _make_event(conn, env)
    _confirm(conn, event_id)
    delegate_selling_in_process(conn, monkeypatch)
    rec = _receive(conn, db_path, event_id, customer_id, deposit_amount="500.00")
    assert is_ok(rec), rec
    pe_id = rec["payment_entry_id"]
    before = snapshot_tables(conn)
    r = _update(conn, event_id, event_status="cancelled")
    assert is_error(r), r
    assert r["message"] == (
        "Catering event %s has an unapplied deposit of 500.00 (payment %s); "
        "apply it to an invoice through payments, or cancel the payment with "
        "cancel-payment if the money was returned, before cancelling"
        % (event_id, pe_id))
    assert snapshot_tables(conn) == before
    result = _complete(conn, db_path, event_id, customer_id)
    assert is_ok(result), result
    before = snapshot_tables(conn)
    r = _update(conn, event_id, event_status="cancelled")
    assert is_error(r), r
    assert r["message"] == (
        "Cannot change event_status on a completed event: a completed event is "
        "billed and its amounts and accounts cannot change")
    assert snapshot_tables(conn) == before


def test_resume_path_receivable_mismatch_is_refused(conn, env, db_path, monkeypatch):
    cash = _setup_cash(conn, env)
    customer_id = _add_customer(conn, env["company_id"])
    event_id = _make_event(conn, env)
    _confirm(conn, event_id)
    captured = delegate_selling_in_process(conn, monkeypatch, allocate_behaviour="fail_once")
    rec = _receive(conn, db_path, event_id, customer_id, deposit_amount="500.00")
    assert is_ok(rec), rec
    first_pe = rec["payment_entry_id"]
    refused = _complete(conn, db_path, event_id, customer_id)
    assert is_error(refused), refused
    link = _link_for_event(conn, event_id)
    assert link is not None
    si_id = link["sales_invoice_id"]
    assert _row(conn, "sales_invoice", si_id)["status"] == "submitted"
    assert _row(conn, "payment_entry", first_pe)["unallocated_amount"] == "500.00"
    second_ar = seed_account(conn, env["company_id"], "Receivable 2", "asset", "receivable", "1150")
    _set_default_receivable(conn, env["company_id"], second_ar)
    cap2 = delegate_selling_in_process(conn, monkeypatch)
    rec2 = _receive(conn, db_path, event_id, customer_id, deposit_amount="300.00")
    assert is_ok(rec2), rec2
    second_pe = rec2["payment_entry_id"]
    assert _row(conn, "payment_entry", second_pe)["paid_from_account"] == second_ar
    cap3 = delegate_selling_in_process(conn, monkeypatch)
    before = snapshot_tables(conn)
    r = _complete(conn, db_path, event_id, customer_id)
    assert is_error(r), r
    assert r["message"] == (
        "Deposit %s was received to receivable %s, but the invoice for catering "
        "event %s posts to %s; apply it through payments"
        % (second_pe, second_ar, event_id, env["ar_account_id"]))
    assert snapshot_tables(conn) == before
    assert cap3["calls"] == []
    _set_default_receivable(conn, env["company_id"], env["ar_account_id"])


def test_two_deposits_apply_in_date_order(conn, env, db_path, monkeypatch):
    cash = _setup_cash(conn, env)
    customer_id = _add_customer(conn, env["company_id"])
    event_id = _make_event(conn, env)
    _confirm(conn, event_id)
    delegate_selling_in_process(conn, monkeypatch)
    rec1 = _receive(conn, db_path, event_id, customer_id, deposit_amount="500.00",
                    deposit_date="2026-10-01")
    assert is_ok(rec1), rec1
    rec2 = _receive(conn, db_path, event_id, customer_id, deposit_amount="200.00",
                    deposit_date="2026-09-30")
    assert is_ok(rec2), rec2
    result = _complete(conn, db_path, event_id, customer_id, final_amount="600.00")
    assert is_ok(result), result
    assert result["deposits_applied"] == [
        {"payment_entry_id": rec2["payment_entry_id"], "allocated_amount": "200.00"},
        {"payment_entry_id": rec1["payment_entry_id"], "allocated_amount": "400.00"},
    ]
    assert _row(conn, "payment_entry", rec1["payment_entry_id"])["unallocated_amount"] == "100.00"
    assert _row(conn, "payment_entry", rec2["payment_entry_id"])["unallocated_amount"] == "0.00"
    assert result["deposit_unapplied"] == "100.00"
    si = _row(conn, "sales_invoice", result["sales_invoice_id"])
    assert si["outstanding_amount"] == "0"
    assert si["status"] == "paid"


def test_resume_with_a_draft_invoice_uses_the_company_receivable(conn, env, db_path, monkeypatch):
    cash = _setup_cash(conn, env)
    customer_id = _add_customer(conn, env["company_id"])
    event_id = _make_event(conn, env)
    _confirm(conn, event_id)
    delegate_selling_in_process(conn, monkeypatch, submit_behaviour="fail")
    refused = _complete(conn, db_path, event_id, customer_id)
    assert is_error(refused), refused
    link = _link_for_event(conn, event_id)
    assert link is not None
    si_id = link["sales_invoice_id"]
    assert _row(conn, "sales_invoice", si_id)["status"] == "draft"
    ple = Table("payment_ledger_entry")
    assert conn.execute(
        Q.from_(ple).select(ple.id).where(ple.voucher_type == P()).where(ple.voucher_id == P()).get_sql(),
        ("sales_invoice", si_id)).fetchall() == []
    assert _event(conn, event_id)["event_status"] == "confirmed"
    delegate_selling_in_process(conn, monkeypatch)
    second_ar = seed_account(conn, env["company_id"], "Receivable 2", "asset", "receivable", "1150")
    _set_default_receivable(conn, env["company_id"], second_ar)
    rec = _receive(conn, db_path, event_id, customer_id, deposit_amount="500.00")
    assert is_ok(rec), rec
    pe_id = rec["payment_entry_id"]
    assert _row(conn, "payment_entry", pe_id)["paid_from_account"] == second_ar
    result = _complete(conn, db_path, event_id, customer_id)
    assert is_ok(result), result
    assert result["resumed"] is True
    assert result["sales_invoice_id"] == si_id
    rows = conn.execute(
        Q.from_(ple).select(ple.account_id).where(ple.voucher_type == P()).where(ple.voucher_id == P()).get_sql(),
        ("sales_invoice", si_id)).fetchall()
    assert [dict(r)["account_id"] for r in rows] == [second_ar]
    allocs = _allocations_for_payment(conn, pe_id)
    assert len(allocs) == 1
    assert allocs[0]["allocated_amount"] == "500.00"
    assert _row(conn, "sales_invoice", si_id)["outstanding_amount"] == "2800.00"
    _set_default_receivable(conn, env["company_id"], env["ar_account_id"])
