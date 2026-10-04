from __future__ import annotations

import shutil
import subprocess
import unittest
from pathlib import Path


class PagesFilterTests(unittest.TestCase):
    def test_production_filters_match_tiers_quantities_specific_priority_and_levels(self) -> None:
        node = shutil.which("node")
        if not node:
            self.skipTest("Node.js is required to exercise the production browser filters")
        script = r"""
const fs = require('node:fs'), vm = require('node:vm'), assert = require('node:assert/strict');
const controls = new Map();
const get = id => {
  if (!controls.has(id)) controls.set(id, {value: '', hidden: true, checked: false, addEventListener() {}});
  return controls.get(id);
};
const sandbox = {document: {getElementById: get, addEventListener() {}}, window: {addEventListener() {}},
  matchMedia: () => ({matches: false, addEventListener() {}}), setTimeout, clearTimeout};
const source = fs.readFileSync(process.argv[1], 'utf8');
vm.runInNewContext(fs.readFileSync(require('node:path').join(require('node:path').dirname(process.argv[1]), 'planting.js'), 'utf8'), sandbox);
vm.runInNewContext(fs.readFileSync(require('node:path').join(require('node:path').dirname(process.argv[1]), 'cooking.js'), 'utf8'), sandbox);
vm.runInNewContext(source.replace(/  load\(\);\s*\}\)\(\);\s*$/, '  globalThis.api = {state, matchesSelectedMaterials, filteredEntries};\n})();'), sandbox);
const {state, matchesSelectedMaterials: matches, filteredEntries: filtered} = sandbox.api;
state.category = 'dish';
state.ingredients = [
  {id: 1, sub_category_id: 1, tier: null},
  {id: 2, sub_category_id: 2, tier: 3}, {id: 3, sub_category_id: 2, tier: 1},
  {id: 4, sub_category_id: 11, tier: 3}, {id: 5, sub_category_id: 11, tier: 1},
  {id: 6, sub_category_id: 11, tier: 2},
];
const recipe = (id, tier, tags, specifics = [], level = 0) => ({id, key: 'r' + id, nameIndex: '', materialIndex: '',
  hasSpecificIngredients: specifics.length > 0, recipe: {tier, tag_combo: tags, specific_items: specifics, min_level: level}});
const low = recipe(100, 3, [1, 2, 11]), mid = recipe(101, 2, [1, 2, 11], [], 1),
  high = recipe(102, 1, [1, 2, 11], [], 2), duplicate = recipe(103, 1, [11, 1, 2], [], 2),
  specific = recipe(200, 0, [], [2, 2], 1), genericPair = recipe(201, 3, [2, 2]);
state.categories = [{id: 'dish', entries: [low, mid, high, duplicate, specific, genericPair]}];
get('tierFloorSelect').value = '0';
const select = (...ids) => ids.map(id => ({id}));
assert.equal(matches(low, select(1, 2, 4)), true);
assert.equal(matches(high, select(1, 2, 4)), false);
assert.equal(matches(high, select(1, 2, 5)), true);
assert.equal(matches(low, select(1, 2, 5)), false);
assert.equal(matches(mid, select(1, 2, 6)), true);
assert.equal(matches(high, select(1, 3, 6)), true);
assert.equal(matches(duplicate, select(1, 2, 5)), false);
assert.equal(matches(high, select(4)), true); // A high-tier meat can complete the remaining slots.
assert.equal(matches(low, select(5)), false);
assert.equal(matches(low, [{group: 1}, {group: 2}, {group: 11}]), true);
assert.equal(matches(specific, select(2, 2)), true);
assert.equal(matches(specific, select(2, 3)), false);
assert.equal(matches(specific, select(2, 2, 2)), false);
assert.equal(matches(genericPair, select(2, 2)), false); // The exact special recipe takes priority.
get('tierFloorSelect').value = '3';
assert.equal(matches(high, select(1, 2, 4)), true);
assert.equal(matches(low, select(1, 2, 4)), false);
assert.equal(matches(specific, select(2, 2)), true);
get('tierFloorSelect').value = '0';
get('sortSelect').value = 'default';
get('cookingLevelSelect').value = '0';
assert.deepEqual(Array.from(filtered(), e => e.id), [100, 201]);
get('cookingLevelSelect').value = '1';
state.materials = select(2, 2);
assert.deepEqual(Array.from(filtered(), e => e.id), [200]);
get('specificRecipesOnly').checked = true;
state.materials = [];
assert.deepEqual(Array.from(filtered(), e => e.id), [200]);
// Fridge stock selects a subset rather than requiring every registered ingredient in one pot.
get('specificRecipesOnly').checked = false;
get('cookingMode').value = 'pantry'; get('sortSelect').value = 'ValueDisplay1';
get('cookingLevelSelect').value = '2';
state.materials = select(6); // Independent exact-query selection must not constrain pantry mode.
state.stock = {1: 2, 2: 1, 3: 1, 4: 1, 5: 1};
state.cookingModel = {tier_coefficients: {1: 1.7, 2: 1.4, 3: 1.1}, quality_coefficients: {'普通': .9}, base_satiety_per_ingredient: 2, split_threshold: 40};
get('qualitySelect').value = '普通';
for (const ingredient of state.ingredients) ingredient.stats = [10, 0, 0, 0, 0];
for (const entry of state.categories[0].entries) {
  entry.portion_model = {mode: entry.recipe.specific_items.length ? 'fixed' : 'ingredients', threshold: 40};
  entry.products = [{quality: '普通', stats: [1,2,3,4,5].map(index => ({field:'ValueDisplay' + index, value:0}))}];
}
assert.deepEqual(Array.from(filtered(), e => e.id), [102, 100]); // Exact pair is short by one use.
get('cookingLevelSelect').value = '0';
assert.deepEqual(Array.from(filtered(), e => e.id), [100]);
state.stock = {}; get('cookingLevelSelect').value = '';
assert.deepEqual(Array.from(filtered(), e => e.id), []);
get('cookingMode').value = 'recipes'; get('sortSelect').value = 'default';
state.materials = []; get('specificRecipesOnly').checked = true;
state.category = 'food';
state.categories.push({id: 'food', entries: [
  {id: 10, nameIndex: '', materialIndex: '', sources: [{category: 'plant'}], food: {sub_category_id: 11, tier: 1}},
  {id: 11, nameIndex: '', materialIndex: '', food: {sub_category_id: 11, tier: 3}},
  {id: 12, nameIndex: '', materialIndex: '', sources: [{category: 'prey'}], food: {sub_category_id: 2, tier: 2}},
  {id: 13, nameIndex: '', materialIndex: '', sources: [{category: 'craft'}], food: {sub_category_id: 1, tier: null}},
]});
state.group = '11';
assert.deepEqual(Array.from(filtered(), e => e.id), [10, 11]);
state.tier = '1';
assert.deepEqual(Array.from(filtered(), e => e.id), [10]);
state.group = '2';
assert.deepEqual(Array.from(filtered(), e => e.id), []);
state.group = ''; state.tier = 'none';
assert.deepEqual(Array.from(filtered(), e => e.id), [13]);
state.tier = ''; get('renewableOnly').checked = true;
assert.deepEqual(Array.from(filtered(), e => e.id), [10, 12]);
state.group = '11';
assert.deepEqual(Array.from(filtered(), e => e.id), [10]); // Sources combine with other ingredient facets.
state.tier = '3';
assert.deepEqual(Array.from(filtered(), e => e.id), []);
state.group = ''; state.tier = '';
get('renewableOnly').checked = false;
assert.deepEqual(Array.from(filtered(), e => e.id), [10, 11, 12, 13]);
get('renewableOnly').checked = true; // Hidden source filter must not affect other categories.
state.category = 'plant';
get('plantOnlySuitable').checked = true;
const plant = (id, size, light, cold) => ({id, nameIndex: '', materialIndex: '',
  plant: {size, light_need: light, cold_resistance: cold}});
state.categories.push({id: 'plant', entries: [plant(20, 1, 0, 0), plant(21, 1, 1, 2),
  plant(22, 2, 2, 3), plant(23, 4, 2, 0), plant(24, 2, 0, 1), plant(25, null, null, null)]});
const result = () => Array.from(filtered(), e => e.id);
assert.deepEqual(result(), [20, 21, 22, 23, 24, 25]); // Blank environmental fields impose no requirements.
get('plantLight').value = '0'; get('plantCold').value = '0';
assert.deepEqual(result(), [20, 24]); // Zero is a real condition, not a blank value.
get('plantLight').value = '2';
assert.deepEqual(result(), [20, 21, 22, 23, 24]); // Exact light and cold boundaries are inclusive.
get('plantCold').value = '3';
assert.deepEqual(result(), [22]);
state.planters = [{id: 60007, capacity: 2, light_bonus: 0, heat_bonus: 1,
  needs_power: true, electric_light: 2, electric_heat: 0}];
get('planterSelect').value = '60007';
get('plantLight').value = '0'; get('plantCold').value = '3';
get('planterPower').value = 'on';
assert.deepEqual(result(), [21, 22]); // Passive insulation plus electric light.
get('planterPower').value = 'off';
assert.deepEqual(result(), []);
get('plantCold').value = '2';
assert.deepEqual(result(), [24]); // Passive heat remains when unpowered.
get('plantLight').value = '1.99'; get('plantCold').value = '1';
assert.deepEqual(result(), [20, 21, 24]);
get('plantLight').value = '2';
assert.deepEqual(result(), [20, 21, 22, 24]); // Large plant does not fit the medium planter.
get('plantLight').value = ''; get('plantCold').value = '';
assert.deepEqual(result(), [20, 21, 22, 24]); // A planter alone checks space, not unknown ambient light/cold.
get('plantLight').value = '-1';
assert.deepEqual(result(), []);
get('plantLight').value = '';
get('plantCold').validity = {badInput: true};
assert.deepEqual(result(), []);
get('plantCold').validity = {valid: true};
get('planterSelect').value = '';
assert.deepEqual(result(), [20, 21, 22, 23, 24, 25]);
"""
        result = subprocess.run([node, "-e", script, str(Path(__file__).resolve().parents[1] / "pages/app.js")],
                                capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)


if __name__ == "__main__":
    unittest.main()
