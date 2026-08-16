#!/usr/bin/env python3
"""FoodClaw schema extension — adds domain tables to the shared database.

AI-native restaurant & food service management.
21 tables across 7 domains: menu, recipes, inventory, staff, catering,
food safety, franchise.

Prerequisite: ERPClaw init_db.py must have run first (creates foundation tables).
Run: python3 init_db.py [db_path]

ADR-0034 phase 2 bulk-39. Schema declared as metadata and provisioned through
`erpclaw_lib.seam`, which emits dialect-correct DDL, replacing a hand-written
``CREATE TABLE`` block opened with ``sqlite3.connect`` that could not run on
PostgreSQL at all. Conversion rules are the pilot's (`erpclaw-esign`): seam
vocabulary only, and every amount this vertical carries — menu and modifier
prices, recipe and ingredient costs, waste cost, purchase-order and catering
totals, hourly rates and tips, franchise royalties — stays TEXT. So do the
quantities that shipped as TEXT (recipe batch size, expected yield, par levels,
stock counts, waste quantity): they are transcribed as they shipped, not
"corrected" to a numeric type, while the counts that shipped as INTEGER
(portions per batch, guest counts, catering line quantity, prep/cook minutes,
sort orders, 0/1 flags) stay INTEGER.

The pre-conversion docstring said "20 tables"; so did the comment at the head of
the DDL block. Both were stale — the per-domain breakdown beneath them already
summed to 21, and the installer creates 21. Corrected here rather than carried.

Convention (unchanged): TEXT for IDs (UUID4), TEXT for money (Decimal),
TEXT for dates (ISO 8601), INTEGER for booleans (0/1).
"""
import importlib.util
import os
import sys

# Bootstrap the shared lib only when it is not already reachable — an
# unconditional insert at position 0 overrides a caller that deliberately bound a
# different tree (ADR-0034 phase 2 step 2d).
if importlib.util.find_spec("erpclaw_lib") is None:
    sys.path.insert(0, os.path.join(os.path.expanduser(
        os.environ.get("ERPCLAW_HOME", "~/.openclaw/erpclaw")), "lib"))

from erpclaw_lib.seam import (  # noqa: E402
    CheckConstraint, Column, ForeignKey, Index, Integer, MetaData, Table, Text,
    provision, reference_table, text,
)

DEFAULT_DB_PATH = os.path.join(os.path.expanduser(os.environ.get("ERPCLAW_HOME", "~/.openclaw/erpclaw")), "data.sqlite")
DISPLAY_NAME = "FoodClaw"

# Foundation tables that must exist before FoodClaw can install
REQUIRED_FOUNDATION = [
    "company", "employee", "naming_series",
]

METADATA = MetaData()

# Foundation tables this module points at but does not own. Declared for foreign
# key resolution only and never created here — see `seam.reference_table`. Only
# two of FoodClaw's cross-module columns actually carry a REFERENCES clause;
# `company_id`, the catering/royalty account and cost-center columns, and
# `foodclaw_shift.employee_id` never did, and that asymmetry is transcribed as
# it shipped rather than tidied up.
reference_table("supplier", METADATA)
reference_table("employee", METADATA)

# ==================================================================
# DOMAIN 1: MENU (4 tables)
# ==================================================================

# ---------------------------------------------------------------------------
# 1. foodclaw_menu
# ---------------------------------------------------------------------------
MENU = Table(
    "foodclaw_menu", METADATA,
    Column("id", Text, primary_key=True, nullable=True),
    Column("naming_series", Text),
    Column("company_id", Text, nullable=False),
    Column("name", Text, nullable=False),
    Column("description", Text),
    Column("menu_type", Text, server_default=text("'regular'")),
    Column("is_active", Integer, server_default=text("1")),
    Column("effective_date", Text),
    Column("end_date", Text),
    Column("created_at", Text, server_default=text("CURRENT_TIMESTAMP")),
    Column("updated_at", Text, server_default=text("CURRENT_TIMESTAMP")),
    CheckConstraint(
        "menu_type IN ('regular','brunch','lunch','dinner','happy_hour',"
        "'seasonal','catering','kids','other')",
        name="ck_foodclaw_menu_menu_type"),
)

