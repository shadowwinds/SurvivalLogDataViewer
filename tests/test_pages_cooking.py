from __future__ import annotations

import json
import shutil
import subprocess
import unittest
from pathlib import Path

from codex_pages import export_data


ROOT = Path(__file__).resolve().parents[1]


class CookingPlannerTests(unittest.TestCase):
    def run_browser(self, assertions: str, payload: dict | None = None) -> None:
        executable = shutil.which("node")
        if not executable:
            self.skipTest("Node.js is required for the production cooking planner")
        script = r"""
const fs = require('node:fs'), vm = require('node:vm'), assert = require('node:assert/strict');
const sandbox = {window: {}};
vm.runInNewContext(fs.readFileSync(process.argv[1] + '/pages/cooking.js', 'utf8'), sandbox);
const {tier, forecast, plan} = sandbox.window.Cooking;
const data = JSON.parse(fs.readFileSync(0, 'utf8'));
const model = JSON.parse(fs.readFileSync(process.argv[1] + '/pages/cooking-model.json', 'utf8'));
const stats = values => values.map((value, i) => ({field: 'ValueDisplay' + (i + 1), value}));
const item = (id, group, tier, values = [10, -100, 99, 2, 3]) =>
  ({id, sub_category_id: group, tier, stats: values, price: 10, use_times: 2});
const recipe = (id, tier, groups, specifics = [], fixed = false, values = [0, 8.1, -2.8, 0, 0]) =>
  ({id, key: 'r' + id, recipe: {tier, tag_combo: groups, specific_items: specifics},
    portion_model: {mode: fixed ? 'fixed' : 'generic', threshold: 40},
    products: [{quality: '普通', stats: stats(values)}]});
""" + assertions
        result = subprocess.run([executable, "-e", script, str(ROOT)], input=json.dumps(payload or {}, ensure_ascii=False),
                                capture_output=True, text=True, encoding="utf-8")
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

    def test_all_seven_player_observations_match_current_data_and_price_boundaries(self) -> None:
        payload = export_data(ROOT / "survival_log_codex.sqlite3")
        self.run_browser(r"""
const ingredients = data.cooking_ingredients, dishes = data.categories.find(c => c.id === 'dish').entries;
const find = id => ingredients.find(i => i.id === id);
assert.equal(find(2529).price, find(2529).tier_thresholds.high); // Cauliflower is exactly high tier.
assert.equal(find(2529).tier, 1);
assert.equal(find(2313).tier, 2); assert.equal(find(2520).tier, 2); assert.equal(find(2519).tier, 1);
assert.equal(find(30000).tier, 3); assert.equal(find(2513).tier, 3);
const cases = [
  [[30025, 2522, 2118], 5011], [[2302, 2529, 2520], 6013], [[2103, 2529, 30000], 6010],
  [[30000, 2529, 2520], 6013], [[30000, 2529, 2513], 6013], [[2313, 2520], 5023], [[2313, 2519], 6023],
  [[30000, 2522, 2513], 5013], // Replacing the highest contributor lowers the dish tier.
];
for (const [ids, expected] of cases) {
  const stock = Object.fromEntries(ids.map(id => [id, ids.filter(other => other === id).length]));
  const results = plan(dishes, ingredients, stock, '普通', 0, 0, data.cooking_model);
  const key = 'Config_CookingRecipe:' + expected;
  assert.ok(results.has(key), JSON.stringify({ids, expected, results: [...results.keys()]}));
  assert.deepEqual(Array.from(results.get(key).ingredients, i => i.id).sort((a, b) => a - b), [...ids].sort((a, b) => a - b));
}
const mid = forecast(dishes.find(e => e.id === 5023), [find(2313), find(2520)], '普通', data.cooking_model);
const high = forecast(dishes.find(e => e.id === 6023), [find(2313), find(2519)], '普通', data.cooking_model);
assert.equal(mid.total[0], 23); assert.equal(mid.total[4], 23);
assert.equal(high.total[0], 32); assert.equal(high.total[4], 16); // Higher tier is not always better for every stat.
""", payload)

    def test_generic_formula_sums_only_satiety_health_life_and_splits_total_once(self) -> None:
        self.run_browser(r"""
const mushroom = item(1, 11, 2), entry = recipe(1, 2, [11, 11]);
let result = forecast(entry, [mushroom, mushroom], '普通', model);
assert.deepEqual(Array.from(result.total), [30, 9, -2, 6, 8]);
assert.equal(result.servings, 1);
result = forecast(entry, [mushroom, mushroom, mushroom], '普通', model);
assert.equal(result.total[0], 44); assert.equal(result.servings, 2);
assert.equal(result.perUse[0], 22); assert.equal(result.perUse[1], 4.5);
entry.products[0].stats = stats([0, -2.1, 3.1, 0, 0]);
const negative = item(2, 11, 2, [-10, 999, 999, -2, -3]);
result = forecast(entry, [negative], '普通', model);
assert.deepEqual(Array.from(result.total), [-10, -2, 4, -2, -3]);
assert.equal(result.servings, 1);
""")

    def test_fixed_products_quality_and_missing_values_are_not_guessed(self) -> None:
        self.run_browser(r"""
const entry = recipe(1, 0, [], [1], true, [40.1, -2.8, 1.01, 0, 2]);
const result = forecast(entry, [item(1, 2, 3)], '普通', null);
assert.deepEqual(Array.from(result.total), [41, -2, 2, 0, 2]);
assert.equal(result.servings, 2); assert.equal(result.perUse[0], 20.5);
assert.equal(forecast(entry, [], '完美', model), null);
entry.products[0].stats[4].value = null;
assert.equal(forecast(entry, [], '普通', model), null);
assert.equal(forecast(recipe(2, 1, [2]), [item(1, 2, 1)], '普通', null), null);
assert.equal(forecast(recipe(2, 1, [2]), [item(1, 2, 1, [null, 0, 0, 0, 0])], '普通', model), null);
""")

    def test_quantity_multisets_special_priority_duplicates_and_minimum_tier(self) -> None:
        self.run_browser(r"""
const foods = [item(1, 11, 3), item(2, 11, 1), item(3, 1, null)];
const low = recipe(10, 3, [11, 11]), high = recipe(11, 1, [11, 11]), duplicate = recipe(12, 1, [11, 11]);
const special = recipe(20, 0, [], [1, 1], true, [50, 1, 1, 1, 1]);
const entries = [low, high, duplicate, special];
assert.equal(plan(entries, foods, {1: 1}, '普通', 0, 0, model).size, 0);
let results = plan(entries, foods, {1: 2}, '普通', 0, 0, model);
assert.deepEqual(Array.from(results.keys()), ['r20']); // Specific match excludes this generic combination.
results = plan(entries, foods, {1: 1, 2: 1}, '普通', 0, 0, model);
assert.deepEqual(Array.from(results.keys()), ['r11']);
assert.deepEqual(Array.from(results.get('r11').ingredients, i => i.id), [1, 2]);
results = plan([low, high], foods, {1: 2}, '普通', 0, 3, model);
assert.deepEqual(Array.from(results.keys()), ['r11']);
assert.equal(tier([foods[2]], 3), null); // Unsupported categories cannot create a tier.
assert.equal(tier([foods[0], foods[2]]), 3);
assert.equal(tier([foods[0], foods[1]]), 1);
""")

    def test_best_concrete_combination_changes_with_recovery_goal(self) -> None:
        self.run_browser(r"""
const foods = [item(1, 2, 2, [20, -5, 9, 0, 0]), item(2, 2, 2, [5, 10, -8, 8, 9]), item(3, 11, 2)];
const entry = recipe(1, 2, [2, 11]);
const stock = {1: 1, 2: 1, 3: 1};
const satiety = plan([entry], foods, stock, '普通', 0, 0, model).get('r1');
const health = plan([entry], foods, stock, '普通', 3, 0, model).get('r1');
assert.deepEqual(Array.from(satiety.ingredients, i => i.id), [1, 3]);
assert.deepEqual(Array.from(health.ingredients, i => i.id), [2, 3]);
assert.ok(satiety.total[0] > health.total[0]); assert.ok(health.total[3] > satiety.total[3]);
assert.deepEqual(stock, {1: 1, 2: 1, 3: 1}); // Independent recommendations never reserve shared inventory.
""")

    def test_parameter_export_validates_values_and_does_not_publish_unrelated_settings(self) -> None:
        from unittest.mock import patch
        from codex_pages_cooking import extract_cooking_model
        model = json.loads((ROOT / "pages/cooking-model.json").read_text(encoding="utf-8"))
        keys = {"CookingVD_TierCoeff_High": 1.7, "CookingVD_TierCoeff_Mid": 1.4, "CookingVD_TierCoeff_Low": 1.1,
                "CookingVD_QualityCoeff_Fail": .5, "CookingVD_QualityCoeff_Normal": .9,
                "CookingVD_QualityCoeff_Good": 1.2, "CookingVD_QualityCoeff_Perfect": 1.5,
                "CookingVD_BaseSatietyPerIngredient": 2, "CookingSatiety_SplitThreshold": 40, "PRIVATE": 900}
        settings = {key: (0, value, None) for key, value in keys.items()}
        with patch("codex_pages_cooking.find_catalog", return_value=Path("catalog")), \
             patch("codex_pages_cooking.parse_catalog", return_value=(None, None, "version")), \
             patch("codex_pages_cooking.read_global_settings", return_value=settings):
            result = extract_cooking_model(Path("game"))
            self.assertEqual(set(result), set(model))
            self.assertNotIn("PRIVATE", json.dumps(result))
            for invalid in (float("nan"), float("inf"), 0, -1):
                settings["CookingVD_TierCoeff_High"] = (0, invalid, None)
                with self.assertRaisesRegex(ValueError, "CookingVD_TierCoeff_High"):
                    extract_cooking_model(Path("game"))


if __name__ == "__main__":
    unittest.main()
