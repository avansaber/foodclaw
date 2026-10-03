"""FoodClaw audit rows name the record (m704).

Every audit row written by the foodclaw skill must carry
  skill       = "foodclaw"            (the module name)
  action      = "<action name>"       (e.g. "food-add-menu")
  entity_type = "<table>"             (e.g. "foodclaw_menu")
  entity_id   = "<record id>"         (that record's id)

so a record's history is found under that record's id.
Reads go through PyPika with bound parameters.
"""
import json
import os
import sys

_TESTS_DIR = os.path.dirname(os.path.abspath(__file__))
if _TESTS_DIR not in sys.path:
    sys.path.insert(0, _TESTS_DIR)

from food_helpers import (  # noqa: E402
    call_action, ns, is_ok, load_db_query,
    delegate_selling_in_process,
)

from erpclaw_lib.query import Q, Table, Field, P  # noqa: E402

_mod = load_db_query()
ACTIONS = _mod.ACTIONS

SKILL = "foodclaw"


def audit_rows_for(conn, entity_id):
    """Audit rows for one record id (PyPika select, bound parameter)."""
    t = Table("audit_log")
    q = (Q.from_(t)
         .select(t.skill, t.action, t.entity_type, t.entity_id, t.new_values)
         .where(t.entity_id == P()))
    return [dict(r) for r in conn.execute(q.get_sql(), (entity_id,)).fetchall()]


def assert_audit_row(conn, entity_id, skill, action, entity_type):
    """Exactly one audit row with this entity_id carries the exact triple."""
    rows = audit_rows_for(conn, entity_id)
    matches = [r for r in rows
               if (r["skill"], r["action"], r["entity_type"])
               == (skill, action, entity_type)]
    assert len(matches) == 1, (
        f"expected exactly one audit row {(skill, action, entity_type)} "
        f"for entity_id {entity_id!r}; matches={matches} all={rows}"
    )
    return matches[0]


def test_menu_audit_rows_name_the_record(conn, env):
    cid = env["company_id"]
    menu = call_action(ACTIONS["food-add-menu"], conn,
                       ns(company_id=cid, name="Dinner Menu"))
    assert is_ok(menu), menu
    assert_audit_row(conn, menu["id"], "foodclaw", "food-add-menu",
                     "foodclaw_menu")

    upd = call_action(ACTIONS["food-update-menu"], conn,
                      ns(menu_id=menu["id"], name="Dinner Menu v2"))
    assert is_ok(upd), upd
    assert_audit_row(conn, menu["id"], "foodclaw", "food-update-menu",
                     "foodclaw_menu")

    item = call_action(ACTIONS["food-add-menu-item"], conn,
                       ns(company_id=cid, name="Grilled Salmon",
                          price="24.99", cost="8.50", category="entree"))
    assert is_ok(item), item
    assert_audit_row(conn, item["id"], "foodclaw", "food-add-menu-item",
                     "foodclaw_menu_item")

    upd_item = call_action(ACTIONS["food-update-menu-item"], conn,
                           ns(menu_item_id=item["id"], price="26.99"))
    assert is_ok(upd_item), upd_item
    assert_audit_row(conn, item["id"], "foodclaw", "food-update-menu-item",
                     "foodclaw_menu_item")

    group = call_action(ACTIONS["food-add-modifier-group"], conn,
                        ns(company_id=cid, name="Protein Choice"))
    assert is_ok(group), group
    assert_audit_row(conn, group["id"], "foodclaw",
                     "food-add-modifier-group", "foodclaw_modifier_group")

    mod = call_action(ACTIONS["food-add-modifier"], conn,
                      ns(company_id=cid, modifier_group_id=group["id"],
                         name="Large", price_adjustment="2.00"))
    assert is_ok(mod), mod
    assert_audit_row(conn, mod["id"], "foodclaw", "food-add-modifier",
                     "foodclaw_modifier")


