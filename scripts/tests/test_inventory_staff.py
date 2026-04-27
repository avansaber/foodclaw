"""L1 tests for FoodClaw inventory + staff domains.

Covers:
  - Ingredients: add, update, get, list
  - Stock Counts: add, list
  - Waste Logs: add, list
  - Purchase Orders: add, list
  - Par Level Alert, Inventory Valuation
  - Employees (extension): add, update, list
  - Shifts: add, update, list, clock-in, clock-out
  - Tip Distribution: add, list
"""
import pytest
import sys
import os

_TESTS_DIR = os.path.dirname(os.path.abspath(__file__))
if _TESTS_DIR not in sys.path:
    sys.path.insert(0, _TESTS_DIR)

from food_helpers import (
    call_action, ns, is_ok, is_error, load_db_query,
    seed_company, seed_naming_series, seed_employee, seed_supplier,
)

_mod = load_db_query()
ACTIONS = _mod.ACTIONS


# ── Ingredient Tests ────────────────────────────────────────────────────────


class TestAddIngredient:
    """food-add-ingredient"""

    def test_add_ingredient_ok(self, conn, env):
        result = call_action(
            ACTIONS["food-add-ingredient"], conn,
            ns(company_id=env["company_id"], name="Tomatoes",
               ingredient_category="produce", unit="lb",
               unit_cost="2.50", current_stock="100", par_level="50"),
        )
        assert is_ok(result), result
        assert result["name"] == "Tomatoes"
        assert result["unit_cost"] == "2.50"

    def test_add_ingredient_missing_name(self, conn, env):
        result = call_action(
            ACTIONS["food-add-ingredient"], conn,
            ns(company_id=env["company_id"]),
        )
        assert is_error(result)

    def test_add_ingredient_defaults(self, conn, env):
        result = call_action(
            ACTIONS["food-add-ingredient"], conn,
            ns(company_id=env["company_id"], name="Salt"),
        )
        assert is_ok(result), result
        # Defaults: unit_cost=0.00
        assert result["unit_cost"] == "0.00"


class TestUpdateIngredient:
    """food-update-ingredient"""

    def test_update_stock(self, conn, env):
        add = call_action(ACTIONS["food-add-ingredient"], conn,
                          ns(company_id=env["company_id"], name="Onion"))
        assert is_ok(add)
        result = call_action(
            ACTIONS["food-update-ingredient"], conn,
            ns(ingredient_id=add["id"], current_stock="200"),
        )
        assert is_ok(result), result
        assert "current_stock" in result["updated_fields"]

    def test_update_ingredient_missing_id(self, conn, env):
        result = call_action(
            ACTIONS["food-update-ingredient"], conn,
            ns(current_stock="10"),
        )
        assert is_error(result)


class TestGetIngredient:
    """food-get-ingredient"""

    def test_get_ingredient_ok(self, conn, env):
        add = call_action(ACTIONS["food-add-ingredient"], conn,
                          ns(company_id=env["company_id"], name="Garlic"))
        assert is_ok(add)
        result = call_action(
            ACTIONS["food-get-ingredient"], conn,
            ns(ingredient_id=add["id"]),
        )
        assert is_ok(result), result
        assert result["name"] == "Garlic"


class TestListIngredients:
    """food-list-ingredients"""

    def test_list_ingredients(self, conn, env):
        call_action(ACTIONS["food-add-ingredient"], conn,
                     ns(company_id=env["company_id"], name="Pepper"))
        result = call_action(
            ACTIONS["food-list-ingredients"], conn,
            ns(company_id=env["company_id"]),
        )
        assert is_ok(result), result
        assert result["total_count"] >= 1


# ── Stock Count Tests ───────────────────────────────────────────────────────


class TestStockCount:
    """food-add-stock-count / food-list-stock-counts"""

    def _make_ingredient(self, conn, env):
        r = call_action(ACTIONS["food-add-ingredient"], conn,
                        ns(company_id=env["company_id"], name="Chicken",
                           current_stock="50", unit_cost="5.00"))
        assert is_ok(r)
        return r["id"]

    def test_add_stock_count(self, conn, env):
        ing_id = self._make_ingredient(conn, env)
        result = call_action(
            ACTIONS["food-add-stock-count"], conn,
            ns(company_id=env["company_id"], ingredient_id=ing_id,
               count_date="2026-03-10", counted_qty="45", counted_by="Chef"),
        )
        assert is_ok(result), result
        assert result["counted_qty"] == "45"
        assert result["system_qty"] == "50"
        assert result["variance"] == "-5"

    def test_stock_count_missing_date(self, conn, env):
        ing_id = self._make_ingredient(conn, env)
        result = call_action(
            ACTIONS["food-add-stock-count"], conn,
            ns(company_id=env["company_id"], ingredient_id=ing_id,
               counted_qty="10"),
        )
        assert is_error(result)

    def test_list_stock_counts(self, conn, env):
        ing_id = self._make_ingredient(conn, env)
        call_action(ACTIONS["food-add-stock-count"], conn,
                     ns(company_id=env["company_id"], ingredient_id=ing_id,
                        count_date="2026-03-10", counted_qty="40"))
        result = call_action(
            ACTIONS["food-list-stock-counts"], conn,
            ns(company_id=env["company_id"]),
        )
        assert is_ok(result), result
        assert result["total_count"] >= 1


