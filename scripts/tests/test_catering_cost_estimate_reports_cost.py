"""M740: catering cost estimate reports cost under its true name."""
import os
import sys

_TESTS_DIR = os.path.dirname(os.path.abspath(__file__))
if _TESTS_DIR not in sys.path:
    sys.path.insert(0, _TESTS_DIR)

from food_helpers import call_action, ns, is_ok, load_db_query

_mod = load_db_query()
ACTIONS = _mod.ACTIONS


def _snapshot(conn):
    out = {}
    for table in ("foodclaw_catering_event", "foodclaw_catering_item", "foodclaw_menu_item", "gl_entry"):
        try:
            rows = conn.execute(f"SELECT * FROM {table} ORDER BY rowid").fetchall()
            out[table] = [tuple(r) for r in rows]
        except Exception:
            out[table] = None
    return out


def test_event_estimate_is_the_cost(conn, env):
    add = call_action(ACTIONS["food-add-catering-event"], conn,
                      ns(company_id=env["company_id"],
                         event_name="Margin Event", client_name="C",
                         event_date="2026-12-01", guest_count=80,
                         estimated_cost="2900.00"))
    assert is_ok(add)
    call_action(ACTIONS["food-add-catering-item"], conn,
                ns(event_id=add["id"], item_name="Buffet",
                   quantity=1, unit_price="3600.00"))
    call_action(ACTIONS["food-add-catering-item"], conn,
                ns(event_id=add["id"], item_name="Bar",
                   quantity=1, unit_price="1200.00"))
    result = call_action(ACTIONS["food-catering-cost-estimate"], conn,
                         ns(event_id=add["id"]))
    assert is_ok(result), result
    assert result["total_cost"] == "2900.00"
    assert result["cost_source"] == "event_estimate"
    assert result["cost_per_guest"] == "36.25"
    assert result["total_price"] == "4800.00"
    assert result["price_per_guest"] == "60.00"
    assert result["estimated_margin"] == "1900.00"


def test_menu_cost_when_no_estimate(conn, env):
    add = call_action(ACTIONS["food-add-catering-event"], conn,
                      ns(company_id=env["company_id"],
                         event_name="Menu Cost", client_name="C",
                         event_date="2026-12-02", guest_count=10,
                         estimated_cost="0.00"))
    assert is_ok(add)
    menu = call_action(ACTIONS["food-add-menu-item"], conn,
                       ns(company_id=env["company_id"], name="Plated",
                          cost="4.35", price="12.00"))
    assert is_ok(menu), menu
    call_action(ACTIONS["food-add-catering-item"], conn,
                ns(event_id=add["id"], item_name="Plated",
                   quantity=10, unit_price="12.00",
                   menu_item_id=menu["id"]))
    call_action(ACTIONS["food-add-catering-item"], conn,
                ns(event_id=add["id"], item_name="Extra",
                   quantity=5, unit_price="3.00"))
    result = call_action(ACTIONS["food-catering-cost-estimate"], conn,
                         ns(event_id=add["id"]))
    assert is_ok(result), result
    assert result["menu_cost"] == "43.50"
    assert result["unlinked_item_count"] == 1
    assert result["total_cost"] == "43.50"
    assert result["cost_source"] == "menu_item_cost"
    assert result["total_price"] == "135.00"
    assert result["estimated_margin"] == "91.50"
    by_name = {i["item_name"]: i for i in result["items"]}
    assert by_name["Plated"]["line_cost"] == "43.50"
    assert by_name["Extra"]["line_cost"] is None


def test_no_cost_known(conn, env):
    add = call_action(ACTIONS["food-add-catering-event"], conn,
                      ns(company_id=env["company_id"],
                         event_name="No Cost", client_name="C",
                         event_date="2026-12-03", guest_count=10))
    assert is_ok(add)
    call_action(ACTIONS["food-add-catering-item"], conn,
                ns(event_id=add["id"], item_name="Snack",
                   quantity=5, unit_price="3.00"))
    result = call_action(ACTIONS["food-catering-cost-estimate"], conn,
                         ns(event_id=add["id"]))
    assert is_ok(result), result
    assert result["total_cost"] == "0.00"
    assert result["cost_source"] == "none"
    assert result["estimated_margin"] is None


def test_estimate_writes_nothing(conn, env):
    add = call_action(ACTIONS["food-add-catering-event"], conn,
                      ns(company_id=env["company_id"],
                         event_name="Snapshot", client_name="C",
                         event_date="2026-12-04", guest_count=10,
                         estimated_cost="100.00"))
    assert is_ok(add)
    menu = call_action(ACTIONS["food-add-menu-item"], conn,
                       ns(company_id=env["company_id"], name="Dish",
                          cost="2.00", price="5.00"))
    assert is_ok(menu), menu
    call_action(ACTIONS["food-add-catering-item"], conn,
                ns(event_id=add["id"], item_name="Dish",
                   quantity=2, unit_price="5.00",
                   menu_item_id=menu["id"]))
    before = _snapshot(conn)
    result = call_action(ACTIONS["food-catering-cost-estimate"], conn,
                         ns(event_id=add["id"]))
    assert is_ok(result), result
    after = _snapshot(conn)
    assert before == after