def test_recipes_audit_rows_name_the_record(conn, env):
    cid = env["company_id"]
    recipe = call_action(ACTIONS["food-add-recipe"], conn,
                         ns(company_id=cid, name="Tomato Soup",
                            batch_size="10", batch_unit="liter",
                            portions_per_batch=20))
    assert is_ok(recipe), recipe
    assert_audit_row(conn, recipe["id"], "foodclaw", "food-add-recipe",
                     "foodclaw_recipe")

    upd = call_action(ACTIONS["food-update-recipe"], conn,
                      ns(recipe_id=recipe["id"],
                         instructions="Simmer 20 minutes."))
    assert is_ok(upd), upd
    assert_audit_row(conn, recipe["id"], "foodclaw", "food-update-recipe",
                     "foodclaw_recipe")

    ri = call_action(ACTIONS["food-add-recipe-ingredient"], conn,
                     ns(recipe_id=recipe["id"], ingredient_name="Flour",
                        quantity="2", unit="cup", unit_cost="0.50"))
    assert is_ok(ri), ri
    assert_audit_row(conn, ri["id"], "foodclaw",
                     "food-add-recipe-ingredient",
                     "foodclaw_recipe_ingredient")

    upd_ri = call_action(ACTIONS["food-update-recipe-ingredient"], conn,
                         ns(recipe_ingredient_id=ri["id"], quantity="3"))
    assert is_ok(upd_ri), upd_ri
    assert_audit_row(conn, ri["id"], "foodclaw",
                     "food-update-recipe-ingredient",
                     "foodclaw_recipe_ingredient")


def test_inventory_audit_rows_name_the_record(conn, env):
    cid = env["company_id"]
    ing = call_action(ACTIONS["food-add-ingredient"], conn,
                      ns(company_id=cid, name="Tomatoes",
                         ingredient_category="produce", unit="lb",
                         unit_cost="2.50", current_stock="100",
                         par_level="50"))
    assert is_ok(ing), ing
    assert_audit_row(conn, ing["id"], "foodclaw", "food-add-ingredient",
                     "foodclaw_ingredient")

    upd = call_action(ACTIONS["food-update-ingredient"], conn,
                      ns(ingredient_id=ing["id"], current_stock="200"))
    assert is_ok(upd), upd
    assert_audit_row(conn, ing["id"], "foodclaw", "food-update-ingredient",
                     "foodclaw_ingredient")

    sc = call_action(ACTIONS["food-add-stock-count"], conn,
                     ns(company_id=cid, ingredient_id=ing["id"],
                        count_date="2026-03-10", counted_qty="45",
                        counted_by="Chef"))
    assert is_ok(sc), sc
    assert_audit_row(conn, sc["id"], "foodclaw", "food-add-stock-count",
                     "foodclaw_stock_count")

    wl = call_action(ACTIONS["food-add-waste-log"], conn,
                     ns(company_id=cid, item_name="Old Bread",
                        waste_date="2026-03-10", quantity="5",
                        waste_reason="expired", waste_cost="12.50"))
    assert is_ok(wl), wl
    assert_audit_row(conn, wl["id"], "foodclaw", "food-add-waste-log",
                     "foodclaw_waste_log")

    po = call_action(ACTIONS["food-add-purchase-order"], conn,
                     ns(company_id=cid, supplier_id=env["supplier_id"],
                        order_date="2026-03-10", total_amount="500.00"))
    assert is_ok(po), po
    assert_audit_row(conn, po["id"], "foodclaw", "food-add-purchase-order",
                     "foodclaw_purchase_order")


