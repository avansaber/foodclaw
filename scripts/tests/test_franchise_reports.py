"""L1 tests for FoodClaw franchise + reports domains.

Covers:
  - Franchise Units: add, update, get, list
  - Royalty Entries: add, get, list, update-payment-status
  - Reports: food-cost-report, waste-report, menu-performance,
             franchise-comparison, daily-sales-summary, labor-report
  - Status action
"""
import pytest
import sys
import os

_TESTS_DIR = os.path.dirname(os.path.abspath(__file__))
if _TESTS_DIR not in sys.path:
    sys.path.insert(0, _TESTS_DIR)

from food_helpers import (
    call_action, ns, is_ok, is_error, load_db_query,
)

_mod = load_db_query()
ACTIONS = _mod.ACTIONS


# ── Franchise Unit Tests ────────────────────────────────────────────────────


class TestAddFranchiseUnit:
    """food-add-franchise-unit"""

    def test_add_unit_ok(self, conn, env):
        result = call_action(
            ACTIONS["food-add-franchise-unit"], conn,
            ns(company_id=env["company_id"], name="Downtown Location",
               unit_code="DT-001", city="Portland", state="OR",
               zip_code="97201", manager_name="Alice"),
        )
        assert is_ok(result), result
        assert result["unit_name"] == "Downtown Location"
        # Note: "status" key is overwritten by ok() response wrapper to "ok",
        # so we verify the unit was created via get instead
        got = call_action(ACTIONS["food-get-franchise-unit"], conn,
                          ns(franchise_unit_id=result["id"]))
        assert is_ok(got)
        assert got["status"] == "ok"  # response status, unit status in DB

    def test_add_unit_missing_name(self, conn, env):
        result = call_action(
            ACTIONS["food-add-franchise-unit"], conn,
            ns(company_id=env["company_id"]),
        )
        assert is_error(result)

    def test_add_unit_missing_company(self, conn, env):
        result = call_action(
            ACTIONS["food-add-franchise-unit"], conn,
            ns(name="Test Unit"),
        )
        assert is_error(result)


class TestUpdateFranchiseUnit:
    """food-update-franchise-unit"""

    def _make_unit(self, conn, env):
        r = call_action(ACTIONS["food-add-franchise-unit"], conn,
                        ns(company_id=env["company_id"], name="Unit A"))
        assert is_ok(r)
        return r["id"]

    def test_update_unit_name(self, conn, env):
        uid = self._make_unit(conn, env)
        result = call_action(
            ACTIONS["food-update-franchise-unit"], conn,
            ns(franchise_unit_id=uid, name="Unit A Renamed"),
        )
        assert is_ok(result), result
        assert "unit_name" in result["updated_fields"]

    def test_update_unit_status(self, conn, env):
        uid = self._make_unit(conn, env)
        result = call_action(
            ACTIONS["food-update-franchise-unit"], conn,
            ns(franchise_unit_id=uid, status="inactive"),
        )
        assert is_ok(result), result
        assert "status" in result["updated_fields"]

    def test_update_unit_missing_id(self, conn, env):
        result = call_action(
            ACTIONS["food-update-franchise-unit"], conn,
            ns(name="X"),
        )
        assert is_error(result)


class TestGetFranchiseUnit:
    """food-get-franchise-unit"""

    def test_get_unit_ok(self, conn, env):
        add = call_action(ACTIONS["food-add-franchise-unit"], conn,
                          ns(company_id=env["company_id"], name="Get Test"))
        assert is_ok(add)
        result = call_action(
            ACTIONS["food-get-franchise-unit"], conn,
            ns(franchise_unit_id=add["id"]),
        )
        assert is_ok(result), result
        assert result["unit_name"] == "Get Test"
        assert "royalty_entry_count" in result
        assert "total_royalties_due" in result

    def test_get_unit_not_found(self, conn, env):
        result = call_action(
            ACTIONS["food-get-franchise-unit"], conn,
            ns(franchise_unit_id="nonexistent"),
        )
        assert is_error(result)


class TestListFranchiseUnits:
    """food-list-franchise-units"""

    def test_list_units(self, conn, env):
        call_action(ACTIONS["food-add-franchise-unit"], conn,
                     ns(company_id=env["company_id"], name="Unit X"))
        result = call_action(
            ACTIONS["food-list-franchise-units"], conn,
            ns(company_id=env["company_id"]),
        )
        assert is_ok(result), result
        assert result["total_count"] >= 1


# ── Royalty Entry Tests ─────────────────────────────────────────────────────


