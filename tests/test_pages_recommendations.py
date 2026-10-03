from __future__ import annotations

import json
import unittest

from codex_pages import dish_servings, food_profile
from codex_pages_recommendations import build_recommendations, rate_rows, recommendation_document


class SupplyRecommendationTests(unittest.TestCase):
    def setUp(self) -> None:
        self.items = {
            1: ("米", {"ID": 1, "Category": 1, "CanCook": True, "CantUse": True, "UseTimes": 7,
                       "price": 35, "Life": 360, "Size": [2, 2], "ValueDisplay1": 5,
                       "ValueDisplay2": 0, "ValueDisplay3": 0, "ValueDisplay4": 0, "ValueDisplay5": 0}),
            2: ("饼干", {"ID": 2, "Category": 1, "CanCook": False, "CantUse": False, "UseTimes": 10,
                         "price": 200, "Life": 360, "Size": [4, 3], "ValueDisplay1": 20,
                         "ValueDisplay2": -3, "ValueDisplay3": 0, "ValueDisplay4": 0, "ValueDisplay5": 0}),
        }
        self.raw = {f"Config_Item:{i}": raw for i, (_name, raw) in self.items.items()}
        self.raw["Config_CookingRecipe:10"] = {"SpecificItems": [1, 1], "TagCombo": [], "MinLevel": 1, "CookTime": 3600}
        self.raw["Config_Plant:20"] = {"Gain": [1, 1], "GrowthTime": 86400, "Size": 2, "Seed_Rate": .5,
                                       "Perfect_Gain": [1, 1, 1, 1], "PRIVATE": "PRIVATE_IGNORE"}
        product = food_profile({"ValueDisplay1": 60, "ValueDisplay2": 4, "ValueDisplay3": 0,
                                "ValueDisplay4": 0, "ValueDisplay5": 0}, {}, {})
        product["serving_count"], product["per_use_stats"] = dish_servings(product, 40, True)
        self.categories = [
            {"id": "food", "entries": [{"key": f"Config_Item:{i}", "id": i, "name": name} for i, (name, _raw) in self.items.items()]},
            {"id": "dish", "entries": [{"key": "Config_CookingRecipe:10", "id": 10, "name": "米饭",
                                          "products": [{**product, "quality": quality} for quality in ("普通", "良好", "完美")], "relations": []}]},
            {"id": "plant", "entries": [{"key": "Config_Plant:20", "id": 20, "name": "作物"}]},
        ]

    def build(self) -> dict:
        return build_recommendations(self.categories, self.raw, self.items, lambda raw: food_profile(raw, {}, {}))

    def test_multislot_use_cost_differs_from_whole_package_purchase(self) -> None:
        dish = self.build()["dishes"][0]
        self.assertEqual(dish["ingredients"][0]["amount"], 2)
        self.assertEqual(dish["cost"], 10)
        self.assertEqual(dish["basket"], 35)
        self.raw["Config_CookingRecipe:10"]["SpecificItems"] = [1] * 8
        dish = self.build()["dishes"][0]
        self.assertEqual(dish["cost"], 40)
        self.assertEqual(dish["basket"], 70)

    def test_servings_do_not_multiply_total_satiety_again(self) -> None:
        dish = self.build()["dishes"][0]
        result = dish["qualities"]["普通"]
        self.assertEqual(result["total"][0], 60)
        self.assertEqual(result["servings"], 2)
        self.assertEqual(result["per_use"][0], 30)
        self.assertEqual(dish["ratings"]["1:普通"]["cost100"], 100 * 10 / 60)
        self.assertEqual(dish["input_satiety"], 10)

    def test_stock_counts_all_uses_and_keeps_negative_recovery_penalty(self) -> None:
        stock = self.build()["stock"][0]
        self.assertEqual(stock["total"], [200, -30, 0, 0, 0])
        self.assertEqual(stock["cost100"], 100)
        self.assertEqual(stock["penalty"], 30)

    def test_zero_price_unknown_uses_and_bool_uses_are_unscored(self) -> None:
        for field, value in (("price", 0), ("UseTimes", None), ("UseTimes", True), ("CantUse", True)):
            with self.subTest(field=field, value=value):
                previous = self.items[2][1][field]
                self.items[2][1][field] = value
                row = self.build()["stock"][0]
                self.assertIsNone(row["score"])
                self.assertTrue(row["reason"])
                self.items[2][1][field] = previous

    def test_level_gate_quality_and_unknown_generic_output(self) -> None:
        self.raw["Config_CookingRecipe:10"]["MinLevel"] = 3
        dish = self.build()["dishes"][0]
        self.assertNotIn("1:普通", dish["ratings"])
        self.assertIsNotNone(dish["ratings"]["3:完美"]["score"])
        self.raw["Config_CookingRecipe:10"].update(SpecificItems=[], TagCombo=[1, 1])
        dish = self.build()["dishes"][0]
        self.assertIsNone(dish["ratings"]["3:普通"]["score"])
        self.assertIsNone(dish["qualities"]["普通"]["total"])

    def test_crops_count_repeated_basic_harvest_and_do_not_add_perfect_or_seed(self) -> None:
        crop = self.build()["crops"][0]
        self.assertEqual(crop["harvest"][0]["amount"], 2)
        self.assertEqual(crop["cook_uses"], 14)
        self.assertEqual(crop["daily_uses"], 7)
        self.assertEqual(crop["satiety"], 0)  # CantUse excludes a made-up direct food yield.
        self.assertNotIn("PRIVATE_", json.dumps(crop))

    def test_missing_input_price_never_becomes_zero_cost_efficiency(self) -> None:
        del self.items[1][1]["price"]
        dish = self.build()["dishes"][0]
        self.assertIsNone(dish["cost"])
        self.assertIsNone(dish["ratings"]["1:普通"]["score"])

    def test_ties_are_equal_and_penalties_cannot_make_negative_scores(self) -> None:
        rows = [{"metrics": {"value": 1, "storage": 1, "space": 1, "effects": 1}, "penalty": penalty} for penalty in (0, 0, 200)]
        rate_rows(rows, "stock")
        self.assertEqual(rows[0]["score"], rows[1]["score"])
        self.assertEqual(rows[2]["score"], 0)

    def test_embedded_json_and_visible_names_escape_game_text(self) -> None:
        malicious = '</script><img src=x onerror="alert(1)">'
        self.categories[1]["entries"][0]["name"] = malicious
        document = recommendation_document({"recommendations": self.build(), "metadata": {}}, "https://example.org/game/")
        self.assertNotIn(malicious, document)
        self.assertIn("\\u003c/script>", document)
        self.assertIn("&lt;/script&gt;", document)
        self.assertIn("https://example.org/game/recommendations/", document)


if __name__ == "__main__":
    unittest.main()