# ── Waste Log Tests ─────────────────────────────────────────────────────────


class TestWasteLog:
    """food-add-waste-log / food-list-waste-logs"""

    def test_add_waste_log(self, conn, env):
        result = call_action(
            ACTIONS["food-add-waste-log"], conn,
            ns(company_id=env["company_id"], item_name="Old Bread",
               waste_date="2026-03-10", quantity="5", waste_reason="expired",
               waste_cost="12.50"),
        )
        assert is_ok(result), result
        assert result["item_name"] == "Old Bread"
        assert result["cost"] == "12.50"

    def test_add_waste_log_missing_item_name(self, conn, env):
        result = call_action(
            ACTIONS["food-add-waste-log"], conn,
            ns(company_id=env["company_id"], waste_date="2026-03-10"),
        )
        assert is_error(result)

    def test_add_waste_log_missing_date(self, conn, env):
        result = call_action(
            ACTIONS["food-add-waste-log"], conn,
            ns(company_id=env["company_id"], item_name="Stale Cake"),
        )
        assert is_error(result)

    def test_list_waste_logs(self, conn, env):
        call_action(ACTIONS["food-add-waste-log"], conn,
                     ns(company_id=env["company_id"], item_name="Lettuce",
                        waste_date="2026-03-10", waste_reason="spoiled",
                        waste_cost="3.00"))
        result = call_action(
            ACTIONS["food-list-waste-logs"], conn,
            ns(company_id=env["company_id"]),
        )
        assert is_ok(result), result
        assert result["total_count"] >= 1


# ── Purchase Order Tests ────────────────────────────────────────────────────


class TestPurchaseOrder:
    """food-add-purchase-order / food-list-purchase-orders"""

    def test_add_purchase_order(self, conn, env):
        result = call_action(
            ACTIONS["food-add-purchase-order"], conn,
            ns(company_id=env["company_id"], supplier_id=env["supplier_id"],
               order_date="2026-03-10", total_amount="500.00"),
        )
        assert is_ok(result), result
        assert result["order_status"] == "draft"
        assert result["total_amount"] == "500.00"

    def test_add_po_missing_supplier(self, conn, env):
        result = call_action(
            ACTIONS["food-add-purchase-order"], conn,
            ns(company_id=env["company_id"], order_date="2026-03-10"),
        )
        assert is_error(result)

    def test_add_po_invalid_supplier(self, conn, env):
        result = call_action(
            ACTIONS["food-add-purchase-order"], conn,
            ns(company_id=env["company_id"], supplier_id="nonexistent",
               order_date="2026-03-10"),
        )
        assert is_error(result)

    def test_list_purchase_orders(self, conn, env):
        call_action(ACTIONS["food-add-purchase-order"], conn,
                     ns(company_id=env["company_id"],
                        supplier_id=env["supplier_id"],
                        order_date="2026-03-10", total_amount="100.00"))
        result = call_action(
            ACTIONS["food-list-purchase-orders"], conn,
            ns(company_id=env["company_id"]),
        )
        assert is_ok(result), result
        assert result["total_count"] >= 1


# ── Par Level Alert / Inventory Valuation ───────────────────────────────────


class TestParLevelAlert:
    """food-par-level-alert"""

    def test_par_level_alert(self, conn, env):
        # Create ingredient below par
        call_action(ACTIONS["food-add-ingredient"], conn,
                     ns(company_id=env["company_id"], name="Milk",
                        current_stock="5", par_level="20"))
        result = call_action(
            ACTIONS["food-par-level-alert"], conn,
            ns(company_id=env["company_id"]),
        )
        assert is_ok(result), result
        assert result["total_count"] >= 1
        assert any(i["name"] == "Milk" for i in result["items"])

    def test_par_level_alert_none_below(self, conn, env):
        call_action(ACTIONS["food-add-ingredient"], conn,
                     ns(company_id=env["company_id"], name="Rice",
                        current_stock="100", par_level="50"))
        result = call_action(
            ACTIONS["food-par-level-alert"], conn,
            ns(company_id=env["company_id"]),
        )
        assert is_ok(result), result
        # Rice should NOT appear (stock > par)
        assert not any(i["name"] == "Rice" for i in result["items"])