Index("idx_foodclaw_menu_company", MENU.c.company_id)

# ---------------------------------------------------------------------------
# 2. foodclaw_menu_item
# ---------------------------------------------------------------------------
MENU_ITEM = Table(
    "foodclaw_menu_item", METADATA,
    Column("id", Text, primary_key=True, nullable=True),
    Column("naming_series", Text),
    Column("company_id", Text, nullable=False),
    Column("menu_id", Text),
    Column("name", Text, nullable=False),
    Column("description", Text),
    Column("category", Text, server_default=text("'other'")),
    Column("price", Text, nullable=False, server_default=text("'0.00'")),
    Column("cost", Text, server_default=text("'0.00'")),
    Column("allergens", Text),
    Column("nutrition_info", Text),
    Column("is_available", Integer, server_default=text("1")),
    Column("is_vegetarian", Integer, server_default=text("0")),
    Column("is_vegan", Integer, server_default=text("0")),
    Column("is_gluten_free", Integer, server_default=text("0")),
    Column("prep_time_min", Integer),
    Column("calories", Integer),
    Column("sort_order", Integer, server_default=text("0")),
    Column("image_url", Text),
    Column("created_at", Text, server_default=text("CURRENT_TIMESTAMP")),
    Column("updated_at", Text, server_default=text("CURRENT_TIMESTAMP")),
    CheckConstraint(
        "category IN ('appetizer','entree','dessert','beverage','side','soup',"
        "'salad','other')",
        name="ck_foodclaw_menu_item_category"),
)

Index("idx_foodclaw_menu_item_menu", MENU_ITEM.c.menu_id)
Index("idx_foodclaw_menu_item_company", MENU_ITEM.c.company_id)
Index("idx_foodclaw_menu_item_category", MENU_ITEM.c.category)

# ---------------------------------------------------------------------------
# 3. foodclaw_modifier_group
# ---------------------------------------------------------------------------
MODIFIER_GROUP = Table(
    "foodclaw_modifier_group", METADATA,
    Column("id", Text, primary_key=True, nullable=True),
    Column("company_id", Text, nullable=False),
    Column("name", Text, nullable=False),
    Column("description", Text),
    Column("min_selections", Integer, server_default=text("0")),
    Column("max_selections", Integer, server_default=text("1")),
    Column("is_required", Integer, server_default=text("0")),
    Column("menu_item_id", Text),
    Column("created_at", Text, server_default=text("CURRENT_TIMESTAMP")),
    Column("updated_at", Text, server_default=text("CURRENT_TIMESTAMP")),
)

Index("idx_foodclaw_mod_group_item", MODIFIER_GROUP.c.menu_item_id)

# ---------------------------------------------------------------------------
# 4. foodclaw_modifier
# ---------------------------------------------------------------------------
MODIFIER = Table(
    "foodclaw_modifier", METADATA,
    Column("id", Text, primary_key=True, nullable=True),
    Column("company_id", Text, nullable=False),
    Column("modifier_group_id", Text, nullable=False),
    Column("name", Text, nullable=False),
    Column("price_adjustment", Text, server_default=text("'0.00'")),
    Column("is_default", Integer, server_default=text("0")),
    Column("is_available", Integer, server_default=text("1")),
    Column("sort_order", Integer, server_default=text("0")),
    Column("created_at", Text, server_default=text("CURRENT_TIMESTAMP")),
    Column("updated_at", Text, server_default=text("CURRENT_TIMESTAMP")),
)

Index("idx_foodclaw_modifier_group", MODIFIER.c.modifier_group_id)

# ==================================================================
# DOMAIN 2: RECIPE (2 tables)
# ==================================================================

