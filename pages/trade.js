"use strict";
/* 交易行情页交互：搜索、分类筛选与排序，全部基于静态表格行，不重建内容。
   数据模型内嵌在 #trade-data；缺失（版本不匹配）时保持静态表格原样。 */
(async () => {
  const i18n = window.I18n;
  await i18n?.ready;
  const dataNode = document.getElementById("trade-data");
  const controls = document.getElementById("trade-controls");
  if (!dataNode || !controls) return;
  let model = null;
  try { model = JSON.parse(dataNode.textContent); } catch { model = null; }
  if (!model) return;
  controls.hidden = false;

  const text = (source, variables = {}) => i18n?.text(source, variables) || source;
  const search = document.getElementById("trade-search");
  const catSelect = document.getElementById("trade-cat");
  const sortSelect = document.getElementById("trade-sort");
  const sharedOnly = document.getElementById("trade-shared-only");
  const status = document.getElementById("trade-status");
  const tables = [...document.querySelectorAll(".trade-table")];
  const rowsFor = table => [...table.querySelectorAll("tr[data-cat]")];

  const categories = model.categories || {};
  const used = new Set();
  for (const table of tables) {
    for (const row of rowsFor(table)) {
      if (row.dataset.cat) used.add(row.dataset.cat);
    }
  }
  for (const cat of [...used].sort((a, b) => Number(a) - Number(b))) {
    const option = document.createElement("option");
    option.value = cat;
    option.textContent = text(categories[cat] || `分类 ${cat}`);
    catSelect.append(option);
  }

  const english = value => (i18n?.english ? i18n.english(value) : value);
  const matches = (row, phrase, cat, shared, sort) => {
    if (cat && row.dataset.cat !== cat) return false;
    if (shared && !row.dataset.shared) return false;
    if (phrase) {
      const haystack = `${row.dataset.name} ${english(row.dataset.name)}`.toLocaleLowerCase();
      if (!haystack.includes(phrase)) return false;
    }
    if (sort === "uses" && !(parseFloat(row.dataset.uses) > 0)) return false;
    return true;
  };

  const apply = () => {
    const phrase = search.value.trim().toLocaleLowerCase();
    const cat = catSelect.value;
    const sort = sortSelect.value;
    const shared = sharedOnly.checked;
    let visible = 0;
    for (const table of tables) {
      const rows = rowsFor(table);
      for (const row of rows) {
        row.hidden = !matches(row, phrase, cat, shared, sort);
        if (!row.hidden) visible += 1;
      }
      if (sort !== "default") {
        const key = sort === "tv" ? "tv" : "uses";
        for (const row of rows.sort((a, b) =>
          (parseFloat(b.dataset[key]) || 0) - (parseFloat(a.dataset[key]) || 0)
          || a.dataset.name.localeCompare(b.dataset.name, "zh-Hans-CN"))) {
          row.parentElement.append(row);
        }
      }
    }
    // 模板占位符在本地插值，避免依赖运行时的变量替换行为。
    status.textContent = phrase || cat || shared || sort !== "default"
      ? text("显示 {count} 项").replace("{count}", String(visible)) : "";
  };

  search.addEventListener("input", apply);
  catSelect.addEventListener("change", apply);
  sortSelect.addEventListener("change", apply);
  sharedOnly.addEventListener("change", apply);
  i18n?.apply();
})();
