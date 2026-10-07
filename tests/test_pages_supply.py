from __future__ import annotations

import json
import shutil
import struct
import subprocess
import unittest
from pathlib import Path
from unittest.mock import patch

from codex_pages import export_data
from codex_pages_seo import trade_document
from codex_pages_supply import extract_supply_model
from codex_pages_trade import extract_trade_model
from codex_parser import CONFIG_SCHEMAS, ConfigRow, parse_config_table


ROOT = Path(__file__).resolve().parents[1]


class SupplyModelTests(unittest.TestCase):
    def run_model(self, assertions: str, data: dict | None = None) -> None:
        node = shutil.which("node")
        if not node:
            self.skipTest("Node.js is required to verify the production model")
        source = r"""
const fs = require('node:fs'), vm = require('node:vm'), assert = require('node:assert/strict');
const sandbox = {window: {}};
for (const file of ['cooking.js', 'supply.js', 'trade.js']) vm.runInNewContext(fs.readFileSync(process.argv[1] + '/pages/' + file, 'utf8'), sandbox);
const S = sandbox.window.Supply, data = JSON.parse(fs.readFileSync(0, 'utf8'));
const close = (a,b) => assert.ok(Math.abs(a-b) < 1e-6, `${a} != ${b}`);
""" + assertions
        result = subprocess.run([node, "-e", source, str(ROOT)], input=json.dumps(data or {}),
                                capture_output=True, text=True, encoding="utf-8")
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

    def test_trade_tables_read_all_fields_and_reject_unknown_layout_or_trailing_bytes(self) -> None:
        for table in ("Config_MapPoint", "Config_Shop"):
            fields = CONFIG_SCHEMAS[table]
            encoded = struct.pack("<iB", 1, len(fields))
            for name, kind in fields:
                if kind == "str":
                    encoded += struct.pack("<i", 0)
                elif kind == "bool":
                    encoded += b"\x01"
                elif kind == "list_i32":
                    encoded += struct.pack("<3i", 2, 911, 9)
                elif kind == "f32":
                    encoded += struct.pack("<f", .5)
                else:
                    encoded += struct.pack("<i", 1100 if name == "ID" else 9)
            rows = parse_config_table(encoded, table)
            self.assertEqual(len(rows), 1)
            if table == "Config_Shop":
                self.assertEqual(rows[0].values["RandomID"], [911, 9])
            else:
                self.assertEqual(rows[0].values["TradeCategory"], 9)
            for invalid in (encoded + b"x", encoded[:4] + b"\x00" + encoded[5:], encoded[:-1]):
                with self.assertRaises((ValueError, struct.error)):
                    parse_config_table(invalid, table)

    def test_trade_export_skill_gate_public_fields_and_html_embedding(self) -> None:
        def row(table: str, **values: object) -> ConfigRow:
            defaults = {name: [] if kind == "list_i32" else "" if kind == "str" else 0
                        for name, kind in CONFIG_SCHEMAS[table]}
            return ConfigRow(table, {**defaults, **values, "PRIVATE": "private-marker"})

        tables = {
            "Config_Item": [row("Config_Item", ID=i, ItemName_Local=f"item-{i}", Category=9,
                                TradeValue=i * 10, UseTimes=2 if i == 3 else 0) for i in (1, 2, 3)],
            "Config_ConstantText": [],
            "Config_MapPoint": [row("Config_MapPoint", ID=1100, PointCategory=3, ShelfShopId=911,
                                    TradeCategory=9, Name_Local="outpost</script>")],
            "Config_Shop": [row("Config_Shop", ID=911, ItemIdList=[2], ItemCountList=[4])],
            "Config_ProductionList": [row("Config_ProductionList", ID=i, InCodex=True, IsUseable=True,
                                          Level=5, craft_level=1, MaterialList=[i], ProductID=[2]) for i in (1, 3)],
            "Config_CookingRecipe": [],
        }
        settings = {"StrangerTradeBoostLv1": (0, .3, None), "StrangerTradeBoostLv2": (0, .6, None),
                    "StrangerTradeBoostLv3": (0, .9, None), "StrangerTradeDemandBoostMax": (0, -1, None),
                    "StrangerTradeDealLineDiscount": (0, 0, None), "StrangerTradeDealLineMaxDiscount": (0, 60, None),
                    "Endless_TradeTakeMedicineRate": (0, 2, None)}
        with patch("codex_pages_trade.load_config_table", side_effect=lambda _, table: (tables[table], None, "test", None)), \
                patch("codex_pages_trade.read_global_settings", return_value=settings):
            model = extract_trade_model(Path("unused"))
        self.assertEqual(model["rules"]["self_stock_rate"], .5)
        self.assertEqual([(r["id"], r["level"]) for r in model["crafts"]], [(1, 1)])
        self.assertNotIn("private-marker", json.dumps(model))
        html = trade_document(model, "../", "test")
        self.assertIn('id="trade-planner"', html)
        embedded = html.split('<script id="trade-data" type="application/json">', 1)[1].split('</script>', 1)[0]
        self.assertNotIn("</script>", embedded)
        self.assertEqual(json.loads(embedded)["points"][0]["name"], "outpost</script>")

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
 close(row.outputTrade,product.trade_value*product.trade_uses);
 close(row.inputTrade,row.output.ingredients.reduce((s,i)=>s+data.resources.find(r=>r.id===i.id).trade_value,0));
 close(row.tradeMargin,row.outputTrade-row.inputTrade);
}
for (const row of rated(late)) {
 const entry=data.cooking.entries.find(e=>e.id===row.id);
 const forecast=sandbox.window.Cooking.forecast(entry,row.output.ingredients,'普通',data.cooking.model);
 assert.deepEqual(Array.from(row.output.total),Array.from(forecast.total));
}
""", data)

    def test_trade_channels_partial_packages_rejection_discount_and_medicine(self) -> None:
        self.run_model(r"""
