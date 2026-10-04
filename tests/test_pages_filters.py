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
vm.runInNewContext(source.replace(/  load\(\);\s*\}\)\(\);\s*$/, '  globalThis.api = {state, matchesSelectedMaterials, filteredEntries};\n})();'), sandbox);
const {state, matchesSelectedMaterials: matches, filteredEntries: filtered} = sandbox.api;
state.category = 'dish';
state.ingredients = [
  {id: 1, sub_category_id: 1, tier: null},
  {id: 2, sub_category_id: 2, tier: 3}, {id: 3, sub_category_id: 2, tier: 1},
  {id: 4, sub_category_id: 11, tier: 3}, {id: 5, sub_category_id: 11, tier: 1},
  {id: 6, sub_category_id: 11, tier: 2},
];
const recipe = (id, tier, tags, specifics = [], level = 0) => ({id, nameIndex: '', materialIndex: '',
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
"""
        result = subprocess.run([node, "-e", script, str(Path(__file__).resolve().parents[1] / "pages/app.js")],
                                capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)


if __name__ == "__main__":
    unittest.main()
