"""L1 tests for FoodClaw menu + recipes domains.

Covers:
  - Menu: add, update, get, list
  - Menu Items: add, update, get, list
  - Modifier Groups: add, list
  - Modifiers: add, list
  - Recipes: add, update, get, list
  - Recipe Ingredients: add, update, list
  - Calculate Recipe Cost, Cost Analysis, Recipe Scaling
"""
import pytest
import sys
import os

_TESTS_DIR = os.path.dirname(os.path.abspath(__file__))
if _TESTS_DIR not in sys.path:
    sys.path.insert(0, _TESTS_DIR)

from food_helpers import (
    call_action, ns, is_ok, is_error, load_db_query,
    seed_company, seed_naming_series,
)

# Load ACTIONS dict from db_query.py
_mod = load_db_query()
ACTIONS = _mod.ACTIONS


# ── Menu Tests ──────────────────────────────────────────────────────────────


class TestAddMenu:
    """food-add-menu"""

    def test_add_menu_ok(self, conn, env):
        result = call_action(
            ACTIONS["food-add-menu"], conn,
            ns(company_id=env["company_id"], name="Dinner Menu"),
        )
        assert is_ok(result), result
        assert result["name"] == "Dinner Menu"
        assert "id" in result
        assert "naming_series" in result

    def test_add_menu_with_type(self, conn, env):
        result = call_action(
            ACTIONS["food-add-menu"], conn,
            ns(company_id=env["company_id"], name="Brunch Special",
               menu_type="brunch"),
        )
        assert is_ok(result), result

    def test_add_menu_missing_name(self, conn, env):
        result = call_action(
            ACTIONS["food-add-menu"], conn,
            ns(company_id=env["company_id"]),
        )
        assert is_error(result)

    def test_add_menu_missing_company(self, conn, env):
        result = call_action(
            ACTIONS["food-add-menu"], conn,
            ns(name="Test Menu"),
        )
        assert is_error(result)


class TestUpdateMenu:
    """food-update-menu"""

    def test_update_menu_name(self, conn, env):
        add = call_action(
            ACTIONS["food-add-menu"], conn,
            ns(company_id=env["company_id"], name="Old Name"),
        )
        assert is_ok(add)
        result = call_action(
            ACTIONS["food-update-menu"], conn,
            ns(menu_id=add["id"], name="New Name"),
        )
        assert is_ok(result), result
        assert "name" in result["updated_fields"]

    def test_update_menu_missing_id(self, conn, env):
        result = call_action(
            ACTIONS["food-update-menu"], conn,
            ns(name="Foo"),
        )
        assert is_error(result)

    def test_update_menu_not_found(self, conn, env):
        result = call_action(
            ACTIONS["food-update-menu"], conn,
            ns(menu_id="nonexistent", name="Foo"),
        )
        assert is_error(result)


class TestGetMenu:
    """food-get-menu"""

    def test_get_menu_ok(self, conn, env):
        add = call_action(
            ACTIONS["food-add-menu"], conn,
            ns(company_id=env["company_id"], name="Test Menu"),
        )
        assert is_ok(add)
        result = call_action(
            ACTIONS["food-get-menu"], conn,
            ns(menu_id=add["id"]),
        )
        assert is_ok(result), result
        assert result["name"] == "Test Menu"
        assert "item_count" in result

    def test_get_menu_not_found(self, conn, env):
        result = call_action(
            ACTIONS["food-get-menu"], conn,
            ns(menu_id="nonexistent"),
        )
        assert is_error(result)


class TestListMenus:
    """food-list-menus"""

    def test_list_menus_empty(self, conn, env):
        result = call_action(
            ACTIONS["food-list-menus"], conn,
            ns(company_id=env["company_id"]),
        )
        assert is_ok(result), result
        assert result["total_count"] == 0

    def test_list_menus_after_add(self, conn, env):
        call_action(ACTIONS["food-add-menu"], conn,
                     ns(company_id=env["company_id"], name="Menu A"))
        call_action(ACTIONS["food-add-menu"], conn,
                     ns(company_id=env["company_id"], name="Menu B"))
        result = call_action(
            ACTIONS["food-list-menus"], conn,
            ns(company_id=env["company_id"]),
        )
        assert is_ok(result), result
        assert result["total_count"] == 2


