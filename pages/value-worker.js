"use strict";
globalThis.window = globalThis;
importScripts("cooking.js");

(() => {
  "use strict";
  const f = Math.fround;
  const uses = item => Math.max(1, item.use_times || 0);
  const counts = ids => {
    const result = {};
    for (const id of ids) result[id] = (result[id] || 0) + 1;
    return result;
  };
  const SUPPLY_POT_CAP = 99;

  function wholeBase(item) {
    return f(f(item.trade_value) * uses(item));
  }

  // 把登记库存换算成"可用次数"，补给品视为无限。
  function parseStock(model, input) {
    const byId = new Map(model.items.map(item => [item.id, item]));
    const stock = {}, supply = new Set(), stockValue = {direct: 0, consumed: 0};
    for (const [id, entry] of Object.entries(input.stock || {})) {
      const item = byId.get(Number(id));
      if (!item || !(entry.quantity > 0)) continue;
      const perItem = Math.max(1, uses(item) * clampPercent(entry.remaining));
      stockValue.direct += f(f(item.trade_value * perItem) * Math.floor(entry.quantity));
      if (input.supply?.includes(item.id)) supply.add(item.id);
      else stock[item.id] = Math.floor(entry.quantity) * perItem;
    }
    return {byId, stock, supply, stockValue};
  }

  const clampPercent = value => Math.min(100, Math.max(0, Number(value) || 100)) / 100;

  function candidate(kind, key, id, name, requirements, outputs, ctx, extra) {
    for (const itemId of Object.keys(requirements)) if (!ctx.byId.has(Number(itemId))) return null;
    for (const itemId of Object.keys(outputs)) if (!ctx.byId.has(Number(itemId))) return null;
    let cost = 0;
    for (const [itemId, count] of Object.entries(requirements)) cost += ctx.byId.get(Number(itemId)).trade_value * count;
    let value = 0;
    for (const [itemId, count] of Object.entries(outputs)) value += wholeBase(ctx.byId.get(Number(itemId))) * count;
    cost = f(cost);
    value = f(value);
    const gain = f(value - cost);
    if (!(cost > 0) || !(value > 0) || !Number.isFinite(gain)) return null;
    return {kind, key, id, name, requirements, outputs, cost, value, gain,
      ratio: gain / cost, supply: Object.keys(requirements).some(itemId => ctx.supply.has(Number(itemId))), ...extra};
  }

  function feasiblePots(plan, ctx) {
    let pots = plan.supply ? SUPPLY_POT_CAP : Infinity;
    for (const [itemId, count] of Object.entries(plan.requirements)) {
      const have = ctx.supply.has(Number(itemId)) ? Infinity : (ctx.stock[itemId] || 0);
      pots = Math.min(pots, Math.floor(have / count));
    }
    return Math.max(0, pots);
  }

  function consume(plan, pots, ctx) {
    for (const [itemId, count] of Object.entries(plan.requirements)) {
      if (!ctx.supply.has(Number(itemId))) ctx.stock[itemId] = (ctx.stock[itemId] || 0) - count * pots;
    }
  }

  function row(plan, pots, ctx) {
    return {
      key: plan.key, kind: plan.kind, id: plan.id, name: plan.name, pots,
      cost_per_pot: plan.cost, value_per_pot: plan.value, gain_per_pot: plan.gain,
      ratio: plan.ratio, total_gain: f(plan.gain * pots), supply: plan.supply,
      servings: plan.servings || null, seconds: plan.seconds || null, level: plan.level || null,
      inputs: Object.entries(plan.requirements).map(([itemId, count]) => describe(ctx.byId.get(Number(itemId)), count)),
      outputs: Object.entries(plan.outputs).map(([itemId, count]) => describe(ctx.byId.get(Number(itemId)), count)),
    };
  }

  function describe(item, count) {
    return {id: item.id, name: item.name, icon: item.icon, uses: count};
  }

  // 重新执行已勾选的方案：按登记的投入组合扣减当前库存，库存不足时按比例缩减。
  function reapply(appliedRows, ctx) {
    const result = [];
    for (const saved of appliedRows) {
      if (!saved || !Array.isArray(saved.inputs) || !Array.isArray(saved.outputs)) continue;
      const requirements = counts(saved.inputs.map(line => line.id));
      const outputs = counts(saved.outputs.map(line => line.id));
      let pots = Math.max(0, Math.floor(saved.pots || 0));
      if (!(pots > 0)) continue;
      for (const [itemId, count] of Object.entries(requirements)) {
        if (!ctx.byId.has(Number(itemId))) { pots = 0; break; }
        const have = ctx.supply.has(Number(itemId)) ? Infinity : (ctx.stock[itemId] || 0);
        if (have !== Infinity) pots = Math.min(pots, Math.floor(have / count));
      }
      if (!(pots > 0)) continue;
      const cost = Object.entries(requirements).reduce((sum, [itemId, count]) => f(sum + ctx.byId.get(Number(itemId)).trade_value * count), 0);
      const value = Object.entries(outputs).reduce((sum, [itemId, count]) => f(sum + wholeBase(ctx.byId.get(Number(itemId))) * count), 0);
      const gain = f(value - cost);
      const plan = {kind: saved.kind || "cook", key: saved.key || `${saved.kind}:${saved.id}`, id: saved.id,
        name: saved.name, requirements, outputs, cost, value, gain, ratio: gain / cost,
        supply: Object.keys(requirements).some(itemId => ctx.supply.has(Number(itemId))),
        servings: saved.servings, seconds: saved.seconds, level: saved.level};
      consume(plan, pots, ctx);
      const line = row(plan, pots, ctx);
      line.short = pots < saved.pots;
      result.push(line);
    }
    return result;
  }

  // 贪心 + 局部交换：固定食材菜与制造配方共用一个候选池，同池竞争原料。
  function greedy(candidates, ctx, taken) {
    const allocation = new Map();
    const applyOnce = (plan, pots) => {
      const free = feasiblePots(plan, ctx);
      const used = Math.min(pots, free);
      if (!(used > 0)) return 0;
      consume(plan, used, ctx);
      allocation.set(plan.key, (allocation.get(plan.key) || 0) + used);
      return used;
    };
    for (const plan of candidates.filter(item => item.gain > 0 && !taken.has(item.key))
      .sort((a, b) => b.ratio - a.ratio || b.gain - a.gain || a.id - b.id))
      applyOnce(plan, plan.supply ? SUPPLY_POT_CAP : Infinity);

    // 局部交换改进：少做一锅 A 腾出原料，多做几锅 B，总增值提升才交换。
    const positive = candidates.filter(item => item.gain > 0);
    for (let round = 0; round < 50; round += 1) {
      let improved = false;
      for (const [key, pots] of [...allocation]) {
        if (!(pots > 0)) continue;
        const planA = positive.find(item => item.key === key);
        if (!planA) continue;
        for (const planB of positive.sort((a, b) => b.ratio - a.ratio).slice(0, 20)) {
          if (planB.key === key) continue;
          for (let drop = 1; drop <= Math.min(3, pots); drop += 1) {
            for (const [itemId, count] of Object.entries(planA.requirements))
              if (!ctx.supply.has(Number(itemId))) ctx.stock[itemId] += count * drop;
            let gained = 0, made = 0;
            for (let add = 0; add < 12; add += 1) {
              const free = feasiblePots(planB, ctx);
              if (!(free > 0)) break;
              consume(planB, free, ctx);
              gained += planB.gain * free;
              made += free;
            }
            if (gained > planA.gain * drop + 1e-4) {
              // 保留模拟结果：A 腾出的原料已计入库存，B 的消耗已扣减。
              allocation.set(key, pots - drop);
              allocation.set(planB.key, (allocation.get(planB.key) || 0) + made);
              improved = true;
              break;
            }
            for (const [itemId, count] of Object.entries(planB.requirements))
              if (!ctx.supply.has(Number(itemId))) ctx.stock[itemId] -= count * made;
            for (const [itemId, count] of Object.entries(planA.requirements))
              if (!ctx.supply.has(Number(itemId))) ctx.stock[itemId] -= count * drop;
          }
          if (improved) break;
        }
        if (improved) break;
      }
      if (!improved) break;
    }
    void taken;
    return allocation;
  }

  self.onmessage = event => {
    const request = event.data;
    try {
      const model = request.model;
      const input = request.input;
      const ctx = parseStock(model, input);
      const quality = input.quality || "普通";
      const cookLevel = Math.min(3, Math.max(1, Number(input.cookLevel) || 1));
      const craftLevel = Math.min(5, Math.max(1, Number(input.craftLevel) || 1));
      const positiveOnly = input.positiveOnly !== false;
      const taken = new Set(input.applied || []);

      const appliedRows = reapply((input.appliedRows || []).filter(item => taken.has(item.key)), ctx);

      // 候选池：固定食材菜 + 制造配方
      const signatures = new Set();
      const fixedDishes = [];
      for (const entry of model.cooking.entries) {
        const specific = entry.recipe.specific_items || [];
        if (specific.length) {
          const signature = specific.join(",");
          if (signatures.has(signature)) continue;
          signatures.add(signature);
          const product = entry.products.find(item => item.quality === quality);
          if (!product) continue;
          const dish = model.dishes.find(item => item.id === entry.id);
          if (!dish || dish.level > cookLevel) continue;
          const plan = candidate("cook", `cook:${entry.id}`, entry.id, dish.name,
            counts(specific), {[product.id]: 1}, ctx, {servings: null, seconds: null, level: dish.level});
          if (plan) fixedDishes.push(plan);
        }
      }
      const crafts = [];
      for (const craft of model.crafts) {
        if (craft.level > craftLevel) continue;
        const plan = candidate("craft", `craft:${craft.id}`, craft.id, craft.name,
          counts(craft.inputs), counts(craft.outputs), ctx, {servings: null, seconds: craft.seconds || null, level: craft.level});
        if (plan) crafts.push(plan);
      }

      const allocation = greedy([...fixedDishes, ...crafts], ctx, taken);
      const suggestions = [];
      for (const plan of [...fixedDishes, ...crafts]) {
        const pots = allocation.get(plan.key) || 0;
        if (!(pots > 0)) continue;
        if (positiveOnly && !(plan.gain > 0)) continue;
        suggestions.push(row(plan, pots, ctx));
      }

      // 通用档位菜：Cooking.plan 枚举可行组合，score 回调记录每个配方净增值最高的组合。
      const suggestedKeys = new Set(suggestions.map(item => item.key));
      const planStock = {...ctx.stock};
      for (const id of ctx.supply) planStock[id] = 1e9;
      const available = model.cooking.ingredients.filter(item => planStock[item.id] > 0);
      const bestGeneric = new Map();
      if (available.length) {
        // cooking.ingredients 没有 trade_value 字段，交易基值统一从 trade items 表（ctx.byId）取。
        Cooking.plan(model.cooking.entries, available, planStock, quality, 0, 0, model.cooking.model, {
          ingredientCost: item => f(ctx.byId.get(item.id)?.trade_value || 0),
          score: (total, chosen, entry, product) => {
            void total;
            const dish = model.dishes.find(item => item.id === entry.id);
            if (!dish || dish.level > cookLevel) return NaN;
            const output = ctx.byId.get(product.id);
            if (!output) return NaN;
            const cost = chosen.reduce((sum, item) => {
              const ingredient = ctx.byId.get(item.id);
              return ingredient ? f(sum + f(ingredient.trade_value)) : NaN;
            }, 0);
            if (!Number.isFinite(cost)) return NaN;
            const gain = f(wholeBase(output) - cost);
            const previous = bestGeneric.get(entry.key);
            if (!previous || gain > previous.gain)
              bestGeneric.set(entry.key, {entryId: entry.id, entryKey: entry.key,
                ingredients: chosen.map(item => item.id), productId: product.id, gain});
            return gain;
          },
        });
      }
      for (const best of [...bestGeneric.values()].sort((a, b) => b.gain - a.gain)) {
        if (suggestedKeys.has(best.entryKey) || taken.has(`cook:${best.entryKey}`)) continue;
        const product = ctx.byId.get(best.productId);
        if (!product) continue;
        const requirements = counts(best.ingredients);
        let pots = Infinity;
        for (const [itemId, count] of Object.entries(requirements)) {
          const have = ctx.supply.has(Number(itemId)) ? SUPPLY_POT_CAP : (ctx.stock[itemId] || 0);
          pots = Math.min(pots, Math.floor(have / count));
        }
        if (!(pots > 0)) continue;
        const generic = candidate("cook", `cook:${best.entryKey}`, best.entryId,
          model.dishes.find(item => item.id === best.entryId)?.name || `ID:${best.entryId}`,
          requirements, {[product.id]: 1}, ctx, {servings: null, seconds: null, level: null});
        if (!generic) continue;
        if (positiveOnly && !(generic.gain > 0)) continue;
        consume(generic, pots, ctx);
        suggestedKeys.add(generic.key);
        suggestions.push(row(generic, pots, ctx));
      }

      suggestions.sort((a, b) => b.total_gain - a.total_gain || b.gain_per_pot - a.gain_per_pot ||
        String(a.kind).localeCompare(String(b.kind)) || a.id - b.id);
      const totalGain = f(suggestions.reduce((sum, item) => f(sum + item.total_gain), 0) +
        appliedRows.reduce((sum, item) => f(sum + item.total_gain), 0));
      const leftovers = model.cooking.ingredients
        .filter(item => ctx.stock[item.id] > 0)
        .map(item => ({id: item.id, name: item.name, icon: item.icon,
          uses_left: Math.round(ctx.stock[item.id]),
          value: f(f(ctx.byId.get(item.id)?.trade_value || 0) * ctx.stock[item.id])}))
        .filter(item => item.uses_left > 0)
        .sort((a, b) => b.value - a.value);

      self.postMessage({job: request.job, direct_total: f(ctx.stockValue.direct),
        plan_total: f(ctx.stockValue.direct + totalGain), total_gain: totalGain,
        rows: suggestions, applied_rows: appliedRows, leftovers});
    } catch (error) {
      self.postMessage({job: request.job, error: String(error && error.message || error)});
    }
  };
})();