# ---------------------------------------------------------------------------
# 5. foodclaw_recipe
# ---------------------------------------------------------------------------
RECIPE = Table(
    "foodclaw_recipe", METADATA,
    Column("id", Text, primary_key=True, nullable=True),
    Column("naming_series", Text),
    Column("company_id", Text, nullable=False),
    Column("name", Text, nullable=False),
    Column("product_name", Text),
    Column("description", Text),
    # No CHECK on this `category`, unlike foodclaw_menu_item.category and
    # foodclaw_ingredient.category. Preserved as shipped.
    Column("category", Text),
    Column("batch_size", Text, server_default=text("'1'")),
    Column("batch_unit", Text, server_default=text("'portion'")),
    Column("expected_yield_pct", Text, server_default=text("'100.00'")),
    Column("total_cost", Text, server_default=text("'0.00'")),
    Column("cost_per_portion", Text, server_default=text("'0.00'")),
    Column("portions_per_batch", Integer, server_default=text("1")),
    Column("prep_time_min", Integer),
    Column("cook_time_min", Integer),
    Column("instructions", Text),
    Column("menu_item_id", Text),
    Column("status", Text, server_default=text("'active'")),
    Column("created_at", Text, server_default=text("CURRENT_TIMESTAMP")),
    Column("updated_at", Text, server_default=text("CURRENT_TIMESTAMP")),
    CheckConstraint("status IN ('active','inactive','archived')",
                    name="ck_foodclaw_recipe_status"),
)

Index("idx_foodclaw_recipe_company", RECIPE.c.company_id)
Index("idx_foodclaw_recipe_menu_item", RECIPE.c.menu_item_id)

# ---------------------------------------------------------------------------
# 6. foodclaw_recipe_ingredient
# ---------------------------------------------------------------------------
RECIPE_INGREDIENT = Table(
    "foodclaw_recipe_ingredient", METADATA,
    Column("id", Text, primary_key=True, nullable=True),
    Column("recipe_id", Text, nullable=False),
    Column("ingredient_id", Text),
    Column("ingredient_name", Text, nullable=False),
    Column("quantity", Text, nullable=False, server_default=text("'0'")),
    Column("unit", Text, server_default=text("'unit'")),
    Column("unit_cost", Text, server_default=text("'0.00'")),
    Column("line_cost", Text, server_default=text("'0.00'")),
    Column("notes", Text),
    Column("sort_order", Integer, server_default=text("0")),
    Column("created_at", Text, server_default=text("CURRENT_TIMESTAMP")),
    Column("updated_at", Text, server_default=text("CURRENT_TIMESTAMP")),
)

Index("idx_foodclaw_recipe_ing_recipe", RECIPE_INGREDIENT.c.recipe_id)
Index("idx_foodclaw_recipe_ing_ingredient", RECIPE_INGREDIENT.c.ingredient_id)

# ==================================================================
# DOMAIN 3: INVENTORY (4 tables)
# ==================================================================

# ---------------------------------------------------------------------------
# 7. foodclaw_ingredient
# ---------------------------------------------------------------------------
INGREDIENT = Table(
    "foodclaw_ingredient", METADATA,
    Column("id", Text, primary_key=True, nullable=True),
    Column("naming_series", Text),
    Column("company_id", Text, nullable=False),
    Column("name", Text, nullable=False),
    Column("category", Text, server_default=text("'other'")),
    Column("unit", Text, server_default=text("'unit'")),
    Column("par_level", Text, server_default=text("'0'")),
    Column("current_stock", Text, server_default=text("'0'")),
    Column("unit_cost", Text, server_default=text("'0.00'")),
    # A free-text supplier name, not a foreign key — foodclaw_purchase_order
    # carries the real `supplier_id` reference. Preserved as shipped.
    Column("supplier", Text),
    Column("is_perishable", Integer, server_default=text("0")),
    Column("expiry_date", Text),
    Column("reorder_point", Text, server_default=text("'0'")),
    Column("storage_location", Text),
    Column("status", Text, server_default=text("'active'")),
    Column("created_at", Text, server_default=text("CURRENT_TIMESTAMP")),
    Column("updated_at", Text, server_default=text("CURRENT_TIMESTAMP")),
    CheckConstraint(
        "category IN ('produce','protein','dairy','dry_goods','frozen',"
        "'beverage','spice','oil','other')",
        name="ck_foodclaw_ingredient_category"),
    CheckConstraint("status IN ('active','inactive','discontinued')",
                    name="ck_foodclaw_ingredient_status"),
)