# ── Menu Item Tests ─────────────────────────────────────────────────────────


class TestAddMenuItem:
    """food-add-menu-item"""

    def test_add_item_ok(self, conn, env):
        result = call_action(
            ACTIONS["food-add-menu-item"], conn,
            ns(company_id=env["company_id"], name="Grilled Salmon",
               price="24.99", cost="8.50", category="entree"),
        )
        assert is_ok(result), result
        assert result["name"] == "Grilled Salmon"
        assert result["price"] == "24.99"
        assert result["cost"] == "8.50"

    def test_add_item_to_menu(self, conn, env):
        menu = call_action(ACTIONS["food-add-menu"], conn,
                           ns(company_id=env["company_id"], name="Dinner"))
        assert is_ok(menu)
        result = call_action(
            ACTIONS["food-add-menu-item"], conn,
            ns(company_id=env["company_id"], name="Steak",
               menu_id=menu["id"], price="35.00"),
        )
        assert is_ok(result), result

    def test_add_item_missing_name(self, conn, env):
        result = call_action(
            ACTIONS["food-add-menu-item"], conn,
            ns(company_id=env["company_id"], price="10.00"),
        )
        assert is_error(result)

    def test_add_item_invalid_menu(self, conn, env):
        result = call_action(
            ACTIONS["food-add-menu-item"], conn,
            ns(company_id=env["company_id"], name="X", menu_id="nonexistent"),
        )
        assert is_error(result)


class TestUpdateMenuItem:
    """food-update-menu-item"""

    def test_update_price(self, conn, env):
        add = call_action(ACTIONS["food-add-menu-item"], conn,
                          ns(company_id=env["company_id"], name="Soup",
                             price="6.00"))
        assert is_ok(add)
        result = call_action(
            ACTIONS["food-update-menu-item"], conn,
            ns(menu_item_id=add["id"], price="7.50"),
        )
        assert is_ok(result), result
        assert "price" in result["updated_fields"]

    def test_update_missing_id(self, conn, env):
        result = call_action(
            ACTIONS["food-update-menu-item"], conn,
            ns(price="10.00"),
        )
        assert is_error(result)


class TestGetMenuItem:
    """food-get-menu-item"""

    def test_get_item_ok(self, conn, env):
        add = call_action(ACTIONS["food-add-menu-item"], conn,
                          ns(company_id=env["company_id"], name="Salad",
                             price="12.00", category="salad"))
        assert is_ok(add)
        result = call_action(
            ACTIONS["food-get-menu-item"], conn,
            ns(menu_item_id=add["id"]),
        )
        assert is_ok(result), result
        assert result["name"] == "Salad"
        assert result["category"] == "salad"


class TestListMenuItems:
    """food-list-menu-items"""

    def test_list_items_by_company(self, conn, env):
        call_action(ACTIONS["food-add-menu-item"], conn,
                     ns(company_id=env["company_id"], name="Item 1",
                        price="10.00"))
        result = call_action(
            ACTIONS["food-list-menu-items"], conn,
            ns(company_id=env["company_id"]),
        )
        assert is_ok(result), result
        assert result["total_count"] >= 1


# ── Modifier Group & Modifier Tests ────────────────────────────────────────


class TestModifierGroup:
    """food-add-modifier-group / food-list-modifier-groups"""

    def test_add_modifier_group(self, conn, env):
        result = call_action(
            ACTIONS["food-add-modifier-group"], conn,
            ns(company_id=env["company_id"], name="Protein Choice"),
        )
        assert is_ok(result), result
        assert result["name"] == "Protein Choice"

    def test_list_modifier_groups(self, conn, env):
        call_action(ACTIONS["food-add-modifier-group"], conn,
                     ns(company_id=env["company_id"], name="Sauce"))
        result = call_action(
            ACTIONS["food-list-modifier-groups"], conn,
            ns(company_id=env["company_id"]),
        )
        assert is_ok(result), result
        assert result["total_count"] >= 1


