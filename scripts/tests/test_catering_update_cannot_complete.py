"""Updating a catering event cannot complete it; completed events are frozen.

`food-update-catering-event --event-status completed` is refused (complete
only through `food-complete-catering-event`, which bills), and on a completed
event the billed money/account fields plus `event_status` are frozen while
descriptive fields stay editable.
"""
import importlib.util
import os
import sys

import pytest

_TESTS_DIR = os.path.dirname(os.path.abspath(__file__))
if _TESTS_DIR not in sys.path:
    sys.path.insert(0, _TESTS_DIR)

from food_helpers import (  # noqa: E402
    call_action, ns, is_ok, is_error, load_db_query,
    delegate_selling_in_process,
)

from erpclaw_lib.query import Q, Table, Field, P  # noqa: E402

_mod = load_db_query()
ACTIONS = _mod.ACTIONS

SCRIPTS_DIR = os.path.dirname(_TESTS_DIR)
SRC_DIR = os.path.dirname(os.path.dirname(SCRIPTS_DIR))

EVENT_DATE = "2026-11-01"
QUOTED = "1500.00"

FROZEN_FIELDS = (
    "estimated_cost",
    "quoted_price",
    "deposit_amount",
    "final_amount",
    "revenue_account_id",
    "receivable_account_id",
    "cost_center_id",
    "event_status",
)


def _load_selling():
    path = os.path.join(SRC_DIR, "erpclaw", "scripts", "erpclaw-selling", "db_query.py")
    spec = importlib.util.spec_from_file_location("_food_complete_selling", path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


SELLING = _load_selling()


class _AnyArgs:
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


def _make_event(conn, env, quoted=QUOTED):
    result = call_action(
        ACTIONS["food-add-catering-event"], conn,
        ns(company_id=env["company_id"], event_name="Gala Dinner",
           client_name="Acme Inc", event_date=EVENT_DATE, quoted_price=quoted),
    )
    assert is_ok(result), result
    return result["id"]


def _confirm(conn, event_id):
    result = call_action(
        ACTIONS["food-confirm-event"], conn, ns(event_id=event_id))
    assert is_ok(result), result


def _complete(conn, db_path, event_id, customer_id):
    return call_action(
        ACTIONS["food-complete-catering-event"], conn,
        ns(event_id=event_id, customer_id=customer_id, db_path=db_path))


def _complete_event(conn, env, db_path, monkeypatch):
    customer_id = _add_customer(conn, env["company_id"])
    event_id = _make_event(conn, env)
    _confirm(conn, event_id)
    delegate_selling_in_process(conn, monkeypatch)
    result = _complete(conn, db_path, event_id, customer_id)
    assert is_ok(result), result
    assert result["event_status"] == "completed"
    return event_id


def _event(conn, event_id):
    t = Table("foodclaw_catering_event")
    row = conn.execute(
        Q.from_(t).select(t.star).where(t.id == P()).get_sql(),
        (event_id,)).fetchone()
    return dict(row)


def _audit_count(conn):
    t = Table("audit_log")
    return len(conn.execute(Q.from_(t).select(Field("id")).get_sql()).fetchall())


def _frozen_value(field, env):
    if field == "event_status":
        return "cancelled"
    if field in ("revenue_account_id", "receivable_account_id", "cost_center_id"):
        return "frozen-acct-" + field
    return "7777.00"


def test_update_to_completed_is_refused(conn, env):
    event_id = _make_event(conn, env)
    _confirm(conn, event_id)
    before = _event(conn, event_id)
    audits = _audit_count(conn)
    result = call_action(
        ACTIONS["food-update-catering-event"], conn,
        ns(event_id=event_id, event_status="completed"),
    )
    assert is_error(result), result
    assert "food-complete-catering-event" in result["message"]
    after = _event(conn, event_id)
    assert after["event_status"] == before["event_status"]
    assert after["final_amount"] == before["final_amount"]
    assert after["updated_at"] == before["updated_at"]
    assert _audit_count(conn) == audits


@pytest.mark.parametrize("field", list(FROZEN_FIELDS))
def test_completed_event_frozen_fields_refused(conn, env, db_path, monkeypatch, field):
    event_id = _complete_event(conn, env, db_path, monkeypatch)
    before = _event(conn, event_id)
    assert before["event_status"] == "completed"
    audits = _audit_count(conn)
    result = call_action(
        ACTIONS["food-update-catering-event"], conn,
        ns(event_id=event_id, **{field: _frozen_value(field, env)}),
    )
    assert is_error(result), result
    assert field in result["message"]
    after = _event(conn, event_id)
    assert after["event_status"] == "completed"
    assert after["final_amount"] == before["final_amount"]
    assert after["updated_at"] == before["updated_at"]
    assert _audit_count(conn) == audits


def test_completed_event_still_accepts_descriptive_edits(conn, env, db_path, monkeypatch):
    event_id = _complete_event(conn, env, db_path, monkeypatch)
    result = call_action(
        ACTIONS["food-update-catering-event"], conn,
        ns(event_id=event_id, notes="Gate code 4321"),
    )
    assert is_ok(result), result
    assert _event(conn, event_id)["notes"] == "Gate code 4321"
    result = call_action(
        ACTIONS["food-update-catering-event"], conn,
        ns(event_id=event_id, venue="Grand Hall"),
    )
    assert is_ok(result), result
    assert _event(conn, event_id)["venue"] == "Grand Hall"


def test_quoted_event_can_move_to_in_progress(conn, env):
    event_id = _make_event(conn, env)
    moved = call_action(
        ACTIONS["food-update-catering-event"], conn,
        ns(event_id=event_id, event_status="quoted"),
    )
    assert is_ok(moved), moved
    moved = call_action(
        ACTIONS["food-update-catering-event"], conn,
        ns(event_id=event_id, event_status="in_progress"),
    )
    assert is_ok(moved), moved
    assert _event(conn, event_id)["event_status"] == "in_progress"


def test_list_completed_filter_still_works(conn, env, db_path, monkeypatch):
    event_id = _complete_event(conn, env, db_path, monkeypatch)
    result = call_action(
        ACTIONS["food-list-catering-events"], conn,
        ns(company_id=env["company_id"], event_status="completed"),
    )
    assert is_ok(result), result
    assert event_id in [item["id"] for item in result["items"]]