Index("idx_foodclaw_ingredient_company", INGREDIENT.c.company_id)
Index("idx_foodclaw_ingredient_category", INGREDIENT.c.category)

# ---------------------------------------------------------------------------
# 8. foodclaw_stock_count
# ---------------------------------------------------------------------------
STOCK_COUNT = Table(
    "foodclaw_stock_count", METADATA,
    Column("id", Text, primary_key=True, nullable=True),
    Column("company_id", Text, nullable=False),
    Column("ingredient_id", Text, nullable=False),
    Column("count_date", Text, nullable=False),
    Column("counted_qty", Text, nullable=False, server_default=text("'0'")),
    Column("system_qty", Text, server_default=text("'0'")),
    Column("variance", Text, server_default=text("'0'")),
    Column("counted_by", Text),
    Column("notes", Text),
    Column("created_at", Text, server_default=text("CURRENT_TIMESTAMP")),
)

Index("idx_foodclaw_stock_count_ingredient", STOCK_COUNT.c.ingredient_id)
Index("idx_foodclaw_stock_count_date", STOCK_COUNT.c.count_date)

# ---------------------------------------------------------------------------
# 9. foodclaw_waste_log
# ---------------------------------------------------------------------------
WASTE_LOG = Table(
    "foodclaw_waste_log", METADATA,
    Column("id", Text, primary_key=True, nullable=True),
    Column("company_id", Text, nullable=False),
    Column("ingredient_id", Text),
    Column("item_name", Text, nullable=False),
    Column("waste_date", Text, nullable=False),
    Column("quantity", Text, nullable=False, server_default=text("'0'")),
    Column("unit", Text, server_default=text("'unit'")),
    Column("reason", Text, server_default=text("'expired'")),
    Column("cost", Text, server_default=text("'0.00'")),
    Column("logged_by", Text),
    Column("notes", Text),
    Column("created_at", Text, server_default=text("CURRENT_TIMESTAMP")),
    CheckConstraint(
        "reason IN ('expired','spoiled','overproduction','damaged',"
        "'prep_waste','plate_waste','other')",
        name="ck_foodclaw_waste_log_reason"),
)

Index("idx_foodclaw_waste_log_company", WASTE_LOG.c.company_id)
Index("idx_foodclaw_waste_log_date", WASTE_LOG.c.waste_date)

# ---------------------------------------------------------------------------
# 10. foodclaw_purchase_order
# ---------------------------------------------------------------------------
PURCHASE_ORDER = Table(
    "foodclaw_purchase_order", METADATA,
    Column("id", Text, primary_key=True, nullable=True),
    Column("naming_series", Text),
    Column("company_id", Text, nullable=False),
    Column("supplier_id", Text, ForeignKey("supplier.id"), nullable=False),
    Column("order_date", Text, nullable=False),
    Column("expected_date", Text),
    Column("total_amount", Text, server_default=text("'0.00'")),
    Column("order_status", Text, server_default=text("'draft'")),
    Column("notes", Text),
    Column("items_json", Text),
    Column("created_at", Text, server_default=text("CURRENT_TIMESTAMP")),
    Column("updated_at", Text, server_default=text("CURRENT_TIMESTAMP")),
    CheckConstraint(
        "order_status IN ('draft','sent','received','partial','cancelled')",
        name="ck_foodclaw_purchase_order_order_status"),
)

Index("idx_foodclaw_po_company", PURCHASE_ORDER.c.company_id)
Index("idx_foodclaw_po_status", PURCHASE_ORDER.c.order_status)

# ==================================================================
# DOMAIN 4: STAFF (3 tables)
# ==================================================================