def test_staff_audit_rows_name_the_record(conn, env):
    cid = env["company_id"]
    emp = call_action(ACTIONS["food-add-employee"], conn,
                      ns(company_id=cid, employee_id=env["employee_id_1"],
                         role="chef", hourly_rate="25.00"))
    assert is_ok(emp), emp
    assert_audit_row(conn, emp["id"], "foodclaw", "food-add-employee",
                     "foodclaw_employee")

    upd = call_action(ACTIONS["food-update-employee"], conn,
                      ns(foodclaw_employee_id=emp["id"], role="sous_chef"))
    assert is_ok(upd), upd
    assert_audit_row(conn, emp["id"], "foodclaw", "food-update-employee",
                     "foodclaw_employee")

    shift = call_action(ACTIONS["food-add-shift"], conn,
                        ns(company_id=cid, foodclaw_employee_id=emp["id"],
                           shift_date="2026-03-10", start_time="08:00",
                           end_time="16:00"))
    assert is_ok(shift), shift
    assert_audit_row(conn, shift["id"], "foodclaw", "food-add-shift",
                     "foodclaw_shift")

    upd_shift = call_action(ACTIONS["food-update-shift"], conn,
                            ns(shift_id=shift["id"], end_time="17:00"))
    assert is_ok(upd_shift), upd_shift
    assert_audit_row(conn, shift["id"], "foodclaw", "food-update-shift",
                     "foodclaw_shift")

    cin = call_action(ACTIONS["food-clock-in"], conn,
                      ns(shift_id=shift["id"]))
    assert is_ok(cin), cin
    assert_audit_row(conn, shift["id"], "foodclaw", "food-clock-in",
                     "foodclaw_shift")

    cout = call_action(ACTIONS["food-clock-out"], conn,
                       ns(shift_id=shift["id"]))
    assert is_ok(cout), cout
    assert_audit_row(conn, shift["id"], "foodclaw", "food-clock-out",
                     "foodclaw_shift")

    tip = call_action(ACTIONS["food-add-tip-distribution"], conn,
                      ns(company_id=cid, foodclaw_employee_id=emp["id"],
                         tip_date="2026-03-10", cash_tips="50.00",
                         credit_tips="75.00", tip_pool_share="10.00"))
    assert is_ok(tip), tip
    assert_audit_row(conn, tip["id"], "foodclaw",
                     "food-add-tip-distribution",
                     "foodclaw_tip_distribution")


def test_catering_audit_rows_name_the_record(conn, env, db_path,
                                             monkeypatch):
    cid = env["company_id"]
    event = call_action(ACTIONS["food-add-catering-event"], conn,
                        ns(company_id=cid, event_name="Wedding Reception",
                           client_name="John Smith", event_date="2026-04-15",
                           guest_count=150, quoted_price="5000.00"))
    assert is_ok(event), event
    assert_audit_row(conn, event["id"], "foodclaw",
                     "food-add-catering-event", "foodclaw_catering_event")

    upd = call_action(ACTIONS["food-update-catering-event"], conn,
                      ns(event_id=event["id"], event_status="quoted",
                         quoted_price="3000.00"))
    assert is_ok(upd), upd
    assert_audit_row(conn, event["id"], "foodclaw",
                     "food-update-catering-event", "foodclaw_catering_event")

    ci = call_action(ACTIONS["food-add-catering-item"], conn,
                     ns(event_id=event["id"], item_name="Prime Rib",
                        quantity=50, unit_price="35.00"))
    assert is_ok(ci), ci
    assert_audit_row(conn, ci["id"], "foodclaw", "food-add-catering-item",
                     "foodclaw_catering_item")

    dr = call_action(ACTIONS["food-add-dietary-requirement"], conn,
                     ns(event_id=event["id"], requirement="Gluten-Free",
                        guest_count=12))
    assert is_ok(dr), dr
    assert_audit_row(conn, dr["id"], "foodclaw",
                     "food-add-dietary-requirement",
                     "foodclaw_dietary_requirement")

    conf = call_action(ACTIONS["food-confirm-event"], conn,
                       ns(event_id=event["id"]))
    assert is_ok(conf), conf
    assert_audit_row(conn, event["id"], "foodclaw", "food-confirm-event",
                     "foodclaw_catering_event")

    import importlib.util as _ilu
    import os as _os
    _src = _os.path.dirname(_os.path.dirname(_os.path.dirname(
        _os.path.dirname(_os.path.abspath(__file__)))))
    _selling_path = _os.path.join(
        _src, "erpclaw", "scripts", "erpclaw-selling", "db_query.py")
    _spec = _ilu.spec_from_file_location("_audit_selling", _selling_path)
    _selling = _ilu.module_from_spec(_spec)
    _spec.loader.exec_module(_selling)

    class _AnyArgs:
        def __init__(self, **kw):
            self.__dict__.update(kw)

        def __getattr__(self, name):
            return None

    _cust = call_action(
        _selling.add_customer, conn,
        _AnyArgs(name="Audit Diner", company_id=cid))
    assert is_ok(_cust), _cust
    delegate_selling_in_process(conn, monkeypatch)
    done = call_action(ACTIONS["food-complete-catering-event"], conn,
                       ns(event_id=event["id"], final_amount="2500.00",
                          customer_id=_cust["customer_id"],
                          db_path=db_path))
    assert is_ok(done), done
    assert_audit_row(conn, event["id"], "foodclaw",
                     "food-complete-catering-event", "foodclaw_catering_event")
    link_t = Table("foodclaw_catering_invoice")
    link_row = conn.execute(
        Q.from_(link_t).select(link_t.id).where(link_t.event_id == P()).get_sql(),
        (event["id"],)).fetchone()
    assert link_row is not None
    assert_audit_row(conn, dict(link_row)["id"], "foodclaw",
                     "food-complete-catering-event", "foodclaw_catering_invoice")


