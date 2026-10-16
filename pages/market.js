(() => {
  "use strict";

  const host = window;
  const clamp = (value, lo, hi) => Math.min(hi, Math.max(lo, Number(value) || 0));

  (async () => {
    await host.I18n?.ready;
    const data = document.getElementById("trade-data");
    if (!data || !host.Trade) return;
    const model = JSON.parse(data.textContent);
    const $ = id => document.getElementById(id);
    const tr = (text, vars) => host.I18n?.text(text, vars) || text;
    const escape = value => String(value ?? "").replace(/[&<>"']/g, ch =>
      ({"&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;"}[ch]));
    const fmt = value => Number.isFinite(value) ? value.toLocaleString(host.I18n?.locale || "zh-CN", {maximumFractionDigits: 2}) : "—";
    const normalized = value => String(value ?? "").replace(/[\u200b\ufeff]/g, "").trim().toLocaleLowerCase();
    const byId = new Map(model.items.map(item => [item.id, item]));
    const name = item => tr(item?.name || "");
    const category = id => model.categories[id] ? tr(model.categories[id]) : tr("其他物品 · 分类 {id}", {id});
    const whole = item => item.trade_value * host.Trade.uses(item);
    const image = (item, size = 36) => item?.icon ? `<img src="../${escape(item.icon)}" width="${size}" height="${size}" loading="lazy" alt="">` : "";
    const settingsKey = `survival-log-market-trade:${model.game_version}`;
    let settings = {point: String(model.points[0]?.id || ""), destination: "all", absent: {}, excluded: [], demand: [],
      boost: 0, appraisal: 0, discount: 0, camp: false, target: "", targetCount: 1, tab: "direct"};
    try {
      const current = JSON.parse(localStorage.getItem(settingsKey) || "null");
      const legacy = JSON.parse(localStorage.getItem(`survival-log-trade:${model.game_version}`) || "null");
      if (legacy) settings = {...settings, absent: legacy.absent || {}, excluded: legacy.excluded || []};
      if (current) settings = {...settings, ...current};
    } catch { /* Persistence is optional. */ }
    settings.point = String(settings.point || model.points[0]?.id || "");
    settings.absent = settings.absent && typeof settings.absent === "object" ? settings.absent : {};
    settings.excluded = Array.isArray(settings.excluded) ? settings.excluded.map(Number) : [];
    settings.demand = Array.isArray(settings.demand) ? settings.demand.map(Number) : [];
    let basket = host.ValuePlanner?.snapshot().basket || {};
    let cargoLimit = 5;

    function save() {
      try { localStorage.setItem(settingsKey, JSON.stringify(settings)); } catch { /* Persistence is optional. */ }
    }
    function option(select, value, label) {
      const node = document.createElement("option");
      node.value = value; node.textContent = tr(label); select.append(node);
    }

    // ---------- 据点情报 ----------
    for (const point of model.points) option($("market-point"), point.id, point.name);
    if (model.points.some(point => String(point.id) === settings.point)) $("market-point").value = settings.point;
    function selectedPoint() {
      return model.points.find(point => String(point.id) === $("market-point").value) || model.points[0];
    }
    function shelfCategories(point) {
      return [...new Set(point.items.map(item => item.cat))].sort((a, b) => a - b);
    }
    function renderPoint() {
      const point = selectedPoint();
      if (!point) return;
      settings.point = String(point.id); save();
      const offers = (point.offer_cats || []).map(category).join("、") || tr("未分类");
      $("market-point-summary").innerHTML = `<div><span>${escape(tr("当前据点"))}</span><strong>${escape(name(point))}</strong><p>${escape(point.hint ? tr("解锁提示：{hint}", {hint: point.hint}) : tr("没有额外解锁提示"))}</p></div>` +
        `<dl><div><dt>${escape(tr("折价类别"))}</dt><dd>${escape(category(point.half_value_cat))}</dd></div><div><dt>${escape(tr("货架分类"))}</dt><dd>${escape(offers)}</dd></div><div><dt>${escape(tr("配置商品"))}</dt><dd>${fmt(point.items.length)}</dd></div></dl>` +
        `<button type="button" id="market-use-point">${escape(tr("用此据点做规划"))} →</button>`;
      const select = $("market-shelf-cat"), selected = select.value;
      select.replaceChildren(); option(select, "", "全部类别");
      for (const cat of shelfCategories(point)) option(select, cat, category(cat));
      select.value = [...select.options].some(item => item.value === selected) ? selected : "";
      $("market-use-point").addEventListener("click", () => {
        $("trade-destination").value = String(point.id);
        settings.destination = String(point.id); save();
        activate("direct", true); targetOptions(); direct();
      });
      renderShelf();
    }
    function renderShelf() {
      const point = selectedPoint();
      if (!point) return;
      const phrase = normalized($("market-shelf-search").value), cat = $("market-shelf-cat").value;
      const rows = point.items.filter(item => (!cat || String(item.cat) === cat) &&
        (!phrase || normalized(`${item.name} ${host.I18n?.english(item.name)} ${item.id}`).includes(phrase)));
      $("market-shelf-status").textContent = tr("货架共 {total} 种，当前显示 {count} 种。配置数量不是实时库存。", {total: point.items.length, count: rows.length});
      $("market-shelf-body").innerHTML = rows.map(item => {
        const key = `${point.id}:${item.id}`;
        return `<tr><th><div class="cargo-name">${image(item)}<span>${escape(name(item))}<small>ID ${item.id}</small></span></div></th><td><span class="trade-cat">${escape(category(item.cat))}</span></td><td class="num">${fmt(item.count)}</td><td class="num">${fmt(whole(item))}</td><td class="shelf-state"><label><input type="checkbox" data-absent="${key}" ${settings.absent[key] ? "checked" : ""}>${escape(tr("当前无货"))}</label></td></tr>`;
      }).join("") || `<tr><td colspan="5" class="trade-empty">${escape(tr("没有匹配的货架物品"))}</td></tr>`;
      $("market-shelf-body").querySelectorAll("[data-absent]").forEach(check => check.addEventListener("change", () => {
        if (check.checked) settings.absent[check.dataset.absent] = true;
        else delete settings.absent[check.dataset.absent];
        save(); direct();
      }));
      host.I18n?.apply($("market-shelf-body"));
    }
    $("market-point").addEventListener("change", renderPoint);
    $("market-shelf-search").addEventListener("input", renderShelf);
    $("market-shelf-cat").addEventListener("change", renderShelf);

    // ---------- 规划页签 ----------
    const tabs = [...document.querySelectorAll("[data-plan]")];
    function activate(plan, scroll = false) {
      if (!tabs.some(tab => tab.dataset.plan === plan)) plan = "direct";
      settings.tab = plan; save();
      for (const tab of tabs) {
        const selected = tab.dataset.plan === plan;
        tab.setAttribute("aria-selected", String(selected)); tab.tabIndex = selected ? 0 : -1;
        $(tab.getAttribute("aria-controls")).hidden = !selected;
      }
      $("market-plan-context").textContent = contextLabel();
      history.replaceState(null, "", `${location.pathname}${location.search}#plan=${plan}`);
      if (scroll) $("planning").scrollIntoView({behavior: "smooth", block: "start"});
    }
    for (const tab of tabs) tab.addEventListener("click", () => activate(tab.dataset.plan));
    document.querySelector(".market-tabs")?.addEventListener("keydown", event => {
      if (!['ArrowLeft', 'ArrowRight', 'Home', 'End'].includes(event.key)) return;
      event.preventDefault();
      const current = Math.max(0, tabs.indexOf(document.activeElement));
      const next = event.key === 'Home' ? 0 : event.key === 'End' ? tabs.length - 1 :
        (current + (event.key === 'ArrowRight' ? 1 : -1) + tabs.length) % tabs.length;
      activate(tabs[next].dataset.plan); tabs[next].focus();
    });
    const hashPlan = new URLSearchParams(location.hash.replace(/^#/, "")).get("plan");

    // ---------- 直接交换 ----------
    const allCategories = [...new Set(model.items.map(item => item.cat))].sort((a, b) => a - b);
    for (const cat of allCategories) {
      option($("cargo-cat"), cat, category(cat));
      if (cat > 0) {
        const label = document.createElement("label"), check = document.createElement("input");
        check.type = "checkbox"; check.value = cat; check.checked = settings.demand.includes(cat);
        label.append(check, document.createTextNode(category(cat))); $("trade-demand").append(label);
      }
    }
    for (const point of model.points) {
      option($("trade-destination"), point.id, point.name);
      const label = document.createElement("label"), check = document.createElement("input");
      check.type = "checkbox"; check.value = point.id; check.checked = !settings.excluded.includes(point.id);
      label.append(check, document.createTextNode(name(point))); $("trade-enabled-points").append(label);
    }
    model.rules.demand_boosts.forEach((boost, index) => option($("trade-urgency"), boost,
      tr("需求 {level} · 加价 {rate}%", {level: index + 1, rate: fmt(boost * 100)})));
    $("trade-discount").max = model.rules.deal_discount_max;
    if (![...$("trade-destination").options].some(node => node.value === String(settings.destination))) settings.destination = "all";
    for (const [id, value] of [["trade-destination", settings.destination], ["trade-urgency", settings.boost],
      ["trade-appraisal", settings.appraisal], ["trade-discount", settings.discount], ["trade-target-count", settings.targetCount]]) $(id).value = String(value ?? "");
    $("trade-camp").checked = Boolean(settings.camp);
    const shelfIds = new Set(model.points.flatMap(point => point.items.map(item => item.id)));
    function targetOptions() {
      const select = $("trade-target"), previous = String(settings.target || select.value || "");
      const phrase = normalized($("trade-target-search").value), destination = $("trade-destination").value;
      const open = destination === "contact" || destination === "base";
      const rows = model.items.filter(item => (open || shelfIds.has(item.id)) &&
        (String(item.id) === previous || !phrase || normalized(`${item.name} ${host.I18n?.english(item.name)} ${item.id}`).includes(phrase)));
      select.replaceChildren(); option(select, "", "只比较交出价值");
      for (const item of rows.sort((a, b) => name(a).localeCompare(name(b), host.I18n?.locale))) option(select, item.id, name(item));
      select.value = rows.some(item => String(item.id) === previous) ? previous : "";
      settings.target = select.value;
    }
    function input() {
      return {destination: $("trade-destination").value, target: $("trade-target").value,
        targetCount: Math.floor(clamp($("trade-target-count").value, 1, 9999)), appraisal: $("trade-appraisal").value,
        discount: $("trade-discount").value, camp: $("trade-camp").checked, boost: $("trade-urgency").value,
        absent: settings.absent, excluded: settings.excluded,
        demand: [...$("trade-demand").querySelectorAll("input:checked")].map(node => Number(node.value)), cargoScope: $("cargo-scope").value};
    }
    function contextLabel() {
      const destination = $("trade-destination")?.value || settings.destination;
      if (destination === "all") return tr("自动比较所有据点");
      if (destination === "base") return tr("交易基准价值");
      if (destination === "contact") return tr("陌生人 / 联系人");
      return name(model.points.find(point => String(point.id) === destination));
    }
    let valuationKey = "";
    function publishValuation(values) {
      const key = JSON.stringify({destination: values.destination, appraisal: Number(values.appraisal) || 0,
        boost: Number(values.boost) || 0, demand: values.demand, absent: values.absent, excluded: values.excluded});
      if (key === valuationKey) return;
      valuationKey = key;
      const options = host.Trade.options(values, model.rules);
      const points = host.Trade.destinations(model, values.destination, values.excluded);
      const costPerUse = {}, salePerUse = {}, saleWhole = {};
      for (const item of model.items) {
        const accepted = points.filter(point => !host.Trade.rates(item, point, options, model.rules).rejected);
        const perUse = accepted.map(point => host.Trade.given(item, 1, 1 / host.Trade.uses(item), point, options, model.rules));
        const wholeValues = accepted.map(point => host.Trade.given(item, 1, 1, point, options, model.rules));
        salePerUse[item.id] = perUse.length ? Math.max(...perUse) : 0;
        saleWhole[item.id] = wholeValues.length ? Math.max(...wholeValues) : 0;
        costPerUse[item.id] = perUse.length ? salePerUse[item.id] : item.trade_value;
      }
      const detail = {key, label: contextLabel(), cost_per_use: costPerUse, sale_per_use: salePerUse, sale_whole: saleWhole};
      host.MarketPlanner = {valuation: detail};
      host.dispatchEvent(new CustomEvent("marketvaluationchange", {detail}));
    }
    function direct() {
      const values = input(), rows = host.Trade.comparison(model, basket, values), best = rows[0];
      publishValuation(values);
      const any = Object.values(basket).some(entry => entry.quantity > 0 && entry.remaining > 0);
      $("trade-contact").hidden = values.destination !== "contact";
      $("trade-point-settings").hidden = values.destination !== "all";
      $("trade-camp").disabled = values.destination === "contact" || values.destination === "base";
      $("market-plan-context").textContent = contextLabel();
      cargo(values);
      if (!best || !any) {
        $("trade-summary").innerHTML = `<strong>${escape(!best ? tr("没有可比较的据点") : tr("先在“我的物资”登记可投入数量"))}</strong><p>${escape(tr("查据点不需要登记物资；只有规划才会使用清单。"))}</p>`;
        $("trade-comparison").replaceChildren(); $("trade-breakdown").replaceChildren(); return;
      }
      const target = byId.get(Number(values.target));
      $("trade-summary").innerHTML = `<span>${escape(tr(target ? "目标物品下的首选方案" : "当前首选交易对象"))}</span><strong>${escape(name(best.point))}</strong><p>${escape(tr("可投入物资交出估值"))} <b>${fmt(best.value)}</b>${target ? ` · ${escape(name(target))} ${escape(tr("最多可换"))} <b>${fmt(best.maximum)}</b>` : ""}</p>`;
      $("trade-comparison").innerHTML = `<div class="table-scroll"><table class="trade-table"><thead><tr><th>${escape(tr("交易对象"))}</th><th>${escape(tr("交出估值"))}</th><th>${escape(tr("拒收种类"))}</th>${target ? `<th>${escape(tr("目标交换"))}</th>` : ""}</tr></thead><tbody>${rows.slice(0, 10).map(row => `<tr><th>${escape(name(row.point))}</th><td class="num">${fmt(row.value)}</td><td class="num">${fmt(row.rejected)}</td>${target ? `<td>${row.available ? escape(tr("最多 {count} 件", {count: fmt(row.maximum)})) : escape(tr("没有目标货物"))}</td>` : ""}</tr>`).join("")}</tbody></table></div>`;
      $("trade-breakdown").innerHTML = `<details><summary>${escape(tr("查看首选方案逐项计价"))}</summary>${best.lines.map(line => `<div class="trade-line"><span>${escape(name(line.item))}</span><b>${fmt(line.value)}</b><small>${escape(line.rejected ? tr("当前货架已有同物品，按拒收计算") : tr("数量 {quantity} · 剩余 {remaining}%", {quantity: line.quantity, remaining: line.remaining}))}</small></div>`).join("")}</details>`;
      host.I18n?.apply($("trade-comparison"));
    }
    const sizeText = item => host.Trade.cells(item) == null ? tr("占格未提供") : tr("{width}×{height} · {cells} 格", {width: item.size[0], height: item.size[1], cells: host.Trade.cells(item)});
    function cargo(values = input()) {
      const phrase = normalized($("cargo-search").value), cat = $("cargo-cat").value;
      const rows = host.Trade.cargo(model, basket, values).filter(row => (!cat || String(row.item.cat) === cat) &&
        (!phrase || normalized(`${row.item.name} ${host.I18n?.english(row.item.name)} ${row.item.id}`).includes(phrase)));
      if ($("cargo-sort").value === "value") rows.sort((a, b) => b.value - a.value || (b.density ?? -Infinity) - (a.density ?? -Infinity));
      $("cargo-status").textContent = tr("找到 {count} 种可比较物资，先显示前 {shown} 种。", {count: rows.length, shown: Math.min(rows.length, cargoLimit)});
      $("cargo-results").innerHTML = rows.length ? `<div class="table-scroll"><table class="trade-table"><thead><tr><th>${escape(tr("物资"))}</th><th>${escape(tr("每格价值"))}</th><th>${escape(tr("占格"))}</th><th>${escape(tr("单件估值"))}</th><th>${escape(tr("优先对象"))}</th></tr></thead><tbody>${rows.slice(0, cargoLimit).map(row => `<tr><th><div class="cargo-name">${image(row.item)}<span>${escape(name(row.item))}<small>${row.quantity == null ? escape(tr("完整一件")) : escape(tr("可投入 {quantity} 件", {quantity: row.quantity}))}</small></span></div></th><td class="num cargo-density">${fmt(row.density)}</td><td>${escape(sizeText(row.item))}</td><td class="num">${fmt(row.value)}</td><td>${escape(name(row.point))}</td></tr>`).join("")}</tbody></table></div>` : `<p class="trade-empty">${escape(tr("没有可比较的物资"))}</p>`;
      $("cargo-more").hidden = rows.length <= cargoLimit;
    }
    function collectSettings() {
      const values = input();
      settings = {...settings, destination: values.destination, target: values.target, targetCount: values.targetCount,
        appraisal: Number($("trade-appraisal").value) || 0, discount: Number($("trade-discount").value) || 0,
        camp: values.camp, boost: Number(values.boost) || 0, demand: values.demand};
      save();
    }
    $("trade-target-search").addEventListener("input", () => { targetOptions(); direct(); });
    for (const id of ["trade-destination", "trade-urgency", "trade-appraisal", "trade-discount", "trade-camp", "trade-demand"])
      $(id).addEventListener("change", () => { collectSettings(); if (id === "trade-destination") targetOptions(); direct(); });
    for (const id of ["trade-target", "trade-target-count"]) $(id).addEventListener("input", () => { collectSettings(); direct(); });
    $("trade-enabled-points").addEventListener("change", () => {
      settings.excluded = [...$("trade-enabled-points").querySelectorAll("input:not(:checked)")].map(node => Number(node.value)); save(); direct();
    });
    for (const id of ["cargo-scope", "cargo-search", "cargo-cat", "cargo-sort"]) $(id).addEventListener("input", () => { cargoLimit = 5; cargo(); });
    $("cargo-more").addEventListener("click", () => { cargoLimit += 20; cargo(); });
    host.addEventListener("valueinventorychange", event => { basket = event.detail.basket || {}; direct(); });
    host.addEventListener("languagechange", () => { renderPoint(); targetOptions(); direct(); });

    renderPoint(); targetOptions();
    if (settings.target) $("trade-target").value = String(settings.target);
    activate(hashPlan || settings.tab || "direct");
    direct();
  })();
})();
