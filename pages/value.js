(() => {
  "use strict";
  const host = typeof window === "undefined" ? globalThis : window;
  const clamp = (value, lo, hi) => Math.min(hi, Math.max(lo, Number(value) || 0));

  (async () => {
    await host.I18n?.ready;
    const element = document.getElementById("value-data");
    if (!element) return;
    const model = JSON.parse(element.textContent);
    if (model.format_version !== 1) return;
    const planner = document.getElementById("value-planner");
    if (planner) planner.hidden = false;
    const $ = id => document.getElementById(id);
    const tr = (text, vars) => host.I18n?.text(text, vars) || text;
    const escape = value => String(value ?? "").replace(/[&<>"']/g, ch => ({"&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;"}[ch]));
    const fmt = value => Number.isFinite(value) ? value.toLocaleString(host.I18n?.locale || "zh-CN", {maximumFractionDigits: 2}) : "—";
    const byId = new Map(model.items.map(item => [item.id, item]));
    const name = item => tr(item.name);
    const image = (item, size = 36) => item?.icon ? `<img src="../${escape(item.icon)}" width="${size}" height="${size}" loading="lazy" alt="">` : "";
    const wholeUses = item => Math.max(1, item.uses || item.use_times || 1);
    const wholeBase = item => item.trade_value * wholeUses(item);
    const category = cat => model.categories[cat] ? tr(model.categories[cat]) : tr("其他物品 · 分类 {id}", {id: cat});
    const storageKey = `survival-log-value:${model.game_version}`;
    const supply = new Set(), appliedRows = [];
    let stock = {}, quality = "普通", cookLevel = 3, craftLevel = 5, positiveOnly = true;
    let job = 0, timer, worker;

    try {
      const saved = JSON.parse(localStorage.getItem(storageKey) || "{}");
      for (const [id, entry] of Object.entries(saved.stock || {})) if (byId.has(Number(id)) && entry?.quantity > 0)
        stock[id] = {quantity: Math.floor(clamp(entry.quantity, 0, 9999)), remaining: clamp(entry.remaining, 0, 100)};
      for (const id of saved.supply || []) if (byId.has(Number(id))) supply.add(Number(id));
      for (const row of saved.appliedRows || []) if (row && row.key) appliedRows.push(row);
      quality = saved.quality || quality;
      cookLevel = clamp(saved.cookLevel ?? cookLevel, 1, 3);
      craftLevel = clamp(saved.craftLevel ?? craftLevel, 1, 5);
      positiveOnly = saved.positiveOnly !== false;
    } catch { /* Optional persistence. */ }
    function save() {
      try { localStorage.setItem(storageKey, JSON.stringify({stock, supply: [...supply], appliedRows,
        quality, cookLevel, craftLevel, positiveOnly})); } catch { /* Optional persistence. */ }
    }

    // ---------- 登记 ----------
    const catalog = $("value-catalog"), search = $("value-search"), catSelect = $("value-stock-cat");
    for (const cat of [...new Set(model.items.map(item => item.cat))].sort((a, b) => a - b)) {
      const option = document.createElement("option");
      option.value = cat;
      option.textContent = category(cat);
      catSelect.append(option);
    }
    function catalogItems() {
      const phrase = search.value.trim().toLocaleLowerCase();
      const cat = catSelect.value === "" ? null : Number(catSelect.value);
      return model.items.filter(item => (cat === null || item.cat === cat) &&
        (!phrase || `${item.name} ${host.I18n?.english(item.name)} ${item.id}`.toLocaleLowerCase().includes(phrase)))
        .sort((a, b) => name(a).localeCompare(name(b), host.I18n?.locale)).slice(0, 60);
    }
    function renderCatalog() {
      catalog.replaceChildren();
      for (const item of catalogItems()) {
        const button = document.createElement("button");
        button.type = "button";
        button.className = "value-item";
        button.title = `${name(item)} · ${tr("基值")} ${fmt(item.trade_value)}`;
        button.innerHTML = `${image(item)}<span>${escape(name(item))}</span><small>${fmt(item.trade_value)}</small>`;
        button.addEventListener("click", () => {
          stock[item.id] = stock[item.id] || {quantity: 0, remaining: 100};
          stock[item.id].quantity = Math.min(9999, (stock[item.id].quantity || 0) + 1);
          save(); renderBasket(); schedule();
        });
        catalog.append(button);
      }
      if (!catalog.children.length) catalog.innerHTML = `<p class="value-empty">${escape(tr("没有匹配的物品"))}</p>`;
    }
    search.addEventListener("input", renderCatalog);
    catSelect.addEventListener("change", renderCatalog);

    const basket = $("value-basket");
    function renderBasket() {
      basket.replaceChildren();
      const entries = Object.entries(stock).map(([id, entry]) => [Number(id), entry]).sort((a, b) => a[0] - b[0]);
      $("value-count").textContent = tr("已登记 {count} 种", {count: entries.length});
      if (!entries.length) {
        basket.innerHTML = `<p class="value-empty">${escape(tr("从上方目录点击登记冰箱里的食材、种子和材料"))}</p>`;
        return;
      }
      for (const [id, entry] of entries) {
        const item = byId.get(id);
        const line = document.createElement("div");
        line.className = "value-basket-row";
        line.innerHTML = `${image(item)}<span class="value-basket-name" title="${escape(name(item))}">${escape(name(item))}</span>`;
        const quantity = document.createElement("input");
        quantity.type = "number"; quantity.min = "1"; quantity.max = "9999"; quantity.value = entry.quantity;
        quantity.title = tr("数量（件）");
        quantity.addEventListener("change", () => {
          entry.quantity = Math.floor(clamp(quantity.value, 1, 9999)); save(); schedule();
        });
        line.append(quantity);
        if (wholeUses(item) > 1) {
          const remaining = document.createElement("input");
          remaining.type = "number"; remaining.min = "0"; remaining.max = "100"; remaining.value = entry.remaining;
          remaining.title = tr("剩余可用次数（%）");
          remaining.addEventListener("change", () => {
            entry.remaining = clamp(remaining.value, 0, 100); save(); schedule();
          });
          line.append(remaining);
        }
        const supplyCheck = document.createElement("label");
        supplyCheck.className = "value-supply";
        const check = document.createElement("input");
        check.type = "checkbox"; check.checked = supply.has(id);
        check.title = tr("补给品：陷阱猎物、交易可获得，按需补充，不占库存上限");
        check.addEventListener("change", () => {
          if (check.checked) supply.add(id); else supply.delete(id); save(); schedule();
        });
        supplyCheck.append(check, document.createTextNode(tr("补给")));
        line.append(supplyCheck);
        const remove = document.createElement("button");
        remove.type = "button"; remove.textContent = "×"; remove.className = "value-remove";
        remove.title = tr("移除");
        remove.addEventListener("click", () => {
          delete stock[id]; supply.delete(id);
          save(); renderBasket(); renderCatalog(); schedule();
        });
        line.append(remove);
        basket.append(line);
      }
    }

    // ---------- 批量导入 ----------
    function parseBulk(text) {
      let count = 0;
      for (const raw of text.split(/[\n,，、;；]+/)) {
        const line = raw.trim();
        if (!line) continue;
        const match = line.match(/^(.*?)[×x\*\s]*(\d+)?$/u);
        const label = (match[1] || "").trim(), quantity = clamp(match[2], 1, 9999) || 1;
        if (!label) continue;
        const item = model.items.find(row => row.name === label ||
          host.I18n?.english(row.name) === label || String(row.id) === label);
        if (item) {
          stock[item.id] = stock[item.id] || {quantity: 0, remaining: 100};
          stock[item.id].quantity = Math.min(9999, (stock[item.id].quantity || 0) + quantity);
          count += 1;
        }
      }
      return count;
    }
    $("value-bulk-apply").addEventListener("click", () => {
      const count = parseBulk($("value-bulk").value);
      $("value-bulk").value = "";
      $("value-bulk-result").textContent = count > 0 ? tr("已登记 {count} 种", {count}) : tr("没有识别到物品名");
      save(); renderBasket(); renderCatalog(); schedule();
    });
    $("value-bulk-example").addEventListener("click", () => {
      const picks = model.items.filter(item => item.cat === 1 && wholeUses(item) === 1).slice(0, 4)
        .map(item => `${name(item)}×2`);
      $("value-bulk").value = picks.join("、");
    });
    $("value-clear").addEventListener("click", () => {
      stock = {}; supply.clear(); appliedRows.length = 0;
      save(); renderBasket(); renderCatalog(); schedule();
    });

    // ---------- 控制 ----------
    const controls = [["value-quality", [["普通", "普通"], ["良好", "良好"], ["完美", "完美"]]],
      ["value-cook-level", [1, 2, 3].map(level => [level, `烹饪 Lv.${level}`])],
      ["value-craft-level", [1, 2, 3, 4, 5].map(level => [level, `制造 Lv.${level}`])]];
    for (const [id, options] of controls) {
      const node = $(id);
      for (const [value, label] of options) {
        const option = document.createElement("option");
        option.value = value;
        option.textContent = tr(label);
        node.append(option);
      }
    }
    $("value-quality").value = quality;
    $("value-cook-level").value = String(cookLevel);
    $("value-craft-level").value = String(craftLevel);
    $("value-positive").checked = positiveOnly;
    $("value-quality").addEventListener("change", () => { quality = $("value-quality").value; save(); if (current) renderCrops(current()); schedule(); });
    $("value-cook-level").addEventListener("change", () => { cookLevel = clamp($("value-cook-level").value, 1, 3); save(); if (current) renderCrops(current()); schedule(); });
    $("value-craft-level").addEventListener("change", () => { craftLevel = clamp($("value-craft-level").value, 1, 5); save(); if (current) renderCrops(current()); schedule(); });
    $("value-positive").addEventListener("change", () => { positiveOnly = $("value-positive").checked; save(); schedule(); });

    // ---------- Worker ----------
    function request() {
      job += 1;
      worker?.terminate();
      worker = new Worker("../value-worker.js");
      worker.onmessage = event => {
        if (event.data.job !== job) return;
        worker.terminate(); worker = null;
        if (event.data.error) {
          $("value-plan-error").textContent = tr("计算失败：{error}", {error: event.data.error});
          return;
        }
        $("value-plan-error").textContent = "";
        renderResult(event.data);
      };
      worker.postMessage({job, model, input: {stock, supply: [...supply], quality, cookLevel, craftLevel,
        positiveOnly, applied: appliedRows.map(row => row.key), appliedRows}});
    }
    function schedule() {
      clearTimeout(timer);
      timer = setTimeout(request, 250);
    }

    // ---------- 结果渲染 ----------
    function ioLine(lines) {
      return lines.map(line => {
        const item = byId.get(line.id);
        return `${image(item, 24)}${escape(name(item))}×${line.uses}`;
      }).join(" + ");
    }
    function planTable(container, rowsToRender, applied) {
      const body = container.querySelector("tbody");
      body.replaceChildren();
      container.hidden = !rowsToRender.length;
      for (const line of rowsToRender) {
        const node = document.createElement("tr");
        if (applied && line.short) node.classList.add("value-short");
        const cells = [];
        cells.push(applied
          ? `<button type="button" class="value-remove" data-unapply="${escape(line.key)}" title="${escape(tr("取消执行，原料退回库存"))}">×</button>`
          : `<input type="checkbox" data-key="${escape(line.key)}" title="${escape(tr("勾选后视为已执行，从库存中扣除"))}">`);
        cells.push(`<div class="value-cell-name">${image(byId.get(line.id))}<div><strong>${escape(line.name)}</strong>` +
          `<small>${tr("共 {pots} 份", {pots: line.pots})}${line.supply ? " · " + tr("含补给") : ""}` +
          `${applied && line.short ? " · " + tr("库存不足，已缩减") : ""}</small></div></div>`);
        cells.push(`<div class="value-io">${ioLine(line.inputs)}</div>`);
        cells.push(`<div class="value-io">${ioLine(line.outputs)}</div>`);
        cells.push(fmt(line.gain_per_pot));
        cells.push(`<strong>${fmt(line.total_gain)}</strong>`);
        node.innerHTML = cells.map(cell => `<td>${cell}</td>`).join("");
        body.append(node);
      }
      if (applied) {
        body.querySelectorAll("[data-unapply]").forEach(button => button.addEventListener("click", () => {
          const index = appliedRows.findIndex(row => row.key === button.dataset.unapply);
          if (index >= 0) appliedRows.splice(index, 1);
          save(); schedule();
        }));
      } else {
        body.querySelectorAll("input[type=checkbox]").forEach(check => check.addEventListener("change", () => {
          const line = rowsToRender.find(row => row.key === check.dataset.key);
          if (!line || !check.checked) return;
          appliedRows.push(line);
          save(); schedule();
        }));
      }
    }
    function renderResult(result) {
      const rows = result.rows || [];
      $("value-direct").textContent = fmt(result.direct_total);
      $("value-plan-total").textContent = fmt(result.plan_total);
      $("value-gain").textContent = fmt(result.total_gain);
      planTable($("value-cook-plan"), rows.filter(row => row.kind === "cook"), false);
      planTable($("value-craft-plan"), rows.filter(row => row.kind === "craft"), false);
      planTable($("value-applied-plan"), result.applied_rows || [], true);
      const leftovers = result.leftovers || [];
      const body = $("value-leftovers").querySelector("tbody");
      body.replaceChildren();
      $("value-leftovers").hidden = !leftovers.length;
      for (const line of leftovers.slice(0, 20)) {
        const item = byId.get(line.id);
        const node = document.createElement("tr");
        node.innerHTML = `<td><div class="value-cell-name">${image(item)}<strong>${escape(name(item))}</strong></div></td>` +
          `<td>${line.uses_left}</td><td>${fmt(line.value)}</td>`;
        body.append(node);
      }
    }

    // ---------- 种植规划 ----------
    const environment = model.planting_environment;
    const choice = {weather: "", cold_wave: 0, location: "", power: "off", planter: ""};
    const addOption = (select, value, label) => {
      const option = document.createElement("option");
      option.value = value;
      option.textContent = tr(label);
      select.append(option);
    };
    let current = null;
    if (environment) {
      const weather = $("value-weather"), location = $("value-location"), planterSelect = $("value-planter");
      for (const scenario of environment.scenarios.filter(row => row.cold_wave === 0))
        addOption(weather, scenario.weather, scenario.name);
      for (const spot of environment.locations) addOption(location, spot.key, spot.name);
      addOption(planterSelect, "", "不指定容器");
      for (const planter of model.planters) addOption(planterSelect, planter.id, planter.name);
      const heaters = $("value-heaters");
      for (const heater of environment.heaters) {
        const label = document.createElement("label");
        const check = document.createElement("input");
        check.type = "checkbox"; check.dataset.heater = heater.key;
        label.append(check, document.createTextNode(tr(heater.name)));
        heaters.append(label);
      }
      current = () => {
        choice.weather = weather.value;
        choice.cold_wave = $("value-cold-wave").checked ? 1 : 0;
        choice.location = location.value;
        choice.power = $("value-power").value;
        choice.planter = planterSelect.value;
        const planter = model.planters.find(row => String(row.id) === choice.planter) || null;
        return window.Planting.conditions(environment, choice, planter);
      };
      const saveChoice = () => {
        choice.heaters = Object.fromEntries([...heaters.querySelectorAll("input")]
          .map(check => [check.dataset.heater, check.checked]));
        try { localStorage.setItem(`${storageKey}:env`, JSON.stringify(choice)); } catch { /* Optional persistence. */ }
      };
      const onChange = () => { renderCrops(current()); saveChoice(); };
      for (const id of ["value-weather", "value-cold-wave", "value-location", "value-power", "value-planter", "value-plantable"])
        $(id).addEventListener("change", onChange);
      for (const check of heaters.querySelectorAll("input")) check.addEventListener("change", onChange);
      try {
        const savedChoice = JSON.parse(localStorage.getItem(`${storageKey}:env`) || "null");
        if (savedChoice) {
          if ([...weather.options].some(option => option.value === String(savedChoice.weather))) weather.value = String(savedChoice.weather);
          $("value-cold-wave").checked = Number(savedChoice.cold_wave) === 1;
          if ([...location.options].some(option => option.value === savedChoice.location)) location.value = savedChoice.location;
          $("value-power").value = savedChoice.power === "on" ? "on" : "off";
          if ([...planterSelect.options].some(option => option.value === String(savedChoice.planter))) planterSelect.value = String(savedChoice.planter);
          for (const check of heaters.querySelectorAll("input")) check.checked = Boolean(savedChoice.heaters?.[check.dataset.heater]);
        }
      } catch { /* Optional persistence. */ }
    } else {
      $("value-env-block").hidden = true;
      $("value-crops-block").hidden = true;
    }

    let cropSort = "net";
    for (const button of document.querySelectorAll("[data-crop-sort]"))
      button.addEventListener("click", () => {
        cropSort = button.dataset.cropSort;
        for (const other of document.querySelectorAll("[data-crop-sort]"))
          other.classList.toggle("active", other === button);
        if (current) renderCrops(current());
      });

    // ---------- 加工增值：收获物最佳烹饪/制造的每单位额外净增值 ----------
    const dishById = new Map(model.dishes.map(item => [item.id, item]));
    const subCategoryById = new Map(model.cooking.ingredients.map(item => [item.id, item.sub_category_id]));
    const ingredientTier = new Map(model.cooking.ingredients.map(item => [item.id, item.tier]));
    const fixedByItem = new Map(), craftByItem = new Map(), genericByGroup = new Map();
    for (const entry of model.cooking.entries) {
      for (const id of entry.recipe?.specific_items || []) {
        if (!fixedByItem.has(id)) fixedByItem.set(id, []);
        fixedByItem.get(id).push(entry);
      }
      const combo = entry.recipe?.tag_combo;
      if (combo?.length) for (const group of new Set(combo)) {
        if (!genericByGroup.has(group)) genericByGroup.set(group, []);
        genericByGroup.get(group).push(entry);
      }
    }
    for (const craft of model.crafts) for (const id of new Set(craft.inputs)) {
      if (!craftByItem.has(id)) craftByItem.set(id, []);
      craftByItem.get(id).push(craft);
    }
    const perUse = id => byId.get(id)?.trade_value;
    const whole = id => {
      const item = byId.get(id);
      return item ? item.trade_value * Math.max(1, item.use_times || 1) : null;
    };
    const cheapestOf = list => list.reduce((a, b) =>
      a == null || perUse(b.id) < perUse(a.id) ? b : a, null);
    const groupPools = new Map();
    const groupPool = (group, tierFloor) => {
      const cacheKey = `${group}:${tierFloor}`;
      if (!groupPools.has(cacheKey)) groupPools.set(cacheKey, model.cooking.ingredients
        .filter(item => item.sub_category_id === group && Number.isFinite(perUse(item.id)) &&
          (item.tier == null || item.tier >= tierFloor)));
      return groupPools.get(cacheKey);
    };

    let cropBonus = null, cropBonusKey = "";
    function cropBonusMap() {
      const cacheKey = `${quality}|${cookLevel}|${craftLevel}`;
      if (cropBonus && cropBonusKey === cacheKey) return cropBonus;
      const map = new Map();
      const keep = (id, recipeName, perUnit) => {
        if (!Number.isFinite(perUnit) || perUnit <= (map.get(id)?.gain ?? 0)) return;
        map.set(id, {name: recipeName, gain: perUnit});
      };
      for (const crop of model.crops) for (const harvest of crop.harvest) {
        const harvestId = harvest.id;
        if (map.has(harvestId)) continue;
        for (const craft of craftByItem.get(harvestId) || []) {
          if (craft.level > craftLevel) continue;
          const units = craft.inputs.filter(id => id === harvestId).length;
          const cost = craft.inputs.reduce((sum, id) => sum + perUse(id), 0);
          const value = craft.outputs.reduce((sum, id) => sum + whole(id), 0);
          keep(harvestId, craft.name, (value - cost) / units);
        }
        for (const entry of fixedByItem.get(harvestId) || []) {
          const dish = dishById.get(entry.id);
          const product = entry.products?.find(item => item.quality === quality);
          if (!dish || (dish.level != null && dish.level > cookLevel) || !product) continue;
          const items = entry.recipe.specific_items;
          const units = items.filter(id => id === harvestId).length;
          const cost = items.reduce((sum, id) => sum + perUse(id), 0);
          keep(harvestId, dish.name, units ? (whole(product.id) - cost) / units : NaN);
        }
        const group = subCategoryById.get(harvestId);
        if (group != null) for (const entry of genericByGroup.get(group) || []) {
          const dish = dishById.get(entry.id);
          const product = entry.products?.find(item => item.quality === quality);
          if (!dish || (dish.level != null && dish.level > cookLevel) || !product) continue;
          const tierFloor = entry.recipe.tier;
          const harvestTier = ingredientTier.get(harvestId);
          if (harvestTier != null && harvestTier < tierFloor) continue;
          const slots = [...entry.recipe.tag_combo];
          slots.splice(slots.indexOf(group), 1);
          const picks = [];
          let feasible = true;
          for (const slot of slots) {
            const pool = groupPool(slot, tierFloor);
            const cheapest = cheapestOf(pool);
            if (!cheapest) { feasible = false; break; }
            const exact = cheapestOf(pool.filter(item => item.tier === tierFloor));
            picks.push({cheapest, exact});
          }
          if (!feasible) continue;
          // 档位约束与 cooking.js 一致：所选食材的有效档位最小值必须恰好等于配方档位。
          const resolved = chosen => {
            let min = harvestTier;
            for (const item of chosen) if (item.tier != null) min = min == null ? item.tier : Math.min(min, item.tier);
            return min;
          };
          let chosen = picks.map(pick => pick.cheapest);
          if (resolved(chosen) !== tierFloor) {
            const swappable = picks.filter(pick => pick.exact && !chosen.includes(pick.exact))
              .sort((a, b) => perUse(b.cheapest.id) - perUse(a.cheapest.id));
            chosen = picks.map(pick => pick === swappable[0] ? pick.exact : pick.cheapest);
            if (resolved(chosen) !== tierFloor) continue;
          }
          const cost = chosen.reduce((sum, item) => sum + perUse(item.id), perUse(harvestId));
          keep(harvestId, dish.name, whole(product.id) - cost);
        }
      }
      cropBonus = map; cropBonusKey = cacheKey;
      return map;
    }

    function cropNet(crop, bonus) {
      const gain = crop.harvest.reduce((sum, item) => sum + (Number.isFinite(item.trade_value) ?
        item.trade_value * Math.max(1, item.uses || 1) * item.amount : 0), 0);
      const extra = crop.harvest.reduce((sum, item) => sum + (bonus.get(item.id)?.gain || 0) * item.amount, 0);
      const best = crop.harvest.map(item => bonus.get(item.id)).filter(Boolean)
        .reduce((a, b) => (!a || b.gain > a.gain ? b : a), null);
      const seed = crop.seeds.find(row => Number.isFinite(row.trade_value) && row.trade_value > 0);
      const seedCost = seed ? seed.trade_value * Math.max(1, seed.uses || 1) : 0;
      const rate = Number.isFinite(crop.seed_rate) ? clamp(crop.seed_rate, 0, 1) : 0;
      return {gain, extra, best, seedCost, net: gain + extra - seedCost,
        netExpected: gain + extra - seedCost * (1 - rate)};
    }
    function renderCrops(state) {
      const body = $("value-crops").querySelector("tbody");
      body.replaceChildren();
      const plantableOnly = $("value-plantable").checked;
      const planter = model.planters.find(row => String(row.id) === choice.planter) || null;
      const view = model.crops.map(crop => {
        const problems = window.Planting.problems(crop, state);
        const money = cropNet(crop, cropBonusMap());
        const perHour = crop.seconds > 0 ? money.netExpected * 3600 / crop.seconds : null;
        return {crop, problems, money, perHour};
      }).filter(row => !plantableOnly || !row.problems.length);
      view.sort((a, b) => cropSort === "hour"
        ? (b.perHour ?? -Infinity) - (a.perHour ?? -Infinity) || (a.crop.seconds || 0) - (b.crop.seconds || 0)
        : (b.money.netExpected ?? -Infinity) - (a.money.netExpected ?? -Infinity) || (a.crop.seconds || 0) - (b.crop.seconds || 0));
      $("value-crop-summary").textContent = tr("共 {count} 种作物{note}", {count: view.length,
        note: planter ? " · " + tr("容器 {name}，容量 {capacity}", {name: planter.name, capacity: planter.capacity}) : ""});
      for (const row of view) {
        const node = document.createElement("tr");
        if (row.problems.length) node.classList.add("value-unfit");
        const harvest = row.crop.harvest.map(item => `${image(item, 24)}×${item.amount}`).join(" ");
        const seed = row.crop.seeds[0];
        const bonus = row.money.best;
        node.innerHTML = `<td><div class="value-cell-name">${image(row.crop)}<div><strong>${escape(row.crop.name)}</strong>` +
          `<small>${escape(row.problems.join("、") || tr("可种"))}</small></div></div></td>` +
          `<td>${harvest}</td>` +
          `<td>${bonus ? `${escape(tr(bonus.name))}<small class="value-bonus">+${fmt(bonus.gain)}</small>` : "—"}</td>` +
          `<td>${seed ? escape(name(seed)) : "—"}</td>` +
          `<td>${Number.isFinite(row.crop.seed_rate) ? `${Math.round(row.crop.seed_rate * 100)}%` : "—"}</td>` +
          `<td>${fmt(row.money.seedCost)}</td><td><strong>${fmt(row.money.netExpected)}</strong></td>` +
          `<td>${fmt(row.perHour)}</td><td>${row.crop.seconds ? fmt(row.crop.seconds / 3600) : "—"}</td>` +
          `<td>${row.crop.size ?? "—"}</td>`;
        body.append(node);
      }
    }

    renderCatalog();
    renderBasket();
    if (current) renderCrops(current());
    schedule();
  })();
})();
