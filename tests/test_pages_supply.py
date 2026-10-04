from __future__ import annotations

import json
import shutil
import subprocess
import unittest
from pathlib import Path
from unittest.mock import patch

from codex_pages import export_data
from codex_pages_supply import extract_supply_model
from codex_parser import ConfigRow, parse_config_table


ROOT = Path(__file__).resolve().parents[1]


class SupplyModelTests(unittest.TestCase):
    def run_model(self, assertions: str, data: dict | None = None) -> None:
        node = shutil.which("node")
        if not node:
            self.skipTest("Node.js is required to verify the production model")
        source = r"""
const fs = require('node:fs'), vm = require('node:vm'), assert = require('node:assert/strict');
const sandbox = {window: {}};
for (const file of ['cooking.js', 'supply.js']) vm.runInNewContext(fs.readFileSync(process.argv[1] + '/pages/' + file, 'utf8'), sandbox);
const S = sandbox.window.Supply, data = JSON.parse(fs.readFileSync(0, 'utf8'));
const close = (a,b) => assert.ok(Math.abs(a-b) < 1e-6, `${a} != ${b}`);
""" + assertions
        result = subprocess.run([node, "-e", source, str(ROOT)], input=json.dumps(data or {}),
                                capture_output=True, text=True, encoding="utf-8")
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

    def test_container_cycles_power_controls_and_short_cycle_work(self) -> None:
        self.run_model(r"""
const model = {anomaly_interval_seconds:86400, special_plants:[39], actions:{sow:{seconds:900},harvest:{seconds:300},pest:{seconds:300},weed:{seconds:300},water:{seconds:300}}};
const row = {id:1, seconds:172800, size:1, care:{pest:.5,weed:.5,water:.2}, seeds:[{price:10,trade_value:20}], harvest:[{id:7,amount:2,uses:1,cookable:true,can_use:true,stats:[5,0,0,0,0]}]};
const cfg = {supply_model:model, planters:[{id:60002,capacity:4,needs_power:false},{id:9,capacity:4,needs_power:true,growth_bonus:1,pest_control:-1,weed_control:-1,water_control:-1}],plant_levels:[{level:1,anomaly_reduction:0}]};
const normal = S.cropModel(row,cfg,S.defaults);
assert.equal(normal.batch,4); close(normal.days,2); close(normal.cycleMinutes,30); close(normal.dailyMinutes,15); close(normal.dailyUses,4);
close(normal.probabilities.pest,5/12); close(normal.probabilities.water,1/6);
const fast = S.cropModel(row,cfg,{...S.defaults,growth:300});
close(fast.days,.5); close(fast.dailyMinutes,40); // More sowing/harvesting despite fewer anomaly checks.
const powered = S.cropModel(row,cfg,{...S.defaults,planter:9});
close(powered.days,1); close(powered.careMinutes,0);
const off = S.cropModel(row,cfg,{...S.defaults,planter:9,powered:false}); close(off.days,2); close(off.careMinutes,10);
assert.ok(S.cropModel({...row,size:5},cfg,S.defaults).reason);
assert.ok(S.cropModel({...row,id:39},cfg,S.defaults).reason);
""")

    def test_morale_settlement_caps_ties_and_trade_units(self) -> None:
        self.run_model(r"""
const model = {morale_base:50,morale_per_point:5};
assert.equal(S.points(49,model),0); assert.equal(S.points(59.99,model),1); assert.equal(S.points(60,model),2);
assert.equal(S.points(62,model,3),4); assert.equal(S.points(60,null),null);
assert.equal(S.givenValue(12,0,'discount'),12); assert.equal(S.givenValue(12,.5,'discount'),6); assert.equal(S.givenValue(12,2,'discount'),12);
const options = S.resourceOptions({id:1,price:35,uses:7,trade_value:13},[],S.defaults,S.weights(S.defaults));
assert.equal(options.purchase,13);
assert.equal(S.resourceOptions({id:1,price:35,uses:7,trade_value:13},[],{...S.defaults,currency:'price'},S.weights(S.defaults)).purchase,5);
assert.equal(S.resourceOptions({id:1,price:0,uses:1,trade_value:0},[],S.defaults,S.weights(S.defaults)).selected,null);
const rows = [{value:1},{value:1},{value:2},{value:null}]; S.rank(rows); assert.equal(rows[0].score,rows[1].score); assert.equal(rows[2].score,100); assert.equal(rows[3].score,null);
""")

    def test_current_recipes_stage_quality_morale_cap_and_trade_use_actual_combinations(self) -> None:
        data = export_data(ROOT / "survival_log_codex.sqlite3")["recommendations"]
        self.run_model(r"""
const early = S.evaluate(data), late = S.evaluate(data,{stage:3}), capped = S.evaluate(data,{stage:3,moraleNow:100});
const rated = r => r.dishes.filter(d => d.score !== null).sort((a,b)=>b.score-a.score || a.id-b.id);
assert.ok(rated(early).every(d=>d.level<=1)); assert.ok(rated(late).some(d=>d.level===3));
assert.notEqual(rated(early)[0].id,rated(late)[0].id);
assert.ok(rated(late).every(d=>d.daily.extraPoints>=0 && d.daily.extraPoints<=10));
assert.ok(rated(capped).every(d=>d.daily.extraPoints<=0));
assert.ok(rated(capped).filter(d=>d.output.total[1]>=0).every(d=>d.daily.extraPoints===0));
assert.ok(rated(capped).every(d=>d.daily.moraleGain<=0 && !d.daily.moraleCovered));
assert.equal(rated(capped)[0].id,rated(late)[0].id); // A full mood meter does not erase long-term food value.
const settlement=S.evaluate(data,{stage:3,moraleNow:100,moraleMode:'settlement'});
assert.notEqual(rated(settlement)[0].id,rated(late)[0].id);
assert.equal(late.crops.find(c=>c.id===39).score,null);
assert.ok(late.ingredients.find(i=>i.id===30000).morale100>0);
const perfect = S.evaluate(data,{stage:3,quality:'完美'}), trade = S.evaluate(data,{stage:3,focus:'trade'});
const before = late.dishes.find(d=>d.id===6023), after = perfect.dishes.find(d=>d.id===6023);
assert.ok(after.output.total[1]>before.output.total[1]);
for (const row of rated(trade)) {
 const product = data.dishes.find(d=>d.id===row.id).qualities['普通'];
 close(row.outputTrade,product.trade_value*row.output.servings);
 close(row.inputTrade,row.output.ingredients.reduce((s,i)=>s+data.resources.find(r=>r.id===i.id).trade_value,0));
 close(row.tradeMargin,row.outputTrade-row.inputTrade);
}
for (const row of rated(late)) {
 const entry=data.cooking.entries.find(e=>e.id===row.id);
 const forecast=sandbox.window.Cooking.forecast(entry,row.output.ingredients,'普通',data.cooking.model);
 assert.deepEqual(Array.from(row.output.total),Array.from(forecast.total));
}
""", data)

    def test_growing_budget_rounds_containers_and_costs(self) -> None:
        data = export_data(ROOT / "survival_log_codex.sqlite3")["recommendations"]
        self.run_model(r"""
const result=S.evaluate(data,{stage:3,source:'grow',currency:'price'});
const dish=result.dishes.find(d=>d.output && d.daily.needs.some(n=>n.selected.type==='grow'));
assert.ok(dish);
const crops=new Map(); let expectedCash=0;
for (const need of dish.daily.needs) {
 if (need.selected.type==='buy') expectedCash+=need.usage*need.selected.cash;
 else if (!crops.has(need.selected.crop.id) || crops.get(need.selected.crop.id).containers<need.containers) crops.set(need.selected.crop.id,need);
}
let expectedCapacity=0,expectedCare=0;
for (const need of crops.values()) {
 assert.ok(Number.isInteger(need.containers));
 expectedCapacity+=need.containers*need.selected.crop.capacity;
 expectedCare+=need.containers*need.selected.crop.dailyMinutes;
 expectedCash+=need.containers*need.selected.crop.seedCost/need.selected.crop.days;
}
close(dish.daily.capacity,expectedCapacity); close(dish.daily.care,expectedCare); close(dish.daily.cash,expectedCash);
""", data)

    def test_action_model_exports_only_parameters_and_rejects_invalid_duration(self) -> None:
        rows = [ConfigRow("Config_Action", {"ID": i, "During": duration, "PRIVATE": "ignore"})
                for i, duration in ((1611, 900), (1617, 300), (1613, 300), (1614, 300), (1615, 300))]
        settings = {"MoraleBase": (50, 0, None), "MoraleToPoint": (5, 0, None),
                    "Greenhouse_DailyFertPlants": (0, 0, "39:4.0"), "Greenhouse_RegrowPlants": (0, 0, "39:345600")}
        with patch("codex_pages_supply.load_config_table", return_value=(rows, None, "test", None)), \
                patch("codex_pages_supply.read_global_settings", return_value=settings):
            model = extract_supply_model(Path("unused"))
            self.assertEqual(model["special_plants"], [39])
            self.assertEqual(model["actions"]["sow"]["seconds"], 900)
            self.assertNotIn("PRIVATE", json.dumps(model))
            rows[0].values["During"] = float("nan")
            with self.assertRaisesRegex(ValueError, "1611"):
                extract_supply_model(Path("unused"))

    def test_action_schema_reports_changed_field_count(self) -> None:
        with self.assertRaisesRegex(ValueError, "Config_Action"):
            parse_config_table(b"\x01\x00\x00\x00\x13", "Config_Action")


if __name__ == "__main__":
    unittest.main()