def test_food_safety_audit_rows_name_the_record(conn, env):
    cid = env["company_id"]
    hl = call_action(ACTIONS["food-add-haccp-log"], conn,
                     ns(company_id=cid, ccp_name="CCP-1 Cooking",
                        log_date="2026-03-10", parameter="Internal Temp",
                        measured_value="165", acceptable_range="165-212",
                        is_within_range=1, monitored_by="Chef"))
    assert is_ok(hl), hl
    assert_audit_row(conn, hl["id"], "foodclaw", "food-add-haccp-log",
                     "foodclaw_haccp_log")

    tr = call_action(ACTIONS["food-add-temp-reading"], conn,
                     ns(company_id=cid, equipment_name="Walk-in Cooler",
                        reading_date="2026-03-10", temperature="38",
                        safe_min="32", safe_max="40", temp_unit="F"))
    assert is_ok(tr), tr
    assert_audit_row(conn, tr["id"], "foodclaw", "food-add-temp-reading",
                     "foodclaw_temp_reading")

    insp = call_action(ACTIONS["food-add-inspection"], conn,
                       ns(company_id=cid, inspection_date="2026-03-10",
                          inspection_type="health_dept",
                          inspector_name="Inspector Bob"))
    assert is_ok(insp), insp
    assert_audit_row(conn, insp["id"], "foodclaw", "food-add-inspection",
                     "foodclaw_inspection")

    upd = call_action(ACTIONS["food-update-inspection"], conn,
                      ns(inspection_id=insp["id"],
                         inspection_status="in_progress",
                         findings="Minor violations found"))
    assert is_ok(upd), upd
    assert_audit_row(conn, insp["id"], "foodclaw", "food-update-inspection",
                     "foodclaw_inspection")

    done = call_action(ACTIONS["food-complete-inspection"], conn,
                       ns(inspection_id=insp["id"], score="92", grade="A-"))
    assert is_ok(done), done
    assert_audit_row(conn, insp["id"], "foodclaw",
                     "food-complete-inspection", "foodclaw_inspection")


