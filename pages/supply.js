(() => {
  "use strict";
  const defaults = {stage: 1, quality: "普通", focus: "auto", source: "mixed", currency: "trade",
    planter: 60002, powered: true, plantLevel: 1, growth: 0, action: 100, harvest: "normal",
    satiety: 100, morale: 20, cash: 100, care: 60, capacity: 8, horizon: 7,
    cookActive: 0, moraleNow: 50, moraleMax: 100, moraleMode: "supply", pointStep: 5, sellChannel: "normal"};
  const profiles = {
    1: {satiety: .7, morale: .1, other: .2, economy: .45, labor: .25, space: .2, wait: .1},
    2: {satiety: .45, morale: .4, other: .15, economy: .35, labor: .3, space: .25, wait: .1},
    3: {satiety: .2, morale: .7, other: .1, economy: .2, labor: .4, space: .3, wait: .1},
  };
  const positive = value => Number.isFinite(value) && value > 0;
  const unit = (item, currency) => currency === "trade" ? positive(item.trade_value) ? item.trade_value : null :
    positive(item.price) && positive(item.uses) ? item.price / item.uses : null;
  const seedCost = (item, currency) => currency === "trade" ? positive(item.trade_value) ? item.trade_value : null :
    positive(item.price) ? item.price : null;
  const givenValue = (value, rate, channel) => positive(value) ? value *
    (channel === "discount" && positive(rate) ? Math.min(1, rate) : 1) : null;
  function weights(options) {
    const w = {...profiles[options.stage]};
    if (options.focus === "satiety") Object.assign(w, {satiety: 1, morale: 0, other: 0});
    if (options.focus === "morale") Object.assign(w, {satiety: .1, morale: .9, other: 0});
    if (options.focus === "ease") Object.assign(w, {economy: .15, labor: .6, space: .2, wait: .05});
    return w;
  }
  function benefit(total, options, w) {
    return w.satiety * Math.max(0, total[0]) / options.satiety +
      w.morale * Math.max(0, total[1]) / options.morale +
      w.other * Math.max(0, total[2] * .5 + total[3] + total[4] * .5) / options.satiety;
  }
  function points(morale, model, step = model?.morale_per_point) {
    return model && positive(step) ? Math.max(0, Math.floor((Math.trunc(morale) - model.morale_base) / step)) : null;
  }
  function cropModel(row, data, options) {
    const model = data.supply_model;
    const planter = data.planters?.find(p => p.id === options.planter);
    const capacity = planter?.capacity || 1;
    const enabled = !planter?.needs_power || options.powered;
    const facility = enabled ? planter?.growth_bonus || 0 : 0;
    const level = data.plant_levels?.find(p => p.level === options.plantLevel);
    const growth = row.seconds / ((1 + facility) * (1 + (level?.growth_bonus || 0)) * (1 + options.growth / 100));
    const seeds = Math.floor(capacity / row.size);
    const harvest = options.harvest === "perfect" ? row.perfect_harvest : row.harvest;
    const result = {...row, batch: seeds, capacity, growth, days: growth / 86400, harvest,
      probabilities: {}, careMinutes: null, cycleMinutes: null, reason: ""};
    if (model?.special_plants?.includes(row.id)) {
      result.reason = "特殊温室施肥或再生作物，基础模型不适用";
      return result;
    }
    if (!positive(growth) || !positive(row.size) || !model || !seeds || !harvest?.length) {
      result.reason = !seeds ? "所选容器空间不足" : "种植时间、收获或照料参数不完整";
      return result;
    }
    let sum = 0;
    for (const type of ["pest", "weed", "water"]) {
      if (!Number.isFinite(row.care[type])) { result.reason = "照料概率不完整"; return result; }
      const control = enabled ? planter?.[type + "_control"] || 0 : 0;
      const probability = Math.max(0, row.care[type] + control) * Math.max(0, 1 - (level?.anomaly_reduction || 0));
      result.probabilities[type] = probability; sum += probability;
    }
    if (sum > 1) for (const type of Object.keys(result.probabilities)) result.probabilities[type] /= sum;
    // One check per growing day and container, with prompt treatment. Delays and stalls are not simulated.
    const checks = Math.floor(growth / model.anomaly_interval_seconds);
    result.checks = checks;
    result.careMinutes = Object.entries(result.probabilities).reduce((minutes, [type, probability]) =>
      minutes + checks * probability * model.actions[type].seconds / 60 * options.action / 100, 0);
    result.cycleMinutes = result.careMinutes + (model.actions.sow.seconds + model.actions.harvest.seconds) / 60 * options.action / 100;
    const prices = row.seeds.map(seed => seedCost(seed, options.currency)).filter(positive);
    result.seedCost = prices.length ? Math.min(...prices) * seeds : null;
    result.dailyMinutes = result.cycleMinutes / result.days;
    result.dailyUses = harvest.reduce((n, item) => n + (item.cookable && positive(item.uses) ? item.uses * item.amount * seeds : 0), 0) / result.days;
    result.dailyRawSatiety = harvest.reduce((n, item) => n + (item.can_use && positive(item.uses) && Number.isFinite(item.stats[0]) ? item.stats[0] * item.uses * item.amount * seeds : 0), 0) / result.days;
    result.reason = row.reason || "";
    return result;
  }
  function resourceOptions(item, crops, options, w) {
    const purchase = unit(item, options.currency), choices = [];
    if (purchase !== null) choices.push({type: "buy", cash: purchase, minutes: 0, spaceDays: 0, lead: 0});
    if (options.source !== "buy") {
      for (const crop of crops) {
        const harvest = crop.harvest?.find(h => h.id === item.id);
        if (crop.reason || !harvest || !positive(harvest.uses) || crop.seedCost === null) continue;
        const count = harvest.uses * harvest.amount * crop.batch;
        choices.push({type: "grow", crop, cash: crop.seedCost / count, minutes: crop.cycleMinutes / count,
          spaceDays: crop.capacity * crop.days / count, lead: crop.days, count});
      }
    }
    const burden = choice => w.economy * choice.cash / options.cash + w.labor * choice.minutes / options.care +
      w.space * choice.spaceDays / options.capacity + w.wait * choice.lead / options.horizon;
    const eligible = choices.filter(choice => options.source !== "grow" || choice.type === "grow" || !choices.some(c => c.type === "grow"));
    eligible.sort((a, b) => burden(a) - burden(b) || a.cash - b.cash || a.lead - b.lead || (a.crop?.id || 0) - (b.crop?.id || 0));
    return {item, purchase, choices, selected: eligible[0] || null};
  }
  function requirements(ingredients, resources) {
    const counts = new Map();
    for (const ingredient of ingredients) counts.set(ingredient.id, (counts.get(ingredient.id) || 0) + 1);
    return [...counts].map(([id, amount]) => ({...resources.get(id), amount}));
  }
  function routeTotals(ingredients, routes) {
    let cash = 0, minutes = 0, spaceDays = 0, lead = 0;
    const batches = new Map();
    const counts = new Map();
    for (const ingredient of ingredients) {
      counts.set(ingredient.id, (counts.get(ingredient.id) || 0) + 1);
    }
    for (const [id, amount] of counts) {
      const route = routes.get(id)?.selected;
      if (!route) return null;
      lead = Math.max(lead, route.lead);
      if (route.type === "grow") {
        const previous = batches.get(route.crop.id);
        const share = amount / route.count;
        if (!previous || previous.share < share) batches.set(route.crop.id, {crop: route.crop, share});
      } else cash += route.cash * amount;
    }
    for (const {crop, share} of batches.values()) {
      cash += crop.seedCost * share; minutes += crop.cycleMinutes * share; spaceDays += crop.capacity * crop.days * share;
    }
    return {cash, minutes, spaceDays, lead};
  }
  function rawPenalty(total) {
    return Math.min(30, 100 * total.slice(1).reduce((s, value, i) => s + Math.max(0, -value) * [2, 1, 3, 2][i], 0) / Math.max(1, total[0]));
  }
  function rank(rows) {
    const valid = rows.filter(row => Number.isFinite(row.value));
    const values = valid.map(row => row.value).sort((a, b) => a - b);
    for (const row of rows) {
      row.score = null;
      if (!Number.isFinite(row.value)) continue;
      const low = values.filter(v => v < row.value).length, equal = values.filter(v => v === row.value).length;
      row.score = Math.round(Math.max(0, (values.length < 2 ? 50 : 100 * (low + (equal - 1) / 2) / (values.length - 1)) - (row.penalty || 0)) * 10) / 10;
    }
    return rows;
  }
  function dailyPlan(row, options, model) {
    if (!row.output || !positive(row.output.perUse[0])) return null;
    const meals = Math.ceil(options.satiety / row.output.perUse[0]);
    const pots = meals / row.output.servings;
    const total = row.output.perUse.map(value => value * meals);
    const space = row.spaceDays * pots;
    const needs = row.requirements.map(requirement => {
      const usage = requirement.amount * pots, route = requirement.selected;
      const containers = route.type === "grow" ? Math.ceil(usage * route.spaceDays / route.crop.capacity) : 0;
      return {...requirement, usage, containers,
        allocatedCapacity: containers * (route.crop?.capacity || 0),
        allocatedMinutes: containers * (route.crop?.dailyMinutes || 0)};
    });
    const crops = new Map();
    for (const need of needs) if (need.selected.type === "grow") {
      const key = need.selected.crop.id, previous = crops.get(key);
      // Shared harvests come from one crop batch; do not duplicate its containers or care.
      if (!previous || previous.containers < need.containers) crops.set(key, need);
    }
    const capacity = [...crops.values()].reduce((sum, need) => sum + need.allocatedCapacity, 0);
    const care = [...crops.values()].reduce((sum, need) => sum + need.allocatedMinutes, 0);
    const purchase = needs.filter(n => n.selected.type === "buy").reduce((sum, n) => sum + n.usage * n.selected.cash, 0) +
      [...crops.values()].reduce((sum, n) => sum + n.containers * n.selected.crop.seedCost / n.selected.crop.days, 0);
    const before = Math.max(0, Math.min(options.moraleNow, options.moraleMax));
    const after = Math.max(0, Math.min(options.moraleMax, before + total[1]));
    const beforePoints = points(before, model, options.pointStep), afterPoints = points(after, model, options.pointStep);
    return {meals, pots, total, space, needs, capacity, care, cash: purchase,
      cookingWait: row.seconds / 60 * pots, activeCook: row.seconds / 60 * pots * options.cookActive / 100,
      extraPoints: afterPoints === null ? null : afterPoints - beforePoints, moraleAfter: after, moraleGain: after - before,
      fits: capacity <= options.capacity && care <= options.care && purchase <= options.cash,
      moraleCovered: after - before >= options.morale, wastedSatiety: Math.max(0, total[0] - options.satiety)};
  }
  function evaluate(data, input = {}) {
    const options = {...defaults, ...input}, w = weights(options);
    const crops = (data.crops || []).map(row => cropModel(row, data, options));
    const resources = new Map((data.resources || []).map(item => [item.id, resourceOptions(item, crops, options, w)]));
    const sourceIngredients = data.cooking?.ingredients || [];
    const stock = Object.fromEntries(sourceIngredients.map(item => [item.id, 9999]));
    const entries = data.cooking?.entries || [], dishById = new Map(data.dishes.map(row => [row.id, row]));
    const bestByIngredient = new Map();
    const score = (total, ingredients, entry, product, trade = false) => {
      if (!positive(total[0])) return NaN;
      const route = routeTotals(ingredients, resources);
      if (!route) return NaN;
      const seconds = dishById.get(entry.id)?.seconds;
      if (!positive(seconds)) return NaN;
      if (trade) {
        const output = dishById.get(entry.id)?.qualities[product.quality];
        const outputValue = givenValue(output?.trade_value, output?.sell_rate, options.sellChannel);
        const inputValues = ingredients.map(item => resources.get(item.id)?.item.trade_value);
        if (outputValue === null || !inputValues.every(positive)) return NaN;
        return (outputValue * (output?.trade_uses || 1) - inputValues.reduce((a, b) => a + b, 0)) / (1 + seconds / 3600);
      }
      const active = seconds / 60 * options.cookActive / 100;
      const burden = 1 + w.economy * route.cash / options.cash + w.labor * (route.minutes + active) / options.care +
        w.space * route.spaceDays / options.capacity + w.wait * (route.lead + seconds / 86400) / options.horizon;
      const threshold = entry.portion_model.threshold > 0 ? entry.portion_model.threshold : data.cooking?.model?.split_threshold;
      const servings = Math.max(1, Math.ceil(Math.fround(total[0] / Math.fround(threshold))));
      const pots = Math.ceil(options.satiety / (total[0] / servings)) / servings;
      const usable = total.slice();
      if (options.moraleMode === "settlement") usable[1] = Math.min(Math.max(0, total[1]), Math.max(0, options.moraleMax - options.moraleNow) / pots);
      const value = benefit(usable, options, w) / burden;
      if (dishById.get(entry.id)?.level <= options.stage) for (const ingredient of ingredients) {
        let matches = bestByIngredient.get(ingredient.id);
        if (!matches) { matches = new Map(); bestByIngredient.set(ingredient.id, matches); }
        const previous = matches.get(entry.id);
        if (!previous || previous.value < value) matches.set(entry.id, {id: entry.id, value, total: total.slice(), ingredients: ingredients.slice()});
      }
      return value;
    };
    const results = window.Cooking.plan(entries, sourceIngredients, stock, options.quality, options.stage === 3 ? 1 : 0, 0,
      data.cooking?.model, {score: (total, ingredients, entry, product) => score(total, ingredients, entry, product, options.focus === "trade")});
    const dishes = [];
    for (const entry of entries) {
      const original = dishById.get(entry.id);
      if (!original || original.level > options.stage) continue;
      const output = results.get(entry.key);
      const row = {...original, value: null, reason: "当前食材来源或效果数据无法完整计算", score: null};
      if (output) {
        const routes = routeTotals(output.ingredients, resources);
        Object.assign(row, routes, {output, requirements: requirements(output.ingredients, resources), reason: "",
          value: score(output.total, output.ingredients, entry, output.product, options.focus === "trade"), penalty: options.focus === "trade" ? 0 : rawPenalty(output.total)});
        row.inputTrade = output.ingredients.reduce((sum, ingredient) => sum + (resources.get(ingredient.id).item.trade_value ?? NaN), 0);
        const product = original.qualities[options.quality];
        const outValue = givenValue(product?.trade_value, product?.sell_rate, options.sellChannel);
        row.outputTrade = outValue === null ? null : outValue * (product?.trade_uses || 1);
        row.tradeMargin = Number.isFinite(row.inputTrade) && row.outputTrade !== null ? row.outputTrade - row.inputTrade : null;
        row.tradeRatio = positive(row.inputTrade) && row.outputTrade !== null ? row.outputTrade / row.inputTrade : null;
        row.cost100 = positive(output.total[0]) ? routes.cash * 100 / output.total[0] : null;
        row.morale100 = output.total[1] * 100 / output.total[0];
        row.daily = dailyPlan(row, options, data.supply_model);
      }
      dishes.push(row);
    }
    rank(dishes);
    const active = dishes.filter(row => row.score !== null);
    const ingredients = [];
    for (const resource of resources.values()) {
      const matches = options.focus === "trade" ? active.filter(dish => dish.requirements.some(r => r.item.id === resource.item.id)) :
        [...(bestByIngredient.get(resource.item.id)?.values() || [])].map(match => ({...dishById.get(match.id), ...match}));
      matches.sort((a, b) => b.value - a.value || a.id - b.id);
      const row = {...resource.item, resource, recipes: matches.slice(0, 3), coverage: matches.length,
        morale100: matches.length ? Math.max(...matches.map(m => (m.total || m.output.total)[1] * 100 / (m.total || m.output.total)[0])) : null,
        value: matches.length && resource.selected ? matches[0].value : null,
        reason: matches.length ? "" : "本阶段没有可完整计算的推荐组合"};
      ingredients.push(row);
    }
    rank(ingredients);
    for (const crop of crops) {
      const harvestIds = new Set(crop.harvest.map(item => item.id));
      crop.recipes = ingredients.filter(item => harvestIds.has(item.id)).flatMap(item => item.recipes)
        .filter((recipe, index, all) => all.findIndex(r => r.id === recipe.id) === index)
        .sort((a, b) => b.value - a.value || a.id - b.id).slice(0, 3);
      const relevant = crop.recipes[0];
      const required = relevant?.ingredients || relevant?.output?.ingredients || [];
      const counts = new Map();
      for (const ingredient of required) if (harvestIds.has(ingredient.id)) counts.set(ingredient.id, (counts.get(ingredient.id) || 0) + 1);
      const pots = counts.size ? Math.min(...[...counts].map(([id, amount]) => {
        const harvest = crop.harvest.find(h => h.id === id);
        return harvest.uses * harvest.amount * crop.batch / crop.days / amount;
      })) : 0;
      crop.morale100 = crop.recipes.length ? Math.max(...crop.recipes.map(r => (r.total || r.output.total)[1] * 100 / (r.total || r.output.total)[0])) : null;
      crop.trade_value = crop.harvest.reduce((n, h) => n + (h.trade_value || 0) * (h.uses || 1) * h.amount * crop.batch, 0) / crop.days;
      crop.value = !crop.reason && relevant && positive(pots) ? relevant.value * pots / crop.capacity /
        (1 + w.labor * crop.dailyMinutes / options.care + w.wait * crop.days / options.horizon) :
        !crop.reason && positive(crop.dailyRawSatiety) ? crop.dailyRawSatiety / options.satiety /
        (1 + w.labor * crop.dailyMinutes / options.care + w.space * crop.capacity / options.capacity) : null;
    }
    rank(crops);
    return {options, weights: w, dishes, ingredients, crops, resources};
  }
  window.Supply = {defaults, profiles, weights, cropModel, resourceOptions, points, givenValue, rank, evaluate};
})();