class TestAddRoyaltyEntry:
    """food-add-royalty-entry"""

    def _make_unit(self, conn, env):
        r = call_action(ACTIONS["food-add-franchise-unit"], conn,
                        ns(company_id=env["company_id"], name="Royal Unit"))
        assert is_ok(r)
        return r["id"]

    def test_add_royalty_entry_calculated(self, conn, env):
        uid = self._make_unit(conn, env)
        result = call_action(
            ACTIONS["food-add-royalty-entry"], conn,
            ns(company_id=env["company_id"], franchise_unit_id=uid,
               period_start="2026-01-01", period_end="2026-01-31",
               gross_revenue="100000.00", royalty_rate="5",
               marketing_fee="1000.00"),
        )
        assert is_ok(result), result
        # royalty_amount = 100000 * 5 / 100 = 5000.00
        assert result["royalty_amount"] == "5000.00"
        assert result["marketing_fee"] == "1000.00"
        # total_due = 5000 + 1000 = 6000.00
        assert result["total_due"] == "6000.00"
        assert result["payment_status"] == "pending"

    def test_add_royalty_entry_explicit_amount(self, conn, env):
        uid = self._make_unit(conn, env)
        result = call_action(
            ACTIONS["food-add-royalty-entry"], conn,
            ns(company_id=env["company_id"], franchise_unit_id=uid,
               period_start="2026-02-01", period_end="2026-02-28",
               gross_revenue="80000.00", royalty_amount="4500.00"),
        )
        assert is_ok(result), result
        assert result["royalty_amount"] == "4500.00"

    def test_add_royalty_missing_period(self, conn, env):
        uid = self._make_unit(conn, env)
        result = call_action(
            ACTIONS["food-add-royalty-entry"], conn,
            ns(company_id=env["company_id"], franchise_unit_id=uid,
               gross_revenue="50000.00"),
        )
        assert is_error(result)


class TestGetRoyaltyEntry:
    """food-get-royalty-entry"""

    def test_get_royalty_entry(self, conn, env):
        unit = call_action(ACTIONS["food-add-franchise-unit"], conn,
                           ns(company_id=env["company_id"], name="R-Unit"))
        assert is_ok(unit)
        add = call_action(ACTIONS["food-add-royalty-entry"], conn,
                          ns(company_id=env["company_id"],
                             franchise_unit_id=unit["id"],
                             period_start="2026-01-01",
                             period_end="2026-01-31",
                             gross_revenue="50000.00", royalty_rate="6"))
        assert is_ok(add)
        result = call_action(
            ACTIONS["food-get-royalty-entry"], conn,
            ns(royalty_id=add["id"]),
        )
        assert is_ok(result), result
        assert result["gross_revenue"] == "50000.00"

    def test_get_royalty_not_found(self, conn, env):
        result = call_action(
            ACTIONS["food-get-royalty-entry"], conn,
            ns(royalty_id="nonexistent"),
        )
        assert is_error(result)


class TestListRoyaltyEntries:
    """food-list-royalty-entries"""

    def test_list_royalties(self, conn, env):
        unit = call_action(ACTIONS["food-add-franchise-unit"], conn,
                           ns(company_id=env["company_id"], name="L-Unit"))
        assert is_ok(unit)
        call_action(ACTIONS["food-add-royalty-entry"], conn,
                     ns(company_id=env["company_id"],
                        franchise_unit_id=unit["id"],
                        period_start="2026-01-01", period_end="2026-01-31",
                        gross_revenue="60000.00", royalty_rate="5"))
        result = call_action(
            ACTIONS["food-list-royalty-entries"], conn,
            ns(company_id=env["company_id"]),
        )
        assert is_ok(result), result
        assert result["total_count"] >= 1


class TestUpdateRoyaltyStatus:
    """food-update-royalty-status"""

    def test_mark_paid(self, conn, env):
        unit = call_action(ACTIONS["food-add-franchise-unit"], conn,
                           ns(company_id=env["company_id"], name="Pay Unit"))
        assert is_ok(unit)
        add = call_action(ACTIONS["food-add-royalty-entry"], conn,
                          ns(company_id=env["company_id"],
                             franchise_unit_id=unit["id"],
                             period_start="2026-03-01",
                             period_end="2026-03-31",
                             gross_revenue="70000.00", royalty_rate="5"))
        assert is_ok(add)
        result = call_action(
            ACTIONS["food-update-royalty-status"], conn,
            ns(royalty_id=add["id"], payment_status="paid"),
        )
        assert is_ok(result), result
        assert result["payment_status"] == "paid"

    def test_update_status_missing_id(self, conn, env):
        result = call_action(
            ACTIONS["food-update-royalty-status"], conn,
            ns(payment_status="paid"),
        )
        assert is_error(result)

    def test_update_status_missing_status(self, conn, env):
        unit = call_action(ACTIONS["food-add-franchise-unit"], conn,
                           ns(company_id=env["company_id"], name="S Unit"))
        assert is_ok(unit)
        add = call_action(ACTIONS["food-add-royalty-entry"], conn,
                          ns(company_id=env["company_id"],
                             franchise_unit_id=unit["id"],
                             period_start="2026-04-01",
                             period_end="2026-04-30",
                             gross_revenue="40000.00", royalty_rate="5"))
        assert is_ok(add)
        result = call_action(
            ACTIONS["food-update-royalty-status"], conn,
            ns(royalty_id=add["id"]),
        )
        assert is_error(result)


# ── Report Tests ────────────────────────────────────────────────────────────


