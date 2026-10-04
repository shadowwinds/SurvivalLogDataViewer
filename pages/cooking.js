(() => {
  "use strict";
  const f = Math.fround;
  const key = ids => [...ids].sort((a, b) => a - b).join(",");
  const values = product => [1, 2, 3, 4, 5].map(index => product.stats?.find(s => s.field === "ValueDisplay" + index)?.value);
  const ingredientStatIndices = [0, 3, 4];
  const cost = item => Number.isFinite(item.price) && item.price >= 0 && Number.isInteger(item.use_times) && item.use_times > 0 ? item.price / item.use_times : null;
  const effectiveTier = (tier, floor) => tier == null ? null : floor ? Math.min(tier, 4 - floor) : tier;
  function tier(items, floor = 0) {
    const tiers = items.map(item => effectiveTier(item.tier, floor)).filter(value => value != null);
    return tiers.length ? Math.min(...tiers) : null;
  }
  function calculateTotal(entry, ingredients, product, model, base = values(product)) {
    let total = base.slice();
    if (entry.portion_model?.mode !== "fixed") {
      const tc = model?.tier_coefficients?.[entry.recipe?.tier], qc = model?.quality_coefficients?.[product.quality];
      if (!Number.isFinite(tc) || !Number.isFinite(qc) || !Number.isFinite(model?.base_satiety_per_ingredient)) return null;
      const sums = [0, 0, 0, 0, 0];
      for (let position = 0; position < ingredients.length; position += 1) {
        const item = ingredients[position];
        let seen = false, count = 1;
        for (let previous = 0; previous < position; previous += 1) if (ingredients[previous].id === item.id) seen = true;
        if (seen) continue;
        for (let next = position + 1; next < ingredients.length; next += 1) if (ingredients[next].id === item.id) count += 1;
        for (const index of ingredientStatIndices) {
          if (!Number.isFinite(item.stats?.[index])) return null;
          sums[index] = f(sums[index] + f(f(count) * f(item.stats[index])));
        }
      }
      for (const index of ingredientStatIndices) {
        let result = f(f(sums[index] * f(tc)) * f(qc));
        if (index === 0) result = f(result + f(f(ingredients.length) * f(model.base_satiety_per_ingredient)));
        total[index] = Math.ceil(result);
      }
    }
    if (!total.every(Number.isFinite)) return null;
    return total.map(value => Math.ceil(f(value)));
  }
  function makeForecast(entry, ingredients, product, total, model) {
    const threshold = entry.portion_model?.threshold > 0 ? entry.portion_model.threshold : model?.split_threshold;
    if (!Number.isFinite(threshold) || threshold <= 0) return null;
    const servings = Math.max(1, Math.ceil(f(total[0] / f(threshold))));
    const perUse = total.map(value => servings > 1 ? f(value / f(servings)) : value);
    const prices = ingredients.map(cost);
    return {total, perUse, servings, ingredients, product,
      cost: prices.every(value => value !== null) ? prices.reduce((a, b) => a + b, 0) : null};
  }
  function forecast(entry, ingredients, quality, model) {
    const product = entry.products?.find(item => item.quality === quality);
    if (!product) return null;
    const total = calculateTotal(entry, ingredients, product, model);
    return total ? makeForecast(entry, ingredients, product, total, model) : null;
  }
  function compare(a, b, goal = 0) {
    return b.total[goal] - a.total[goal] || b.total[0] - a.total[0] ||
      (a.cost ?? Infinity) - (b.cost ?? Infinity) || key(a.ingredients.map(item => item.id)).localeCompare(key(b.ingredients.map(item => item.id)), "en");
  }
  function plan(entries, ingredients, stock, quality, goal, floor, model, options = {}) {
    const available = ingredients.filter(item => stock[item.id] > 0);
    const byId = new Map(available.map(item => [item.id, item]));
    const specifics = new Map(), generics = new Map(), results = new Map();
    for (const entry of [...entries].sort((a, b) => a.id - b.id)) {
      const recipe = entry.recipe;
      if (recipe?.specific_items?.length) {
        const signature = key(recipe.specific_items);
        if (!specifics.has(signature)) specifics.set(signature, entry.id);
      } else if (recipe?.tag_combo?.length) {
        const signature = key(recipe.tag_combo) + ":" + recipe.tier;
        if (!generics.has(signature)) generics.set(signature, entry.id);
      }
    }
    for (const entry of entries) {
      const recipe = entry.recipe;
      if (!recipe) continue;
      if (recipe.specific_items?.length) {
        if (specifics.get(key(recipe.specific_items)) !== entry.id) continue;
        const required = new Map();
        for (const id of recipe.specific_items) required.set(id, (required.get(id) || 0) + 1);
        if ([...required].some(([id, count]) => !byId.has(id) || stock[id] < count)) continue;
        const result = forecast(entry, recipe.specific_items.map(id => byId.get(id)), quality, model);
        if (result && (!options.score || Number.isFinite(options.score(result.total, result.ingredients, entry, result.product)))) results.set(entry.key, result);
        continue;
      }
      if (!recipe.tag_combo?.length || generics.get(key(recipe.tag_combo) + ":" + recipe.tier) !== entry.id) continue;
      const product = entry.products?.find(item => item.quality === quality);
      if (!product) continue;
      const base = values(product);
      const slots = [...recipe.tag_combo].sort((a, b) => a - b);
      const candidates = slots.map(group => available.filter(item => item.sub_category_id === group &&
        (effectiveTier(item.tier, floor) === null || effectiveTier(item.tier, floor) >= recipe.tier)).sort((a, b) => a.id - b.id));
      if (candidates.some(items => !items.length)) continue;
      let best = null, bestScore = -Infinity;
      const chosen = [], used = new Map();
      const visit = (index, resolvedTier) => {
        if (index === slots.length) {
          if (resolvedTier !== recipe.tier) return;
          const total = calculateTotal(entry, chosen, product, model, base);
          if (!total || (!options.score && best && (total[goal] < best.total[goal] ||
            (total[goal] === best.total[goal] && total[0] < best.total[0])))) return;
          if (specifics.has(key(chosen.map(item => item.id)))) return;
          const candidateScore = options.score ? options.score(total, chosen, entry, product) : 0;
          if (!Number.isFinite(candidateScore) || candidateScore < bestScore) return;
          const result = makeForecast(entry, chosen.slice(), product, total, model);
          if (result && (!best || candidateScore > bestScore || compare(result, best, goal) < 0)) {
            best = result; bestScore = candidateScore;
          }
          return;
        }
        for (const item of candidates[index]) {
          const count = used.get(item.id) || 0;
          if (count >= stock[item.id] || (index > 0 && slots[index] === slots[index - 1] && item.id < chosen[index - 1].id)) continue;
          const itemTier = effectiveTier(item.tier, floor);
          used.set(item.id, count + 1); chosen.push(item);
          visit(index + 1, itemTier === null ? resolvedTier : Math.min(resolvedTier ?? itemTier, itemTier));
          chosen.pop(); used.set(item.id, count);
        }
      };
      visit(0, null);
      if (best) results.set(entry.key, best);
    }
    return results;
  }
  window.Cooking = {tier, forecast, compare, plan};
})();