# ---------------------------------------------------------------------------
# 11. foodclaw_employee
# ---------------------------------------------------------------------------
FOODCLAW_EMPLOYEE = Table(
    "foodclaw_employee", METADATA,
    Column("id", Text, primary_key=True, nullable=True),
    Column("naming_series", Text),
    Column("company_id", Text, nullable=False),
    Column("employee_id", Text, ForeignKey("employee.id"), nullable=False),
    Column("role", Text, server_default=text("'staff'")),
    Column("hourly_rate", Text, server_default=text("'0.00'")),
    Column("status", Text, server_default=text("'active'")),
    Column("certifications", Text),
    Column("created_at", Text, server_default=text("CURRENT_TIMESTAMP")),
    Column("updated_at", Text, server_default=text("CURRENT_TIMESTAMP")),
    CheckConstraint(
        "role IN ('manager','chef','sous_chef','line_cook','prep_cook',"
        "'server','bartender','host','busser','dishwasher','delivery',"
        "'cashier','staff','other')",
        name="ck_foodclaw_employee_role"),
    CheckConstraint("status IN ('active','inactive','terminated')",
                    name="ck_foodclaw_employee_status"),
)

Index("idx_foodclaw_employee_company", FOODCLAW_EMPLOYEE.c.company_id)
Index("idx_foodclaw_employee_role", FOODCLAW_EMPLOYEE.c.role)
# UNIQUE: one FoodClaw staff row per core employee. A uniqueness guarantee, not a
# lookup hint — the `unique=True` is the whole point of this index.
Index("idx_foodclaw_employee_empid", FOODCLAW_EMPLOYEE.c.employee_id, unique=True)

# ---------------------------------------------------------------------------
# 12. foodclaw_shift
# ---------------------------------------------------------------------------
SHIFT = Table(
    "foodclaw_shift", METADATA,
    Column("id", Text, primary_key=True, nullable=True),
    Column("company_id", Text, nullable=False),
    # No FK, unlike foodclaw_employee.employee_id and unlike
    # foodclaw_tip_distribution's column of the same name. Preserved as shipped.
    Column("employee_id", Text, nullable=False),
    Column("shift_date", Text, nullable=False),
    Column("start_time", Text, nullable=False),
    Column("end_time", Text),
    Column("role_assigned", Text),
    Column("clock_in_time", Text),
    Column("clock_out_time", Text),
    Column("break_minutes", Integer, server_default=text("0")),
    Column("hours_worked", Text, server_default=text("'0.00'")),
    Column("shift_status", Text, server_default=text("'scheduled'")),
    Column("notes", Text),
    Column("created_at", Text, server_default=text("CURRENT_TIMESTAMP")),
    Column("updated_at", Text, server_default=text("CURRENT_TIMESTAMP")),
    CheckConstraint(
        "shift_status IN ('scheduled','clocked_in','clocked_out','no_show',"
        "'cancelled')",
        name="ck_foodclaw_shift_shift_status"),
)

Index("idx_foodclaw_shift_employee", SHIFT.c.employee_id)
Index("idx_foodclaw_shift_date", SHIFT.c.shift_date)

# ---------------------------------------------------------------------------
# 13. foodclaw_tip_distribution
# ---------------------------------------------------------------------------
TIP_DISTRIBUTION = Table(
    "foodclaw_tip_distribution", METADATA,
    Column("id", Text, primary_key=True, nullable=True),
    Column("company_id", Text, nullable=False),
    Column("employee_id", Text, nullable=False),
    Column("shift_id", Text),
    Column("tip_date", Text, nullable=False),
    Column("cash_tips", Text, server_default=text("'0.00'")),
    Column("credit_tips", Text, server_default=text("'0.00'")),
    Column("tip_pool_share", Text, server_default=text("'0.00'")),
    Column("total_tips", Text, server_default=text("'0.00'")),
    Column("notes", Text),
    Column("created_at", Text, server_default=text("CURRENT_TIMESTAMP")),
)

Index("idx_foodclaw_tips_employee", TIP_DISTRIBUTION.c.employee_id)
Index("idx_foodclaw_tips_date", TIP_DISTRIBUTION.c.tip_date)

