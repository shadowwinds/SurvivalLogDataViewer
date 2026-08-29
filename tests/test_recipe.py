from __future__ import annotations

from pathlib import Path
import sqlite3
import unittest
from unittest.mock import patch

from codex_recipe import (
    RecipeConfigError,
    RecipeItemSpec,
    RecipeSpec,
    SUPPORTED_TIER_SUBCATEGORIES,
    StorageFurnitureSpec,
    _inventory_payload,
    _load_storage_furniture_from_database,
    build_recipe_plan,
    TierRule,
    find_near_matches,
    match_inventory,
    recipe_specs_from_rows,
    resolve_cooking_tier,
    resolve_generic_recipe_tier,
    storage_furniture_specs_from_rows,
)
from codex_parser import ConfigRow
from codex_save import (
    CodexSaveState,
    InventoryItem,
    SaveFileInfo,
    SaveHistoryRecord,
    SaveInventoryState,
)


def item(
    item_id: int,
    *,
    sub_category: int,
    price: float,
    can_cook: bool = True,
    category: int = 1,
    in_codex: bool = True,
) -> RecipeItemSpec:
    return RecipeItemSpec(
        item_id=item_id,
        name=f"Item {item_id}",
        can_cook=can_cook,
        category=category,
        sub_category=sub_category,
        sub_category_name=f"Subcategory {sub_category}",
        price=price,
        raw_json="{}",
        in_codex=in_codex,
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

    def test_cooking_level_selects_generic_recipe_tier(self) -> None:
        self.assertEqual(resolve_generic_recipe_tier(1), 3)
        self.assertEqual(resolve_generic_recipe_tier(2), 3)
        self.assertEqual(resolve_generic_recipe_tier(3), 2)
        self.assertEqual(resolve_generic_recipe_tier(4), 2)
        self.assertEqual(resolve_generic_recipe_tier(5), 1)
        self.assertIsNone(resolve_generic_recipe_tier(None))
        self.assertIsNone(resolve_generic_recipe_tier(0))
        self.assertIsNone(resolve_generic_recipe_tier(6))
        self.assertIsNone(resolve_generic_recipe_tier(True))

    def test_tag_combo_selects_recipe_by_cooking_level(self) -> None:
        recipes = [
            recipe(1001, tier=1, tag_combo=(5,)),
            recipe(1002, tier=2, tag_combo=(5,)),
            recipe(1003, tier=3, tag_combo=(5,)),
        ]
        for cooking_level, expected_recipe_id, expected_tier in (
            (5, 1001, 1),
            (3, 1002, 2),
            (1, 1003, 3),
        ):
            matches, diagnostics = match_inventory(
                [InventoryItem(2527, 1, "主控背包", "backpack")],
                recipes,
                self.items,
                self.rules,
                cooking_level=cooking_level,
            )
            self.assertEqual(diagnostics, [])
            self.assertEqual([match["recipe_id"] for match in matches], [expected_recipe_id])
            self.assertEqual(matches[0]["tier"], expected_tier)
            self.assertEqual(matches[0]["recipe_kind_label_zh"], "通用菜肴")
            self.assertEqual(matches[0]["candidate_recipe_ids"], [1001, 1002, 1003])

    def test_known_generic_recipe_groups_follow_cooking_level(self) -> None:
        items = dict(self.items)
        items[1001] = item(1001, sub_category=1, price=1)
        items[1002] = item(1002, sub_category=2, price=1)
        items[1003] = item(1003, sub_category=3, price=1)
        recipes = [
            recipe(5010, tier=2, tag_combo=(1, 2, 5)),
            recipe(6010, tier=1, tag_combo=(1, 2, 5)),
            recipe(7010, tier=3, tag_combo=(1, 2, 5)),
            recipe(5021, tier=2, tag_combo=(3, 5)),
            recipe(6021, tier=1, tag_combo=(3, 5)),
            recipe(7021, tier=3, tag_combo=(3, 5)),
        ]
        cases = (
            (1, 7010, 7021),
            (2, 7010, 7021),
            (3, 5010, 5021),
            (4, 5010, 5021),
            (5, 6010, 6021),
        )
        for cooking_level, expected_rice, expected_egg in cases:
            with self.subTest(cooking_level=cooking_level):
                rice_matches, rice_diagnostics = match_inventory(
                    [
                        InventoryItem(1001, 1, "主控背包", "backpack"),
                        InventoryItem(1002, 1, "主控背包", "backpack"),
                        InventoryItem(2527, 1, "主控背包", "backpack"),
                    ],
                    recipes,
                    items,
                    self.rules,
                    cooking_level=cooking_level,
                )
                egg_matches, egg_diagnostics = match_inventory(
                    [
                        InventoryItem(1003, 1, "主控背包", "backpack"),
                        InventoryItem(2527, 1, "主控背包", "backpack"),
                    ],
                    recipes,
                    items,
                    self.rules,
                    cooking_level=cooking_level,
                )
                self.assertEqual(rice_diagnostics, [])
                self.assertEqual(egg_diagnostics, [])
                self.assertEqual([match["recipe_id"] for match in rice_matches], [expected_rice])
                self.assertEqual([match["recipe_id"] for match in egg_matches], [expected_egg])

    def test_invalid_cooking_level_keeps_specific_and_skips_generic(self) -> None:
        recipes = [
            recipe(9001, specific_items=(2527,)),
            recipe(9002, tier=2, tag_combo=(5,)),
        ]
        inventory = [InventoryItem(2527, 1, "主控背包", "backpack")]
        matches, diagnostics = match_inventory(
            inventory,
            recipes,
            self.items,
            self.rules,
            cooking_level=0,
        )
        near_matches = find_near_matches(
            inventory,
            recipes,
            self.items,
            self.rules,
            cooking_level=None,
        )

        self.assertEqual([match["recipe_id"] for match in matches], [9001])
        self.assertEqual(near_matches, [])
        self.assertEqual(len(diagnostics), 1)
        self.assertIn("AgentSave.CookingLevel", diagnostics[0])

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
            cooking_level=3,
        )
        self.assertEqual(diagnostics, [])
        self.assertEqual(
            {
                (match["recipe_id"], match["other_combination_count"])
                for match in matches
            },
            {(1002, 1)},
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
        self.assertEqual(matches[0]["recipe_kind_label_zh"], "特色菜肴")
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
            cooking_level=1,
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
            cooking_level=1,
        )
        self.assertEqual(diagnostics, [])
        self.assertEqual([match["recipe_id"] for match in matches], [3011])

    def test_specific_recipe_near_match_uses_one_item_quantity_gap(self) -> None:
        near_matches = find_near_matches(
            [InventoryItem(2527, 1, "冰柜", "freezer")],
            [recipe(4001, specific_items=(2527, 2527))],
            self.items,
            self.rules,
        )

        self.assertEqual([match["recipe_id"] for match in near_matches], [4001])
        self.assertEqual([item["item_id"] for item in near_matches[0]["missing_items"]], [2527])
        self.assertEqual(near_matches[0]["missing_item_candidates"], [])
        self.assertEqual(near_matches[0]["available_combination"][0]["source"], "冰柜")

        missing_two = find_near_matches(
            [],
            [recipe(4002, specific_items=(2527, 2528))],
            self.items,
            self.rules,
        )
        self.assertEqual(missing_two, [])

        complete = find_near_matches(
            [InventoryItem(2527, 2, "主控背包", "backpack")],
            [recipe(4001, specific_items=(2527, 2527))],
            self.items,
            self.rules,
        )
        self.assertEqual(complete, [])

    def test_tag_recipe_near_match_resolves_missing_slot_and_tier(self) -> None:
        near_matches = find_near_matches(
            [InventoryItem(2528, 1, "主控背包", "backpack")],
            [
                recipe(4101, tier=1, tag_combo=(4, 5)),
                recipe(4102, tier=2, tag_combo=(4, 5)),
                recipe(4103, tier=3, tag_combo=(4, 5)),
            ],
            self.items,
            self.rules,
            cooking_level=1,
        )

        self.assertEqual([match["recipe_id"] for match in near_matches], [4103])
        self.assertEqual(near_matches[0]["missing_sub_category"]["sub_category"], 4)
        self.assertEqual(near_matches[0]["missing_sub_category"]["count"], 1)
        self.assertEqual(near_matches[0]["missing_items"], [])
        self.assertEqual(
            [item["item_id"] for item in near_matches[0]["missing_item_candidates"]],
            [2901],
        )
        self.assertEqual(
            [item["name"] for item in near_matches[0]["missing_item_candidates"]],
            ["Item 2901"],
        )
        self.assertEqual(near_matches[0]["available_combination"][0]["item_id"], 2528)

        items = dict(self.items)
        items[2902] = item(2902, sub_category=4, price=5)
        generic_near_matches = find_near_matches(
            [InventoryItem(2528, 1, "主控背包", "backpack")],
            [recipe(4104, tier=3, tag_combo=(4, 5))],
            items,
            self.rules,
            cooking_level=1,
        )
        self.assertEqual(
            [item["name"] for item in generic_near_matches[0]["missing_item_candidates"]],
            ["Item 2901", "Item 2902"],
        )
        self.assertEqual(
            {
                item["item_id"] for item in generic_near_matches[0]["missing_item_candidates"]
            }.intersection(
                item["item_id"] for item in generic_near_matches[0]["available_combination"]
            ),
            set(),
        )

    def test_tag_recipe_near_match_requires_every_other_slot_and_quantity(self) -> None:
        self.assertEqual(
            find_near_matches(
                [InventoryItem(2528, 1, "主控背包", "backpack")],
                [recipe(4110, tier=3, tag_combo=(4, 5, 5))],
                self.items,
                self.rules,
                cooking_level=1,
            ),
            [],
        )

        near_matches = find_near_matches(
            [InventoryItem(2528, 1, "主控背包", "backpack")],
            [recipe(4111, tier=3, tag_combo=(5, 5))],
            self.items,
            self.rules,
            cooking_level=1,
        )
        self.assertEqual([match["recipe_id"] for match in near_matches], [4111])
        self.assertEqual(near_matches[0]["missing_items"], [])
        self.assertEqual(near_matches[0]["missing_sub_category"]["count"], 1)
        self.assertEqual(
            [item["item_id"] for item in near_matches[0]["missing_item_candidates"]],
            [2527, 2528, 2529],
        )

    def test_near_matches_exclude_completed_and_already_cookable_recipes(self) -> None:
        recipes = [
            recipe(4201, tier=2, tag_combo=(5,)),
            recipe(4202, tier=2, tag_combo=(5,)),
        ]
        inventory = [InventoryItem(2528, 1, "主控背包", "backpack")]

        matches, _diagnostics = match_inventory(
            inventory,
            recipes,
            self.items,
            self.rules,
            completed_recipe_ids={4201},
            cooking_level=3,
        )
        near_matches = find_near_matches(
            inventory,
            recipes,
            self.items,
            self.rules,
            completed_recipe_ids={4201},
            excluded_recipe_ids={int(match["recipe_id"]) for match in matches},
            cooking_level=3,
        )

        self.assertEqual([match["recipe_id"] for match in matches], [4202])
        self.assertEqual(near_matches, [])

    def test_specific_and_generic_results_do_not_reserve_shared_ingredients(self) -> None:
        recipes = [
            recipe(4401, specific_items=(2527,)),
            recipe(4402, tier=3, tag_combo=(4, 5, 5)),
        ]
        inventory = [
            InventoryItem(2527, 1, "backpack", "backpack"),
            InventoryItem(2901, 1, "backpack", "backpack"),
        ]

        matches, diagnostics = match_inventory(
            inventory,
            recipes,
            self.items,
            self.rules,
            cooking_level=1,
        )
        near_matches = find_near_matches(
            inventory,
            recipes,
            self.items,
            self.rules,
            excluded_recipe_ids={int(match["recipe_id"]) for match in matches},
            cooking_level=1,
        )

        self.assertEqual(diagnostics, [])
        self.assertEqual([match["recipe_id"] for match in matches], [4401])
        self.assertEqual([match["recipe_id"] for match in near_matches], [4402])
        self.assertEqual(
            [item["item_id"] for item in near_matches[0]["missing_item_candidates"]],
            [2527, 2528, 2529],
        )

    def test_specific_recipe_wins_over_single_slot_generic_result(self) -> None:
        cases = (
            (2530, 5, 9, 4044, 7003),
            (2908, 11, 15, 4067, 7006),
            (2524, 5, 9, 4070, 7003),
        )
        for item_id, sub_category, price, specific_id, generic_id in cases:
            with self.subTest(item_id=item_id):
                items = dict(self.items)
                items[item_id] = item(
                    item_id,
                    sub_category=sub_category,
                    price=price,
                )
                rules = dict(self.rules)
                if sub_category == 11:
                    items[2909] = item(2909, sub_category=11, price=7)
                    rules[11] = TierRule(
                        11,
                        "Mushroom",
                        30,
                        16,
                        "mushroom.high",
                        "mushroom.mid_low",
                    )
                recipes = [
                    recipe(specific_id, specific_items=(item_id,)),
                    recipe(generic_id, tier=3, tag_combo=(sub_category,)),
                ]
                inventory = [InventoryItem(item_id, 1, "主控背包", "backpack")]

                matches, diagnostics = match_inventory(
                    inventory,
                    recipes,
                    items,
                    rules,
                    cooking_level=1,
                )
                near_matches = find_near_matches(
                    inventory,
                    recipes,
                    items,
                    rules,
                    cooking_level=1,
                )

                self.assertEqual(diagnostics, [])
                self.assertEqual(
                    [match["recipe_id"] for match in matches],
                    [specific_id],
                )
                generic_near = [
                    match for match in near_matches if match["recipe_id"] == generic_id
                ]
                self.assertEqual(len(generic_near), 1)
                self.assertNotIn(
                    item_id,
                    {
                        candidate["item_id"]
                        for candidate in generic_near[0]["missing_item_candidates"]
                    },
                )

    def test_specific_precedence_uses_exact_multiset_only(self) -> None:
        recipes = [
            recipe(4701, specific_items=(2527, 2527)),
            recipe(4702, tier=1, tag_combo=(5, 5)),
            recipe(4703, tier=2, tag_combo=(5, 5)),
            recipe(4704, tier=3, tag_combo=(5, 5)),
        ]
        exact_matches, diagnostics = match_inventory(
            [InventoryItem(2527, 2, "主控背包", "backpack")],
            recipes,
            self.items,
            self.rules,
            cooking_level=5,
        )
        self.assertEqual(diagnostics, [])
        self.assertEqual([match["recipe_id"] for match in exact_matches], [4701])

        near_matches = find_near_matches(
            [InventoryItem(2527, 1, "主控背包", "backpack")],
            recipes,
            self.items,
            self.rules,
            cooking_level=5,
        )
        candidates = {
            candidate["item_id"]
            for match in near_matches
            for candidate in match["missing_item_candidates"]
        }
        self.assertNotIn(2527, candidates)
        self.assertIn(2528, candidates)
        self.assertIn(2529, candidates)

        different_length_matches, diagnostics = match_inventory(
            [InventoryItem(2527, 1, "主控背包", "backpack")],
            [recipe(4705, specific_items=(2527, 2527)), recipe(4706, tier=3, tag_combo=(5,))],
            self.items,
            self.rules,
            cooking_level=1,
        )
        self.assertEqual(diagnostics, [])
        self.assertEqual([match["recipe_id"] for match in different_length_matches], [4706])

    def test_completed_specific_recipe_still_blocks_generic_result(self) -> None:
        items = dict(self.items)
        items[2530] = item(2530, sub_category=5, price=9)
        recipes = [
            recipe(4801, specific_items=(2530,)),
            recipe(4802, tier=3, tag_combo=(5,)),
        ]
        inventory = [InventoryItem(2530, 1, "主控背包", "backpack")]

        matches, diagnostics = match_inventory(
            inventory,
            recipes,
            items,
            self.rules,
            completed_recipe_ids={4801},
            cooking_level=1,
        )
        near_matches = find_near_matches(
            inventory,
            recipes,
            items,
            self.rules,
            completed_recipe_ids={4801},
            cooking_level=1,
        )

        self.assertEqual(diagnostics, [])
        self.assertEqual(matches, [])
        generic_near = [
            match for match in near_matches if match["recipe_id"] == 4802
        ]
        self.assertEqual(len(generic_near), 1)
        self.assertNotIn(
            2530,
            {
                candidate["item_id"]
                for candidate in generic_near[0]["missing_item_candidates"]
            },
        )

    def test_non_food_category_is_not_a_cookable_ingredient(self) -> None:
        items = dict(self.items)
        items[9600] = item(9600, sub_category=5, price=20, category=2)
        recipes = [
            recipe(4501, specific_items=(9600,)),
            recipe(4502, tier=2, tag_combo=(4, 5)),
        ]
        inventory = [InventoryItem(9600, 1, "backpack", "backpack")]

        matches, diagnostics = match_inventory(
            inventory,
            recipes,
            items,
            self.rules,
            cooking_level=3,
        )
        near_matches = find_near_matches(
            inventory,
            recipes,
            items,
            self.rules,
            cooking_level=3,
        )

        self.assertEqual(matches, [])
        self.assertEqual(near_matches, [])
        self.assertEqual(diagnostics, [])

    def test_exact_generic_tier_suppresses_same_tier_near_recipe(self) -> None:
        recipes = [
            recipe(4601, tier=3, tag_combo=(5,)),
            recipe(4602, tier=3, tag_combo=(5,)),
        ]
        inventory = [InventoryItem(2527, 1, "backpack", "backpack")]
        matches, diagnostics = match_inventory(
            inventory,
            recipes,
            self.items,
            self.rules,
            cooking_level=1,
        )
        near_matches = find_near_matches(
            inventory,
            recipes,
            self.items,
            self.rules,
            excluded_recipe_ids={int(match["recipe_id"]) for match in matches},
            cooking_level=1,
        )

        self.assertEqual(diagnostics, [])
        self.assertEqual([match["recipe_id"] for match in matches], [4601])
        self.assertEqual(near_matches, [])

    def test_recipe_inventory_display_requires_in_codex_but_matching_does_not(self) -> None:
        hidden_item = RecipeItemSpec(
            **{
                **self.items[2527].__dict__,
                "in_codex": False,
            }
        )
        visible_items = dict(self.items)
        visible_items[2527] = hidden_item
        recipes = [recipe(4301, tier=3, tag_combo=(5,))]
        matches, _diagnostics = match_inventory(
            [InventoryItem(2527, 1, "主控背包", "backpack")],
            recipes,
            visible_items,
            self.rules,
            cooking_level=1,
        )

        self.assertEqual([match["recipe_id"] for match in matches], [4301])
        inventory_state = SaveInventoryState(
            SaveFileInfo(Path("<memory>"), "0" * 64, 0, 0, "test"),
            (InventoryItem(2527, 1, "主控背包", "backpack"),),
        )
        inventory_payload, diagnostics = _inventory_payload(
            inventory_state,
            items=visible_items,
        )
        self.assertEqual(inventory_payload, [])
        self.assertEqual(diagnostics, [])

    def test_recipe_inventory_display_merges_same_item_across_sources(self) -> None:
        inventory_state = SaveInventoryState(
            SaveFileInfo(Path("<memory>"), "0" * 64, 0, 0, "test"),
            (
                InventoryItem(2527, 2, "主控背包", "backpack"),
                InventoryItem(2527, 3, "冰柜", "freezer"),
                InventoryItem(2528, 1, "冰柜", "freezer"),
            ),
        )

        inventory_payload, diagnostics = _inventory_payload(
            inventory_state,
            items=self.items,
        )

        self.assertEqual(diagnostics, [])
        self.assertEqual(
            inventory_payload[:2],
            [
                {
                    "item_id": 2527,
                    "name": "Item 2527",
                    "count": 5,
                    "source": "主控背包、冰柜",
                    "container": "backpack、freezer",
                    "category": 1,
                    "sub_category": 5,
                    "sub_category_name": "Subcategory 5",
                    "price": 7,
                },
                {
                    "item_id": 2528,
                    "name": "Item 2528",
                    "count": 1,
                    "source": "冰柜",
                    "container": "freezer",
                    "category": 1,
                    "sub_category": 5,
                    "sub_category_name": "Subcategory 5",
                    "price": 20,
                },
            ],
        )