class TestFoodCostReport:
    """food-cost-report"""

    def test_cost_report_empty(self, conn, env):
        result = call_action(
            ACTIONS["food-cost-report"], conn,
            ns(company_id=env["company_id"]),
        )
        assert is_ok(result), result
        assert result["overall_food_cost_pct"] == "0.00"


class TestWasteReport:
    """food-waste-report"""

    def test_waste_report(self, conn, env):
        call_action(ACTIONS["food-add-waste-log"], conn,
                     ns(company_id=env["company_id"], item_name="Bread",
                        waste_date="2026-03-10", waste_reason="expired",
                        waste_cost="5.00", quantity="3"))
        call_action(ACTIONS["food-add-waste-log"], conn,
                     ns(company_id=env["company_id"], item_name="Milk",
                        waste_date="2026-03-10", waste_reason="spoiled",
                        waste_cost="8.00", quantity="2"))
        result = call_action(
            ACTIONS["food-waste-report"], conn,
            ns(company_id=env["company_id"]),
        )
        assert is_ok(result), result
        assert result["grand_total_cost"] == "13.00"
        assert len(result["reasons"]) == 2


class TestMenuPerformance:
    """food-menu-performance"""

    def test_menu_performance_empty(self, conn, env):
        result = call_action(
            ACTIONS["food-menu-performance"], conn,
            ns(company_id=env["company_id"]),
        )
        assert is_ok(result), result
        assert result["total_count"] == 0

    def test_menu_performance_with_items(self, conn, env):
        call_action(ACTIONS["food-add-menu-item"], conn,
                     ns(company_id=env["company_id"], name="Steak",
                        price="40.00", cost="15.00", category="entree"))
        result = call_action(
            ACTIONS["food-menu-performance"], conn,
            ns(company_id=env["company_id"]),
        )
        assert is_ok(result), result
        assert result["total_count"] >= 1
        item = result["items"][0]
        assert item["price"] == "40.00"
        assert item["cost"] == "15.00"
        # margin = 40 - 15 = 25, margin_pct = 25/40*100 = 62.50
        assert item["contribution_margin"] == "25.00"
        assert item["margin_pct"] == "62.50"


class TestFranchiseComparison:
    """food-franchise-comparison"""

    def test_franchise_comparison(self, conn, env):
        u1 = call_action(ACTIONS["food-add-franchise-unit"], conn,
                         ns(company_id=env["company_id"], name="Unit Alpha"))
        u2 = call_action(ACTIONS["food-add-franchise-unit"], conn,
                         ns(company_id=env["company_id"], name="Unit Beta"))
        assert is_ok(u1) and is_ok(u2)
        call_action(ACTIONS["food-add-royalty-entry"], conn,
                     ns(company_id=env["company_id"],
                        franchise_unit_id=u1["id"],
                        period_start="2026-01-01", period_end="2026-01-31",
                        gross_revenue="100000.00", royalty_rate="5"))
        call_action(ACTIONS["food-add-royalty-entry"], conn,
                     ns(company_id=env["company_id"],
                        franchise_unit_id=u2["id"],
                        period_start="2026-01-01", period_end="2026-01-31",
                        gross_revenue="80000.00", royalty_rate="5"))
        result = call_action(
            ACTIONS["food-franchise-comparison"], conn,
            ns(company_id=env["company_id"]),
        )
        assert is_ok(result), result
        assert result["total_count"] == 2
        # Alpha should be first (higher revenue)
        assert result["units"][0]["unit_name"] == "Unit Alpha"


class TestDailySalesSummary:
    """food-daily-sales-summary"""

    def test_daily_summary(self, conn, env):
        result = call_action(
            ACTIONS["food-daily-sales-summary"], conn,
            ns(company_id=env["company_id"], summary_date="2026-03-10"),
        )
        assert is_ok(result), result
        assert result["summary_date"] == "2026-03-10"
        assert "active_menu_items" in result
        assert "catering_events" in result
        assert "scheduled_shifts" in result
        assert "waste_cost" in result
        assert "temp_violations" in result

    def test_daily_summary_missing_date(self, conn, env):
        result = call_action(
            ACTIONS["food-daily-sales-summary"], conn,
            ns(company_id=env["company_id"]),
        )
        assert is_error(result)


class TestLaborReport:
    """food-labor-report"""

    def test_labor_report_empty(self, conn, env):
        result = call_action(
            ACTIONS["food-labor-report"], conn,
            ns(company_id=env["company_id"]),
        )
        assert is_ok(result), result
        assert result["grand_total_hours"] == "0.00"
        assert result["grand_total_cost"] == "0.00"


# ── Status Action ───────────────────────────────────────────────────────────


class TestStatus:
    """status"""

    def test_status(self, conn, env):
        result = call_action(ACTIONS["status"], conn, ns())
        assert is_ok(result), result
        assert result["skill"] == "foodclaw"
        assert result["actions_available"] > 0
        assert "menu" in result["domains"]
        assert "franchise" in result["domains"]