# ==================================================================
# DOMAIN 5: CATERING (3 tables)
# ==================================================================

# ---------------------------------------------------------------------------
# 14. foodclaw_catering_event
# ---------------------------------------------------------------------------
CATERING_EVENT = Table(
    "foodclaw_catering_event", METADATA,
    Column("id", Text, primary_key=True, nullable=True),
    Column("naming_series", Text),
    Column("company_id", Text, nullable=False),
    Column("event_name", Text, nullable=False),
    Column("client_name", Text, nullable=False),
    Column("client_phone", Text),
    Column("client_email", Text),
    Column("event_date", Text, nullable=False),
    Column("event_time", Text),
    Column("venue", Text),
    Column("guest_count", Integer, server_default=text("0")),
    Column("event_status", Text, server_default=text("'inquiry'")),
    Column("estimated_cost", Text, server_default=text("'0.00'")),
    Column("quoted_price", Text, server_default=text("'0.00'")),
    Column("deposit_amount", Text, server_default=text("'0.00'")),
    Column("final_amount", Text, server_default=text("'0.00'")),
    # GL wiring, carried without foreign keys as it shipped.
    Column("revenue_account_id", Text),
    Column("receivable_account_id", Text),
    Column("cost_center_id", Text),
    Column("gl_entry_ids", Text),
    Column("notes", Text),
    Column("created_at", Text, server_default=text("CURRENT_TIMESTAMP")),
    Column("updated_at", Text, server_default=text("CURRENT_TIMESTAMP")),
    CheckConstraint(
        "event_status IN ('inquiry','quoted','confirmed','in_progress',"
        "'completed','cancelled')",
        name="ck_foodclaw_catering_event_event_status"),
)

Index("idx_foodclaw_catering_company", CATERING_EVENT.c.company_id)
Index("idx_foodclaw_catering_date", CATERING_EVENT.c.event_date)
Index("idx_foodclaw_catering_status", CATERING_EVENT.c.event_status)

# ---------------------------------------------------------------------------
# 15. foodclaw_catering_item
# ---------------------------------------------------------------------------
CATERING_ITEM = Table(
    "foodclaw_catering_item", METADATA,
    Column("id", Text, primary_key=True, nullable=True),
    Column("event_id", Text, nullable=False),
    Column("menu_item_id", Text),
    Column("item_name", Text, nullable=False),
    # INTEGER here — a headcount of plated portions — where the recipe and waste
    # `quantity` columns are TEXT. Both spellings are transcribed as they shipped.
    Column("quantity", Integer, server_default=text("1")),
    Column("unit_price", Text, server_default=text("'0.00'")),
    Column("line_total", Text, server_default=text("'0.00'")),
    Column("notes", Text),
    Column("created_at", Text, server_default=text("CURRENT_TIMESTAMP")),
)

Index("idx_foodclaw_catering_item_event", CATERING_ITEM.c.event_id)

# ---------------------------------------------------------------------------
# 16. foodclaw_dietary_requirement
# ---------------------------------------------------------------------------
DIETARY_REQUIREMENT = Table(
    "foodclaw_dietary_requirement", METADATA,
    Column("id", Text, primary_key=True, nullable=True),
    Column("event_id", Text, nullable=False),
    Column("requirement", Text, nullable=False),
    Column("guest_count", Integer, server_default=text("1")),
    Column("notes", Text),
    Column("created_at", Text, server_default=text("CURRENT_TIMESTAMP")),
)

Index("idx_foodclaw_dietary_event", DIETARY_REQUIREMENT.c.event_id)

# ==================================================================
# DOMAIN 6: FOOD SAFETY (3 tables)
# ==================================================================

