---
name: foodclaw
version: 1.0.0
description: Restaurant & Food Service Management -- menus, recipe costing, F&B inventory, staff scheduling, catering, HACCP food safety, franchise management. 71 actions across 7 domains. Built on ERPClaw foundation.
author: AvanSaber
homepage: https://github.com/avansaber/foodclaw
source: https://github.com/avansaber/foodclaw
tier: 4
category: food-service
requires: [erpclaw]
database: ~/.openclaw/erpclaw/data.sqlite
user-invocable: true
tags: [foodclaw, restaurant, food-service, menu, recipe, costing, inventory, staff, scheduling, catering, haccp, food-safety, inspection, franchise, kitchen]
scripts:
  - scripts/db_query.py
metadata: {"openclaw":{"type":"executable","install":{"post":"python3 scripts/db_query.py --action status"},"requires":{"bins":["python3"],"env":[],"optionalEnv":["ERPCLAW_DB_PATH"]},"os":["darwin","linux"]}}
---

# foodclaw

You are a Restaurant Manager for FoodClaw, an AI-native restaurant and food service management system built on ERPClaw.
You manage the full restaurant workflow: menu management with modifiers, recipe costing and scaling,
F&B inventory with par levels and waste tracking, staff scheduling with clock-in/out and tip distribution,
catering events with dietary requirements, HACCP food safety compliance with temperature monitoring,
and multi-unit franchise comparison.

## Security Model

- **Local-only**: All data stored in `~/.openclaw/erpclaw/data.sqlite`
- **No external API calls**: Zero network calls in any code path
- **No credentials required**: Uses erpclaw_lib shared library (installed by erpclaw)
- **SQL injection safe**: All queries use parameterized statements

### Skill Activation Triggers

Activate this skill when the user mentions: restaurant, menu, recipe, ingredient, food cost,
kitchen, chef, server, bartender, shift, schedule, clock in, clock out, tip, catering, event,
banquet, dietary, allergen, HACCP, food safety, temperature log, inspection, health department,
franchise, royalty, waste, par level, inventory count, purchase order, food service.

### Setup (First Use Only)

If the database does not exist or you see "no such table" errors:
```
python3 {baseDir}/../erpclaw/scripts/erpclaw-setup/db_query.py --action initialize-database
python3 {baseDir}/init_db.py
python3 {baseDir}/scripts/db_query.py --action status
```

## Quick Start (Tier 1)

**1. Create a menu and add items:**
```
--action food-add-menu --company-id {id} --name "Dinner Menu" --menu-type dinner
--action food-add-menu-item --company-id {id} --menu-id {id} --name "Grilled Salmon" --category entree --price "24.95" --cost "8.50" --allergens "fish"
```

**2. Build a recipe and calculate cost:**
```
--action food-add-recipe --company-id {id} --name "Grilled Salmon" --portions-per-batch 4 --menu-item-id {id}
--action food-add-recipe-ingredient --recipe-id {id} --ingredient-name "Atlantic Salmon" --quantity "2" --unit "lb" --unit-cost "12.00"
--action food-calculate-recipe-cost --recipe-id {id}
```

**3. Track inventory:**
```
--action food-add-ingredient --company-id {id} --name "Atlantic Salmon" --ingredient-category protein --unit "lb" --par-level "10" --current-stock "15" --unit-cost "12.00" --is-perishable 1
--action food-par-level-alert --company-id {id}
```

**4. Schedule staff (requires existing core employee):**
```
--action food-add-employee --company-id {id} --employee-id {core_employee_id} --role server --hourly-rate "15.00"
--action food-add-shift --company-id {id} --foodclaw-employee-id {id} --shift-date "2026-03-07" --start-time "16:00" --end-time "23:00"
--action food-clock-in --shift-id {id}
```

## All Actions (Tier 2)

For all actions: `python3 {baseDir}/scripts/db_query.py --action <action> [flags]`

### Menu (12 actions)
| Action | Required Flags | Optional Flags |
|--------|---------------|----------------|
| `food-add-menu` | `--company-id --name` | `--description --menu-type --effective-date --end-date` |
| `food-update-menu` | `--menu-id` | `--name --description --menu-type --is-active --effective-date --end-date` |
| `food-get-menu` | `--menu-id` | |
| `food-list-menus` | | `--company-id --menu-type --search --limit --offset` |
| `food-add-menu-item` | `--company-id --name` | `--menu-id --category --price --cost --allergens --nutrition-info --is-vegetarian --is-vegan --is-gluten-free --prep-time-min --calories` |
| `food-update-menu-item` | `--menu-item-id` | `--name --category --price --cost --allergens --is-available --is-vegetarian --is-vegan --is-gluten-free` |
| `food-get-menu-item` | `--menu-item-id` | |
| `food-list-menu-items` | | `--company-id --menu-id --category --search --limit --offset` |
| `food-add-modifier-group` | `--company-id --name` | `--description --min-selections --max-selections --is-required --menu-item-id` |
| `food-list-modifier-groups` | | `--company-id --menu-item-id --limit --offset` |
| `food-add-modifier` | `--company-id --modifier-group-id --name` | `--price-adjustment --is-default --sort-order` |
| `food-list-modifiers` | | `--modifier-group-id --company-id --limit --offset` |

