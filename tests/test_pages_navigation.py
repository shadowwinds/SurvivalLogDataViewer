from __future__ import annotations

import json
import re
import shutil
import subprocess
import unittest
from pathlib import Path

from codex_pages_recommendations import VIEW_LABELS
from codex_pages_seo import CATEGORY_INTROS, site_nav, trade_document


ROOT = Path(__file__).resolve().parents[1]
PAGES = ROOT / "pages"
# 由 prey-model.json 动态追加的分类，以及冰箱配餐、首页这两个只在网址上区分的入口。
EXTRA_ROUTES = {"traps", "baits", "cages", "pantry", "home"}


class NavigationEntryTests(unittest.TestCase):
    def setUp(self) -> None:
        self.index = (PAGES / "index.html").read_text(encoding="utf-8")
        self.app = (PAGES / "app.js").read_text(encoding="utf-8")
        self.routes = set(CATEGORY_INTROS) | EXTRA_ROUTES
        trade = trade_document({"points": [], "items": [], "categories": {}, "shared": []}, "../", "test")
        self.plans = set(re.findall(r'data-plan="([\w-]+)"', trade))

    def assert_target(self, href: str) -> None:
        if href.startswith("#"):
            self.assertRegex(href, r"^#[\w-]+/$")
            self.assertIn(href[1:-1], self.routes, href)
        elif href.startswith("./recommendations/"):
            view = href.partition("#")[2]
            self.assertTrue(not view or view in VIEW_LABELS, href)
        elif href.startswith("./trade/"):
            fragment = href.partition("#")[2]
            self.assertTrue(not fragment or fragment.removeprefix("plan=") in self.plans, href)
        else:
            self.fail(f"unexpected entry link: {href}")

    def test_home_tasks_point_to_existing_routes_tabs_and_views(self) -> None:
        tasks = re.findall(r'<a class="hub-task" href="([^"]+)"', self.index)
        self.assertGreaterEqual(len(tasks), 15)
        for href in tasks:
            with self.subTest(href=href):
                self.assert_target(href)
        for group in re.findall(r'data-group="(\d+)"', self.index):
            self.assertIn(group, {"3", "6"})
        for control in re.findall(r'data-focus="(\w+)"', self.index):
            self.assertIn(f'id="{control}"', self.index)

    def test_related_tools_and_nav_targets_exist(self) -> None:
        block = self.app[self.app.index("const relatedTools = {"):self.app.index("const searchOrder")]
        links = re.findall(r'\["([^"]+)", "[^"]+"', block)
        self.assertTrue(links)
        for href in links:
            with self.subTest(href=href):
                self.assert_target(href)
        nav = self.app[self.app.index("const navGroups = ["):self.app.index("const navLabels")]
        for route in re.findall(r'"([\w-]+)"', nav):
            if not re.search(r"[㐀-鿿]", route):
                self.assertIn(route, self.routes)

    def test_new_interface_text_has_english_translations(self) -> None:
        english = json.loads((PAGES / "locales/en.json").read_text(encoding="utf-8"))
        home = self.index[self.index.index('id="homeView"'):self.index.index('id="queryTools"')]
        texts = re.findall(r">([^<>]*[㐀-鿿][^<>]*)<", home)
        texts += re.findall(r'(?:placeholder|aria-label)="([^"]*[㐀-鿿][^"]*)"', home)
        self.assertTrue(texts)
        for text in texts:
            self.assertIn(text.strip(), english, text)

    def test_standalone_pages_share_navigation_and_mark_current_page(self) -> None:
        nav = site_nav("../", "trade")
        for label, href in (("图鉴首页", '"../"'), ("冰箱配餐", '"../#pantry/"'),
                            ("补给计划", '"../recommendations/"'), ("交易规划", '"../trade/"')):
            self.assertIn(f"href={href}", nav)
            self.assertIn(label, nav)
        self.assertEqual(nav.count('aria-current="page"'), 1)
        self.assertIn('href="../trade/" aria-current="page"', nav)
        self.assertNotIn("aria-current", site_nav("../"))

    def test_pantry_route_and_global_search_ranking(self) -> None:
        node = shutil.which("node")
        if not node:
            self.skipTest("Node.js is required to exercise the production navigation helpers")
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
vm.runInNewContext(source.replace(/  load\(\);\s*\}\)\(\);\s*$/, '  globalThis.api = {state, currentRoute, urlFor, matchRank};\n})();'), sandbox);
const {state, currentRoute, urlFor, matchRank} = sandbox.api;
state.category = 'dish';
get('cookingMode').value = 'recipes';
assert.equal(currentRoute(), 'dish');
get('cookingMode').value = 'pantry';
assert.equal(currentRoute(), 'pantry');
assert.equal(urlFor(currentRoute(), 'Config_CookingRecipe:1'), '#pantry/Config_CookingRecipe%3A1');
state.category = 'food';
assert.equal(currentRoute(), 'food'); // Pantry mode only applies to dishes.
state.home = true;
assert.equal(currentRoute(), 'home');
const entry = (id, name) => ({id, name});
assert.equal(matchRank(entry(2527, '土豆'), '土豆'), 0);
assert.equal(matchRank(entry(2527, '薯片'), '2527'), 0);
assert.equal(matchRank(entry(1, '土豆炖牛腩'), '土豆'), 1);
assert.equal(matchRank(entry(1, '香煎土豆'), '土豆'), 2);
assert.equal(matchRank(entry(1, '杂烩'), '土豆'), 3); // Matched through tags or notes only.
"""
        result = subprocess.run([node, "-e", script, str(PAGES / "app.js")], capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)


if __name__ == "__main__":
    unittest.main()