def test_franchise_audit_rows_name_the_record(conn, env):
    cid = env["company_id"]
    unit = call_action(ACTIONS["food-add-franchise-unit"], conn,
                       ns(company_id=cid, name="Downtown Location",
                          unit_code="DT-001", city="Portland", state="OR",
                          zip_code="97201", manager_name="Alice"))
    assert is_ok(unit), unit
    assert_audit_row(conn, unit["id"], "foodclaw",
                     "food-add-franchise-unit", "foodclaw_franchise_unit")

    upd = call_action(ACTIONS["food-update-franchise-unit"], conn,
                      ns(franchise_unit_id=unit["id"], name="Downtown v2"))
    assert is_ok(upd), upd
    assert_audit_row(conn, unit["id"], "foodclaw",
                     "food-update-franchise-unit", "foodclaw_franchise_unit")

    entry = call_action(ACTIONS["food-add-royalty-entry"], conn,
                        ns(company_id=cid, franchise_unit_id=unit["id"],
                           period_start="2026-01-01", period_end="2026-01-31",
                           gross_revenue="100000.00", royalty_rate="5",
                           marketing_fee="1000.00"))
    assert is_ok(entry), entry
    assert_audit_row(conn, entry["id"], "foodclaw", "food-add-royalty-entry",
                     "foodclaw_royalty_entry")

    paid = call_action(ACTIONS["food-update-royalty-status"], conn,
                       ns(royalty_id=entry["id"], payment_status="paid"))
    assert is_ok(paid), paid
    assert_audit_row(conn, entry["id"], "foodclaw",
                     "food-update-royalty-status", "foodclaw_royalty_entry")


def test_no_audit_row_is_keyed_by_company(conn, env):
    cid = env["company_id"]
    menu = call_action(ACTIONS["food-add-menu"], conn,
                       ns(company_id=cid, name="Audit Key Probe"))
    assert is_ok(menu), menu
    recipe = call_action(ACTIONS["food-add-recipe"], conn,
                         ns(company_id=cid, name="Audit Key Probe"))
    assert is_ok(recipe), recipe
    ing = call_action(ACTIONS["food-add-ingredient"], conn,
                      ns(company_id=cid, name="Audit Key Probe"))
    assert is_ok(ing), ing
    emp = call_action(ACTIONS["food-add-employee"], conn,
                      ns(company_id=cid, employee_id=env["employee_id_1"],
                         role="server"))
    assert is_ok(emp), emp
    event = call_action(ACTIONS["food-add-catering-event"], conn,
                        ns(company_id=cid, event_name="Audit Key Probe",
                           client_name="Probe", event_date="2026-04-15"))
    assert is_ok(event), event
    hl = call_action(ACTIONS["food-add-haccp-log"], conn,
                     ns(company_id=cid, ccp_name="Probe",
                        log_date="2026-03-10"))
    assert is_ok(hl), hl
    unit = call_action(ACTIONS["food-add-franchise-unit"], conn,
                       ns(company_id=cid, name="Audit Key Probe"))
    assert is_ok(unit), unit

    t = Table("audit_log")
    q = Q.from_(t).select(t.skill, t.action, t.entity_type, t.entity_id)
    rows = [dict(r) for r in conn.execute(q.get_sql()).fetchall()]
    assert rows, "expected audit rows from the probe flows"

    keyed = [r for r in rows
             if r["skill"] == "foodclaw" and r["entity_id"] == cid]
    assert keyed == [], f"audit rows keyed by company id: {keyed}"

    table_skilled = [r for r in rows if (r["skill"] or "").startswith("foodclaw_")]
    assert table_skilled == [], f"audit rows with table as skill: {table_skilled}"

    bad_action = [r for r in rows
                  if r["skill"] == "foodclaw"
                  and not (r["action"] or "").startswith("food-")]
    assert bad_action == [], f"foodclaw rows with bad action: {bad_action}"


def test_update_action_new_values_preserved(conn, env):
    # No foodclaw audit call passes a trailing positional dict, so an update
    # row carries new_values NULL; the triple and the record key still apply.
    menu = call_action(ACTIONS["food-add-menu"], conn,
                       ns(company_id=env["company_id"], name="NV Probe"))
    assert is_ok(menu), menu
    upd = call_action(ACTIONS["food-update-menu"], conn,
                      ns(menu_id=menu["id"], name="NV Probe v2"))
    assert is_ok(upd), upd
    row = assert_audit_row(conn, menu["id"], "foodclaw", "food-update-menu",
                           "foodclaw_menu")
    assert row["new_values"] is None, (
        f"expected new_values NULL (no dict passed), got {row['new_values']!r}")