class TestInventoryValuation:
    """food-inventory-valuation"""

    def test_inventory_valuation(self, conn, env):
        call_action(ACTIONS["food-add-ingredient"], conn,
                     ns(company_id=env["company_id"], name="Beef",
                        current_stock="20", unit_cost="10.00"))
        call_action(ACTIONS["food-add-ingredient"], conn,
                     ns(company_id=env["company_id"], name="Salmon",
                        current_stock="10", unit_cost="15.00"))
        result = call_action(
            ACTIONS["food-inventory-valuation"], conn,
            ns(company_id=env["company_id"]),
        )
        assert is_ok(result), result
        # 20*10 + 10*15 = 200 + 150 = 350.00
        assert result["total_value"] == "350.00"
        assert result["total_count"] == 2


# ── Employee Tests ──────────────────────────────────────────────────────────


class TestAddEmployee:
    """food-add-employee"""

    def test_add_employee_ok(self, conn, env):
        result = call_action(
            ACTIONS["food-add-employee"], conn,
            ns(company_id=env["company_id"], employee_id=env["employee_id_1"],
               role="chef", hourly_rate="25.00"),
        )
        assert is_ok(result), result
        assert result["role"] == "chef"
        assert "full_name" in result

    def test_add_employee_missing_core(self, conn, env):
        result = call_action(
            ACTIONS["food-add-employee"], conn,
            ns(company_id=env["company_id"]),
        )
        assert is_error(result)

    def test_add_employee_invalid_core(self, conn, env):
        result = call_action(
            ACTIONS["food-add-employee"], conn,
            ns(company_id=env["company_id"], employee_id="nonexistent"),
        )
        assert is_error(result)

    def test_add_employee_duplicate(self, conn, env):
        call_action(ACTIONS["food-add-employee"], conn,
                     ns(company_id=env["company_id"],
                        employee_id=env["employee_id_1"], role="chef"))
        result = call_action(
            ACTIONS["food-add-employee"], conn,
            ns(company_id=env["company_id"],
               employee_id=env["employee_id_1"], role="server"),
        )
        assert is_error(result)


class TestUpdateEmployee:
    """food-update-employee"""

    def test_update_role(self, conn, env):
        add = call_action(ACTIONS["food-add-employee"], conn,
                          ns(company_id=env["company_id"],
                             employee_id=env["employee_id_1"], role="staff"))
        assert is_ok(add)
        result = call_action(
            ACTIONS["food-update-employee"], conn,
            ns(foodclaw_employee_id=add["id"], role="sous_chef"),
        )
        assert is_ok(result), result
        assert "role" in result["updated_fields"]


class TestListEmployees:
    """food-list-employees"""

    def test_list_employees(self, conn, env):
        call_action(ACTIONS["food-add-employee"], conn,
                     ns(company_id=env["company_id"],
                        employee_id=env["employee_id_1"], role="chef"))
        result = call_action(
            ACTIONS["food-list-employees"], conn,
            ns(company_id=env["company_id"]),
        )
        assert is_ok(result), result
        assert result["total_count"] >= 1


# ── Shift Tests ─────────────────────────────────────────────────────────────


class TestShift:
    """food-add-shift / food-update-shift / food-list-shifts"""

    def _make_food_employee(self, conn, env):
        r = call_action(ACTIONS["food-add-employee"], conn,
                        ns(company_id=env["company_id"],
                           employee_id=env["employee_id_1"],
                           role="server", hourly_rate="15.00"))
        assert is_ok(r)
        return r["id"]

    def test_add_shift(self, conn, env):
        femp_id = self._make_food_employee(conn, env)
        result = call_action(
            ACTIONS["food-add-shift"], conn,
            ns(company_id=env["company_id"], foodclaw_employee_id=femp_id,
               shift_date="2026-03-10", start_time="08:00",
               end_time="16:00"),
        )
        assert is_ok(result), result
        assert result["shift_status"] == "scheduled"
        assert result["shift_date"] == "2026-03-10"

    def test_add_shift_missing_date(self, conn, env):
        femp_id = self._make_food_employee(conn, env)
        result = call_action(
            ACTIONS["food-add-shift"], conn,
            ns(company_id=env["company_id"], foodclaw_employee_id=femp_id,
               start_time="08:00"),
        )
        assert is_error(result)

    def test_update_shift(self, conn, env):
        femp_id = self._make_food_employee(conn, env)
        add = call_action(ACTIONS["food-add-shift"], conn,
                          ns(company_id=env["company_id"],
                             foodclaw_employee_id=femp_id,
                             shift_date="2026-03-10", start_time="08:00"))
        assert is_ok(add)
        result = call_action(
            ACTIONS["food-update-shift"], conn,
            ns(shift_id=add["id"], end_time="17:00"),
        )
        assert is_ok(result), result
        assert "end_time" in result["updated_fields"]

    def test_list_shifts(self, conn, env):
        femp_id = self._make_food_employee(conn, env)
        call_action(ACTIONS["food-add-shift"], conn,
                     ns(company_id=env["company_id"],
                        foodclaw_employee_id=femp_id,
                        shift_date="2026-03-10", start_time="09:00"))
        result = call_action(
            ACTIONS["food-list-shifts"], conn,
            ns(company_id=env["company_id"]),
        )
        assert is_ok(result), result
        assert result["total_count"] >= 1


