from __future__ import annotations

import json
import shutil
import struct
import subprocess
import unittest
from pathlib import Path

from codex_parser import parse_config_table


ROOT = Path(__file__).resolve().parents[1]


class PlantingEnvironmentTests(unittest.TestCase):
    def test_new_environment_tables_reject_changed_members_truncation_and_trailing_bytes(self) -> None:
        # Exact native EnvAreaWeather row: ID, AreaID, WeatherID, LightMul, TempAdd.
        data = struct.pack("<iBiiifi", 1, 5, 1, 1, 0, 0.5, 1)
        rows = parse_config_table(data, "Config_EnvAreaWeather")
        self.assertEqual(rows[0].values["LightMul"], 0.5)
        for invalid in (data[:-1], data + b"x", data[:4] + b"\x04" + data[5:]):
            with self.assertRaises(ValueError):
                parse_config_table(invalid, "Config_EnvAreaWeather")

    def test_screenshot_conditions_all_weather_scenarios_and_player_sorting(self) -> None:
        node = shutil.which("node")
        if not node:
            self.skipTest("Node.js is required for planting calculations")
        script = r"""
const fs = require('node:fs'), vm = require('node:vm'), assert = require('node:assert/strict');
const root = process.argv[1], sandbox = {window: {}};
vm.runInNewContext(fs.readFileSync(root + '/pages/planting.js', 'utf8'), sandbox);
const {conditions, problems, compare} = sandbox.window.Planting;
const env = JSON.parse(fs.readFileSync(root + '/pages/planting-environment.json', 'utf8'));
const pot = {capacity: 1, light_bonus: 0, heat_bonus: 0, needs_power: false};
const choice = {weather: 'cloudy', cold_wave: 3, location: 'first', ac: true, stove: false, power: 'on'};
const grass = {id: 6, plant: {size: 1, light_need: 0, cold_resistance: 0, growth_seconds: 259200, food_harvest: true}};
const screen = conditions(env, choice, pot);
assert.equal(screen.scenario.name, '重度寒潮');
assert.equal(screen.light, 0.5); assert.equal(screen.cold, 0); assert.equal(screen.deviceHeat, 2);
assert.equal(problems(grass, screen).length, 0);
choice.location = 'basement'; choice.ac = false;
assert.equal(conditions(env, choice, pot).cold, 1);
assert.deepEqual(Array.from(problems(grass, conditions(env, choice, pot))), ['寒冷过高']);
choice.stove = true;
assert.equal(conditions(env, choice, pot).cold, 0);
choice.location = 'terrace'; choice.ac = true;
assert.equal(conditions(env, choice, pot).deviceHeat, 0);
assert.equal(conditions(env, choice, pot).cold, 3);
assert.equal(conditions(env, choice, pot).light, 1);
for (const scenario of env.scenarios) {
  const current = conditions(env, {...choice, weather: scenario.weather, cold_wave: scenario.cold_wave,
    location: 'second', ac: false, stove: false}, pot);
  assert.equal(current.light, scenario.light);
  assert.equal(current.cold, Math.max(0, scenario.cold - 1));
  assert.equal(current.valid, true);
}
assert.equal(env.scenarios.find(row => row.weather === 'rainy' && row.cold_wave === 3).light, 0);
const electric = {...pot, light_bonus: 0, heat_bonus: 1, needs_power: true, electric_light: 2, electric_heat: 0};
choice.location = 'basement'; choice.ac = false; choice.stove = false;
const tomato = {id: 17, plant: {size: 1, light_need: 2, cold_resistance: 0}};
assert.equal(problems(tomato, conditions(env, choice, electric)).length, 0);
assert.deepEqual(Array.from(problems(tomato, conditions(env, {...choice, power: 'off'}, electric))), ['光照不足']);
assert.equal(conditions(env, choice, pot, {light: null, cold: null}).light, null);
assert.equal(conditions(env, choice, pot, {light: 0, cold: -5}).cold, 0);
assert.equal(conditions(env, choice, pot, {light: NaN, cold: 0}).valid, false);
assert.equal(conditions(env, {...choice, weather: 'unknown'}, pot).valid, false);
const current = conditions(env, {...choice, weather: 'sunny', cold_wave: 0, location: 'second'}, null);
const fastFlower = {id: 35, plant: {size: 1, light_need: 2, cold_resistance: 1, growth_seconds: 240000, food_harvest: false}};
const slowerFood = {id: 7, plant: {...grass.plant, cold_resistance: 2, growth_seconds: 292500}};
const unknown = {id: 99, plant: {size: 1, light_need: 0, cold_resistance: 1}};
const ranked = sort => [fastFlower, slowerFood, grass, unknown].sort((a,b) => compare(a,b,sort,current)).map(row => row.id);
assert.deepEqual(ranked('plant-food'), [6,7,35,99]);
assert.deepEqual(ranked('plant-growth'), [35,6,7,99]);
assert.deepEqual(ranked('plant-cold'), [7,35,99,6]);
const coldBasement = conditions(env, choice, pot);
assert.deepEqual([grass,slowerFood].sort((a,b)=>compare(a,b,'plant-growth',coldBasement)).map(row=>row.id),[7,6]);
// The production filtering path also combines environment, search and the show-all switch.
const controls = new Map();
const get = id => {if(!controls.has(id)) controls.set(id,{value:'',hidden:true,checked:false,addEventListener(){}});return controls.get(id);};
Object.assign(sandbox,{document:{getElementById:get,addEventListener(){}},matchMedia:()=>({matches:false,addEventListener(){}}),setTimeout,clearTimeout});
sandbox.window.addEventListener=()=>{};
const app=fs.readFileSync(root+'/pages/app.js','utf8');
vm.runInNewContext(app.replace(/  load\(\);\s*\}\)\(\);\s*$/,'  globalThis.api={state,filteredEntries};\n})();'),sandbox);
const {state,filteredEntries}=sandbox.api;
state.category='plant';state.plantingEnvironment=env;state.planters=[{id:60000,...pot}];
state.categories=[{id:'plant',entries:[{...grass,nameIndex:'grass',materialIndex:''},{...slowerFood,nameIndex:'oyster',materialIndex:''}]}];
for(const [key,val] of Object.entries({plantWeather:'cloudy',plantColdWave:'3',plantLocation:'basement',plantHeating:'none',planterSelect:'60000',planterPower:'on',sortSelect:'plant-food'})) get(key).value=val;
get('plantOnlySuitable').checked=true;
assert.deepEqual(Array.from(filteredEntries(),row=>row.id),[7]);
get('plantOnlySuitable').checked=false;
assert.deepEqual(Array.from(filteredEntries(),row=>row.id),[7,6]);
get('nameSearch').value='grass';
assert.deepEqual(Array.from(filteredEntries(),row=>row.id),[6]);
get('plantOnlySuitable').checked=true;
assert.deepEqual(Array.from(filteredEntries(),row=>row.id),[]);
get('plantLocation').value='first';get('plantHeating').value='ac';
assert.deepEqual(Array.from(filteredEntries(),row=>row.id),[6]);
"""
        result = subprocess.run([node, "-e", script, str(ROOT)], capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)


if __name__ == "__main__":
    unittest.main()