const T=sandbox.window.Trade, rules={self_stock_rate:.5,demand_boost_max:-1,deal_discount:0,deal_discount_max:60,camp_medicine_rate:2};
const iron={id:1,cat:9,trade_value:10,use_times:0,sell_rate:1};
const rice={id:2,cat:1,trade_value:12,use_times:7,sell_rate:.6};
const medicine={id:3,cat:2,trade_value:11,use_times:2,sell_rate:1};
const point={id:10,half_value_cat:9,items:[{...iron,count:3},{...medicine,count:5}]};
const other={id:11,half_value_cat:10,items:[{...medicine,count:5}]};
const contact={id:'contact',contact:true,items:[]};
let o=T.options({appraisal:20,boost:.9,demand:[1,9]},rules);
close(T.given(iron,1,1,point,o,rules),0); // Reject only current visible stock.
o.absent['10:1']=true; close(T.given(iron,1,1,point,o,rules),6);
close(T.given(iron,1,1,other,o,rules),12); // No point demand bonus.
close(T.given(rice,2,.5,contact,o,rules),Math.fround(176.4)); // 7 uses/package; demand + appraisal, no TradeSellRate.
close(T.given(rice,1,1,other,T.options({},rules),rules),Math.fround(50.4));
const model={rules,items:[iron,rice,medicine],points:[point,other]};
const basket={1:{quantity:10,remaining:100}};
let r=T.comparison(model,basket,{destination:'all',target:3,targetCount:5,discount:999});
assert.equal(r[0].point.id,11); assert.equal(r[0].maximum,7); assert.equal(r[0].required,50);
r=T.comparison(model,basket,{destination:'all',excluded:[11],target:3,targetCount:1,camp:true});
assert.equal(r.length,1); assert.equal(r[0].unit,44);
assert.equal(T.takeValue(medicine,contact,T.options({camp:true},rules),rules),22);
assert.equal(T.comparison(model,basket,{destination:'all',excluded:[10,11]}).length,0);
assert.equal(T.options({boost:.9},{...rules,demand_boost_max:.5}).boost,.5);
""")

    def test_trade_processing_opportunity_cost_duplicate_materials_and_whole_pot(self) -> None:
        self.run_model(r"""
const T=sandbox.window.Trade, rules={self_stock_rate:.5,demand_boost_max:-1,deal_discount:0,deal_discount_max:60,camp_medicine_rate:2};
const a={id:1,cat:9,trade_value:10,use_times:0,sell_rate:1}, b={id:2,cat:1,trade_value:12,use_times:7,sell_rate:1};
const wire={id:3,cat:9,trade_value:36,use_times:0,sell_rate:1}, dish={id:4,cat:1,trade_value:40,use_times:1,sell_rate:1};
const ingredients=[{id:2,tier:3,sub_category_id:1,stats:[100,0,0,0,0],price:7,use_times:7}];
const entry={id:20,key:'r20',recipe:{specific_items:[2,2],tier:3},portion_model:{mode:'fixed',threshold:30},
products:[{id:4,quality:'普通',stats:[1,2,3,4,5].map((i,n)=>({field:'ValueDisplay'+i,value:n===0?120:0}))}]};
const model={rules,items:[a,b,wire,dish],points:[{id:10,name:'recycling',half_value_cat:9,items:[]},{id:11,name:'nursery',half_value_cat:10,items:[]}],
crafts:[{id:1,name:'wire',level:1,inputs:[1,1,1],outputs:[3],can_fail:true}],
cooking:{ingredients,entries:[entry],model:{split_threshold:30}},dishes:[{id:20,name:'dish',level:1,seconds:600}]};
const input={destination:'all',scope:'stock',kind:'',cookLevel:1,craftLevel:1,quality:'普通',sort:'gain'};
const basket={1:{quantity:10,remaining:100},2:{quantity:1,remaining:50}};
let rows=T.processing(model,basket,input), w=rows.find(r=>r.kind==='craft'), d=rows.find(r=>r.kind==='cook');
assert.equal(w.cost,30); assert.equal(w.value,36); assert.equal(w.gain,6); assert.equal(w.batches,3); assert.equal(w.total,18);
assert.equal(d.servings,4); assert.equal(d.value,40); assert.equal(d.cost,24); assert.equal(d.batches,1); // Servings cannot multiply full-pot trade value.
model.points[1].items=[{...dish,count:1}];
rows=T.processing(model,basket,{...input,destination:'11'}); assert.equal(rows.some(r=>r.kind==='cook'),false);
model.points[1].items=[{...b,count:1}];
d=T.processing(model,basket,{...input,destination:'11'}).find(r=>r.kind==='cook'); assert.equal(d.fallback,true); assert.equal(d.cost,24);
assert.equal(T.processing(model,{1:{quantity:2,remaining:100}},input).length,0);
assert.equal(T.processing(model,{}, {...input,scope:'all'}).find(r=>r.kind==='craft').batches,null);
""")

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