class TestClockInOut:
    """food-clock-in / food-clock-out"""

    def _make_shift(self, conn, env):
        femp = call_action(ACTIONS["food-add-employee"], conn,
                           ns(company_id=env["company_id"],
                              employee_id=env["employee_id_1"],
                              role="server", hourly_rate="15.00"))
        assert is_ok(femp)
        shift = call_action(ACTIONS["food-add-shift"], conn,
                            ns(company_id=env["company_id"],
                               foodclaw_employee_id=femp["id"],
                               shift_date="2026-03-10", start_time="08:00"))
        assert is_ok(shift)
        return shift["id"]

    def test_clock_in(self, conn, env):
        sid = self._make_shift(conn, env)
        result = call_action(
            ACTIONS["food-clock-in"], conn,
            ns(shift_id=sid),
        )
        assert is_ok(result), result
        assert result["shift_status"] == "clocked_in"

    def test_clock_in_already_clocked_in(self, conn, env):
        sid = self._make_shift(conn, env)
        call_action(ACTIONS["food-clock-in"], conn, ns(shift_id=sid))
        result = call_action(
            ACTIONS["food-clock-in"], conn,
            ns(shift_id=sid),
        )
        assert is_error(result)

    def test_clock_out(self, conn, env):
        sid = self._make_shift(conn, env)
        call_action(ACTIONS["food-clock-in"], conn, ns(shift_id=sid))
        result = call_action(
            ACTIONS["food-clock-out"], conn,
            ns(shift_id=sid),
        )
        assert is_ok(result), result
        assert result["shift_status"] == "clocked_out"
        assert "hours_worked" in result

    def test_clock_out_not_clocked_in(self, conn, env):
        sid = self._make_shift(conn, env)
        result = call_action(
            ACTIONS["food-clock-out"], conn,
            ns(shift_id=sid),
        )
        assert is_error(result)


# ── Tip Distribution Tests ──────────────────────────────────────────────────


class TestTipDistribution:
    """food-add-tip-distribution / food-list-tip-distributions"""

    def _make_food_employee(self, conn, env):
        r = call_action(ACTIONS["food-add-employee"], conn,
                        ns(company_id=env["company_id"],
                           employee_id=env["employee_id_2"],
                           role="server", hourly_rate="12.00"))
        assert is_ok(r)
        return r["id"]

    def test_add_tip_distribution(self, conn, env):
        femp_id = self._make_food_employee(conn, env)
        result = call_action(
            ACTIONS["food-add-tip-distribution"], conn,
            ns(company_id=env["company_id"], foodclaw_employee_id=femp_id,
               tip_date="2026-03-10", cash_tips="50.00",
               credit_tips="75.00", tip_pool_share="10.00"),
        )
        assert is_ok(result), result
        # total = 50 + 75 + 10 = 135
        assert result["total_tips"] == "135.00"

    def test_add_tip_missing_date(self, conn, env):
        femp_id = self._make_food_employee(conn, env)
        result = call_action(
            ACTIONS["food-add-tip-distribution"], conn,
            ns(company_id=env["company_id"], foodclaw_employee_id=femp_id,
               cash_tips="20.00"),
        )
        assert is_error(result)

    def test_list_tip_distributions(self, conn, env):
        femp_id = self._make_food_employee(conn, env)
        call_action(ACTIONS["food-add-tip-distribution"], conn,
                     ns(company_id=env["company_id"],
                        foodclaw_employee_id=femp_id,
                        tip_date="2026-03-10", cash_tips="30.00"))
        result = call_action(
            ACTIONS["food-list-tip-distributions"], conn,
            ns(company_id=env["company_id"]),
        )
        assert is_ok(result), result
        assert result["total_count"] >= 1
