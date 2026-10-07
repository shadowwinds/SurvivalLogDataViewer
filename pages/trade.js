(() => {
  "use strict";
  const host = typeof window === "undefined" ? globalThis : window, f = Math.fround;
  const clamp = (v, lo, hi) => Math.min(hi, Math.max(lo, Number(v) || 0));
  const uses = item => Math.max(1, item.use_times || 0);
  const cells = item => Array.isArray(item.size) && item.size.length === 2 &&
    item.size.every(n => Number.isInteger(n) && n > 0) ? item.size[0] * item.size[1] : null;
  const counts = ids => { const r = {}; for (const id of ids) r[id] = (r[id] || 0) + 1; return r; };
  function options(input, rules) {
    return {...input, appraisal: f(clamp(input.appraisal, 0, 1000) / 100),
      discount: f(clamp((Number(input.discount) || 0) + rules.deal_discount, 0, Math.max(0, rules.deal_discount_max))),
      boost: f(Math.max(0, rules.demand_boost_max > 0 ? Math.min(Number(input.boost) || 0, rules.demand_boost_max) : Number(input.boost) || 0)),
      demand: input.demand || [], absent: input.absent || {}, camp: Boolean(input.camp)};
  }
  function destinations(model, selection, excluded = []) {
    if (selection === "contact") return [{id: "contact", name: "陌生人 / 联系人", contact: true, items: []}];
    return selection === "all" ? model.points.filter(p => !excluded.includes(p.id)) : model.points.filter(p => String(p.id) === String(selection));
  }
  function rates(item, point, o, rules) {
    const rejected = !point.contact && !o.absent[`${point.id}:${item.id}`] &&
      point.items.some(row => row.id === item.id && (row.count == null || row.count > 0));
    const own = !point.contact && item.cat === point.half_value_cat ? rules.self_stock_rate : 1;
    const sell = !point.contact && item.sell_rate > 0 && item.sell_rate < 1 ? item.sell_rate : 1;
    const boost = point.contact && o.demand.includes(item.cat) ? o.boost : 0;
    return {rejected, own, sell, boost, scale: f(own * sell), coefficient: f(f(1 + boost) + o.appraisal)};
  }
  function given(item, quantity, remaining, point, o, rules) {
    const rate = rates(item, point, o, rules);
    if (rate.rejected || !(quantity > 0) || !(remaining > 0)) return 0;
    return f(f(f(quantity * item.trade_value) * f(f(remaining) * uses(item))) * f(rate.scale * rate.coefficient));
  }
  function takeValue(item, point, o, rules) {
    const price = !point.contact && o.camp && item.cat === 2 ?
      Math.max(item.trade_value, Math.ceil(f(item.trade_value * rules.camp_medicine_rate))) : item.trade_value;
    return price * uses(item);
  }
  const availableTarget = (target, point, o) => !target || point.contact ||
    point.items.some(i => i.id === target.id && i.count > 0 && !o.absent[`${point.id}:${i.id}`]);
  function cargo(model, basket, input) {
    const o = options(input, model.rules), target = model.items.find(i => i.id === Number(input.target));
    const points = destinations(model, input.destination, input.excluded).filter(p => availableTarget(target, p, o));
    const rows = [];
    for (const item of model.items) {
      const b = basket[item.id], fromStock = input.cargoScope !== "all";
      if (fromStock && !(b?.quantity > 0 && b.remaining > 0)) continue;
      const remaining = fromStock ? b.remaining / 100 : 1, area = cells(item);
      let best = null;
      for (const point of points) {
        const value = given(item, 1, remaining, point, o, model.rules);
        if (!(value > 0)) continue;
        const required = target ? Math.max(0, takeValue(target, point, o, model.rules) * clamp(input.targetCount, 1, 9999) - o.discount) : null;
        let needed = null;
        if (required !== null) {
          // Check whole-item counts against the same float32 valuation used for the deal.
          let lo = 0, hi = Math.max(1, Math.ceil(required / value) * 2 + 2);
          while (lo < hi) {
            const mid = Math.floor((lo + hi) / 2);
            if (given(item, mid, remaining, point, o, model.rules) + .001 >= required) hi = mid;
            else lo = mid + 1;
          }
          needed = lo;
        }
        const row = {item, point, value, area, density: area === null ? null : value / area,
          quantity: fromStock ? b.quantity : null, remaining: remaining * 100, needed,
          neededCells: needed === null || area === null ? null : needed * area};
        if (!best || (target && row.needed < best.needed) ||
            ((!target || row.needed === best.needed) && row.value > best.value)) best = row;
      }
      if (best) rows.push(best);
    }
    return rows.sort((a, b) => (b.density ?? -Infinity) - (a.density ?? -Infinity) || b.value - a.value || a.item.id - b.item.id);
  }
  function comparison(model, basket, input) {
    const o = options(input, model.rules), byId = new Map(model.items.map(i => [i.id, i]));
    const target = byId.get(Number(input.target));
    return destinations(model, input.destination, input.excluded).map(point => {
      const lines = Object.entries(basket).filter(([id, b]) => byId.has(Number(id)) && b.quantity > 0 && b.remaining > 0).map(([id, b]) => {
        const item = byId.get(Number(id));
        return {item, ...rates(item, point, o, model.rules), quantity: b.quantity, remaining: b.remaining,
          value: given(item, b.quantity, b.remaining / 100, point, o, model.rules)};
      });
      const value = lines.reduce((sum, row) => f(sum + row.value), 0);
      const available = availableTarget(target, point, o);
      const unit = target ? takeValue(target, point, o, model.rules) : null;
      const required = unit === null ? null : Math.max(0, unit * clamp(input.targetCount, 1, 9999) - o.discount);
      return {point, lines, value, available, required, unit,
        maximum: available && unit > 0 ? Math.floor((value + o.discount + .001) / unit) : null,
        rejected: lines.filter(row => row.rejected).length};
    }).sort((a, b) => Number(b.available) - Number(a.available) ||
      (target ? (b.maximum ?? -1) - (a.maximum ?? -1) : b.value - a.value) || b.value - a.value || String(a.point.id).localeCompare(String(b.point.id)));
  }
  function processing(model, basket, input) {
    const o = options(input, model.rules), byId = new Map(model.items.map(i => [i.id, i]));
    const stock = Object.fromEntries(model.items.map(item => [item.id, input.scope === "all" ? 999999 :
      Math.floor((basket[item.id]?.quantity || 0) * uses(item) * (basket[item.id]?.remaining ?? 100) / 100 + 1e-7)]));
    const results = new Map(), points = destinations(model, input.destination, input.excluded);
    const opportunity = new Map(model.items.map(item => {
      const accepted = points.filter(point => !rates(item, point, o, model.rules).rejected);
      return [item.id, {fallback: !accepted.length, value: accepted.length ?
        Math.max(...accepted.map(point => given(item, 1, 1 / uses(item), point, o, model.rules))) : item.trade_value}];
    }));
    const objective = row => input.sort === "density" ? row.density : input.sort === "ratio" ? row.ratio : input.sort === "total" && row.total !== null ? row.total : row.gain;
    function candidate(kind, recipe, requirements, outputs, point, extra = {}) {
      if (Object.entries(requirements).some(([id, n]) => !byId.has(Number(id)) || stock[id] < n) ||
          outputs.some(id => !byId.has(id) || rates(byId.get(id), point, o, model.rules).rejected)) return null;
      let cost = 0, fallback = false;
      for (const [id, n] of Object.entries(requirements)) {
        const costLine = opportunity.get(Number(id));
        fallback ||= costLine.fallback;
        cost += costLine.value * n;
      }
      const outputCounts = counts(outputs);
      const value = Object.entries(outputCounts).reduce((sum, [id, n]) => sum + given(byId.get(Number(id)), n, 1, point, o, model.rules), 0);
      const outputAreas = Object.entries(outputCounts).map(([id, n]) => cells(byId.get(Number(id))) === null ? null : cells(byId.get(Number(id))) * n);
      const outputCells = outputAreas.every(v => v !== null) ? outputAreas.reduce((sum, v) => sum + v, 0) : null;
      if (!(cost > 0)) return null;
      const gain = value - cost, batches = input.scope === "all" ? null :
        Math.min(...Object.entries(requirements).map(([id, n]) => Math.floor(stock[id] / n)));
      return {key: `${kind}:${recipe.id}`, kind, id: recipe.id, name: recipe.name, point, requirements, outputCounts,
        cost, value, gain, ratio: gain / cost, density: outputCells > 0 ? value / outputCells : null, outputCells,
        batches, total: batches === null ? null : gain * batches, fallback, ...extra};
    }
    function keep(row) {
      if (!row || !Number.isFinite(objective(row))) return;
      const previous = results.get(row.key);
      if (!previous || objective(row) > objective(previous) + 1e-6 ||
          (Math.abs(objective(row) - objective(previous)) <= 1e-6 && (row.gain > previous.gain || row.cost < previous.cost))) results.set(row.key, row);
    }
    for (const point of points) {
      if (input.kind !== "cook") for (const recipe of model.crafts) {
        if (recipe.level <= input.craftLevel) keep(candidate("craft", recipe, counts(recipe.inputs), recipe.outputs, point, {canFail: recipe.can_fail}));
      }
      if (input.kind === "craft" || !model.cooking?.model || !host.Cooking) continue;
      const dishes = new Map(model.dishes.map(row => [row.id, row]));
      // Keep all signatures so a specific recipe still takes priority over a generic combination.
      const planned = host.Cooking.plan(model.cooking.entries, model.cooking.ingredients, stock, input.quality, 0, 0, model.cooking.model,
        {ingredientCost: input.sort === "total" ? null : item => opportunity.get(item.id)?.value ?? Infinity,
          score: (total, ingredients, entry, product) => {
          const recipe = dishes.get(entry.id);
          if (!recipe || !recipe.level || recipe.level > input.cookLevel) return NaN;
          const row = candidate("cook", recipe, counts(ingredients.map(i => i.id)), [product.id], point);
          return row ? input.sort === "density" ? row.gain : objective(row) : NaN;
        }});
      for (const entry of model.cooking.entries) {
        const output = planned.get(entry.key), recipe = dishes.get(entry.id);
        if (output && recipe?.level && recipe.level <= input.cookLevel) keep(candidate("cook", recipe,
          counts(output.ingredients.map(i => i.id)), [output.product.id], point, {servings: output.servings, seconds: recipe.seconds}));
      }
    }
    return [...results.values()];
  }
  host.Trade = {uses, cells, options, rates, given, takeValue, cargo, comparison, processing};
  if (typeof document === "undefined") return;

  (async () => {
    await host.I18n?.ready;
    const element = document.getElementById("trade-data");
    if (!element) return;
    const model = JSON.parse(element.textContent);
    if (model.format_version !== 2) return;
    const $ = id => document.getElementById(id), tr = (s, v) => host.I18n?.text(s, v) || s;
    const escape = value => String(value ?? "").replace(/[&<>"']/g, ch => ({"&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;"}[ch]));
    const normalized = value => String(value).replace(/[\u200b\ufeff]/g, "").trim().toLocaleLowerCase();
    const fmt = v => Number.isFinite(v) ? v.toLocaleString(host.I18n?.locale || "zh-CN", {maximumFractionDigits: 2}) : "—";
    const byId = new Map(model.items.map(i => [i.id, i])), name = i => tr(i.name);
    const category = cat => model.categories[cat] ? tr(model.categories[cat]) : tr("其他物品 · 分类 {id}", {id: cat});
    const image = i => i.icon ? `<img src="../${escape(i.icon)}" width="36" height="36" loading="lazy" alt="">` : "";
    const storageKey = `survival-log-trade:${model.game_version}`;
    let basket = {}, absent = {}, excluded = [], rows = [], limit = 20, cargoLimit = 20, job = 0, timer, worker;
    try {
      const saved = JSON.parse(localStorage.getItem(storageKey) || "{}");
      for (const [id, b] of Object.entries(saved.basket || {})) if (byId.has(Number(id)) && b && b.quantity > 0)
        basket[id] = {quantity: Math.floor(clamp(b.quantity, 0, 9999)), remaining: clamp(b.remaining, 0, 100)};
      absent = saved.absent && typeof saved.absent === "object" ? saved.absent : {};
      excluded = Array.isArray(saved.excluded) ? saved.excluded : [];
    } catch { /* Optional persistence. */ }
    function save() { try { localStorage.setItem(storageKey, JSON.stringify({basket, absent, excluded})); } catch { /* Optional persistence. */ } }
    function addOption(select, value, label) {
      const option = document.createElement("option"); option.value = value; option.textContent = tr(label); select.append(option);
    }
    for (const cat of [...new Set(model.items.map(i => i.cat))].sort((a, b) => a - b)) {
      addOption($("stock-cat"), cat, category(cat));
      addOption($("cargo-cat"), cat, category(cat));
      if (cat > 0) {
        const label = document.createElement("label"), check = document.createElement("input"); check.type = "checkbox"; check.value = cat;
        label.append(check, document.createTextNode(category(cat))); $("trade-demand").append(label);
      }
    }
    for (const p of model.points) {
      addOption($("trade-destination"), p.id, p.name);
      const label = document.createElement("label"), check = document.createElement("input");
      check.type = "checkbox"; check.value = p.id; check.checked = !excluded.includes(p.id);
      label.append(check, document.createTextNode(name(p))); $("trade-enabled-points").append(label);
    }
    const shelfIds = new Set(model.points.flatMap(p => p.items.map(i => i.id)));
    function targetOptions() {
      const selected = $("trade-target").value;
      $("trade-target").replaceChildren(); addOption($("trade-target"), "", "只比较交出价值");
      const phrase = $("trade-target-search").value.trim().toLocaleLowerCase();
      const items = model.items.filter(i => ($("trade-destination").value === "contact" || shelfIds.has(i.id)) &&
        (String(i.id) === selected || !phrase || `${i.name} ${host.I18n?.english(i.name)} ${i.id}`.toLocaleLowerCase().includes(phrase)));
      for (const i of items.sort((a, b) => name(a).localeCompare(name(b), host.I18n?.locale))) addOption($("trade-target"), i.id, name(i));
      $("trade-target").value = items.some(i => String(i.id) === selected) ? selected : "";
    }
    model.rules.demand_boosts.forEach((boost, index) => addOption($("trade-urgency"), boost, tr("需求 {level} · 加价 {rate}%", {level: index + 1, rate: fmt(boost * 100)})));
    $("trade-discount").max = model.rules.deal_discount_max;
    function input() {
      return {destination: $("trade-destination").value, target: $("trade-target").value,
        targetCount: Math.floor(clamp($("trade-target-count").value, 1, 9999)), appraisal: $("trade-appraisal").value,
        discount: $("trade-discount").value, camp: $("trade-camp").checked, boost: $("trade-urgency").value, absent, excluded,
        demand: [...$("trade-demand").querySelectorAll("input:checked")].map(i => Number(i.value)),
        cargoScope: $("cargo-scope").value,
        scope: $("process-scope").value, kind: $("process-kind").value, cookLevel: Number($("process-cook-level").value),
        craftLevel: Number($("process-craft-level").value), quality: $("process-quality").value, sort: $("process-sort").value};
    }
    const sizeText = item => cells(item) === null ? tr("占格未提供") :
      tr("{width}×{height} · {cells} 格", {width: item.size[0], height: item.size[1], cells: cells(item)});
    const baseDensityText = item => tr("每格基值 {value}", {value: fmt(cells(item) ? item.trade_value * uses(item) / cells(item) : null)});
    function catalog() {
      const phrase = $("stock-search").value.trim().toLocaleLowerCase(), cat = $("stock-cat").value;
      const items = model.items.filter(i => (!cat || String(i.cat) === cat) &&
        (!phrase || `${i.name} ${host.I18n?.english(i.name)} ${i.id}`.toLocaleLowerCase().includes(phrase)))
        .sort((a, b) => Number(shelfIds.has(b.id)) - Number(shelfIds.has(a.id)) || a.id - b.id);
      $("stock-catalog").innerHTML = items.slice(0, 24).map(i => `<button type="button" data-add="${i.id}" title="${escape(tr("加入待交换清单"))}">${image(i)}<span>${escape(name(i))}<small>${escape(category(i.cat))} · ${fmt(i.trade_value * uses(i))}</small><small>${escape(sizeText(i))} · ${escape(baseDensityText(i))}</small></span><b aria-hidden="true">+</b></button>`).join("") || `<p>${tr("没有匹配的物资，试试名称或 ID。")}</p>`;
      $("stock-status").textContent = tr("找到 {count} 种，展示前 24 种；可搜索缩小范围。", {count: fmt(items.length)});
    }
    function basketHtml() {
      $("stock-basket").innerHTML = Object.entries(basket).map(([id, b]) => {
        const item = byId.get(Number(id));
        return `<div class="trade-basket-row">${image(item)}<span>${escape(name(item))}<small>${escape(tr("完整一件基值"))} ${fmt(item.trade_value * uses(item))}</small><small>${escape(sizeText(item))} · ${escape(baseDensityText(item))}</small></span>
          <label>${tr("件 / 包")}<input type="number" min="0" max="9999" step="1" value="${b.quantity}" data-quantity="${id}" aria-label="${escape(name(item) + ' ' + tr('件 / 包'))}"></label>
          <label>${tr("剩余 / %")}<input type="number" min="0" max="100" step="1" value="${b.remaining}" data-remaining="${id}" aria-label="${escape(name(item) + ' ' + tr('剩余 / %'))}"></label>
          <button type="button" data-remove="${id}" aria-label="${escape(tr('移除') + ' ' + name(item))}">×</button></div>`;
      }).join("") || `<p class="trade-empty">${tr("从上方添加物资，先比较直接交换。")}</p>`;
    }
    function direct() {
      const o = input(), result = comparison(model, basket, o), best = result[0], any = Object.values(basket).some(b => b.quantity > 0 && b.remaining > 0);
      $("trade-contact").hidden = o.destination !== "contact"; $("trade-camp").disabled = o.destination === "contact";
      $("trade-point-settings").hidden = o.destination !== "all";
      cargoHtml(o);
      if (!best || !any) {
        $("trade-summary").textContent = tr(!best ? "先选择至少一个已解锁的据点。" : "添加物资后，这里会比较收货价值与拒收原因。");
        $("trade-comparison").replaceChildren(); $("trade-breakdown").replaceChildren(); return;
      }
      const target = byId.get(Number(o.target));
      $("trade-summary").innerHTML = `<span>${tr(target ? "目标物品下的优先交易对象" : "交出价值最高的对象")}</span><strong>${escape(tr(target && !best.available ? "所选范围没有目标物品" : best.point.name))}</strong><p>${tr("清单交出估值")} <b>${fmt(best.value)}</b>${target ? ` · ${escape(name(target))} ${tr("估值上限")} <b>${fmt(best.maximum)}</b> ${tr("件 / 包")}` : ""}</p>`;
      if (target && best.available && best.value > best.required + .001) {
        const note = document.createElement("p");
        note.textContent = tr("清单超出目标 {value} 价值点，可以减少交出数量。", {value: fmt(best.value - best.required)});
        $("trade-summary").append(note);
      }
      $("trade-comparison").innerHTML = `<div class="table-scroll"><table class="trade-table"><thead><tr><th>${tr("交易对象")}</th><th>${tr("交出估值")}</th><th>${tr("拒收种类")}</th>${target ? `<th>${tr("目标交换")}</th>` : ""}</tr></thead><tbody>${result.map(row => `<tr><th>${escape(name(row.point))}</th><td class="num">${fmt(row.value)}</td><td class="num">${fmt(row.rejected)}</td>${target ? `<td>${row.available ? tr(row.value + .001 >= row.required ? "估值够换 {count} 件" : "估值还差 {value}", {count: fmt(o.targetCount), value: fmt(Math.max(0, row.required - row.value))}) : tr("配置货架无货，无法估算换入")}</td>` : ""}</tr>`).join("")}</tbody></table></div>`;
      $("trade-breakdown").innerHTML = `<details><summary>${tr("查看首选对象的逐项计价")}</summary>${best.lines.map(row => `<div class="trade-line"><span>${escape(name(row.item))}</span><b>${fmt(row.value)}</b><small>${row.rejected ? tr("当前货架已有同物品，按拒收计算；售空后可在下方校正。") :
        `${tr("基值")} ${fmt(row.item.trade_value)} × ${fmt(uses(row.item))} × ${fmt(row.quantity)} × ${fmt(row.remaining)}% · ${tr("同类折价")} ${fmt(row.own)} · ${tr("物品折价")} ${fmt(row.sell)} · ${tr("需求加成")} ${fmt(row.boost * 100)}% · ${tr("鉴价加成")} ${fmt(Number(o.appraisal) || 0)}%`}</small></div>`).join("")}</details>`;
    }
    function cargoHtml(o = input()) {
      const phrase = $("cargo-search").value.trim().toLocaleLowerCase(), cat = $("cargo-cat").value;
      const ranked = cargo(model, basket, o).filter(row => (!cat || String(row.item.cat) === cat) &&
        (!phrase || `${row.item.name} ${host.I18n?.english(row.item.name)} ${row.item.id}`.toLocaleLowerCase().includes(phrase)));
      if ($("cargo-sort").value === "value") ranked.sort((a, b) => b.value - a.value || (b.density ?? -Infinity) - (a.density ?? -Infinity) || a.item.id - b.item.id);
      $("cargo-status").textContent = tr("找到 {count} 种可收货物资；每种列出比较范围内的优先交易对象。", {count: fmt(ranked.length)});
      const hasTarget = Boolean(o.target);
      $("cargo-results").innerHTML = ranked.length ? `<div class="table-scroll"><table class="trade-table"><thead><tr><th>${tr("物资")}</th><th>${tr("每格交出价值")}</th><th>${tr("占格")}</th><th>${tr("单件交出估值")}</th><th>${tr("交易对象")}</th>${hasTarget ? `<th>${tr("只用此物换目标")}</th>` : ""}</tr></thead><tbody>${ranked.slice(0, cargoLimit).map(row => `<tr>
        <th><div class="cargo-name">${image(row.item)}<span>${escape(name(row.item))}<small>${row.quantity === null ? tr("完整一件") : tr("清单 {quantity} 件 · 剩余 {remaining}%", {quantity: fmt(row.quantity), remaining: fmt(row.remaining)})}</small></span></div></th>
        <td class="num cargo-density">${fmt(row.density)}</td><td class="cargo-size">${escape(sizeText(row.item))}</td><td class="num">${fmt(row.value)}</td><td>${escape(name(row.point))}</td>
        ${hasTarget ? `<td class="cargo-needed">${tr("需 {count} 件 · {cells} 格", {count: fmt(row.needed), cells: fmt(row.neededCells)})}<small>${row.quantity === null ? tr("备料参考") : tr(row.quantity >= row.needed ? "清单余量够换" : "清单余量不够")}</small></td>` : ""}</tr>`).join("")}</tbody></table></div>` : `<p class="trade-empty">${tr("没有可比较的物资。可添加清单、切换“全部物品”，或检查目标是否有货。")}</p>`;
      $("cargo-more").hidden = ranked.length <= cargoLimit; host.I18n?.apply($("cargo-results"));
    }
    const list = quantities => Object.entries(quantities).map(([id, n]) => `${name(byId.get(Number(id)))} × ${fmt(n)}`).join("、");
    const signed = value => (value >= 0 ? "+" : "") + fmt(value);
    function processHtml() {
      const phrase = $("process-search").value.trim().toLocaleLowerCase(), sort = $("process-sort").value;
      const filtered = rows.filter(row => (!$("process-positive").checked || row.gain > .001) && (!phrase ||
        `${row.name} ${host.I18n?.english(row.name)} ${list(row.requirements)} ${list(row.outputCounts)}`.toLocaleLowerCase().includes(phrase)))
        .sort((a, b) => (b[sort] ?? -Infinity) - (a[sort] ?? -Infinity) || b.gain - a.gain || a.cost - b.cost || a.id - b.id);
      $("process-status").textContent = tr("找到 {count} 个独立方案；排序会重新选择原料组合和交易对象。", {count: fmt(filtered.length)});
      $("process-results").innerHTML = filtered.slice(0, limit).map((row, index) => `<article class="process-row"><div class="process-rank">${String(index + 1).padStart(2, "0")}</div>
        <div class="process-recipe"><span class="process-kind">${tr(row.kind === "cook" ? "烹饪" : "制造")}</span><h3><a href="../guide/${row.kind === 'cook' ? 'dish' : 'craft'}/${row.id}/">${escape(tr(row.name))}</a></h3>
        <p>${escape(list(row.requirements))} <small>${tr("次用量")}</small> → ${escape(list(row.outputCounts))} <small>${tr("完整件 / 锅")}</small></p>
        <p>${tr("交给")} ${escape(name(row.point))}${row.seconds ? ` · ${tr("基础烹饪 {minutes} 分钟", {minutes: fmt(row.seconds / 60)})}` : ""}</p>
        <p>${tr("原料直接交换估值")} ${fmt(row.cost)} → ${tr("成品交出估值")} ${fmt(row.value)}</p>
        <p>${tr("成品共 {cells} 格 · 每格交出价值 {value}", {cells: fmt(row.outputCells), value: fmt(row.density)})}</p>
        ${row.fallback ? `<p class="process-caution">${tr("含拒收原料，成本已按原始基值保守计入。")}</p>` : ""}
        ${row.canFail ? `<p class="process-caution">${tr("此配方有失败产物；这里比较普通成功结果。")}</p>` : ""}
        <details><summary>${tr("查看余量与分份")}</summary>
        <p>${row.batches === null ? tr("备料参考，未按现有库存限制次数。") : tr("这组余量最多加工 {count} 次，总增值 {value}。", {count: fmt(row.batches), value: fmt(row.total)})}</p>
        ${row.servings ? `<p>${tr("食用分份")} ${fmt(row.servings)} · ${tr("整锅交易不额外乘分份次数。")}</p>` : ""}</details></div>
        <div class="process-gain"><span>${tr(sort === "density" ? "成品每格价值" : sort === "ratio" ? "原料增值" : sort === "total" ? "余量总增值" : "每次加工增值")}</span><strong>${sort === "density" ? fmt(row.density) : sort === "ratio" ? fmt(row.ratio * 100) + "%" : signed(row[sort] ?? row.gain)}</strong><small>${tr(sort === "gain" ? "原料增值" : "每次加工增值")} ${sort === "gain" ? fmt(row.ratio * 100) + "%" : signed(row.gain)}</small>${row.batches !== null ? `<small>${tr("余量可加工 {count} 次", {count: fmt(row.batches)})}</small>` : ""}</div></article>`).join("") || `<p class="trade-empty">${tr("没有符合条件的方案。可补齐原料、切换等级，或关闭“只看有增值”查看亏损方案。")}</p>`;
      $("process-more").hidden = filtered.length <= limit; host.I18n?.apply($("process-results"));
    }
    function receive(message) {
      if (message.job !== job) return;
      if (message.error) { $("process-status").textContent = tr("加工计算失败，请重新加载页面。"); return; }
      rows = message.rows; limit = 20; processHtml();
    }
    function startWorker() {
      const result = new Worker(new URL("../trade-worker.js", location.href));
      result.onmessage = e => receive(e.data);
      result.onerror = () => { result.terminate(); worker = null; $("process-status").textContent = tr("加工计算失败，请重新加载页面。"); };
      return result;
    }
    try { worker = startWorker(); } catch { /* The same engine can run without workers. */ }
    function recalculate() {
      save(); direct(); clearTimeout(timer); job += 1;
      rows = []; $("process-results").replaceChildren(); $("process-more").hidden = true;
      $("process-status").textContent = tr("正在比较加工方案…");
      const request = {job, model, basket, input: input()};
      if (request.input.scope === "stock" && !Object.values(basket).some(b => b.quantity > 0 && b.remaining > 0)) { receive({job, rows: []}); return; }
      timer = setTimeout(() => {
        // Cancel obsolete exhaustive searches so the latest conditions do not wait behind them.
        if (worker) { worker.terminate(); worker = startWorker(); worker.postMessage(request); }
        else { try { receive({job: request.job, rows: processing(model, basket, request.input)}); }
          catch { receive({job: request.job, error: true}); } }
      }, 250);
    }
    $("stock-catalog").addEventListener("click", event => {
      const button = event.target.closest("[data-add]"); if (!button) return;
      const id = button.dataset.add;
      basket[id] ||= {quantity: 0, remaining: 100}; basket[id].quantity = Math.min(9999, basket[id].quantity + 1);
      basketHtml(); recalculate();
    });
    $("stock-basket").addEventListener("input", event => {
      const id = event.target.dataset.quantity || event.target.dataset.remaining; if (!id) return;
      basket[id][event.target.dataset.quantity ? "quantity" : "remaining"] = event.target.dataset.quantity ?
        Math.floor(clamp(event.target.value, 0, 9999)) : clamp(event.target.value, 0, 100);
      recalculate();
    });
    $("stock-basket").addEventListener("click", event => {
      const button = event.target.closest("[data-remove]"); if (!button) return;
      delete basket[button.dataset.remove]; basketHtml(); recalculate();
    });
    $("stock-clear").addEventListener("click", () => { basket = {}; basketHtml(); recalculate(); });
    $("stock-import").addEventListener("click", () => {
      let added = 0; const errors = [];
      for (const [index, line] of $("stock-bulk").value.split(/\r?\n/).entries()) {
        if (!line.trim()) continue;
        const parts = line.trim().split(/[,，\t]/).map(s => s.trim()), [term, quantity, remaining = "100"] = parts;
        const matches = model.items.filter(i => String(i.id) === term || normalized(i.name) === normalized(term) || normalized(name(i)) === normalized(term));
        if (parts.length < 2 || parts.length > 3 || !/^\d+$/.test(quantity) || Number(quantity) > 9999 ||
            !/^\d+(?:\.\d+)?$/.test(remaining) || Number(remaining) > 100 || matches.length !== 1) {
          errors.push(tr("第 {line} 行未登记：请检查名称、ID 和数量。", {line: index + 1})); continue;
        }
        basket[matches[0].id] = {quantity: Number(quantity), remaining: Number(remaining)}; added += 1;
      }
      $("stock-import-status").textContent = tr("已登记 {count} 行。", {count: added}) + " " + errors.join(" ");
      basketHtml(); recalculate();
    });
    $("stock-example").addEventListener("click", () => {
      for (const [id, quantity] of [[20004, 10], [2103, 2]]) if (byId.has(id) && !basket[id]) basket[id] = {quantity, remaining: 100};
      basketHtml(); recalculate();
    });
    for (const id of ["stock-search", "stock-cat"]) $(id).addEventListener("input", catalog);
    $("trade-target-search").addEventListener("input", () => { targetOptions(); direct(); });
    $("trade-enabled-points").addEventListener("change", () => {
      excluded = [...$("trade-enabled-points").querySelectorAll("input:not(:checked)")].map(i => Number(i.value)); recalculate();
    });
    for (const id of ["trade-destination", "trade-appraisal", "trade-discount", "trade-camp", "trade-urgency", "trade-demand", "process-scope", "process-kind", "process-cook-level", "process-craft-level", "process-quality"]) $(id).addEventListener("change", () => {
      if (id === "trade-destination") targetOptions();
      $("process-sort").querySelector('[value="total"]').disabled = $("process-scope").value === "all";
      if ($("process-scope").value === "all" && $("process-sort").value === "total") $("process-sort").value = "gain";
      recalculate();
    });
    for (const id of ["trade-target", "trade-target-count"]) $(id).addEventListener("input", direct);
    for (const id of ["cargo-scope", "cargo-search", "cargo-cat", "cargo-sort"]) $(id).addEventListener("input", () => { cargoLimit = 20; cargoHtml(); });
    $("cargo-more").addEventListener("click", () => { cargoLimit += 20; cargoHtml(); });
    $("process-sort").addEventListener("change", recalculate);
    for (const id of ["process-search", "process-positive"]) $(id).addEventListener("input", () => { limit = 20; processHtml(); });
    $("process-more").addEventListener("click", () => { limit += 20; processHtml(); });
    for (const check of document.querySelectorAll("[data-absent-point]")) {
      const key = `${check.dataset.absentPoint}:${check.dataset.absentItem}`; check.checked = Boolean(absent[key]);
      check.addEventListener("change", () => { if (check.checked) absent[key] = true; else delete absent[key]; recalculate(); });
    }
    $("shelf-search").addEventListener("input", () => {
      const phrase = $("shelf-search").value.trim().toLocaleLowerCase();
      for (const row of document.querySelectorAll(".trade-point tr[data-name]")) row.hidden = Boolean(phrase) &&
        !`${row.dataset.name} ${host.I18n?.english(row.dataset.name)} ${row.querySelector('[data-absent-item]').dataset.absentItem}`.toLocaleLowerCase().includes(phrase);
    });
    host.addEventListener("languagechange", () => { targetOptions(); catalog(); basketHtml(); direct(); processHtml(); });
    $("trade-planner").hidden = false; targetOptions(); catalog(); basketHtml(); recalculate();
  })();
})();
