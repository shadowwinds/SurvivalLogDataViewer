"use strict";
(async () => {
  const i18n = window.I18n;
  await i18n?.ready;
  const data = JSON.parse(document.getElementById("rec-data").textContent);
  const byId = id => document.getElementById("rec-" + id);
  const controls = byId("controls"), settings = byId("settings");
  const labels = {stock: "即食囤货", ingredients: "烹饪备料", dishes: "菜肴推荐", crops: "作物种植", trade: "交易取舍"};
  const parameterNames = Object.keys(window.Supply.defaults), tabs = [...document.querySelectorAll("[data-view]")];
  const escape = value => String(value ?? "").replace(/[&<>"']/g, char => ({"&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;"}[char]));
  const text = (source, variables = {}) => i18n?.text(source, variables) || source.replace(/\{(\w+)\}/g, (_, name) => variables[name] ?? "");
  const format = value => Number.isFinite(value) ? value.toLocaleString(i18n?.locale || "zh-CN", {maximumFractionDigits: 2}) : "—";
  const link = (path, name) => path ? `<a href="../${escape(path)}">${escape(text(name))}</a>` : escape(text(name));
  const stats = values => ["饱食", "心态", "精力", "健康", "生命"].map((name, i) => `${text(name)} ${format(values?.[i])}`).join(" · ");
  const combo = ingredients => {
    const counts = new Map();
    for (const item of ingredients || []) counts.set(item.id, {item, amount: (counts.get(item.id)?.amount || 0) + 1});
    return [...counts.values()].map(({item, amount}) => `${text(item.name)} ×${amount}`).join(" + ");
  };
  let view = "dishes", result = null, signature = "", resultSignature = "", generation = 0, timer, worker;
  try {
    worker = new Worker(new URL("../supply-worker.js", location.href));
    worker.onmessage = event => {
      if (event.data.id !== generation) return;
      byId("status").removeAttribute("aria-busy");
      if (event.data.error) { byId("status").textContent = text("计算未完成，请重新加载页面"); return; }
      result = event.data.result; resultSignature = signature; render();
    };
    worker.onerror = () => { worker?.terminate(); worker = null; signature = ""; compute(); };
  } catch { /* The pure model also works without Workers. */ }
  function planterLabels() {
    const selected = byId("planter").value;
    byId("planter").innerHTML = (data.planters || []).map(p => `<option value="${p.id}">${escape(text(p.name))} · ${p.capacity}</option>`).join("");
    if (selected) byId("planter").value = selected;
  }
  planterLabels();
  function options() {
    const values = {};
    for (const key of parameterNames) {
      const input = byId(key); if (!input) continue;
      if (input.type === "checkbox") values[key] = input.checked;
      else if (typeof window.Supply.defaults[key] === "number") {
        const number = Number(input.value);
        values[key] = input.value !== "" && Number.isFinite(number) && (!input.min || number >= Number(input.min)) && (!input.max || number <= Number(input.max)) ? number : window.Supply.defaults[key];
      } else values[key] = input.value;
    }
    if (view === "trade") values.focus = "trade";
    return values;
  }
  function compute() {
    const input = options(), current = JSON.stringify(input);
    if (current === signature) { render(); return; }
    signature = current; generation += 1;
    render();
    byId("status").textContent = text("正在比较具体食材组合…"); byId("status").setAttribute("aria-busy", "true");
    if (worker) worker.postMessage({id: generation, data, options: input});
    else {
      const id = generation;
      setTimeout(() => { if (id !== generation) return; result = window.Supply.evaluate(data, input); resultSignature = signature; byId("status").removeAttribute("aria-busy"); render(); }, 0);
    }
  }
  const factsHtml = facts => `<dl class="rec-facts">${facts.map(([label, value]) => `<div><dt>${escape(text(label))}</dt><dd>${escape(typeof value === "string" ? value : format(value))}</dd></div>`).join("")}</dl>`;
  function table(caption, headers, rows) {
    return `<div class="rec-table-wrap"><table class="rec-source-table"><caption>${text(caption)}</caption><thead><tr>${headers.map(label => `<th scope="col">${text(label)}</th>`).join("")}</tr></thead><tbody>${rows.map(cells => `<tr>${cells.map(value => `<td>${value}</td>`).join("")}</tr>`).join("")}</tbody></table></div>`;
  }
  function sourceHtml(resource) {
    if (!resource?.selected) return `<p>${text("获取成本不完整")}</p>`;
    return table("每次烹饪用量的获取成本", ["来源", "计价成本", "操作分钟", "容量 × 日", "首批等待 / 日"], resource.choices.map(choice => [
      escape(choice.type === "buy" ? text("买入") : `${text("种植")} ${text(choice.crop.name)}`) + (choice === resource.selected ? ` · ${text("推荐")}` : ""),
      format(choice.cash), format(choice.minutes), format(choice.spaceDays), format(choice.lead)]));
  }
  function dailyHtml(d) {
    if (!d) return "";
    return `<div class="rec-day"><h4>${text("按一天饱食需求配餐")}</h4><p>${text("每天吃 {meals} 次 · 均摊 {pots} 锅 · 首次备餐至少 {first} 锅", {meals: format(d.meals), pots: format(d.pots), first: format(Math.ceil(d.pots))})}</p>
      <p>${escape(stats(d.total))}</p><p>${text("扣除心态上限溢出后，实际补心态 {gain}", {gain: format(d.moraleGain)})}</p><p>${text("超出饱食需求 {waste}；心态目标缺口 {gap}", {waste: format(d.wastedSatiety), gap: format(Math.max(0, result.options.morale - d.moraleGain))})}</p>
      <p>${text("均摊成本 {cash} · 整数容器占容量 {space} · 每天照料约 {care} 分钟", {cash: format(d.cash), space: format(d.capacity), care: format(d.care)})}</p>
      <p>${text("烹饪等待 {wait} 分钟，其中计作占用 {active} 分钟", {wait: format(d.cookingWait), active: format(d.activeCook)})}</p>
      <p>${text("结算前心态约 {morale} · 心态兑换额外约 {points} 点", {morale: format(d.moraleAfter), points: format(d.extraPoints)})}</p>` +
      table("每日平均备料与容器安排", ["食材", "用量 / 日", "来源", "容器数 / 容量"], d.needs.map(n => [link(n.item.path, n.item.name), format(n.usage), escape(text(n.selected.type === "grow" ? n.selected.crop.name : "买入")), n.containers ? `${n.containers} / ${format(n.allocatedCapacity)}` : "—"])) +
      `<p>${text("先达到首批成熟时间，再错峰播种维持供给；均摊锅数和用量用于长期备料，首次采购与制作需按整包、整锅准备。")}</p></div>`;
  }
  function card(row, rank) {
    const output = row.output;
    let reason = row.reason || "", facts = [], detail = "", badge = "";
    if (view === "stock") {
      facts = [["整包基价", row.price], ["整包饱食", row.total?.[0]], ["每 100 饱食成本", row.cost100], ["基础保质值", row.life]];
      detail = `<p>${escape(stats(row.total || row.stats))}</p><p>${text("整包食用次数")} ${format(row.uses)} · ${text("背包占格")} ${format(row.area)}</p>`; badge = row.group;
    } else if (view === "dishes" || view === "trade") {
      badge = `Lv.${row.level} · ${text(result.options.quality)} · ${text(row.ingredients.length ? "指定配方" : "通用配方")}`;
      if (output) {
        reason = combo(output.ingredients);
        facts = view === "trade" ? [["原料换入基值", row.inputTrade], ["成品交出估值", row.outputTrade], ["净交易基值", row.tradeMargin], ["每锅心态", output.total[1]]] :
          [["一天饱食 / 实补心态", `${format(row.daily.total[0])} / ${format(row.daily.moraleGain)}`], ["额外生存点 / 日", row.daily.extraPoints], ["每天照料 / 分钟", row.daily.care], ["均摊成本 / 占容量", `${format(row.daily.cash)} / ${format(row.daily.capacity)}`]];
        detail = `<p>${text("每锅总恢复")}：${escape(stats(output.total))}</p><p>${text("每次食用")}：${escape(stats(output.perUse))} · ${format(output.servings)} ${text("次")}</p>
          <p>${text("首批备料等待 / 日")} ${format(row.lead)} · ${text("烹饪等待 / 分钟")} ${format(row.seconds / 60)}</p>
          <p>${text("每锅照料摊销 / 分钟")} ${format(row.minutes)} · ${text("种植容量 × 日")} ${format(row.spaceDays)}</p>
          <p>${text("原料换入基值")} ${format(row.inputTrade)} → ${text("成品交出估值")} ${format(row.outputTrade)} · ${text("净交易基值")} ${format(row.tradeMargin)}</p>` +
          row.requirements.map(r => `<h4>${link(r.item.path, r.item.name)} ×${r.amount}</h4>${sourceHtml(r)}`).join("") + dailyHtml(row.daily);
      }
    } else if (view === "ingredients") {
      const route = row.resource.selected;
      badge = `${text(row.group)} · ${text(route?.type === "grow" ? "建议种植" : "建议买入")}`;
      facts = [["买入 / 每次用量", row.resource.purchase], ["推荐来源均摊成本", route?.cash], ["搭配心态 / 100 饱食", row.morale100], ["可搭配组合", row.coverage]];
      reason = route?.type === "grow" ? text("种 {crop}，成熟约 {days} 日", {crop: text(route.crop.name), days: format(route.lead)}) : text("按当前预算比较买入与种植");
      detail = `<p>${text("每次原始恢复")}：${escape(stats(row.stats))}</p><p>${text("整包基价")} ${format(row.price)} · ${text("烹饪次数")} ${format(row.uses)} · ${text("基础保质值")} ${format(row.life)}</p><p>${text("每用量交易基值")} ${format(row.trade_value)} · ${text("商人配置交出估值")} ${format(window.Supply.givenValue(row.trade_value, row.sell_rate, result.options.sellChannel))}</p>${sourceHtml(row.resource)}`;
    } else {
      badge = text(result.options.harvest === "perfect" ? "完美收获（情景）" : "普通收获");
      facts = [["成熟 / 日", row.days], ["每容器每日烹饪用量", row.dailyUses], ["每容器照料 / 分钟每天", row.dailyMinutes], ["占用容量", row.capacity]];
      reason = text("一批种 {count} 份种子 · 作物尺寸 {size}", {count: format(row.batch), size: format(row.size)});
      detail = `<p>${text("每批收获")}：${row.harvest.map(i => `${link(i.path, i.name)} ×${format(i.amount * row.batch)}（${format(i.uses)} ${text("次")}）`).join("、")}</p>
        <p>${text("每批种子计价成本")} ${format(row.seedCost)} · ${text("每批照料与播种收获 / 分钟")} ${format(row.cycleMinutes)}</p>
        <p>${text("除虫 / 除草 / 浇水的每次检查概率")}：${["pest", "weed", "water"].map(type => `${format((row.probabilities[type] || 0) * 100)}%`).join(" / ")} · ${text("本轮预计检查次数")} ${format(row.checks)}</p>
        <p>${text("每容器每日生食饱食")} ${format(row.dailyRawSatiety)} · ${text("不能与加工产出相加")}</p>`;
    }
    if (row.recipes?.length) detail += `<h4>${text("用这份食材可以这样搭配")}</h4>` + row.recipes.map(recipe => `<p>${link(recipe.path, recipe.name)}${recipe.ingredients?.length ? `：${escape(combo(recipe.ingredients))}` : ""}</p>`).join("");
    if (view !== "stock" && row.value !== null) detail += `<p>${text("比较效率")} ${format(row.value)} · ${text("负面恢复扣分")} ${format(row.penalty || 0)}</p>`;
    const icon = output?.product?.icon || row.icon || row.qualities?.[result?.options.quality]?.icon, count = output?.servings || row.uses;
    const art = `<span class="guide-item-art small"><img class="entry-art" src="../${escape(icon?.replace(/^\.\//, "") || "favicon.svg")}" width="72" height="72" alt="${escape(text(row.name))}" loading="lazy">${count ? `<span class="icon-uses">${format(count)}${text("次")}</span>` : ""}</span>`;
    const limits = row.daily && !row.daily.fits ? `<span class="rec-adverse">${text("超出当前均摊预算或种植容量")}</span>` : "";
    return `<article class="rec-card${row.score === null ? " rec-unrated" : ""}"><div class="rec-card-top"><span class="rec-rank">${String(rank).padStart(2, "0")}</span>${art}<div class="rec-name"><p>${escape(badge)}${limits}</p><h3>${link(row.path, row.name)}</h3><span>${escape(row.reason || reason)}</span></div><div class="rec-score"><strong>${format(row.score)}</strong><span>${text(row.score === null ? "暂不计分" : "推荐指数")}</span></div></div>${factsHtml(facts)}<details><summary>${text("食材、恢复与每日备料明细")}</summary>${detail}</details></article>`;
  }
  function sortValue(row) {
    const sort = byId("sort").value;
    if (sort === "cost") return view === "stock" || view === "dishes" || view === "trade" ? -row.cost100 : view === "crops" ? row.dailyUses / row.capacity : -row.resource?.selected?.cash;
    if (sort === "satiety") return view === "stock" ? row.total?.[0] : view === "crops" ? row.dailyRawSatiety : view === "ingredients" ? row.stats[0] : row.output?.total[0];
    if (sort === "morale") return view === "stock" ? row.total?.[1] : row.morale100;
    if (sort === "time") return view === "stock" ? row.life : view === "crops" ? -row.dailyMinutes : view === "ingredients" ? -row.resource?.selected?.minutes : -(row.daily?.care + row.daily?.activeCook);
    if (sort === "trade") return row.tradeMargin ?? (view === "stock" ? row.trade_value * row.uses : row.trade_value);
    return row.score;
  }
  function updateUrl() {
    const url = new URL(location.href), input = options(); url.hash = view;
    for (const key of parameterNames) { url.searchParams.delete(key); if (input[key] !== window.Supply.defaults[key] && !(key === "focus" && input[key] === "trade")) url.searchParams.set(key, input[key]); }
    for (const [key, value, fallback] of [["q", byId("search").value, ""], ["sort", byId("sort").value, "score"], ["life", byId("life").value, "7"], ["new", byId("stage-only").checked ? "1" : "", ""], ["fit", byId("fit").checked ? "1" : "", ""], ["mood", byId("mood").checked ? "1" : "", ""]]) { url.searchParams.delete(key); if (value !== fallback) url.searchParams.set(key, value); }
    history.replaceState(null, "", url);
  }
  function render() {
    updateUrl();
    const sortLabels = view === "crops" ? {cost: "烹饪用量 / 容量每天", satiety: "每日生食饱食", time: "每天照料最少", trade: "每日收获交易基值"} :
      view === "ingredients" ? {cost: "推荐来源成本最低", satiety: "原始饱食 / 用量", time: "每用量照料最少", trade: "每用量交易基值"} :
      view === "stock" ? {time: "基础保质值", morale: "整包心态", trade: "整包交易基值"} : {};
    const common = {score: "综合指数", cost: "每 100 饱食成本", satiety: "每锅饱食", morale: "心态 / 100 饱食", time: "每天照料最少", trade: "净交易基值"};
    for (const option of byId("sort").options) option.textContent = text(sortLabels[option.value] || common[option.value]);
    for (const section of document.querySelectorAll(".rec-section")) section.hidden = section.id !== view;
    for (const tab of tabs) { tab.classList.toggle("active", tab.dataset.view === view); if (tab.dataset.view === view) tab.setAttribute("aria-current", "page"); else tab.removeAttribute("aria-current"); }
    settings.hidden = view === "stock"; byId("brief").hidden = view === "stock";
    byId("quality").disabled = view === "stock"; byId("focus").disabled = view === "stock" || view === "trade";
    byId("life-label").hidden = view !== "stock" && view !== "ingredients"; byId("stage-only-label").hidden = view !== "dishes" && view !== "trade";
    byId("fit-label").hidden = view !== "dishes" && view !== "trade";
    byId("mood-label").hidden = view !== "dishes";
    if (signature !== resultSignature && view !== "stock") {
      document.querySelector(`#${view} .rec-list`).innerHTML = ""; byId("brief").hidden = true;
      byId("status").textContent = text("正在比较具体食材组合…"); return;
    }
    const phrase = byId("search").value.trim().toLocaleLowerCase(), source = view === "stock" ? data.stock : result[view === "trade" ? "dishes" : view];
    const rows = source.filter(row => {
      if ((view === "dishes" || view === "trade") && byId("stage-only").checked && row.level !== Number(byId("stage").value)) return false;
      if ((view === "dishes" || view === "trade") && byId("fit").checked && !row.daily?.fits) return false;
      if (view === "dishes" && byId("mood").checked && !row.daily?.moraleCovered) return false;
      if ((view === "stock" || view === "ingredients") && row.life > 0 && row.life < Number(byId("life").value)) return false;
      const values = [row.name, row.id, row.group, ...(row.tags || []).map(tag => tag.name || tag), ...(row.output?.ingredients || row.ingredients || []).map(item => item.name), ...(row.harvest || []).map(item => item.name)];
      return !phrase || values.flatMap(value => [value, i18n?.english(value) || value]).join(" ").toLocaleLowerCase().includes(phrase);
    });
    const ranked = rows.filter(row => row.score !== null).sort((a, b) => (sortValue(b) ?? -Infinity) - (sortValue(a) ?? -Infinity) || a.id - b.id), unranked = rows.filter(row => row.score === null);
    byId("status").textContent = text("{rated} 个可计分候选 · {unrated} 个暂不计分候选", {rated: ranked.length, unrated: unranked.length});
    const list = document.querySelector(`#${view} .rec-list`);
    list.innerHTML = ranked.slice(0, 20).map((row, i) => card(row, i + 1)).join("") || `<div class="rec-empty"><p>${text("没有符合条件的推荐")}</p></div>`;
    if (ranked.length > 20) list.innerHTML += `<details class="rec-more"><summary>${text("其余可计分候选")}（${ranked.length - 20}）</summary>${ranked.slice(20).map((row, i) => card(row, i + 21)).join("")}</details>`;
    if (unranked.length) list.innerHTML += `<details class="rec-more"><summary>${text("数据不足或条件不满足")}（${unranked.length}）</summary>${unranked.map((row, i) => card(row, i + 1)).join("")}</details>`;
    for (const img of list.querySelectorAll("img")) img.addEventListener("error", () => { img.src = "../favicon.svg"; }, {once: true});
    if (view !== "stock") {
      const o = result.options, w = result.weights;
      byId("context").textContent = text("{stage} · {quality}品质 · {currency} · 每日目标：饱食 {satiety} / 心态 {morale}", {stage: text(data.stages[o.stage]), quality: text(o.quality), currency: text(o.currency === "trade" ? "交易基值" : "购买基价"), satiety: format(o.satiety), morale: format(o.morale)});
      const benefit = view === "trade" ? text("按净交易基值与烹饪等待比较，食用效果保留供取舍。") : text("收益权重：饱食 {satiety}% · 心态 {morale}% · 其他恢复 {other}%", {satiety: format(w.satiety * 100), morale: format(w.morale * 100), other: format(w.other * 100)});
      const heading = view === "trade" ? "比较直接交换与加工成菜" : o.focus === "ease" ? "少照料，留时间" : o.focus === "satiety" ? "优先饱食" : o.focus === "morale" ? "优先心态" : o.stage === 3 ? "补心态，也把时间留出来" : o.stage === 1 ? "先吃饱，再节省备料" : "稳定供给，兼顾心态";
      byId("brief").innerHTML = `<div><p class="eyebrow">${text("本阶段优先级")}</p><h2>${text(heading)}</h2><p>${benefit}</p></div><div><p>${text("预算与照料")} ${format(o.cash)} / ${format(o.care)} ${text("分钟每天")}</p><p>${text("种植容量")} ${format(o.capacity)} · ${text("等待容忍")} ${format(o.horizon)} ${text("日")}</p><a href="../#dish/">${text("用冰箱库存确认能做什么 →")}</a></div>`;
      byId("model-summary").innerHTML = `<p>${benefit}</p><p>${view === "trade" ? text("交易效率 = 净交易基值 ÷（1 + 烹饪小时）；食用负面恢复不扣交易分。") : text("负担权重：计价成本 {economy}% · 操作时间 {labor}% · 空间 {space}% · 等待 {wait}%", {economy: format(w.economy * 100), labor: format(w.labor * 100), space: format(w.space * 100), wait: format(w.wait * 100)})}</p>`;
    } else byId("context").textContent = text("即食囤货沿用整包饱食、购买价、保质与背包格比较。");
    i18n?.apply();
  }
  function loadState() {
    const url = new URL(location.href); view = Object.hasOwn(labels, url.hash.slice(1)) ? url.hash.slice(1) : "dishes";
    for (const key of parameterNames) {
      const input = byId(key); if (!input) continue;
      const value = url.searchParams.get(key);
      if (input.type === "checkbox") input.checked = value === null ? window.Supply.defaults[key] : value === "true";
      else if (input.tagName === "SELECT") input.value = [...input.options].some(option => option.value === String(value ?? window.Supply.defaults[key])) ? String(value ?? window.Supply.defaults[key]) : String(window.Supply.defaults[key]);
      else input.value = value ?? window.Supply.defaults[key];
    }
    byId("search").value = url.searchParams.get("q") || "";
    byId("sort").value = ["score", "cost", "satiety", "morale", "time", "trade"].includes(url.searchParams.get("sort")) ? url.searchParams.get("sort") : "score";
    byId("life").value = ["0", "7", "30", "90"].includes(url.searchParams.get("life")) ? url.searchParams.get("life") : "7"; byId("stage-only").checked = url.searchParams.get("new") === "1"; byId("fit").checked = url.searchParams.get("fit") === "1"; byId("mood").checked = url.searchParams.get("mood") === "1"; compute();
  }
  controls.hidden = false;
  function onInput() { clearTimeout(timer); timer = setTimeout(() => compute(), 180); }
  controls.addEventListener("submit", event => event.preventDefault()); controls.addEventListener("input", onInput); settings.addEventListener("input", onInput);
  controls.addEventListener("reset", event => { event.preventDefault(); history.replaceState(null, "", location.pathname + (i18n ? `?lang=${i18n.language}` : "") + "#" + view); loadState(); });
  for (const tab of tabs) tab.addEventListener("click", event => { event.preventDefault(); view = tab.dataset.view; compute(); });
  window.addEventListener("popstate", loadState); window.addEventListener("languagechange", () => { planterLabels(); render(); }); loadState();
  if (Object.hasOwn(labels, location.hash.slice(1))) window.scrollTo(0, 0);
})();