class RecipePlanTests(unittest.TestCase):
    def test_targeted_refresh_reads_only_requested_child_save(self) -> None:
        history_path = Path("HistorySave.bytes")

        def history_record(file_name: str, player_select_id: int) -> SaveHistoryRecord:
            return SaveHistoryRecord(
                file_name=file_name,
                name=file_name,
                player_select_id=player_select_id,
                max_day=3,
                turn=4,
                is_finished=False,
                finish_result=0,
                difficulty_preset_id=0,
                difficulty_levels=(),
                is_pure_endless=False,
                endless_start_day=0,
                is_story_endless=False,
                story_endless_origin_ending=0,
            )

        history = CodexSaveState(
            file_info=SaveFileInfo(history_path, "h" * 64, 1, 1, "test"),
            category_ids={"dish": ()},
            raw_category_ids={},
            codex_offset=0,
            trailing_offset=0,
            history_records=(
                history_record("Save_one.bytes", 1),
                history_record("Save_two.bytes", 2),
            ),
            last_play_file_name="Save_one.bytes",
        )
        items = {2527: item(2527, sub_category=5, price=7)}
        rules = {
            sub_category: TierRule(
                sub_category,
                f"Subcategory {sub_category}",
                30,
                16,
                "high",
                "mid",
            )
            for sub_category in SUPPORTED_TIER_SUBCATEGORIES
        }
        recipes = tuple(
            recipe(10000 + index, specific_items=(2527,))
            for index in range(496)
        )
        existing_saves = {
            "Save_one.bytes": {
                "file_name": "Save_one.bytes",
                "status": "ok",
                "inventory": [{"item_id": 1}],
                "diagnostics": [],
            },
            "Save_two.bytes": {
                "file_name": "Save_two.bytes",
                "status": "ok",
                "inventory": [{"item_id": 2}],
                "diagnostics": [],
            },
        }
        read_paths: list[Path] = []

        def read_inventory(path: Path, **_kwargs: object) -> SaveInventoryState:
            read_paths.append(path)
            return SaveInventoryState(
                SaveFileInfo(path, "s" * 64, 0, 0, "test"),
                (),
            )

        connection = sqlite3.connect(":memory:")
        try:
            with (
                patch("codex_recipe.read_history_save", return_value=history),
                patch("codex_recipe._load_items_from_database", return_value=items),
                patch("codex_recipe._load_rules_from_database", return_value=rules),
                patch("codex_recipe._load_recipes_from_database", return_value=recipes),
                patch("codex_recipe._load_storage_furniture_from_database", return_value={}),
                patch("codex_recipe.read_game_save_inventory", side_effect=read_inventory),
            ):
                payload = build_recipe_plan(
                    connection,
                    history_path,
                    refresh_file_name="Save_one.bytes",
                    existing_saves=existing_saves,
                )
        finally:
            connection.close()

        self.assertEqual([path.name for path in read_paths], ["Save_one.bytes"])
        result_by_name = {save["file_name"]: save for save in payload["saves"]}
        self.assertEqual(result_by_name["Save_two.bytes"], existing_saves["Save_two.bytes"])
        self.assertEqual(result_by_name["Save_one.bytes"]["status"], "ok")


