"""L1 tests for FoodClaw catering + food safety domains.

Covers:
  - Catering Events: add, update, get, list
  - Catering Items: add, list
  - Dietary Requirements: add, list
  - Confirm Event, Complete Catering Event, Cost Estimate
  - HACCP Logs: add, list
  - Temp Readings: add, list
  - Inspections: add, update, list, complete
  - Temp Violation Alert, HACCP Compliance Report
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


# ── Catering Event Tests ────────────────────────────────────────────────────


class TestAddCateringEvent:
    """food-add-catering-event"""

    def test_add_event_ok(self, conn, env):
        result = call_action(
            ACTIONS["food-add-catering-event"], conn,
            ns(company_id=env["company_id"], event_name="Wedding Reception",
               client_name="John Smith", event_date="2026-04-15",
               guest_count=150, quoted_price="5000.00"),
        )
        assert is_ok(result), result
        assert result["event_name"] == "Wedding Reception"
        assert result["event_status"] == "inquiry"

    def test_add_event_missing_name(self, conn, env):
        result = call_action(
            ACTIONS["food-add-catering-event"], conn,
            ns(company_id=env["company_id"], client_name="X",
               event_date="2026-04-15"),
        )
        assert is_error(result)

    def test_add_event_missing_client(self, conn, env):
        result = call_action(
            ACTIONS["food-add-catering-event"], conn,
            ns(company_id=env["company_id"], event_name="Party",
               event_date="2026-04-15"),
        )
        assert is_error(result)

    def test_add_event_missing_date(self, conn, env):
        result = call_action(
            ACTIONS["food-add-catering-event"], conn,
            ns(company_id=env["company_id"], event_name="Party",
               client_name="X"),
        )
        assert is_error(result)


class TestUpdateCateringEvent:
    """food-update-catering-event"""

    def _make_event(self, conn, env):
        r = call_action(ACTIONS["food-add-catering-event"], conn,
                        ns(company_id=env["company_id"],
                           event_name="Corp Dinner", client_name="Acme Inc",
                           event_date="2026-05-01"))
        assert is_ok(r)
        return r["id"]

    def test_update_event_status(self, conn, env):
        eid = self._make_event(conn, env)
        result = call_action(
            ACTIONS["food-update-catering-event"], conn,
            ns(event_id=eid, event_status="quoted", quoted_price="3000.00"),
        )
        assert is_ok(result), result
        assert "event_status" in result["updated_fields"]
        assert "quoted_price" in result["updated_fields"]

    def test_update_event_missing_id(self, conn, env):
        result = call_action(
            ACTIONS["food-update-catering-event"], conn,
            ns(event_status="confirmed"),
        )
        assert is_error(result)


class TestGetCateringEvent:
    """food-get-catering-event"""

    def test_get_event_ok(self, conn, env):
        add = call_action(ACTIONS["food-add-catering-event"], conn,
                          ns(company_id=env["company_id"],
                             event_name="Birthday", client_name="Jane",
                             event_date="2026-06-01"))
        assert is_ok(add)
        result = call_action(
            ACTIONS["food-get-catering-event"], conn,
            ns(event_id=add["id"]),
        )
        assert is_ok(result), result
        assert result["event_name"] == "Birthday"
        assert "catering_items" in result
        assert "dietary_requirements" in result


class TestListCateringEvents:
    """food-list-catering-events"""

    def test_list_events(self, conn, env):
        call_action(ACTIONS["food-add-catering-event"], conn,
                     ns(company_id=env["company_id"], event_name="E1",
                        client_name="C1", event_date="2026-07-01"))
        result = call_action(
            ACTIONS["food-list-catering-events"], conn,
            ns(company_id=env["company_id"]),
        )
        assert is_ok(result), result
        assert result["total_count"] >= 1


# ── Catering Item Tests ─────────────────────────────────────────────────────


class TestCateringItem:
    """food-add-catering-item / food-list-catering-items"""

    def _make_event(self, conn, env):
        r = call_action(ACTIONS["food-add-catering-event"], conn,
                        ns(company_id=env["company_id"],
                           event_name="Gala", client_name="Big Corp",
                           event_date="2026-08-01"))
        assert is_ok(r)
        return r["id"]

    def test_add_catering_item(self, conn, env):
        eid = self._make_event(conn, env)
        result = call_action(
            ACTIONS["food-add-catering-item"], conn,
            ns(event_id=eid, item_name="Prime Rib",
               quantity=50, unit_price="35.00"),
        )
        assert is_ok(result), result
        assert result["item_name"] == "Prime Rib"
        assert result["quantity"] == 50
        assert result["line_total"] == "1750.00"

    def test_add_catering_item_missing_name(self, conn, env):
        eid = self._make_event(conn, env)
        result = call_action(
            ACTIONS["food-add-catering-item"], conn,
            ns(event_id=eid, quantity=10),
        )
        assert is_error(result)

    def test_list_catering_items(self, conn, env):
        eid = self._make_event(conn, env)
        call_action(ACTIONS["food-add-catering-item"], conn,
                     ns(event_id=eid, item_name="Salad", quantity=50,
                        unit_price="8.00"))
        result = call_action(
            ACTIONS["food-list-catering-items"], conn,
            ns(event_id=eid),
        )
        assert is_ok(result), result
        assert result["total_count"] >= 1


# ── Dietary Requirement Tests ───────────────────────────────────────────────


class TestDietaryRequirement:
    """food-add-dietary-requirement / food-list-dietary-requirements"""

    def _make_event(self, conn, env):
        r = call_action(ACTIONS["food-add-catering-event"], conn,
                        ns(company_id=env["company_id"],
                           event_name="Event DR", client_name="DR Corp",
                           event_date="2026-09-01"))
        assert is_ok(r)
        return r["id"]

    def test_add_dietary_requirement(self, conn, env):
        eid = self._make_event(conn, env)
        result = call_action(
            ACTIONS["food-add-dietary-requirement"], conn,
            ns(event_id=eid, requirement="Gluten-Free", guest_count=12),
        )
        assert is_ok(result), result
        assert result["requirement"] == "Gluten-Free"

    def test_add_dietary_requirement_missing(self, conn, env):
        eid = self._make_event(conn, env)
        result = call_action(
            ACTIONS["food-add-dietary-requirement"], conn,
            ns(event_id=eid),
        )
        assert is_error(result)

    def test_list_dietary_requirements(self, conn, env):
        eid = self._make_event(conn, env)
        call_action(ACTIONS["food-add-dietary-requirement"], conn,
                     ns(event_id=eid, requirement="Vegan"))
        result = call_action(
            ACTIONS["food-list-dietary-requirements"], conn,
            ns(event_id=eid),
        )
        assert is_ok(result), result
        assert result["total_count"] >= 1


# ── Confirm / Complete / Cost Estimate ──────────────────────────────────────


class TestConfirmEvent:
    """food-confirm-event"""

    def test_confirm_from_inquiry(self, conn, env):
        add = call_action(ACTIONS["food-add-catering-event"], conn,
                          ns(company_id=env["company_id"],
                             event_name="Conf Test", client_name="X",
                             event_date="2026-10-01"))
        assert is_ok(add)
        result = call_action(
            ACTIONS["food-confirm-event"], conn,
            ns(event_id=add["id"]),
        )
        assert is_ok(result), result
        assert result["event_status"] == "confirmed"

    def test_confirm_already_confirmed(self, conn, env):
        add = call_action(ACTIONS["food-add-catering-event"], conn,
                          ns(company_id=env["company_id"],
                             event_name="Conf Test 2", client_name="Y",
                             event_date="2026-10-02"))
        assert is_ok(add)
        call_action(ACTIONS["food-confirm-event"], conn,
                     ns(event_id=add["id"]))
        result = call_action(
            ACTIONS["food-confirm-event"], conn,
            ns(event_id=add["id"]),
        )
        assert is_error(result)


class TestCompleteCateringEvent:
    """food-complete-catering-event"""

    def test_complete_with_final_amount(self, conn, env):
        add = call_action(ACTIONS["food-add-catering-event"], conn,
                          ns(company_id=env["company_id"],
                             event_name="Complete Test", client_name="Z",
                             event_date="2026-11-01", quoted_price="2000.00"))
        assert is_ok(add)
        # Confirm first
        call_action(ACTIONS["food-confirm-event"], conn,
                     ns(event_id=add["id"]))
        result = call_action(
            ACTIONS["food-complete-catering-event"], conn,
            ns(event_id=add["id"], final_amount="2500.00"),
        )
        assert is_ok(result), result
        assert result["event_status"] == "completed"
        assert result["final_amount"] == "2500.00"

    def test_complete_with_quoted_price(self, conn, env):
        add = call_action(ACTIONS["food-add-catering-event"], conn,
                          ns(company_id=env["company_id"],
                             event_name="QP Test", client_name="W",
                             event_date="2026-11-02", quoted_price="1500.00"))
        assert is_ok(add)
        call_action(ACTIONS["food-confirm-event"], conn,
                     ns(event_id=add["id"]))
        result = call_action(
            ACTIONS["food-complete-catering-event"], conn,
            ns(event_id=add["id"]),
        )
        assert is_ok(result), result
        assert result["final_amount"] == "1500.00"

    def test_complete_from_inquiry_fails(self, conn, env):
        add = call_action(ACTIONS["food-add-catering-event"], conn,
                          ns(company_id=env["company_id"],
                             event_name="Fail Test", client_name="F",
                             event_date="2026-11-03", quoted_price="1000.00"))
        assert is_ok(add)
        result = call_action(
            ACTIONS["food-complete-catering-event"], conn,
            ns(event_id=add["id"], final_amount="1000.00"),
        )
        assert is_error(result)


class TestCateringCostEstimate:
    """food-catering-cost-estimate"""

    def test_cost_estimate(self, conn, env):
        add = call_action(ACTIONS["food-add-catering-event"], conn,
                          ns(company_id=env["company_id"],
                             event_name="Cost Est", client_name="C",
                             event_date="2026-12-01", guest_count=100))
        assert is_ok(add)
        call_action(ACTIONS["food-add-catering-item"], conn,
                     ns(event_id=add["id"], item_name="Chicken",
                        quantity=100, unit_price="20.00"))
        call_action(ACTIONS["food-add-catering-item"], conn,
                     ns(event_id=add["id"], item_name="Dessert",
                        quantity=100, unit_price="8.00"))
        result = call_action(
            ACTIONS["food-catering-cost-estimate"], conn,
            ns(event_id=add["id"]),
        )
        assert is_ok(result), result
        # 100*20 + 100*8 = 2000 + 800 = 2800
        assert result["total_cost"] == "2800.00"
        assert result["cost_per_guest"] == "28.00"


# ── HACCP Log Tests ─────────────────────────────────────────────────────────


class TestHaccpLog:
    """food-add-haccp-log / food-list-haccp-logs"""

    def test_add_haccp_log(self, conn, env):
        result = call_action(
            ACTIONS["food-add-haccp-log"], conn,
            ns(company_id=env["company_id"], ccp_name="CCP-1 Cooking",
               log_date="2026-03-10", parameter="Internal Temp",
               measured_value="165", acceptable_range="165-212",
               is_within_range=1, monitored_by="Chef"),
        )
        assert is_ok(result), result
        assert result["ccp_name"] == "CCP-1 Cooking"
        assert result["is_within_range"] == 1

    def test_add_haccp_log_missing_ccp(self, conn, env):
        result = call_action(
            ACTIONS["food-add-haccp-log"], conn,
            ns(company_id=env["company_id"], log_date="2026-03-10"),
        )
        assert is_error(result)

    def test_add_haccp_log_missing_date(self, conn, env):
        result = call_action(
            ACTIONS["food-add-haccp-log"], conn,
            ns(company_id=env["company_id"], ccp_name="CCP-2"),
        )
        assert is_error(result)

    def test_list_haccp_logs(self, conn, env):
        call_action(ACTIONS["food-add-haccp-log"], conn,
                     ns(company_id=env["company_id"], ccp_name="CCP-1",
                        log_date="2026-03-10"))
        result = call_action(
            ACTIONS["food-list-haccp-logs"], conn,
            ns(company_id=env["company_id"]),
        )
        assert is_ok(result), result
        assert result["total_count"] >= 1


# ── Temperature Reading Tests ───────────────────────────────────────────────


class TestTempReading:
    """food-add-temp-reading / food-list-temp-readings"""

    def test_add_temp_reading_safe(self, conn, env):
        result = call_action(
            ACTIONS["food-add-temp-reading"], conn,
            ns(company_id=env["company_id"], equipment_name="Walk-in Cooler",
               reading_date="2026-03-10", temperature="38",
               safe_min="32", safe_max="40", temp_unit="F"),
        )
        assert is_ok(result), result
        assert result["is_safe"] == 1

    def test_add_temp_reading_unsafe(self, conn, env):
        result = call_action(
            ACTIONS["food-add-temp-reading"], conn,
            ns(company_id=env["company_id"], equipment_name="Freezer",
               reading_date="2026-03-10", temperature="10",
               safe_min="-5", safe_max="0", temp_unit="F"),
        )
        assert is_ok(result), result
        assert result["is_safe"] == 0

    def test_add_temp_reading_missing_equip(self, conn, env):
        result = call_action(
            ACTIONS["food-add-temp-reading"], conn,
            ns(company_id=env["company_id"], reading_date="2026-03-10",
               temperature="38"),
        )
        assert is_error(result)

    def test_add_temp_reading_missing_temp(self, conn, env):
        result = call_action(
            ACTIONS["food-add-temp-reading"], conn,
            ns(company_id=env["company_id"], equipment_name="Oven",
               reading_date="2026-03-10"),
        )
        assert is_error(result)

    def test_list_temp_readings(self, conn, env):
        call_action(ACTIONS["food-add-temp-reading"], conn,
                     ns(company_id=env["company_id"],
                        equipment_name="Fridge", reading_date="2026-03-10",
                        temperature="35"))
        result = call_action(
            ACTIONS["food-list-temp-readings"], conn,
            ns(company_id=env["company_id"]),
        )
        assert is_ok(result), result
        assert result["total_count"] >= 1


# ── Inspection Tests ────────────────────────────────────────────────────────


class TestAddInspection:
    """food-add-inspection"""

    def test_add_inspection_ok(self, conn, env):
        result = call_action(
            ACTIONS["food-add-inspection"], conn,
            ns(company_id=env["company_id"], inspection_date="2026-03-10",
               inspection_type="health_dept", inspector_name="Inspector Bob",
               score="95", max_score="100", grade="A"),
        )
        assert is_ok(result), result
        assert result["inspection_type"] == "health_dept"
        assert result["inspection_status"] == "scheduled"

    def test_add_inspection_missing_date(self, conn, env):
        result = call_action(
            ACTIONS["food-add-inspection"], conn,
            ns(company_id=env["company_id"]),
        )
        assert is_error(result)


class TestUpdateInspection:
    """food-update-inspection"""

    def test_update_inspection(self, conn, env):
        add = call_action(ACTIONS["food-add-inspection"], conn,
                          ns(company_id=env["company_id"],
                             inspection_date="2026-03-10"))
        assert is_ok(add)
        result = call_action(
            ACTIONS["food-update-inspection"], conn,
            ns(inspection_id=add["id"], inspection_status="in_progress",
               findings="Minor violations found"),
        )
        assert is_ok(result), result
        assert "inspection_status" in result["updated_fields"]
        assert "findings" in result["updated_fields"]


class TestListInspections:
    """food-list-inspections"""

    def test_list_inspections(self, conn, env):
        call_action(ACTIONS["food-add-inspection"], conn,
                     ns(company_id=env["company_id"],
                        inspection_date="2026-03-10"))
        result = call_action(
            ACTIONS["food-list-inspections"], conn,
            ns(company_id=env["company_id"]),
        )
        assert is_ok(result), result
        assert result["total_count"] >= 1


class TestCompleteInspection:
    """food-complete-inspection"""

    def test_complete_inspection(self, conn, env):
        add = call_action(ACTIONS["food-add-inspection"], conn,
                          ns(company_id=env["company_id"],
                             inspection_date="2026-03-10",
                             inspection_type="internal"))
        assert is_ok(add)
        result = call_action(
            ACTIONS["food-complete-inspection"], conn,
            ns(inspection_id=add["id"], score="92", grade="A-"),
        )
        assert is_ok(result), result
        assert result["inspection_status"] == "completed"
        assert result["score"] == "92"
        assert result["grade"] == "A-"

    def test_complete_already_completed(self, conn, env):
        add = call_action(ACTIONS["food-add-inspection"], conn,
                          ns(company_id=env["company_id"],
                             inspection_date="2026-03-10"))
        assert is_ok(add)
        call_action(ACTIONS["food-complete-inspection"], conn,
                     ns(inspection_id=add["id"], score="90"))
        result = call_action(
            ACTIONS["food-complete-inspection"], conn,
            ns(inspection_id=add["id"], score="95"),
        )
        assert is_error(result)


# ── Temp Violation Alert / HACCP Compliance ─────────────────────────────────


class TestTempViolationAlert:
    """food-temp-violation-alert"""

    def test_temp_violation_alert(self, conn, env):
        # Create a safe reading and an unsafe one
        call_action(ACTIONS["food-add-temp-reading"], conn,
                     ns(company_id=env["company_id"],
                        equipment_name="Cooler", reading_date="2026-03-10",
                        temperature="36", safe_min="32", safe_max="40"))
        call_action(ACTIONS["food-add-temp-reading"], conn,
                     ns(company_id=env["company_id"],
                        equipment_name="Freezer", reading_date="2026-03-10",
                        temperature="15", safe_min="-5", safe_max="0"))
        result = call_action(
            ACTIONS["food-temp-violation-alert"], conn,
            ns(company_id=env["company_id"]),
        )
        assert is_ok(result), result
        # Only the freezer reading should be flagged
        assert result["total_count"] == 1
        assert result["items"][0]["equipment_name"] == "Freezer"


class TestHaccpComplianceReport:
    """food-haccp-compliance-report"""

    def test_compliance_report(self, conn, env):
        # Add some within-range and out-of-range logs
        call_action(ACTIONS["food-add-haccp-log"], conn,
                     ns(company_id=env["company_id"], ccp_name="CCP-1",
                        log_date="2026-03-10", is_within_range=1))
        call_action(ACTIONS["food-add-haccp-log"], conn,
                     ns(company_id=env["company_id"], ccp_name="CCP-1",
                        log_date="2026-03-10", is_within_range=1))
        call_action(ACTIONS["food-add-haccp-log"], conn,
                     ns(company_id=env["company_id"], ccp_name="CCP-2",
                        log_date="2026-03-10", is_within_range=0))
        result = call_action(
            ACTIONS["food-haccp-compliance-report"], conn,
            ns(company_id=env["company_id"]),
        )
        assert is_ok(result), result
        assert result["total_logs"] == 3
        assert result["within_range"] == 2
        assert result["out_of_range"] == 1
        # 2/3 * 100 = 66.67
        assert result["compliance_pct"] == "66.67"
        assert len(result["ccp_breakdown"]) == 2