# ---------------------------------------------------------------------------
# 17. foodclaw_haccp_log
# ---------------------------------------------------------------------------
HACCP_LOG = Table(
    "foodclaw_haccp_log", METADATA,
    Column("id", Text, primary_key=True, nullable=True),
    Column("company_id", Text, nullable=False),
    Column("ccp_name", Text, nullable=False),
    Column("log_date", Text, nullable=False),
    Column("log_time", Text),
    Column("monitored_by", Text),
    Column("parameter", Text),
    Column("measured_value", Text),
    Column("acceptable_range", Text),
    Column("is_within_range", Integer, server_default=text("1")),
    Column("corrective_action", Text),
    Column("notes", Text),
    Column("created_at", Text, server_default=text("CURRENT_TIMESTAMP")),
)

Index("idx_foodclaw_haccp_company", HACCP_LOG.c.company_id)
Index("idx_foodclaw_haccp_date", HACCP_LOG.c.log_date)

# ---------------------------------------------------------------------------
# 18. foodclaw_temp_reading
# ---------------------------------------------------------------------------
TEMP_READING = Table(
    "foodclaw_temp_reading", METADATA,
    Column("id", Text, primary_key=True, nullable=True),
    Column("company_id", Text, nullable=False),
    Column("equipment_name", Text, nullable=False),
    Column("location", Text),
    Column("reading_date", Text, nullable=False),
    Column("reading_time", Text),
    Column("temperature", Text, nullable=False),
    Column("temp_unit", Text, server_default=text("'F'")),
    Column("safe_min", Text),
    Column("safe_max", Text),
    Column("is_safe", Integer, server_default=text("1")),
    Column("recorded_by", Text),
    Column("corrective_action", Text),
    Column("created_at", Text, server_default=text("CURRENT_TIMESTAMP")),
    CheckConstraint("temp_unit IN ('F','C')",
                    name="ck_foodclaw_temp_reading_temp_unit"),
)

Index("idx_foodclaw_temp_company", TEMP_READING.c.company_id)
Index("idx_foodclaw_temp_date", TEMP_READING.c.reading_date)

# ---------------------------------------------------------------------------
# 19. foodclaw_inspection
# ---------------------------------------------------------------------------
INSPECTION = Table(
    "foodclaw_inspection", METADATA,
    Column("id", Text, primary_key=True, nullable=True),
    Column("naming_series", Text),
    Column("company_id", Text, nullable=False),
    Column("inspection_type", Text, server_default=text("'routine'")),
    Column("inspector_name", Text),
    Column("inspection_date", Text, nullable=False),
    Column("score", Text),
    Column("max_score", Text, server_default=text("'100'")),
    Column("grade", Text),
    Column("findings", Text),
    Column("corrective_actions", Text),
    Column("follow_up_date", Text),
    Column("inspection_status", Text, server_default=text("'scheduled'")),
    Column("notes", Text),
    Column("created_at", Text, server_default=text("CURRENT_TIMESTAMP")),
    Column("updated_at", Text, server_default=text("CURRENT_TIMESTAMP")),
    CheckConstraint(
        "inspection_type IN ('routine','health_dept','internal','fire',"
        "'third_party','other')",
        name="ck_foodclaw_inspection_inspection_type"),
    CheckConstraint(
        "inspection_status IN ('scheduled','in_progress','completed','failed',"
        "'follow_up')",
        name="ck_foodclaw_inspection_inspection_status"),
)

Index("idx_foodclaw_inspection_company", INSPECTION.c.company_id)
Index("idx_foodclaw_inspection_date", INSPECTION.c.inspection_date)

# ==================================================================
# DOMAIN 7: FRANCHISE (2 tables)
# ==================================================================

# ---------------------------------------------------------------------------
# 20. foodclaw_franchise_unit
# ---------------------------------------------------------------------------
FRANCHISE_UNIT = Table(
    "foodclaw_franchise_unit", METADATA,
    Column("id", Text, primary_key=True, nullable=True),
    Column("naming_series", Text),
    Column("company_id", Text, nullable=False),
    Column("unit_name", Text, nullable=False),
    Column("unit_code", Text),
    Column("address", Text),
    Column("city", Text),
    Column("state", Text),
    Column("zip_code", Text),
    Column("manager_name", Text),
    Column("phone", Text),
    Column("open_date", Text),
    Column("status", Text, server_default=text("'active'")),
    Column("created_at", Text, server_default=text("CURRENT_TIMESTAMP")),
    Column("updated_at", Text, server_default=text("CURRENT_TIMESTAMP")),
    CheckConstraint(
        "status IN ('active','inactive','closed','under_construction')",
        name="ck_foodclaw_franchise_unit_status"),
)