class TestModifier:
    """food-add-modifier / food-list-modifiers"""

    def test_add_modifier(self, conn, env):
        grp = call_action(ACTIONS["food-add-modifier-group"], conn,
                          ns(company_id=env["company_id"], name="Size"))
        assert is_ok(grp)
        result = call_action(
            ACTIONS["food-add-modifier"], conn,
            ns(company_id=env["company_id"], modifier_group_id=grp["id"],
               name="Large", price_adjustment="2.00"),
        )
        assert is_ok(result), result
        assert result["name"] == "Large"
        assert result["price_adjustment"] == "2.00"

    def test_add_modifier_missing_group(self, conn, env):
        result = call_action(
            ACTIONS["food-add-modifier"], conn,
            ns(company_id=env["company_id"], name="Extra"),
        )
        assert is_error(result)

    def test_list_modifiers(self, conn, env):
        grp = call_action(ACTIONS["food-add-modifier-group"], conn,
                          ns(company_id=env["company_id"], name="Temp"))
        assert is_ok(grp)
        call_action(ACTIONS["food-add-modifier"], conn,
                     ns(company_id=env["company_id"],
                        modifier_group_id=grp["id"], name="Rare"))
        result = call_action(
            ACTIONS["food-list-modifiers"], conn,
            ns(modifier_group_id=grp["id"]),
        )
        assert is_ok(result), result
        assert result["total_count"] >= 1


# ── Recipe Tests ────────────────────────────────────────────────────────────


class TestAddRecipe:
    """food-add-recipe"""

    def test_add_recipe_ok(self, conn, env):
        result = call_action(
            ACTIONS["food-add-recipe"], conn,
            ns(company_id=env["company_id"], name="Tomato Soup",
               batch_size="10", batch_unit="liter",
               portions_per_batch=20),
        )
        assert is_ok(result), result
        assert result["name"] == "Tomato Soup"

    def test_add_recipe_missing_name(self, conn, env):
        result = call_action(
            ACTIONS["food-add-recipe"], conn,
            ns(company_id=env["company_id"]),
        )
        assert is_error(result)


class TestUpdateRecipe:
    """food-update-recipe"""

    def test_update_recipe_instructions(self, conn, env):
        add = call_action(ACTIONS["food-add-recipe"], conn,
                          ns(company_id=env["company_id"], name="Pasta"))
        assert is_ok(add)
        result = call_action(
            ACTIONS["food-update-recipe"], conn,
            ns(recipe_id=add["id"], instructions="Boil water, add pasta."),
        )
        assert is_ok(result), result
        assert "instructions" in result["updated_fields"]

    def test_update_recipe_missing_id(self, conn, env):
        result = call_action(
            ACTIONS["food-update-recipe"], conn,
            ns(instructions="Some text"),
        )
        assert is_error(result)


class TestGetRecipe:
    """food-get-recipe"""

    def test_get_recipe_ok(self, conn, env):
        add = call_action(ACTIONS["food-add-recipe"], conn,
                          ns(company_id=env["company_id"], name="Caesar Salad"))
        assert is_ok(add)
        result = call_action(
            ACTIONS["food-get-recipe"], conn,
            ns(recipe_id=add["id"]),
        )
        assert is_ok(result), result
        assert result["name"] == "Caesar Salad"
        assert "ingredients" in result
        assert "ingredient_count" in result


class TestListRecipes:
    """food-list-recipes"""

    def test_list_recipes(self, conn, env):
        call_action(ACTIONS["food-add-recipe"], conn,
                     ns(company_id=env["company_id"], name="Recipe 1"))
        result = call_action(
            ACTIONS["food-list-recipes"], conn,
            ns(company_id=env["company_id"]),
        )
        assert is_ok(result), result
        assert result["total_count"] >= 1


# ── Recipe Ingredient Tests ─────────────────────────────────────────────────


