#!/usr/bin/env python3
"""FoodClaw schema extension — adds domain tables to the shared database.

AI-native restaurant & food service management.
20 tables across 7 domains: menu, recipes, inventory, staff, catering,
food safety, franchise.

Prerequisite: ERPClaw init_db.py must have run first (creates foundation tables).
Run: python3 init_db.py [db_path]
"""
import os
import sqlite3
import sys
import uuid


DEFAULT_DB_PATH = os.path.expanduser("~/.openclaw/erpclaw/data.sqlite")
DISPLAY_NAME = "FoodClaw"

# Foundation tables that must exist before FoodClaw can install
REQUIRED_FOUNDATION = [
    "company", "employee", "naming_series",
]


def init_foodclaw_schema(db_path=None):
    db_path = db_path or DEFAULT_DB_PATH
    conn = sqlite3.connect(db_path)
    conn.execute("PRAGMA foreign_keys=ON")

    # ── Verify ERPClaw foundation ────────────────────────────────
    tables = [r[0] for r in conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table'"
    ).fetchall()]
    missing = [t for t in REQUIRED_FOUNDATION if t not in tables]
    if missing:
        print(f"ERROR: Foundation tables missing: {', '.join(missing)}")
        print("Run erpclaw-setup first: clawhub install erpclaw-setup")
        conn.close()
        sys.exit(1)

    # ── Create all FoodClaw domain tables ────────────────────────
    conn.executescript("""
        -- ==========================================================
        -- FoodClaw Domain Tables
        -- 20 tables, 7 domains, foodclaw_ prefix
        -- Convention: TEXT for IDs (UUID4), TEXT for money (Decimal),
        --             TEXT for dates (ISO 8601), INTEGER for booleans (0/1)
        -- ==========================================================

        -- ──────────────────────────────────────────────────────────
        -- MENU DOMAIN (4 tables)
        -- ──────────────────────────────────────────────────────────
        CREATE TABLE IF NOT EXISTS foodclaw_menu (
            id              TEXT PRIMARY KEY,
            naming_series   TEXT,
            company_id      TEXT NOT NULL,
            name            TEXT NOT NULL,
            description     TEXT,
            menu_type       TEXT DEFAULT 'regular'
                            CHECK (menu_type IN ('regular','brunch','lunch','dinner','happy_hour','seasonal','catering','kids','other')),
            is_active       INTEGER DEFAULT 1,
            effective_date  TEXT,
            end_date        TEXT,
            created_at      TEXT DEFAULT (datetime('now')),
            updated_at      TEXT DEFAULT (datetime('now'))
        );
        CREATE INDEX IF NOT EXISTS idx_foodclaw_menu_company ON foodclaw_menu(company_id);

        CREATE TABLE IF NOT EXISTS foodclaw_menu_item (
            id              TEXT PRIMARY KEY,
            naming_series   TEXT,
            company_id      TEXT NOT NULL,
            menu_id         TEXT,
            name            TEXT NOT NULL,
            description     TEXT,
            category        TEXT DEFAULT 'other'
                            CHECK (category IN ('appetizer','entree','dessert','beverage','side','soup','salad','other')),
            price           TEXT NOT NULL DEFAULT '0.00',
            cost            TEXT DEFAULT '0.00',
            allergens       TEXT,
            nutrition_info  TEXT,
            is_available    INTEGER DEFAULT 1,
            is_vegetarian   INTEGER DEFAULT 0,
            is_vegan        INTEGER DEFAULT 0,
            is_gluten_free  INTEGER DEFAULT 0,
            prep_time_min   INTEGER,
            calories        INTEGER,
            sort_order      INTEGER DEFAULT 0,
            image_url       TEXT,
            created_at      TEXT DEFAULT (datetime('now')),
            updated_at      TEXT DEFAULT (datetime('now'))
        );
        CREATE INDEX IF NOT EXISTS idx_foodclaw_menu_item_menu ON foodclaw_menu_item(menu_id);
        CREATE INDEX IF NOT EXISTS idx_foodclaw_menu_item_company ON foodclaw_menu_item(company_id);
        CREATE INDEX IF NOT EXISTS idx_foodclaw_menu_item_category ON foodclaw_menu_item(category);

        CREATE TABLE IF NOT EXISTS foodclaw_modifier_group (
            id              TEXT PRIMARY KEY,
            company_id      TEXT NOT NULL,
            name            TEXT NOT NULL,
            description     TEXT,
            min_selections  INTEGER DEFAULT 0,
            max_selections  INTEGER DEFAULT 1,
            is_required     INTEGER DEFAULT 0,
            menu_item_id    TEXT,
            created_at      TEXT DEFAULT (datetime('now')),
            updated_at      TEXT DEFAULT (datetime('now'))
        );
        CREATE INDEX IF NOT EXISTS idx_foodclaw_mod_group_item ON foodclaw_modifier_group(menu_item_id);

        CREATE TABLE IF NOT EXISTS foodclaw_modifier (
            id              TEXT PRIMARY KEY,
            company_id      TEXT NOT NULL,
            modifier_group_id TEXT NOT NULL,
            name            TEXT NOT NULL,
            price_adjustment TEXT DEFAULT '0.00',
            is_default      INTEGER DEFAULT 0,
            is_available    INTEGER DEFAULT 1,
            sort_order      INTEGER DEFAULT 0,
            created_at      TEXT DEFAULT (datetime('now')),
            updated_at      TEXT DEFAULT (datetime('now'))
        );
        CREATE INDEX IF NOT EXISTS idx_foodclaw_modifier_group ON foodclaw_modifier(modifier_group_id);

        -- ──────────────────────────────────────────────────────────
        -- RECIPE DOMAIN (2 tables)
        -- ──────────────────────────────────────────────────────────
        CREATE TABLE IF NOT EXISTS foodclaw_recipe (
            id                  TEXT PRIMARY KEY,
            naming_series       TEXT,
            company_id          TEXT NOT NULL,
            name                TEXT NOT NULL,
            product_name        TEXT,
            description         TEXT,
            category            TEXT,
            batch_size          TEXT DEFAULT '1',
            batch_unit          TEXT DEFAULT 'portion',
            expected_yield_pct  TEXT DEFAULT '100.00',
            total_cost          TEXT DEFAULT '0.00',
            cost_per_portion    TEXT DEFAULT '0.00',
            portions_per_batch  INTEGER DEFAULT 1,
            prep_time_min       INTEGER,
            cook_time_min       INTEGER,
            instructions        TEXT,
            menu_item_id        TEXT,
            status              TEXT DEFAULT 'active'
                                CHECK (status IN ('active','inactive','archived')),
            created_at          TEXT DEFAULT (datetime('now')),
            updated_at          TEXT DEFAULT (datetime('now'))
        );
        CREATE INDEX IF NOT EXISTS idx_foodclaw_recipe_company ON foodclaw_recipe(company_id);
        CREATE INDEX IF NOT EXISTS idx_foodclaw_recipe_menu_item ON foodclaw_recipe(menu_item_id);

        CREATE TABLE IF NOT EXISTS foodclaw_recipe_ingredient (
            id              TEXT PRIMARY KEY,
            recipe_id       TEXT NOT NULL,
            ingredient_id   TEXT,
            ingredient_name TEXT NOT NULL,
            quantity        TEXT NOT NULL DEFAULT '0',
            unit            TEXT DEFAULT 'unit',
            unit_cost       TEXT DEFAULT '0.00',
            line_cost       TEXT DEFAULT '0.00',
            notes           TEXT,
            sort_order      INTEGER DEFAULT 0,
            created_at      TEXT DEFAULT (datetime('now')),
            updated_at      TEXT DEFAULT (datetime('now'))
        );
        CREATE INDEX IF NOT EXISTS idx_foodclaw_recipe_ing_recipe ON foodclaw_recipe_ingredient(recipe_id);
        CREATE INDEX IF NOT EXISTS idx_foodclaw_recipe_ing_ingredient ON foodclaw_recipe_ingredient(ingredient_id);

        -- ──────────────────────────────────────────────────────────
        -- INVENTORY DOMAIN (4 tables)
        -- ──────────────────────────────────────────────────────────
        CREATE TABLE IF NOT EXISTS foodclaw_ingredient (
            id              TEXT PRIMARY KEY,
            naming_series   TEXT,
            company_id      TEXT NOT NULL,
            name            TEXT NOT NULL,
            category        TEXT DEFAULT 'other'
                            CHECK (category IN ('produce','protein','dairy','dry_goods','frozen','beverage','spice','oil','other')),
            unit            TEXT DEFAULT 'unit',
            par_level       TEXT DEFAULT '0',
            current_stock   TEXT DEFAULT '0',
            unit_cost       TEXT DEFAULT '0.00',
            supplier        TEXT,
            is_perishable   INTEGER DEFAULT 0,
            expiry_date     TEXT,
            reorder_point   TEXT DEFAULT '0',
            storage_location TEXT,
            status          TEXT DEFAULT 'active'
                            CHECK (status IN ('active','inactive','discontinued')),
            created_at      TEXT DEFAULT (datetime('now')),
            updated_at      TEXT DEFAULT (datetime('now'))
        );
        CREATE INDEX IF NOT EXISTS idx_foodclaw_ingredient_company ON foodclaw_ingredient(company_id);
        CREATE INDEX IF NOT EXISTS idx_foodclaw_ingredient_category ON foodclaw_ingredient(category);

        CREATE TABLE IF NOT EXISTS foodclaw_stock_count (
            id              TEXT PRIMARY KEY,
            company_id      TEXT NOT NULL,
            ingredient_id   TEXT NOT NULL,
            count_date      TEXT NOT NULL,
            counted_qty     TEXT NOT NULL DEFAULT '0',
            system_qty      TEXT DEFAULT '0',
            variance        TEXT DEFAULT '0',
            counted_by      TEXT,
            notes           TEXT,
            created_at      TEXT DEFAULT (datetime('now'))
        );
        CREATE INDEX IF NOT EXISTS idx_foodclaw_stock_count_ingredient ON foodclaw_stock_count(ingredient_id);
        CREATE INDEX IF NOT EXISTS idx_foodclaw_stock_count_date ON foodclaw_stock_count(count_date);

        CREATE TABLE IF NOT EXISTS foodclaw_waste_log (
            id              TEXT PRIMARY KEY,
            company_id      TEXT NOT NULL,
            ingredient_id   TEXT,
            item_name       TEXT NOT NULL,
            waste_date      TEXT NOT NULL,
            quantity         TEXT NOT NULL DEFAULT '0',
            unit            TEXT DEFAULT 'unit',
            reason          TEXT DEFAULT 'expired'
                            CHECK (reason IN ('expired','spoiled','overproduction','damaged','prep_waste','plate_waste','other')),
            cost            TEXT DEFAULT '0.00',
            logged_by       TEXT,
            notes           TEXT,
            created_at      TEXT DEFAULT (datetime('now'))
        );
        CREATE INDEX IF NOT EXISTS idx_foodclaw_waste_log_company ON foodclaw_waste_log(company_id);
        CREATE INDEX IF NOT EXISTS idx_foodclaw_waste_log_date ON foodclaw_waste_log(waste_date);

        CREATE TABLE IF NOT EXISTS foodclaw_purchase_order (
            id              TEXT PRIMARY KEY,
            naming_series   TEXT,
            company_id      TEXT NOT NULL,
            supplier_id     TEXT NOT NULL REFERENCES supplier(id),
            order_date      TEXT NOT NULL,
            expected_date   TEXT,
            total_amount    TEXT DEFAULT '0.00',
            order_status    TEXT DEFAULT 'draft'
                            CHECK (order_status IN ('draft','sent','received','partial','cancelled')),
            notes           TEXT,
            items_json      TEXT,
            created_at      TEXT DEFAULT (datetime('now')),
            updated_at      TEXT DEFAULT (datetime('now'))
        );
        CREATE INDEX IF NOT EXISTS idx_foodclaw_po_company ON foodclaw_purchase_order(company_id);
        CREATE INDEX IF NOT EXISTS idx_foodclaw_po_status ON foodclaw_purchase_order(order_status);

        -- ──────────────────────────────────────────────────────────
        -- STAFF DOMAIN (3 tables)
        -- ──────────────────────────────────────────────────────────
        CREATE TABLE IF NOT EXISTS foodclaw_employee (
            id              TEXT PRIMARY KEY,
            naming_series   TEXT,
            company_id      TEXT NOT NULL,
            employee_id     TEXT NOT NULL REFERENCES employee(id),
            role            TEXT DEFAULT 'staff'
                            CHECK (role IN ('manager','chef','sous_chef','line_cook','prep_cook','server','bartender','host','busser','dishwasher','delivery','cashier','staff','other')),
            hourly_rate     TEXT DEFAULT '0.00',
            status          TEXT DEFAULT 'active'
                            CHECK (status IN ('active','inactive','terminated')),
            certifications  TEXT,
            created_at      TEXT DEFAULT (datetime('now')),
            updated_at      TEXT DEFAULT (datetime('now'))
        );
        CREATE INDEX IF NOT EXISTS idx_foodclaw_employee_company ON foodclaw_employee(company_id);
        CREATE INDEX IF NOT EXISTS idx_foodclaw_employee_role ON foodclaw_employee(role);
        CREATE UNIQUE INDEX IF NOT EXISTS idx_foodclaw_employee_empid ON foodclaw_employee(employee_id);

        CREATE TABLE IF NOT EXISTS foodclaw_shift (
            id              TEXT PRIMARY KEY,
            company_id      TEXT NOT NULL,
            employee_id     TEXT NOT NULL,
            shift_date      TEXT NOT NULL,
            start_time      TEXT NOT NULL,
            end_time        TEXT,
            role_assigned   TEXT,
            clock_in_time   TEXT,
            clock_out_time  TEXT,
            break_minutes   INTEGER DEFAULT 0,
            hours_worked    TEXT DEFAULT '0.00',
            shift_status    TEXT DEFAULT 'scheduled'
                            CHECK (shift_status IN ('scheduled','clocked_in','clocked_out','no_show','cancelled')),
            notes           TEXT,
            created_at      TEXT DEFAULT (datetime('now')),
            updated_at      TEXT DEFAULT (datetime('now'))
        );
        CREATE INDEX IF NOT EXISTS idx_foodclaw_shift_employee ON foodclaw_shift(employee_id);
        CREATE INDEX IF NOT EXISTS idx_foodclaw_shift_date ON foodclaw_shift(shift_date);

        CREATE TABLE IF NOT EXISTS foodclaw_tip_distribution (
            id              TEXT PRIMARY KEY,
            company_id      TEXT NOT NULL,
            employee_id     TEXT NOT NULL,
            shift_id        TEXT,
            tip_date        TEXT NOT NULL,
            cash_tips       TEXT DEFAULT '0.00',
            credit_tips     TEXT DEFAULT '0.00',
            tip_pool_share  TEXT DEFAULT '0.00',
            total_tips      TEXT DEFAULT '0.00',
            notes           TEXT,
            created_at      TEXT DEFAULT (datetime('now'))
        );
        CREATE INDEX IF NOT EXISTS idx_foodclaw_tips_employee ON foodclaw_tip_distribution(employee_id);
        CREATE INDEX IF NOT EXISTS idx_foodclaw_tips_date ON foodclaw_tip_distribution(tip_date);

        -- ──────────────────────────────────────────────────────────
        -- CATERING DOMAIN (3 tables)
        -- ──────────────────────────────────────────────────────────
        CREATE TABLE IF NOT EXISTS foodclaw_catering_event (
            id              TEXT PRIMARY KEY,
            naming_series   TEXT,
            company_id      TEXT NOT NULL,
            event_name      TEXT NOT NULL,
            client_name     TEXT NOT NULL,
            client_phone    TEXT,
            client_email    TEXT,
            event_date      TEXT NOT NULL,
            event_time      TEXT,
            venue           TEXT,
            guest_count     INTEGER DEFAULT 0,
            event_status    TEXT DEFAULT 'inquiry'
                            CHECK (event_status IN ('inquiry','quoted','confirmed','in_progress','completed','cancelled')),
            estimated_cost  TEXT DEFAULT '0.00',
            quoted_price    TEXT DEFAULT '0.00',
            deposit_amount  TEXT DEFAULT '0.00',
            final_amount    TEXT DEFAULT '0.00',
            revenue_account_id      TEXT,
            receivable_account_id   TEXT,
            cost_center_id          TEXT,
            gl_entry_ids    TEXT,
            notes           TEXT,
            created_at      TEXT DEFAULT (datetime('now')),
            updated_at      TEXT DEFAULT (datetime('now'))
        );
        CREATE INDEX IF NOT EXISTS idx_foodclaw_catering_company ON foodclaw_catering_event(company_id);
        CREATE INDEX IF NOT EXISTS idx_foodclaw_catering_date ON foodclaw_catering_event(event_date);
        CREATE INDEX IF NOT EXISTS idx_foodclaw_catering_status ON foodclaw_catering_event(event_status);

        CREATE TABLE IF NOT EXISTS foodclaw_catering_item (
            id              TEXT PRIMARY KEY,
            event_id        TEXT NOT NULL,
            menu_item_id    TEXT,
            item_name       TEXT NOT NULL,
            quantity        INTEGER DEFAULT 1,
            unit_price      TEXT DEFAULT '0.00',
            line_total      TEXT DEFAULT '0.00',
            notes           TEXT,
            created_at      TEXT DEFAULT (datetime('now'))
        );
        CREATE INDEX IF NOT EXISTS idx_foodclaw_catering_item_event ON foodclaw_catering_item(event_id);

        CREATE TABLE IF NOT EXISTS foodclaw_dietary_requirement (
            id              TEXT PRIMARY KEY,
            event_id        TEXT NOT NULL,
            requirement     TEXT NOT NULL,
            guest_count     INTEGER DEFAULT 1,
            notes           TEXT,
            created_at      TEXT DEFAULT (datetime('now'))
        );
        CREATE INDEX IF NOT EXISTS idx_foodclaw_dietary_event ON foodclaw_dietary_requirement(event_id);

        -- ──────────────────────────────────────────────────────────
        -- FOOD SAFETY DOMAIN (3 tables)
        -- ──────────────────────────────────────────────────────────
        CREATE TABLE IF NOT EXISTS foodclaw_haccp_log (
            id              TEXT PRIMARY KEY,
            company_id      TEXT NOT NULL,
            ccp_name        TEXT NOT NULL,
            log_date        TEXT NOT NULL,
            log_time        TEXT,
            monitored_by    TEXT,
            parameter       TEXT,
            measured_value  TEXT,
            acceptable_range TEXT,
            is_within_range INTEGER DEFAULT 1,
            corrective_action TEXT,
            notes           TEXT,
            created_at      TEXT DEFAULT (datetime('now'))
        );
        CREATE INDEX IF NOT EXISTS idx_foodclaw_haccp_company ON foodclaw_haccp_log(company_id);
        CREATE INDEX IF NOT EXISTS idx_foodclaw_haccp_date ON foodclaw_haccp_log(log_date);

        CREATE TABLE IF NOT EXISTS foodclaw_temp_reading (
            id              TEXT PRIMARY KEY,
            company_id      TEXT NOT NULL,
            equipment_name  TEXT NOT NULL,
            location        TEXT,
            reading_date    TEXT NOT NULL,
            reading_time    TEXT,
            temperature     TEXT NOT NULL,
            temp_unit       TEXT DEFAULT 'F' CHECK (temp_unit IN ('F','C')),
            safe_min        TEXT,
            safe_max        TEXT,
            is_safe         INTEGER DEFAULT 1,
            recorded_by     TEXT,
            corrective_action TEXT,
            created_at      TEXT DEFAULT (datetime('now'))
        );
        CREATE INDEX IF NOT EXISTS idx_foodclaw_temp_company ON foodclaw_temp_reading(company_id);
        CREATE INDEX IF NOT EXISTS idx_foodclaw_temp_date ON foodclaw_temp_reading(reading_date);

        CREATE TABLE IF NOT EXISTS foodclaw_inspection (
            id                  TEXT PRIMARY KEY,
            naming_series       TEXT,
            company_id          TEXT NOT NULL,
            inspection_type     TEXT DEFAULT 'routine'
                                CHECK (inspection_type IN ('routine','health_dept','internal','fire','third_party','other')),
            inspector_name      TEXT,
            inspection_date     TEXT NOT NULL,
            score               TEXT,
            max_score           TEXT DEFAULT '100',
            grade               TEXT,
            findings            TEXT,
            corrective_actions  TEXT,
            follow_up_date      TEXT,
            inspection_status   TEXT DEFAULT 'scheduled'
                                CHECK (inspection_status IN ('scheduled','in_progress','completed','failed','follow_up')),
            notes               TEXT,
            created_at          TEXT DEFAULT (datetime('now')),
            updated_at          TEXT DEFAULT (datetime('now'))
        );
        CREATE INDEX IF NOT EXISTS idx_foodclaw_inspection_company ON foodclaw_inspection(company_id);
        CREATE INDEX IF NOT EXISTS idx_foodclaw_inspection_date ON foodclaw_inspection(inspection_date);

        -- ──────────────────────────────────────────────────────────
        -- FRANCHISE DOMAIN (2 tables)
        -- ──────────────────────────────────────────────────────────
        CREATE TABLE IF NOT EXISTS foodclaw_franchise_unit (
            id              TEXT PRIMARY KEY,
            naming_series   TEXT,
            company_id      TEXT NOT NULL,
            unit_name       TEXT NOT NULL,
            unit_code       TEXT,
            address         TEXT,
            city            TEXT,
            state           TEXT,
            zip_code        TEXT,
            manager_name    TEXT,
            phone           TEXT,
            open_date       TEXT,
            status          TEXT DEFAULT 'active'
                            CHECK (status IN ('active','inactive','closed','under_construction')),
            created_at      TEXT DEFAULT (datetime('now')),
            updated_at      TEXT DEFAULT (datetime('now'))
        );
        CREATE INDEX IF NOT EXISTS idx_foodclaw_franchise_company ON foodclaw_franchise_unit(company_id);

        CREATE TABLE IF NOT EXISTS foodclaw_royalty_entry (
            id              TEXT PRIMARY KEY,
            naming_series   TEXT,
            company_id      TEXT NOT NULL,
            franchise_unit_id TEXT NOT NULL,
            period_start    TEXT NOT NULL,
            period_end      TEXT NOT NULL,
            gross_revenue   TEXT DEFAULT '0.00',
            royalty_rate    TEXT DEFAULT '0.00',
            royalty_amount  TEXT DEFAULT '0.00',
            marketing_fee   TEXT DEFAULT '0.00',
            total_due       TEXT DEFAULT '0.00',
            payment_status  TEXT DEFAULT 'pending'
                            CHECK (payment_status IN ('pending','paid','overdue')),
            royalty_income_account_id   TEXT,
            royalty_receivable_account_id TEXT,
            marketing_expense_account_id TEXT,
            cost_center_id              TEXT,
            gl_entry_ids    TEXT,
            notes           TEXT,
            created_at      TEXT DEFAULT (datetime('now'))
        );
        CREATE INDEX IF NOT EXISTS idx_foodclaw_royalty_unit ON foodclaw_royalty_entry(franchise_unit_id);
        CREATE INDEX IF NOT EXISTS idx_foodclaw_royalty_period ON foodclaw_royalty_entry(period_start, period_end);
    """)

    conn.commit()
    print(f"[{DISPLAY_NAME}] Schema initialized: 20 tables created in {db_path}")
    conn.close()


if __name__ == "__main__":
    path = sys.argv[1] if len(sys.argv) > 1 else DEFAULT_DB_PATH
    init_foodclaw_schema(path)