class RecipeConfigTests(unittest.TestCase):
    def test_storage_furniture_is_selected_by_storage_behavior(self) -> None:
        specs = storage_furniture_specs_from_rows(
            [
                ConfigRow(
                    "Config_Furniture",
                    {"ID": 204, "Name_Local": "任意置物架", "FurnitureFunc": [215]},
                ),
                ConfigRow(
                    "Config_Furniture",
                    {"ID": 10000, "Name_Local": "无关名称", "ShowStorage": 100},
                ),
                ConfigRow(
                    "Config_Furniture",
                    {"ID": 215, "Name_Local": "双门冰箱", "FurnitureFunc": [215]},
                ),
                ConfigRow(
                    "Config_Furniture",
                    {"ID": 431, "Name_Local": "冰箱", "FurnitureFunc": [1]},
                ),
                ConfigRow(
                    "Config_Furniture",
                    {"ID": 102, "Name_Local": "冷冻柜", "FurnitureFunc": [1744]},
                ),
            ]
        )

        self.assertEqual(
            specs,
            (
                StorageFurnitureSpec(204, "任意置物架"),
                StorageFurnitureSpec(215, "双门冰箱"),
                StorageFurnitureSpec(10000, "无关名称"),
            ),
        )

    def test_database_storage_mapping_reads_current_storage_behavior(self) -> None:
        connection = sqlite3.connect(":memory:")
        try:
            connection.execute(
                """
                CREATE TABLE codex_entries (
                    source_table TEXT NOT NULL,
                    source_id INTEGER NOT NULL,
                    name TEXT NOT NULL,
                    raw_json TEXT NOT NULL,
                    is_current INTEGER NOT NULL
                )
                """
            )
            connection.executemany(
                """
                INSERT INTO codex_entries(source_table, source_id, name, raw_json, is_current)
                VALUES ('Config_Furniture', ?, ?, ?, ?)
                """,
                [
                    (102, "冷冻柜", '{"FurnitureFunc":[1744],"ShowStorage":0}', 1),
                    (215, "任意容器", '{"FurnitureFunc":[215],"ShowStorage":0}', 1),
                    (107, "架子", '{"FurnitureFunc":[],"ShowStorage":100}', 1),
                    (900, "旧容器", '{"FurnitureFunc":[215],"ShowStorage":0}', 0),
                ],
            )
            self.assertEqual(
                _load_storage_furniture_from_database(connection),
                {107: "架子", 215: "任意容器"},
            )
        finally:
            connection.close()

    def test_database_storage_mapping_uses_dedicated_table_as_authority(self) -> None:
        connection = sqlite3.connect(":memory:")
        try:
            connection.execute(
                """
                CREATE TABLE codex_entries (
                    source_table TEXT NOT NULL,
                    source_id INTEGER NOT NULL,
                    name TEXT NOT NULL,
                    raw_json TEXT NOT NULL,
                    is_current INTEGER NOT NULL
                )
                """
            )
            connection.execute(
                """
                INSERT INTO codex_entries(source_table, source_id, name, raw_json, is_current)
                VALUES ('Config_Furniture', 215, 'Current storage',
                        '{"FurnitureFunc":[215],"ShowStorage":0}', 1)
                """
            )
            connection.execute(
                """
                CREATE TABLE storage_furniture (
                    config_id INTEGER NOT NULL,
                    name TEXT NOT NULL
                )
                """
            )
            connection.executemany(
                "INSERT INTO storage_furniture(config_id, name) VALUES (?, ?)",
                [(215, "Legacy storage"), (80062, "Legacy fridge")],
            )

            mapping = _load_storage_furniture_from_database(connection)
            self.assertEqual(mapping, {215: "Legacy storage", 80062: "Legacy fridge"})
        finally:
            connection.close()

    def test_database_storage_mapping_keeps_non_current_dedicated_rows(self) -> None:
        connection = sqlite3.connect(":memory:")
        try:
            connection.execute(
                """
                CREATE TABLE codex_entries (
                    source_table TEXT NOT NULL,
                    source_id INTEGER NOT NULL,
                    name TEXT NOT NULL,
                    raw_json TEXT NOT NULL,
                    is_current INTEGER NOT NULL
                )
                """
            )
            connection.execute(
                """
                CREATE TABLE storage_furniture (
                    config_id INTEGER NOT NULL,
                    name TEXT NOT NULL
                )
                """
            )
            connection.execute(
                """
                INSERT INTO codex_entries(source_table, source_id, name, raw_json, is_current)
                VALUES ('Config_Furniture', 900, 'Old storage',
                        '{"FurnitureFunc":[215],"ShowStorage":0}', 0)
                """
            )
            connection.execute(
                "INSERT INTO storage_furniture(config_id, name) VALUES (?, ?)",
                (900, "Old storage"),
            )

            self.assertEqual(_load_storage_furniture_from_database(connection), {900: "Old storage"})
        finally:
            connection.close()

    def test_empty_dedicated_storage_table_does_not_reintroduce_legacy_rows(self) -> None:
        connection = sqlite3.connect(":memory:")
        try:
            connection.execute(
                "CREATE TABLE storage_furniture (config_id INTEGER NOT NULL, name TEXT NOT NULL)"
            )

            self.assertEqual(_load_storage_furniture_from_database(connection), {})
        finally:
            connection.close()

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