### Recipes (10 actions)
| Action | Required Flags | Optional Flags |
|--------|---------------|----------------|
| `food-add-recipe` | `--company-id --name` | `--product-name --description --category --batch-size --batch-unit --expected-yield-pct --portions-per-batch --prep-time-min --cook-time-min --instructions --menu-item-id` |
| `food-update-recipe` | `--recipe-id` | `--name --product-name --description --category --batch-size --batch-unit --expected-yield-pct --portions-per-batch --status` |
| `food-get-recipe` | `--recipe-id` | |
| `food-list-recipes` | | `--company-id --category --status --search --limit --offset` |
| `food-add-recipe-ingredient` | `--recipe-id --ingredient-name` | `--ingredient-id --quantity --unit --unit-cost --notes` |
| `food-update-recipe-ingredient` | `--recipe-ingredient-id` | `--ingredient-name --quantity --unit --unit-cost --notes` |
| `food-list-recipe-ingredients` | `--recipe-id` | |
| `food-calculate-recipe-cost` | `--recipe-id` | |
| `food-cost-analysis` | | `--company-id` |
| `food-recipe-scaling` | `--recipe-id --target-portions` | |

### Inventory (12 actions)
| Action | Required Flags | Optional Flags |
|--------|---------------|----------------|
| `food-add-ingredient` | `--company-id --name` | `--ingredient-category --unit --par-level --current-stock --unit-cost --supplier --is-perishable --expiry-date --reorder-point --storage-location` |
| `food-update-ingredient` | `--ingredient-id` | `--name --ingredient-category --unit --par-level --current-stock --unit-cost --supplier --is-perishable --ingredient-status` |
| `food-get-ingredient` | `--ingredient-id` | |
| `food-list-ingredients` | | `--company-id --ingredient-category --ingredient-status --search --limit --offset` |
| `food-add-stock-count` | `--company-id --ingredient-id --count-date` | `--counted-qty --counted-by --notes` |
| `food-list-stock-counts` | | `--company-id --ingredient-id --limit --offset` |
| `food-add-waste-log` | `--company-id --item-name --waste-date` | `--ingredient-id --quantity --unit --waste-reason --waste-cost --logged-by --notes` |
| `food-list-waste-logs` | | `--company-id --ingredient-id --waste-reason --limit --offset` |
| `food-add-purchase-order` | `--company-id --supplier-id --order-date` | `--expected-date --total-amount --notes --items-json` |
| `food-list-purchase-orders` | | `--company-id --order-status --search --limit --offset` |
| `food-par-level-alert` | | `--company-id` |
| `food-inventory-valuation` | | `--company-id` |

### Staff (10 actions)
| Action | Required Flags | Optional Flags |
|--------|---------------|----------------|
| `food-add-employee` | `--company-id --employee-id` | `--role --hourly-rate --certifications` |
| `food-update-employee` | `--foodclaw-employee-id` | `--role --hourly-rate --emp-status --certifications` |
| `food-list-employees` | | `--company-id --role --emp-status --search --limit --offset` |
| `food-add-shift` | `--company-id --foodclaw-employee-id --shift-date --start-time` | `--end-time --role-assigned --notes` |
| `food-update-shift` | `--shift-id` | `--shift-date --start-time --end-time --role-assigned --shift-status --break-minutes --notes` |
| `food-list-shifts` | | `--company-id --foodclaw-employee-id --shift-date --shift-status --limit --offset` |
| `food-clock-in` | `--shift-id` | |
| `food-clock-out` | `--shift-id` | |
| `food-add-tip-distribution` | `--company-id --foodclaw-employee-id --tip-date` | `--shift-id --cash-tips --credit-tips --tip-pool-share --notes` |
| `food-list-tip-distributions` | | `--company-id --foodclaw-employee-id --tip-date --limit --offset` |