Index("idx_foodclaw_franchise_company", FRANCHISE_UNIT.c.company_id)

# ---------------------------------------------------------------------------
# 21. foodclaw_royalty_entry
# ---------------------------------------------------------------------------
ROYALTY_ENTRY = Table(
    "foodclaw_royalty_entry", METADATA,
    Column("id", Text, primary_key=True, nullable=True),
    Column("naming_series", Text),
    Column("company_id", Text, nullable=False),
    Column("franchise_unit_id", Text, nullable=False),
    Column("period_start", Text, nullable=False),
    Column("period_end", Text, nullable=False),
    Column("gross_revenue", Text, server_default=text("'0.00'")),
    # A rate, not an amount, but TEXT for the same reason every amount is:
    # Decimal in, Decimal out, no float anywhere on the royalty calculation.
    Column("royalty_rate", Text, server_default=text("'0.00'")),
    Column("royalty_amount", Text, server_default=text("'0.00'")),
    Column("marketing_fee", Text, server_default=text("'0.00'")),
    Column("total_due", Text, server_default=text("'0.00'")),
    Column("payment_status", Text, server_default=text("'pending'")),
    Column("royalty_income_account_id", Text),
    Column("royalty_receivable_account_id", Text),
    Column("marketing_expense_account_id", Text),
    Column("cost_center_id", Text),
    Column("gl_entry_ids", Text),
    Column("notes", Text),
    Column("created_at", Text, server_default=text("CURRENT_TIMESTAMP")),
    CheckConstraint("payment_status IN ('pending','paid','overdue')",
                    name="ck_foodclaw_royalty_entry_payment_status"),
)

Index("idx_foodclaw_royalty_unit", ROYALTY_ENTRY.c.franchise_unit_id)
Index("idx_foodclaw_royalty_period",
      ROYALTY_ENTRY.c.period_start, ROYALTY_ENTRY.c.period_end)


def _require_foundation(db_path):
    """The pre-conversion installer's foundation probe, asked through the seam.

    The original read ``sqlite_master`` directly, so the guard that exists to
    produce a friendly error was itself SQLite-only — on PostgreSQL it raised
    instead of printing. ``seam.table_exists`` answers on both backends
    (ADR-0034 bulk-39). The wording is this module's own, unchanged.
    """
    from erpclaw_lib import seam

    missing = [t for t in REQUIRED_FOUNDATION if not seam.table_exists(t, db_path)]
    if missing:
        print(f"ERROR: Foundation tables missing: {', '.join(missing)}")
        print("Run erpclaw-setup first: clawhub install erpclaw-setup")
        sys.exit(1)


def init_foodclaw_schema(db_path=None):
    """Create FoodClaw tables and indexes on whichever backend is configured.

    Same contract as before the ADR-0034 conversion: idempotent, and the returned
    counts are what was ACTUALLY created rather than what was declared. The old
    body printed a hardcoded "20 tables created" whether it created 21, 0 or
    anything in between; `provision` reports the delta it measured.
    """
    db_path = db_path or DEFAULT_DB_PATH
    _require_foundation(db_path)
    result = provision(METADATA, db_path)
    return {
        "database": db_path,
        "tables": result["tables"],
        "indexes": result["indexes"],
    }


if __name__ == "__main__":
    path = sys.argv[1] if len(sys.argv) > 1 else DEFAULT_DB_PATH
    result = init_foodclaw_schema(path)
    print(f"[{DISPLAY_NAME}] Schema initialized in {result['database']}")
    print(f"  Tables: {result['tables']}")
    print(f"  Indexes: {result['indexes']}")
