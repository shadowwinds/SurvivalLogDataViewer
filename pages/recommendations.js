"use strict";

(async () => {
  const i18n = window.I18n;
  await i18n?.ready;
  const data = JSON.parse(document.getElementById("rec-data").textContent);
  const labels = {stock: "即食囤货", ingredients: "烹饪备料", dishes: "菜肴推荐", crops: "作物种植"};
  const controls = document.getElementById("rec-controls");
  const stageInput = document.getElementById("rec-stage");
  const qualityInput = document.getElementById("rec-quality");
  const lifeInput = document.getElementById("rec-life");
  const searchInput = document.getElementById("rec-search");
  const sortInput = document.getElementById("rec-sort");
  const stageOnly = document.getElementById("rec-stage-only");
  const tabs = [...document.querySelectorAll("[data-view]")];
  const sections = [...document.querySelectorAll(".rec-section")];
  const escape = value => String(value ?? "").replace(/[&<>"']/g, char => ({"&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;"}[char]));
  const format = value => typeof value === "number" && Number.isFinite(value) ? value.toLocaleString(i18n?.locale || "zh-CN", {maximumFractionDigits: 2}) : "—";
  const link = (path, name) => path ? `<a href="../${escape(path)}">${escape(name)}</a>` : escape(name);
  const statLabels = ["饱食", "心态", "精力", "健康", "生命"];
  const restoreStats = stats => statLabels.map((label, index) => `${label} ${format(stats[index])}`).join(" · ");
  let view = "stock";

  function rating(row) {
    return view === "stock" ? row : row.ratings[`${stageInput.value}:${qualityInput.value}`] || {score: null, reason: "等级未解锁"};
  }

  function art(row, output) {
    const icon = output?.icon || row.icon;
    const source = icon ? `../${icon.replace(/^\.\//, "")}` : "../favicon.svg";
    const count = view === "dishes" ? output?.servings : row.uses;
    const countLabel = Number.isInteger(count) && count > 0 ? `${count}次` : view === "dishes" && row.groups.length ? "可变" : "—";
    const purpose = view === "ingredients" ? "烹饪" : "食用";
    const fullLabel = countLabel === "可变" ? "食用次数随实际食材变化" : `${purpose}次数：${countLabel}`;
    return `<span class="guide-item-art small"><img class="entry-art" src="${escape(source)}" width="72" height="72" alt="${escape(row.name)}游戏图标" loading="lazy">${view === "crops" ? "" : `<span class="icon-uses" title="${escape(fullLabel)}" aria-label="${escape(fullLabel)}">${countLabel}</span>`}</span>`;
  }

  function card(row, rank) {
    const result = rating(row);
    const output = row.qualities?.[qualityInput.value] || {};
    let facts;
    let detail = "";
    let reason = result.reason || "";
    let badge = row.group || "";
    if (view === "stock") {
      facts = [["整包基价", row.price], ["整包饱食", row.total?.[0]], ["每 100 饱食成本", row.cost100], ["基础保质值", row.life]];
      detail = `<p>整包食用 ${format(row.uses)} 次，背包占格 ${format(row.area)}。</p><p>每次原始恢复：${restoreStats(row.stats)}</p>`;
      if (!reason) reason = `整包 ${format(row.total[0])} 饱食 / 基价 ${format(row.price)}${row.penalty ? " · 有负面恢复" : " · 无负面恢复"}`;
    } else if (view === "ingredients") {
      facts = [["整包基价", row.price], ["每次用量摊销价", result.unit_cost], ["可用固定配方", result.coverage], ["基础保质值", row.life]];
      detail = `<p>整包可烹饪 ${format(row.uses)} 次。每次原始恢复：${restoreStats(row.stats)}</p>`;
      if (!reason) reason = `${format(row.uses)} 次烹饪用量 · 可搭配 ${format(result.coverage)} 道当前等级固定配方`;
    } else if (view === "dishes") {
      badge = `${row.level === null ? "等级未提供" : `Lv.${row.level}`} · ${qualityInput.value}品质`;
      facts = [["每锅食材摊销价", row.cost], ["每锅总饱食", output.total?.[0]], ["每次食用饱食", output.per_use?.[0]], ["烹饪小时", row.seconds ? row.seconds / 3600 : null]];
      const ingredients = row.ingredients.map(item => `${link(item.path, item.name)} ×${item.amount}`).join("、");
      detail = `<p>食材需求（每锅消耗用量）：${ingredients || "未指定物品"}</p>`;
      if (row.groups.length) detail += `<p>分类条件：${row.groups.map(group => `${escape(group.name)} ×${group.amount}`).join("、")}；食材档位 ${escape(row.tier)}。</p><p>实际食材组合还需符合档位和特色配方优先规则。</p>`;
      if (row.cost !== null) detail += `<p>从零整包购买：${format(row.basket)}；按用量摊销：${format(row.cost)}。未用完的食材仍可留存。</p>`;
      if (output.total) detail += `<p>每锅 1 件成品，可吃 ${format(output.servings)} 次。整锅恢复：${restoreStats(output.total)}</p><p>每次食用：${restoreStats(output.per_use || [])}</p><p>食材原始饱食 ${format(row.input_satiety)} → 成品 ${format(output.total[0])}；增量 ${format(row.input_satiety === null ? null : output.total[0] - row.input_satiety)}。每 100 饱食食材摊销价 ${format(result.cost100)}。</p>`;
      if (!reason) reason = `${row.ingredients.map(i => `${i.name} ×${i.amount}`).join(" + ")} · 每锅可吃 ${format(output.servings)} 次`;
    } else {
      badge = "基础普通收获";
      facts = [["基础成熟 / 小时", row.seconds ? row.seconds / 3600 : null], ["每轮烹饪用量", row.cook_uses], ["每轮生食饱食", row.satiety], ["配置尺寸", row.size]];
      detail = `<p>普通收获：${row.harvest.map(item => `${link(item.path, item.name)} ×${item.amount}（每份 ${format(item.uses)} 次）`).join("、")}</p><p>每尺寸单位 / 基础生长日：生食饱食 ${format(row.daily_satiety)}，烹饪用量 ${format(row.daily_uses)}。返种配置概率 ${format(row.seed_rate)}，未计入指数。</p>`;
      if (!reason) reason = `${row.harvest.map(i => `${i.name} ×${i.amount}`).join(" + ")} · ${format(row.seconds / 86400)} 个基础生长日`;
    }
    if (result.recipes?.length) detail += `<p>可搭配：${result.recipes.map(recipe => `${link(recipe.path, recipe.name)}（${format(recipe.score)}）`).join("、")}</p>`;
    if (result.score !== null) {
      detail += `<ul class="rec-components">${result.components.map(component => `<li><span>${escape(component.label)}</span><span>${format(component.percentile)} × ${component.weight}%</span></li>`).join("")}</ul><p>负面恢复扣分：${format(result.penalty || 0)}；综合指数 ${format(result.score)} / 100。</p>`;
    }
    const stats = view === "stock" ? row.total : output.total;
    const negative = stats?.some((value, index) => index > 0 && value < 0);
    return `<article class="rec-card${result.score === null ? " rec-unrated" : ""}"><div class="rec-card-top"><span class="rec-rank">${String(rank).padStart(2, "0")}</span>${art(row, output)}<div class="rec-name"><p>${escape(badge)}${negative ? '<span class="rec-adverse">负面恢复</span>' : ""}</p><h3>${link(row.path, row.name)}</h3><span>${escape(reason)}</span></div><div class="rec-score"><strong>${format(result.score)}</strong><span>${result.score === null ? "暂不计分" : "推荐指数"}</span></div></div><dl class="rec-facts">${facts.map(([label, value]) => `<div><dt>${label}</dt><dd>${format(value)}</dd></div>`).join("")}</dl><details><summary>食材、恢复与评分明细</summary>${detail}</details></article>`;
  }

  function sorting(row) {
    const result = rating(row);
    const output = row.qualities?.[qualityInput.value];
    if (sortInput.value === "cost") return view === "crops" ? row.daily_uses ?? -Infinity : view === "ingredients" ? -result.unit_cost : -result.cost100;
    if (sortInput.value === "satiety") return view === "stock" ? row.total?.[0] : view === "crops" ? row.satiety : view === "ingredients" ? row.stats[0] : output?.total?.[0];
    if (sortInput.value === "time") return view === "stock" || view === "ingredients" ? row.life : view === "dishes" ? result.metrics?.speed : row.daily_uses;
    return result.score;
  }

  function updateUrl() {
    const url = new URL(location.href);
    url.hash = view;
    for (const key of ["stage", "quality", "life", "q", "sort", "new"]) url.searchParams.delete(key);
    if (stageInput.value !== "1") url.searchParams.set("stage", stageInput.value);
    if (qualityInput.value !== "普通") url.searchParams.set("quality", qualityInput.value);
    if (lifeInput.value !== "7") url.searchParams.set("life", lifeInput.value);
    if (searchInput.value) url.searchParams.set("q", searchInput.value);
    if (sortInput.value !== "score") url.searchParams.set("sort", sortInput.value);
    if (stageOnly.checked) url.searchParams.set("new", "1");
    history.replaceState(null, "", url);
  }

  function render(syncUrl = true) {
    const phrase = searchInput.value.trim().toLocaleLowerCase();
    const rows = data[view].filter(row => {
      if (view === "dishes" && row.level !== null && row.level > Number(stageInput.value)) return false;
      if (view === "dishes" && stageOnly.checked && row.level !== Number(stageInput.value)) return false;
      if ((view === "stock" || view === "ingredients") && row.life !== null && row.life > 0 && row.life < Number(lifeInput.value)) return false;
      const values = [row.name, row.id, row.group, ...(row.tags || []),
        ...(row.ingredients || []).map(i => i.name), ...(row.groups || []).map(i => i.name), ...(row.harvest || []).map(i => i.name)];
      return !phrase || values.flatMap(value => [value, i18n?.english(value) || value]).join(" ").toLocaleLowerCase().includes(phrase);
    });
    const ranked = rows.filter(row => rating(row).score !== null).sort((a, b) => (sorting(b) ?? -Infinity) - (sorting(a) ?? -Infinity) || a.id - b.id);
    const unranked = rows.filter(row => rating(row).score === null).sort((a, b) => a.id - b.id);
    for (const section of sections) section.hidden = section.id !== view;
    for (const tab of tabs) {
      tab.classList.toggle("active", tab.dataset.view === view);
      if (tab.dataset.view === view) tab.setAttribute("aria-current", "page"); else tab.removeAttribute("aria-current");
    }
    document.getElementById("rec-quality").disabled = view === "stock";
    document.getElementById("rec-life-label").hidden = view !== "stock" && view !== "ingredients";
    document.getElementById("rec-stage-only-label").hidden = view !== "dishes";
    sortInput.options[1].textContent = view === "crops" ? "单位尺寸每日烹饪用量" : "价格优势";
    sortInput.options[2].textContent = view === "ingredients" ? "每次原始饱食" : "总饱食";
    sortInput.options[3].textContent = view === "stock" || view === "ingredients" ? "基础保质值" : "单位时间产出";
    document.getElementById("rec-context").textContent = `${data.stages[stageInput.value]}${view === "stock" ? " · 即食补给" : ` · ${qualityInput.value}品质情景`}。中后期包含此前等级配方；指数只在同类、同阶段候选中比较。`;
    document.getElementById("rec-status").textContent = `${ranked.length} 个可计分候选 · ${unranked.length} 个暂不计分候选${phrase ? ` · 搜索“${searchInput.value.trim()}”` : ""}`;
    const list = document.querySelector(`#${view} .rec-list`);
    list.innerHTML = (ranked.length ? ranked.map((row, index) => card(row, index + 1)).join("") : '<div class="rec-empty"><h3>没有符合条件的推荐</h3><p>试试减少搜索条件、降低保质筛选或提高烹饪等级。</p></div>') +
      (unranked.length ? `<details class="rec-more"><summary>通用配方、专项物品与数据不足候选（${unranked.length}）</summary><p>以下条目保留条件与来源；缺失数据不按零成本或固定产量处理。</p>${unranked.map((row, index) => card(row, index + 1)).join("")}</details>` : "");
    for (const img of list.querySelectorAll("img")) img.addEventListener("error", () => { img.src = "../favicon.svg"; }, {once: true});
    if (syncUrl) updateUrl();
    i18n?.apply();
  }

  function loadState() {
    const url = new URL(location.href);
    view = Object.hasOwn(labels, url.hash.slice(1)) ? url.hash.slice(1) : "stock";
    stageInput.value = ["1", "2", "3"].includes(url.searchParams.get("stage")) ? url.searchParams.get("stage") : "1";
    qualityInput.value = data.qualities.includes(url.searchParams.get("quality")) ? url.searchParams.get("quality") : "普通";
    lifeInput.value = ["0", "7", "30", "90"].includes(url.searchParams.get("life")) ? url.searchParams.get("life") : "7";
    searchInput.value = url.searchParams.get("q") || "";
    sortInput.value = ["score", "cost", "satiety", "time"].includes(url.searchParams.get("sort")) ? url.searchParams.get("sort") : "score";
    stageOnly.checked = url.searchParams.get("new") === "1";
    render(false);
  }
  controls.hidden = false;
  controls.addEventListener("submit", event => event.preventDefault());
  controls.addEventListener("input", () => render());
  controls.addEventListener("reset", event => {
    event.preventDefault();
    stageInput.value = "1"; qualityInput.value = "普通"; lifeInput.value = "7"; searchInput.value = ""; sortInput.value = "score";
    stageOnly.checked = false;
    render();
  });
  for (const tab of tabs) tab.addEventListener("click", event => { event.preventDefault(); view = tab.dataset.view; render(); });
  window.addEventListener("popstate", loadState);
  window.addEventListener("languagechange", () => {
    const expanded = [...document.querySelectorAll(`#${view} .rec-card`)].filter(card => card.querySelector("details").open)
      .map(card => card.querySelector(".rec-name a")?.pathname);
    render(false);
    for (const card of document.querySelectorAll(`#${view} .rec-card`)) {
      card.querySelector("details").open = expanded.includes(card.querySelector(".rec-name a")?.pathname);
    }
  });
  loadState();
})();