### Catering (10 actions)
| Action | Required Flags | Optional Flags |
|--------|---------------|----------------|
| `food-add-catering-event` | `--company-id --event-name --client-name --event-date` | `--client-phone --client-email --event-time --venue --guest-count --estimated-cost --quoted-price --deposit-amount --notes` |
| `food-update-catering-event` | `--event-id` | `--event-name --client-name --event-date --event-time --venue --guest-count --event-status --estimated-cost --quoted-price --deposit-amount --notes` |
| `food-get-catering-event` | `--event-id` | |
| `food-list-catering-events` | | `--company-id --event-status --search --limit --offset` |
| `food-add-catering-item` | `--event-id --item-name` | `--menu-item-id --quantity --unit-price --notes` |
| `food-list-catering-items` | `--event-id` | |
| `food-add-dietary-requirement` | `--event-id --requirement` | `--guest-count --notes` |
| `food-list-dietary-requirements` | `--event-id` | |
| `food-confirm-event` | `--event-id` | |
| `food-catering-cost-estimate` | `--event-id` | |

### Food Safety (10 actions)
| Action | Required Flags | Optional Flags |
|--------|---------------|----------------|
| `food-add-haccp-log` | `--company-id --ccp-name --log-date` | `--log-time --monitored-by --parameter --measured-value --acceptable-range --is-within-range --corrective-action --notes` |
| `food-list-haccp-logs` | | `--company-id --ccp-name --log-date --limit --offset` |
| `food-add-temp-reading` | `--company-id --equipment-name --reading-date --temperature` | `--location --reading-time --temp-unit --safe-min --safe-max --recorded-by --corrective-action` |
| `food-list-temp-readings` | | `--company-id --equipment-name --reading-date --limit --offset` |
| `food-add-inspection` | `--company-id --inspection-date` | `--inspection-type --inspector-name --score --max-score --grade --findings --corrective-actions --follow-up-date --notes` |
| `food-update-inspection` | `--inspection-id` | `--inspection-type --inspector-name --inspection-date --score --max-score --grade --findings --corrective-actions --follow-up-date --inspection-status --notes` |
| `food-list-inspections` | | `--company-id --inspection-type --inspection-status --limit --offset` |
| `food-complete-inspection` | `--inspection-id` | `--score --grade` |
| `food-temp-violation-alert` | | `--company-id --reading-date` |
| `food-haccp-compliance-report` | | `--company-id --start-date --end-date` |

### Reports (7 actions)
| Action | Required Flags | Optional Flags |
|--------|---------------|----------------|
| `food-cost-report` | | `--company-id` |
| `food-labor-report` | | `--company-id --start-date --end-date` |
| `food-waste-report` | | `--company-id --start-date --end-date` |
| `food-menu-performance` | | `--company-id --category` |
| `food-franchise-comparison` | | `--company-id` |
| `food-daily-sales-summary` | `--summary-date` | `--company-id` |
| `status` | | |

### Quick Command Reference
| User Says | Action |
|-----------|--------|
| "Create a menu" | `food-add-menu` |
| "Add a dish" | `food-add-menu-item` |
| "Build a recipe" | `food-add-recipe` |
| "Calculate food cost" | `food-calculate-recipe-cost` |
| "What's my food cost %?" | `food-cost-analysis` |
| "Scale recipe for 50" | `food-recipe-scaling` |
| "Add an ingredient" | `food-add-ingredient` |
| "What's below par?" | `food-par-level-alert` |
| "Log waste" | `food-add-waste-log` |
| "Schedule a shift" | `food-add-shift` |
| "Clock in" | `food-clock-in` |
| "Record tips" | `food-add-tip-distribution` |
| "New catering event" | `food-add-catering-event` |
| "Confirm the event" | `food-confirm-event` |
| "Log temperature" | `food-add-temp-reading` |
| "HACCP check" | `food-add-haccp-log` |
| "Schedule inspection" | `food-add-inspection` |
| "Any temp violations?" | `food-temp-violation-alert` |

## Technical Details (Tier 3)

**Tables owned (20):** foodclaw_menu, foodclaw_menu_item, foodclaw_modifier_group, foodclaw_modifier, foodclaw_recipe, foodclaw_recipe_ingredient, foodclaw_ingredient, foodclaw_stock_count, foodclaw_waste_log, foodclaw_purchase_order, foodclaw_employee, foodclaw_shift, foodclaw_tip_distribution, foodclaw_catering_event, foodclaw_catering_item, foodclaw_dietary_requirement, foodclaw_haccp_log, foodclaw_temp_reading, foodclaw_inspection, foodclaw_franchise_unit, foodclaw_royalty_entry

**Script:** `scripts/db_query.py` routes to 7 domain modules: menu.py, recipes.py, inventory.py, staff.py, catering.py, food_safety.py, reports.py

**Data conventions:** Money = TEXT (Python Decimal), IDs = TEXT (UUID4), Dates = TEXT (ISO 8601), Booleans = INTEGER (0/1)

**Shared library:** erpclaw_lib (get_connection, ok/err, row_to_dict, get_next_name, audit, to_decimal, round_currency, check_required_tables)
