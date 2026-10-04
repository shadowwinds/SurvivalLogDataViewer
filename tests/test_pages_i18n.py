from __future__ import annotations

import shutil
import struct
import subprocess
import unittest
from pathlib import Path

from codex_pages_i18n import read_localization


class LocalizationTests(unittest.TestCase):
    def test_memorypack_dictionary_requires_unique_keys_and_eof(self) -> None:
        def string(value: str) -> bytes:
            encoded = value.encode("utf-16-le")
            return struct.pack("<i", len(encoded) // 2) + encoded

        row = string("Item_ItemName_1") + string("Mushroom")
        data = struct.pack("<i", 1) + row
        self.assertEqual(read_localization(data, "English"), {"Item_ItemName_1": "Mushroom"})
        for invalid in (data[:-1], data + b"x", struct.pack("<i", 2) + row + row, struct.pack("<i", -1)):
            with self.assertRaises(ValueError):
                read_localization(invalid, "English")

    def test_language_preferences_templates_and_disabled_storage(self) -> None:
        node = shutil.which("node")
        if not node:
            self.skipTest("Node.js is required for browser localization checks")
        script = r"""
const fs = require('node:fs'), vm = require('node:vm'), assert = require('node:assert/strict');
const root = process.argv[1], source = fs.readFileSync(root + '/pages/i18n.js', 'utf8');
async function setup(query, saved, browser, disabled = false, failed = false) {
  const location = {href: 'https://example.org/project/?stage=2' + query + '#dish/recipe'};
  let persisted, events = [];
  const textNode = {nodeValue: '高档食材', parentElement: {closest: () => false, getAttribute: () => null}};
  const sandbox = {URL, Object, Map, WeakMap, RegExp, Event, NodeFilter: {SHOW_TEXT: 4}, location,
    navigator: {languages: [browser]}, localStorage: {getItem() {if (disabled) throw Error(); return saved;},
      setItem(k, v) {if (disabled) throw Error(); persisted = v;}},
    history: {replaceState(a, b, url) {location.href = String(url);}},
    fetch: async url => ({ok: !failed, status: 404, json: async () => JSON.parse(fs.readFileSync(root + '/pages/locales/' + url.pathname.split('/').pop(), 'utf8'))}),
    document: {currentScript: {src: 'https://example.org/project/i18n.js'}, documentElement: {},
      createTreeWalker() {let visited = false; return {currentNode: textNode, nextNode() {if (visited) return false; visited = true; return true;}};},
      querySelector: () => null, querySelectorAll: () => []}};
  sandbox.window = {dispatchEvent: e => events.push(e.type)};
  vm.runInNewContext(source, sandbox);
  await sandbox.window.I18n.ready;
  return {i18n: sandbox.window.I18n, location, textNode, get persisted() {return persisted;}, events};
}
(async () => {
  const state = await setup('&lang=en', 'zh-CN', 'zh-TW');
  assert.equal(state.i18n.language, 'en');
  assert.equal(state.i18n.locale, 'en-US');
  assert.equal(state.textNode.nodeValue, 'High tier');
  assert.equal(state.i18n.text('已选 2 份 · 继续添加'), '2 uses selected · Add more');
  assert.equal(state.i18n.text('任意菌菇'), 'Any Mushrooms');
  assert.equal(state.i18n.text('按冰箱食材配餐'), 'Plan from fridge ingredients');
  assert.equal(state.i18n.text('已登记 12 种 · 添加食材'), '12 ingredients recorded · Add more');
  assert.equal(state.i18n.text('这组材料最多可做 3 锅'), 'Maximum pots with these ingredients: 3');
  assert.equal(state.i18n.text('花椰菜 · 高档 · 配置基价 30；高档 ≥ 30，中档 ≥ 16'), 'Cauliflower · High tier · Base price 30; high ≥ 30, mid ≥ 16');
  assert.equal(state.i18n.text('配置基价 30；高档 ≥ 30，中档 ≥ 16'), 'Base price 30; high ≥ 30, mid ≥ 16');
  assert.equal(state.i18n.text('分份标准：30 饱腹 / 次。次数 = 整份总饱腹 ÷ 30，向上取整，至少 1 次。'),
    'Serving threshold: 30 satiety per use. Uses = total satiety ÷ 30, rounded up, with a minimum of 1.');
  assert.equal(state.i18n.text('ID:1234'), 'ID:1234');
  assert.equal(state.i18n.text('容器容量 2 · 有效光照 1.5 · 有效寒冷 0'),
    'Planter capacity 2 · Effective light 1.5 · Effective cold 0');
  assert.equal(state.i18n.text('图片：松茸（收获物）'), 'Image: Matsutake (harvest)');
  assert.equal(state.i18n.text('种植：松茸'), 'Grow: Matsutake');
  assert.equal(state.i18n.text('当前容器需种满：2 份种子'), 'Seeds to fill this planter: 2');
  assert.equal(state.i18n.text('当前条件：光照不足 · 寒冷过高'), 'Current conditions: Not enough light · Too cold');
  assert.equal(state.i18n.text('天气光照 1 × 区域系数 0.5 + 容器补光 0 = 0.5；天气寒冷 3 − 区域保温 1 − 设备供暖 2 − 容器加热 0 → 0'),
    'Weather light 1 × Area multiplier 0.5 + Planter light 0 = 0.5; Weather cold 3 − Area insulation 1 − Heating 2 − Planter heat 0 → 0');
  assert.equal(state.i18n.text('3 个可计分候选 · 0 个暂不计分候选 · 搜索“matsutake”'),
    '3 rated candidates · 0 unrated candidates · Search: “matsutake”');
  assert.equal(state.i18n.text('中期 · 烹饪 Lv.2 · 完美品质情景。中后期包含此前等级配方；指数只在同类、同阶段候选中比较。'),
    'Mid game · Cooking Lv.2 · Perfect quality scenario. Later stages include earlier recipes. Scores compare the same type and stage.');
  state.i18n.setLanguage('zh-CN');
  assert.equal(state.textNode.nodeValue, '高档食材');
  assert.equal(state.persisted, 'zh-CN');
  assert.equal(new URL(state.location.href).searchParams.get('stage'), '2');
  assert.equal(new URL(state.location.href).hash, '#dish/recipe');
  assert.equal(state.events[0], 'languagechange');
  state.i18n.setLanguage('en');
  assert.equal(state.textNode.nodeValue, 'High tier');
  assert.equal((await setup('', 'en', 'zh-CN')).i18n.language, 'en');
  assert.equal((await setup('', '', 'zh-TW')).i18n.language, 'zh-CN');
  assert.equal((await setup('&lang=fr', '', 'fr-FR')).i18n.language, 'zh-CN');
  const noStorage = await setup('', '', 'en-US', true);
  noStorage.i18n.setLanguage('zh-CN');
  assert.equal(noStorage.i18n.language, 'zh-CN');
  const offline = await setup('&lang=en', '', 'en-US', false, true);
  assert.equal(offline.i18n.language, 'zh-CN');
  assert.equal(offline.textNode.nodeValue, '高档食材');
})().catch(error => {console.error(error); process.exitCode = 1;});
"""
        result = subprocess.run([node, "-e", script, str(Path(__file__).resolve().parents[1])], capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)


if __name__ == "__main__":
    unittest.main()