class TestRecipeIngredient:
    """food-add-recipe-ingredient / food-update-recipe-ingredient / food-list-recipe-ingredients"""

    def _make_recipe(self, conn, env):
        r = call_action(ACTIONS["food-add-recipe"], conn,
                        ns(company_id=env["company_id"], name="Test Recipe",
                           portions_per_batch=4))
        assert is_ok(r)
        return r["id"]

    def test_add_recipe_ingredient_ok(self, conn, env):
        rid = self._make_recipe(conn, env)
        result = call_action(
            ACTIONS["food-add-recipe-ingredient"], conn,
            ns(recipe_id=rid, ingredient_name="Flour",
               quantity="2", unit="cup", unit_cost="0.50"),
        )
        assert is_ok(result), result
        assert result["ingredient_name"] == "Flour"
        assert result["quantity"] == "2"
        assert result["line_cost"] == "1.00"

    def test_add_recipe_ingredient_missing_name(self, conn, env):
        rid = self._make_recipe(conn, env)
        result = call_action(
            ACTIONS["food-add-recipe-ingredient"], conn,
            ns(recipe_id=rid, quantity="1"),
        )
        assert is_error(result)

    def test_update_recipe_ingredient(self, conn, env):
        rid = self._make_recipe(conn, env)
        add = call_action(ACTIONS["food-add-recipe-ingredient"], conn,
                          ns(recipe_id=rid, ingredient_name="Sugar",
                             quantity="1", unit_cost="2.00"))
        assert is_ok(add)
        result = call_action(
            ACTIONS["food-update-recipe-ingredient"], conn,
            ns(recipe_ingredient_id=add["id"], quantity="3"),
        )
        assert is_ok(result), result
        # line_cost should be recalculated: 3 * 2.00 = 6.00
        assert result["line_cost"] == "6.00"

    def test_list_recipe_ingredients(self, conn, env):
        rid = self._make_recipe(conn, env)
        call_action(ACTIONS["food-add-recipe-ingredient"], conn,
                     ns(recipe_id=rid, ingredient_name="Egg",
                        quantity="2", unit_cost="0.30"))
        result = call_action(
            ACTIONS["food-list-recipe-ingredients"], conn,
            ns(recipe_id=rid),
        )
        assert is_ok(result), result
        assert result["total_count"] >= 1


# ── Recipe Cost / Analysis / Scaling ────────────────────────────────────────


class TestRecipeCost:
    """food-calculate-recipe-cost"""

    def test_calculate_recipe_cost(self, conn, env):
        r = call_action(ACTIONS["food-add-recipe"], conn,
                        ns(company_id=env["company_id"], name="Cake",
                           portions_per_batch=8))
        assert is_ok(r)
        call_action(ACTIONS["food-add-recipe-ingredient"], conn,
                     ns(recipe_id=r["id"], ingredient_name="Flour",
                        quantity="4", unit_cost="0.50"))
        call_action(ACTIONS["food-add-recipe-ingredient"], conn,
                     ns(recipe_id=r["id"], ingredient_name="Butter",
                        quantity="2", unit_cost="3.00"))
        result = call_action(
            ACTIONS["food-calculate-recipe-cost"], conn,
            ns(recipe_id=r["id"]),
        )
        assert is_ok(result), result
        # total_cost = 4*0.50 + 2*3.00 = 2.00 + 6.00 = 8.00
        assert result["total_cost"] == "8.00"
        # cost_per_portion = 8.00 / 8 = 1.00
        assert result["cost_per_portion"] == "1.00"


class TestCostAnalysis:
    """food-cost-analysis"""

    def test_cost_analysis_empty(self, conn, env):
        result = call_action(
            ACTIONS["food-cost-analysis"], conn,
            ns(company_id=env["company_id"]),
        )
        assert is_ok(result), result
        assert result["total_count"] == 0


class TestRecipeScaling:
    """food-recipe-scaling"""

    def test_recipe_scaling(self, conn, env):
        r = call_action(ACTIONS["food-add-recipe"], conn,
                        ns(company_id=env["company_id"], name="Soup",
                           portions_per_batch=4))
        assert is_ok(r)
        call_action(ACTIONS["food-add-recipe-ingredient"], conn,
                     ns(recipe_id=r["id"], ingredient_name="Tomato",
                        quantity="4", unit_cost="1.00"))
        result = call_action(
            ACTIONS["food-recipe-scaling"], conn,
            ns(recipe_id=r["id"], target_portions="12"),
        )
        assert is_ok(result), result
        assert result["original_portions"] == 4
        assert result["target_portions"] == 12
        assert result["scale_factor"] == "3.00"
        # scaled quantity = 4 * 3 = 12
        assert result["ingredients"][0]["scaled_quantity"] == "12.00"

    def test_recipe_scaling_missing_target(self, conn, env):
        r = call_action(ACTIONS["food-add-recipe"], conn,
                        ns(company_id=env["company_id"], name="X"))
        assert is_ok(r)
        result = call_action(
            ACTIONS["food-recipe-scaling"], conn,
            ns(recipe_id=r["id"]),
        )
        assert is_error(result)
