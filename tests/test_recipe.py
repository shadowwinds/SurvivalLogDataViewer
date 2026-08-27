from __future__ import annotations

import unittest

from codex_recipe import (
    RecipeConfigError,
    RecipeItemSpec,
    RecipeSpec,
    TierRule,
    match_inventory,
    recipe_specs_from_rows,
    resolve_cooking_tier,
)
from codex_parser import ConfigRow
from codex_save import InventoryItem


def item(
    item_id: int,
    *,
    sub_category: int,
    price: float,
    can_cook: bool = True,
) -> RecipeItemSpec:
    return RecipeItemSpec(
        item_id=item_id,
        name=f"Item {item_id}",
        can_cook=can_cook,
        category=1,
        sub_category=sub_category,
        sub_category_name=f"Subcategory {sub_category}",
        price=price,
        raw_json="{}",
    )


def recipe(
    recipe_id: int,
    *,
    tier: int = 0,
    tag_combo: tuple[int, ...] = (),
    specific_items: tuple[int, ...] = (),
) -> RecipeSpec:
    return RecipeSpec(
        recipe_id=recipe_id,
        name=f"Recipe {recipe_id}",
        name_key=f"Recipe_{recipe_id}",
        tag_combo=tag_combo,
        specific_items=specific_items,
        tier=tier,
        raw_json="{}",
    )


class CookingTierTests(unittest.TestCase):
    def setUp(self) -> None:
        self.items = {
            2527: item(2527, sub_category=5, price=7),
            2528: item(2528, sub_category=5, price=20),
            2529: item(2529, sub_category=5, price=40),
            2901: item(2901, sub_category=4, price=5),
            70105: item(70105, sub_category=2, price=100, can_cook=False),
        }
        self.rules = {
            4: TierRule(4, "Fish", 150, 50, "fish.high", "fish.mid_low"),
            5: TierRule(5, "Vegetable", 30, 16, "veg.high", "veg.mid_low"),
        }

    def test_group_uses_worst_supported_ingredient_tier(self) -> None:
        self.assertEqual(
            resolve_cooking_tier((2529, 2527), items=self.items, rules=self.rules),
            3,
        )

    def test_tag_combo_selects_recipe_after_tier_resolution(self) -> None:
        recipes = [
            recipe(1001, tier=1, tag_combo=(5,)),
            recipe(1002, tier=2, tag_combo=(5,)),
            recipe(1003, tier=3, tag_combo=(5,)),
        ]
        for item_id, expected_recipe_id, expected_tier in (
            (2529, 1001, 1),
            (2528, 1002, 2),
            (2527, 1003, 3),
        ):
            matches, diagnostics = match_inventory(
                [InventoryItem(item_id, 1, "主控背包", "backpack")],
                recipes,
                self.items,
                self.rules,
            )
            self.assertEqual(diagnostics, [])
            self.assertEqual([match["recipe_id"] for match in matches], [expected_recipe_id])
            self.assertEqual(matches[0]["tier"], expected_tier)
            self.assertEqual(matches[0]["candidate_recipe_ids"], [1001, 1002, 1003])

    def test_tag_combo_combination_count_is_for_selected_recipe(self) -> None:
        recipes = [
            recipe(1001, tier=1, tag_combo=(5,)),
            recipe(1002, tier=2, tag_combo=(5,)),
            recipe(1003, tier=3, tag_combo=(5,)),
        ]
        matches, diagnostics = match_inventory(
            [
                InventoryItem(2527, 1, "主控背包", "backpack"),
                InventoryItem(2528, 1, "双开门冰箱", "fridge"),
            ],
            recipes,
            self.items,
            self.rules,
        )
        self.assertEqual(diagnostics, [])
        self.assertEqual(
            {
                (match["recipe_id"], match["other_combination_count"])
                for match in matches
            },
            {(1002, 0), (1003, 0)},
        )

    def test_specific_items_are_a_multiset_and_uncookable_items_are_ignored(self) -> None:
        recipes = [recipe(2001, specific_items=(2527, 2527))]
        matches, diagnostics = match_inventory(
            [InventoryItem(2527, 1, "主控背包", "backpack")],
            recipes,
            self.items,
            self.rules,
        )
        self.assertEqual(matches, [])
        self.assertEqual(diagnostics, [])

        matches, diagnostics = match_inventory(
            [
                InventoryItem(2527, 2, "主控背包", "backpack"),
                InventoryItem(70105, 20, "主控背包", "backpack"),
            ],
            [recipe(2002, specific_items=(2527, 2527))],
            self.items,
            self.rules,
        )
        self.assertEqual(diagnostics, [])
        self.assertEqual([match["recipe_id"] for match in matches], [2002])
        self.assertNotIn(70105, [item["item_id"] for item in matches[0]["representative_combination"]])

    def test_completed_recipe_is_not_returned(self) -> None:
        matches, diagnostics = match_inventory(
            [InventoryItem(2527, 1, "主控背包", "backpack")],
            [
                recipe(3001, tier=3, tag_combo=(5,)),
                recipe(3002, tier=3, tag_combo=(5,)),
            ],
            self.items,
            self.rules,
            completed_recipe_ids={3001},
        )
        self.assertEqual([match["recipe_id"] for match in matches], [3002])
        self.assertEqual(diagnostics, [])

    def test_completed_same_tier_recipe_does_not_block_pending_recipe(self) -> None:
        matches, diagnostics = match_inventory(
            [InventoryItem(2527, 1, "主控背包", "backpack")],
            [
                recipe(3010, tier=3, tag_combo=(5,)),
                recipe(3011, tier=3, tag_combo=(5,)),
            ],
            self.items,
            self.rules,
            completed_recipe_ids={3010},
        )
        self.assertEqual(diagnostics, [])
        self.assertEqual([match["recipe_id"] for match in matches], [3011])


class RecipeConfigTests(unittest.TestCase):
    def test_specific_items_and_tag_combo_are_rejected_together(self) -> None:
        row = ConfigRow(
            "Config_CookingRecipe",
            {"ID": 999, "RecipeName": "Invalid", "TagCombo": [5], "SpecificItems": [2527]},
        )
        with self.assertRaisesRegex(RecipeConfigError, "同时设置"):
            recipe_specs_from_rows([row])

    def test_recipe_list_values_must_be_integers(self) -> None:
        row = ConfigRow(
            "Config_CookingRecipe",
            {"ID": 1000, "RecipeName": "Invalid", "TagCombo": ["5"]},
        )
        with self.assertRaisesRegex(RecipeConfigError, "应为整数"):
            recipe_specs_from_rows([row])


if __name__ == "__main__":
    unittest.main()
