(function () {
  "use strict";

  const FALLBACK_POLL_INTERVAL = 5000;
  const CLIENT_ID =
    typeof crypto !== "undefined" && typeof crypto.randomUUID === "function"
      ? crypto.randomUUID()
      : `${Date.now().toString(36)}${Math.random().toString(36).slice(2)}`;
  const state = {
    category: "furniture",
    nameSearch: "",
    materialSearch: "",
    completion: "all",
    selectedKey: null,
    categories: [],
    overall: { completed: 0, total: 0 },
    metadata: {},
    sync: null,
    revision: null,
    entries: [],
    loaded: false,
    polling: false,
    entriesRequest: 0,
    detailRequest: 0,
    recipeRequest: 0,
    recipePlan: null,
    recipeSaveSelection: "",
  };

  const byId = (id) => document.getElementById(id);

  function makeElement(tag, className, text) {
    const node = document.createElement(tag);
    if (className) node.className = className;
    if (text !== undefined && text !== null) node.textContent = String(text);
    return node;
  }

  async function requestJson(path) {
    const response = await fetch(path, {
      cache: "no-store",
      headers: {
        Accept: "application/json",
        "X-SurvivalLog-Client": CLIENT_ID,
      },
    });
    let payload = null;
    try {
      payload = await response.json();
    } catch (error) {
      payload = null;
    }
    if (!response.ok) {
      throw new Error((payload && payload.error) || `请求失败：${response.status}`);
    }
    return payload;
  }

  function formatRatio(completed, total) {
    if (!total) return "0%";
    return `${Math.round((completed * 100) / total)}%`;
  }

  function currentCategory() {
    return state.categories.find((item) => item.category === state.category) || {
      category: state.category,
      label: "图鉴",
      emoji: "📖",
      total: 0,
      completed: 0,
    };
  }

  function setStatusNode(node, status, text) {
    if (!node) return;
    node.dataset.status = status;
    const label = node.querySelector("span:last-child");
    if (label) label.textContent = text;
  }

  function renderCategories() {
    const nav = byId("categoryNav");
    nav.replaceChildren();
    const fragment = document.createDocumentFragment();
    state.categories.forEach((category) => {
      const button = makeElement("button", "category-button");
      button.type = "button";
      button.dataset.category = category.category;
      button.classList.toggle("active", category.category === state.category);

      const identity = makeElement("span", "category-identity");
      identity.append(
        makeElement("span", "category-emoji", category.emoji),
        makeElement("span", "category-label", category.label),
      );
      const count = makeElement(
        "span",
        "category-count",
        category.category === "recipes"
          ? "查看"
          : `${category.completed}/${category.total}`,
      );
      button.append(identity, count);
      fragment.append(button);
    });
    nav.append(fragment);
  }

  function renderProgress() {
    const completed = Number(state.overall.completed || 0);
    const total = Number(state.overall.total || 0);
    byId("overallNumber").textContent = `${completed}/${total}`;
    byId("overallRate").textContent = `完成率 ${formatRatio(completed, total)}`;
    byId("overallProgress").style.width = `${total ? Math.min(100, (completed * 100) / total) : 0}%`;
  }

  function renderHeader() {
    const category = currentCategory();
    byId("entriesTitle").textContent = `${category.label}条目`;
    byId("resultCount").textContent = `${state.entries.length} 条`;
  }

  function renderSource() {
    const version = state.metadata.game_version || "未知";
    const savePath = (state.metadata.save_path || (state.sync && state.sync.save_path) || state.metadata.save_requested_path || "未指定");
    const versionParts = version.split(" / catalog ", 2);
    byId("gameVersion").querySelector(".source-version-value").textContent = versionParts[0] || "未知";
    byId("gameVersion").querySelector(".source-catalog-value").textContent =
      versionParts[1] ? `catalog ${versionParts[1]}` : "catalog 未知";
    byId("savePath").textContent = savePath;
    byId("savePath").title = savePath;
  }

  function renderSync() {
    if (!state.sync) return;
    let status = state.sync.status || "loading";
    let message = state.sync.message || "正在读取存档";
    if (status === "ok") {
      const readAt = state.metadata.save_read_at || "未知时间";
      message = `已同步 · ${readAt}`;
    } else if (status === "fallback") {
      message = "已使用存档备份同步";
    } else if (status === "error") {
      message = "存档同步失败";
    }
    setStatusNode(byId("syncStatus"), status, message);
    setStatusNode(byId("headerSync"), status, message);
  }

  function renderFilters() {
    document.querySelectorAll("[data-filter]").forEach((button) => {
      button.classList.toggle("active", button.dataset.filter === state.completion);
    });
  }

  function renderSearchControls() {
    const input = byId("materialSearchInput");
    const field = input && input.closest(".material-search-field");
    const supported = ["dish", "craft", "furniture"].includes(state.category);
    if (!input || !field) return;
    input.disabled = !supported;
    field.classList.toggle("is-disabled", !supported);
    input.placeholder = supported ? "材料名称或 ID" : "当前分类无材料检索";
    if (!supported && state.materialSearch) {
      state.materialSearch = "";
      input.value = "";
    }
  }

  function renderMainView() {
    const recipes = state.category === "recipes";
    byId("entryToolbar").hidden = recipes;
    byId("codexWorkspace").hidden = recipes;
    byId("recipeView").hidden = !recipes;
  }

  function renderEntries() {
    const list = byId("entryList");
    list.replaceChildren();
    if (!state.entries.length) {
      list.append(makeElement("div", "empty-state", "没有符合条件的条目"));
      renderHeader();
      return;
    }

    const fragment = document.createDocumentFragment();
    state.entries.forEach((entry) => {
      const row = makeElement("article", "entry-row");
      row.classList.toggle("selected", entry.entry_key === state.selectedKey);

      const indicator = makeElement("span", "entry-indicator");
      indicator.classList.toggle("completed", Boolean(entry.completed));
      const body = makeElement("div", "entry-body");
      const titleLine = makeElement("div", "entry-title-line");
      titleLine.append(
        makeElement("div", "entry-name", entry.name),
        makeElement("span", "entry-id", `ID ${entry.source_id}`),
      );
      const highlightLine = makeElement("div", "entry-highlight");
      const highlightItems = Array.isArray(entry.highlight_items)
        ? entry.highlight_items
        : [];
      if (highlightItems.length) {
        highlightItems.forEach((item) => {
          const highlightItem = makeElement("span", "entry-highlight-item");
          const label = String(item.label || "");
          const value = String(item.value || "无");
          highlightItem.append(
            makeElement("span", "entry-highlight-label", `${label}：`),
            makeElement("span", "entry-highlight-value", value),
          );
          highlightItem.title = `${label}：${value}`;
          highlightLine.append(highlightItem);
        });
      } else {
        highlightLine.append(makeElement("span", "entry-highlight-item", "无"));
      }
      body.append(
        titleLine,
        highlightLine,
      );

      const status = makeElement(
        "span",
        `entry-status ${entry.completed ? "completed" : "pending"}`,
        entry.completed ? "已解锁" : "未解锁",
      );
      row.dataset.entryKey = entry.entry_key;
      row.tabIndex = 0;
      row.setAttribute("role", "button");
      row.setAttribute("aria-label", `查看 ${entry.name} 详情`);
      row.append(indicator, body, status);
      fragment.append(row);
    });
    list.append(fragment);
    renderHeader();
  }

  function recipeDisplayName(value, fallback) {
    const name = typeof value === "string" ? value.trim() : "";
    return name && !/^ID\s*:/i.test(name) ? name : fallback;
  }

  function recipeItemName(item) {
    return recipeDisplayName(item && item.name, "未命名食材");
  }

  function renderRecipeSelector(payload) {
    const select = byId("recipeSaveSelect");
    const saves = Array.isArray(payload && payload.saves) ? payload.saves : [];
    select.replaceChildren();
    const preferred = state.recipeSaveSelection
      || payload.selected_save_file
      || payload.default_save_file
      || (saves[0] && saves[0].file_name)
      || "";
    const selected = saves.find((save) => save.file_name === preferred) || saves[0] || null;
    state.recipeSaveSelection = selected ? selected.file_name : "";
    saves.forEach((save) => {
      const option = makeElement("option", "", recipeDisplayName(save.name, "未命名存档"));
      option.value = save.file_name || "";
      option.selected = Boolean(selected && save.file_name === selected.file_name);
      select.append(option);
    });
    select.disabled = !selected;
  }

  function compactRecipeItems(items, emptyText = "无") {
    if (!Array.isArray(items) || !items.length) return emptyText;
    const merged = new Map();
    items.forEach((item) => {
      const key = item && item.item_id !== undefined
        ? String(item.item_id)
        : recipeItemName(item);
      const current = merged.get(key);
      if (current) {
        current.count += Number(item && item.count) > 0 ? Number(item.count) : 1;
        return;
      }
      merged.set(key, {
        name: recipeItemName(item),
        count: Number(item && item.count) > 0 ? Number(item.count) : 1,
      });
    });
    return Array.from(merged.values())
      .map((item) => item.count > 1 ? `${item.name} ×${item.count}` : item.name)
      .join("、");
  }

  function recipeKindLabel(result) {
    if (result && result.recipe_kind_label_zh) {
      return String(result.recipe_kind_label_zh);
    }
    return Array.isArray(result && result.candidate_group) ? "通用菜肴" : "特色菜肴";
  }

  function recipeNearSummary(result) {
    const missingItems = Array.isArray(result && result.missing_items)
      ? result.missing_items
      : [];
    const missingCategory = result && result.missing_sub_category;
    const missing = missingItems.length
      ? compactRecipeItems(missingItems)
      : recipeDisplayName(missingCategory && missingCategory.name, "食材");
    const available = compactRecipeItems(
      result && result.available_combination,
      "尚无可用组合",
    );
    return `缺少：${missing}；当前：${available}`;
  }

  function renderRecipeResult(result, { near = false } = {}) {
    const card = makeElement("article", `recipe-match${near ? " recipe-near-match" : ""}`);
    const primary = makeElement("div", "recipe-match-line recipe-match-line-primary");
    const name = makeElement(
      "strong",
      "recipe-match-name",
      recipeDisplayName(result.name, "未命名菜肴"),
    );
    const badge = makeElement(
      "span",
      `recipe-kind recipe-kind-${result.recipe_kind || (Array.isArray(result.candidate_group) ? "generic" : "specific")}`,
      recipeKindLabel(result),
    );
    primary.append(name, badge);
    const secondaryText = near
      ? recipeNearSummary(result)
      : `食材：${compactRecipeItems(result.representative_combination, "尚无可用组合")}`;
    const secondary = makeElement(
      "div",
      "recipe-match-line recipe-match-line-secondary",
      secondaryText,
    );
    secondary.title = secondaryText;
    name.title = recipeDisplayName(result.name, "未命名菜肴");
    card.append(primary, secondary);
    return card;
  }

  function renderRecipeSave(save) {
    const panel = makeElement("article", "recipe-save-panel");
    const heading = makeElement("div", "recipe-save-heading");
    const title = makeElement("div", "recipe-save-title");
    title.append(
      makeElement("h4", "recipe-save-name", recipeDisplayName(save.name, "未命名存档")),
    );
    const statusText = save.status === "ok" ? "已读取" : save.status === "missing" ? "存档缺失" : "读取失败";
    heading.append(title, makeElement("span", `recipe-status ${save.status || "error"}`, statusText));
    panel.append(heading);
    const meta = makeElement("div", "recipe-save-meta");
    meta.append(
      makeElement("span", "recipe-meta-item", save.mode || "未知模式"),
      makeElement("span", "recipe-meta-item", `第 ${Number(save.max_day || 0)} 天`),
    );
    panel.append(meta);

    const inventoryColumn = makeElement("div", "recipe-column recipe-inventory-column");
    const inventorySection = makeElement("section", "recipe-section");
    const inventory = Array.isArray(save.inventory) ? save.inventory : [];
    inventorySection.append(makeElement("h5", "recipe-section-title", "拥有食材"));
    if (!inventory.length) {
      inventorySection.append(makeElement("div", "empty-state compact", save.status === "ok" ? "当前没有可烹饪食材" : "库存暂不可用"));
    } else {
      const list = makeElement("div", "recipe-inventory-list");
      inventory.forEach((item) => {
        const row = makeElement("div", "recipe-inventory-row");
        row.append(
          makeElement("span", "recipe-inventory-name", recipeItemName(item)),
          makeElement("span", "recipe-inventory-count", `× ${item.count}`),
        );
        list.append(row);
      });
      inventorySection.append(list);
    }
    inventoryColumn.append(inventorySection);

    const dishesColumn = makeElement("div", "recipe-column recipe-dishes-column");
    const matchSection = makeElement("section", "recipe-section");
    const matches = Array.isArray(save.matches) ? save.matches : [];
    matchSection.append(
      makeElement("h5", "recipe-section-title", "可烹饪菜肴"),
      makeElement("span", "recipe-match-count", `${matches.length} 道`),
    );
    if (!matches.length) {
      matchSection.append(makeElement("div", "empty-state compact", "没有满足食材与烹饪档位的未完成菜肴"));
    } else {
      const list = makeElement("div", "recipe-match-list");
      matches.forEach((match) => {
        list.append(renderRecipeResult(match));
      });
      matchSection.append(list);
    }
    const nearSection = makeElement("section", "recipe-section recipe-near-section");
    const nearMatches = Array.isArray(save.near_matches) ? save.near_matches : [];
    nearSection.append(
      makeElement("h5", "recipe-section-title", "仅差一个食材"),
      makeElement("span", "recipe-match-count", `${nearMatches.length} 道`),
    );
    if (!nearMatches.length) {
      nearSection.append(makeElement("div", "empty-state compact", "没有仅差一个食材的未完成菜肴"));
    } else {
      const list = makeElement("div", "recipe-match-list");
      nearMatches.forEach((nearMatch) => list.append(renderRecipeResult(nearMatch, { near: true })));
      nearSection.append(list);
    }
    dishesColumn.append(matchSection, nearSection);

    const content = makeElement("div", "recipe-save-content");
    content.append(inventoryColumn, dishesColumn);
    panel.append(content);
    return panel;
  }

  function renderRecipeSaves(payload) {
    const container = byId("recipeSavePanels");
    container.replaceChildren();
    const saves = Array.isArray(payload && payload.saves) ? payload.saves : [];
    const selected = saves.find((save) => save.file_name === state.recipeSaveSelection);
    if (!selected) {
      container.append(makeElement("div", "empty-state", "没有可显示的存档结果"));
      return;
    }
    container.append(renderRecipeSave(selected));
  }

  function renderRecipePlan(payload) {
    state.recipePlan = payload;
    renderRecipeSelector(payload);
    renderRecipeSaves(payload);
  }

  function captureRecipeScrollPositions() {
    return Array.from(document.querySelectorAll("#recipeSavePanels .recipe-column"))
      .map((column) => column.scrollTop);
  }

  function restoreRecipeScrollPositions(positions) {
    if (!Array.isArray(positions)) return;
    window.requestAnimationFrame(() => {
      document.querySelectorAll("#recipeSavePanels .recipe-column").forEach((column, index) => {
        if (positions[index] !== undefined) column.scrollTop = positions[index];
      });
    });
  }

  function resetRecipeScrollPositions() {
    document.querySelectorAll("#recipeSavePanels .recipe-column").forEach((column) => {
      column.scrollTop = 0;
    });
  }

  async function loadRecipePlans() {
    const requestId = ++state.recipeRequest;
    byId("recipeView").classList.add("is-loading");
    try {
      const payload = await requestJson("/api/recipe-plans");
      if (requestId !== state.recipeRequest) return;
      if (
        state.recipePlan
        && payload
        && payload.status !== "error"
        && state.recipePlan.revision
        && payload.revision === state.recipePlan.revision
      ) {
        return;
      }
      const selectedSaveBeforeRender = state.recipeSaveSelection;
      const scrollPositions = captureRecipeScrollPositions();
      renderRecipePlan(payload);
      if (state.recipeSaveSelection === selectedSaveBeforeRender) {
        restoreRecipeScrollPositions(scrollPositions);
      }
    } catch (error) {
      if (requestId !== state.recipeRequest) return;
      renderRecipePlan({ status: "error", saves: [], diagnostics: [error.message] });
    } finally {
      if (requestId === state.recipeRequest) byId("recipeView").classList.remove("is-loading");
    }
  }

  function renderDetailEmpty(message) {
    const content = byId("detailContent");
    content.replaceChildren(makeElement("div", "empty-state", message));
  }

  function renderDetail(payload) {
    const content = byId("detailContent");
    content.replaceChildren();
    if (!payload || !payload.entry) {
      renderDetailEmpty("选择一个条目查看详情");
      return;
    }

    const entry = payload.entry;
    const heading = makeElement("div", "detail-heading");
    heading.append(
      makeElement("h4", "detail-name", entry.name),
      makeElement("div", "detail-source", `${entry.source_table} · ID ${entry.source_id}`),
    );
    const status = makeElement(
      "span",
      `detail-status ${entry.completed ? "completed" : "pending"}`,
      entry.completed ? "已解锁" : "未解锁",
    );
    heading.append(status);
    content.append(heading);

    if (payload.highlights && payload.highlights.length) {
      const highlightSection = makeElement("section", "detail-section detail-highlights");
      highlightSection.append(makeElement("h5", "detail-section-title", "重点信息"));
      const highlightTable = makeElement("dl", "highlight-table");
      payload.highlights.forEach((field) => {
        highlightTable.append(
          makeElement("dt", "highlight-label", field.label),
          makeElement("dd", "highlight-value", field.value),
        );
      });
      highlightSection.append(highlightTable);
      content.append(highlightSection);
    }

    const excludedPrefixes = payload.highlight_relation_prefixes || [];
    const extraRelations = (payload.relations || []).filter(
      (relation) => !excludedPrefixes.some(
        (prefix) => relation.relation_type === prefix || relation.relation_type.startsWith(`${prefix}（`),
      ),
    );
    const extraFields = payload.fields || [];
    if (extraRelations.length || extraFields.length) {
      const details = makeElement("details", "detail-collapse");
      details.append(makeElement("summary", "detail-collapse-summary", "其余词条"));
      const extraContent = makeElement("div", "detail-extra-content");
      if (extraRelations.length) {
        const relationSection = makeElement("section", "detail-section");
        relationSection.append(makeElement("h5", "detail-section-title", "关联数据"));
        const groups = new Map();
        extraRelations.forEach((relation) => {
          if (!groups.has(relation.relation_type)) groups.set(relation.relation_type, []);
          groups.get(relation.relation_type).push(
            `${relation.target_name}（ID ${relation.target_id}）`,
          );
        });
        groups.forEach((values, relationType) => {
          const row = makeElement("div", "relation-row");
          row.append(
            makeElement("span", "relation-label", relationType),
            makeElement("span", "relation-value", values.join("、")),
          );
          relationSection.append(row);
        });
        extraContent.append(relationSection);
      }

      if (extraFields.length) {
        const fieldSection = makeElement("section", "detail-section");
        fieldSection.append(makeElement("h5", "detail-section-title", "配置字段"));
        const fieldTable = makeElement("dl", "field-table");
        extraFields.forEach((field) => {
          fieldTable.append(
            makeElement("dt", "field-label", field.label),
            makeElement("dd", "field-value", field.value),
          );
        });
        fieldSection.append(fieldTable);
        extraContent.append(fieldSection);
      }
      details.append(extraContent);
      content.append(details);
    }
  }

  async function loadDetail(entryKey) {
    const requestId = ++state.detailRequest;
    if (!entryKey) {
      renderDetailEmpty("选择一个条目查看详情");
      return;
    }
    byId("detailContent").classList.add("is-loading");
    try {
      const query = new URLSearchParams({ category: state.category });
      const payload = await requestJson(`/api/entries/${encodeURIComponent(entryKey)}?${query}`);
      if (requestId === state.detailRequest) renderDetail(payload);
    } catch (error) {
      if (requestId === state.detailRequest) renderDetailEmpty(error.message);
    } finally {
      if (requestId === state.detailRequest) byId("detailContent").classList.remove("is-loading");
    }
  }

  async function loadEntries() {
    const requestId = ++state.entriesRequest;
    byId("entryList").classList.add("is-loading");
    const query = new URLSearchParams({
      category: state.category,
      name_search: state.nameSearch,
      material_search: state.materialSearch,
      completion: state.completion,
    });
    try {
      const payload = await requestJson(`/api/entries?${query}`);
      if (requestId !== state.entriesRequest) return;
      state.entries = payload.entries || [];
      if (!state.entries.some((entry) => entry.entry_key === state.selectedKey)) {
        state.selectedKey = state.entries.length ? state.entries[0].entry_key : null;
      }
      renderEntries();
      await loadDetail(state.selectedKey);
    } catch (error) {
      if (requestId === state.entriesRequest) {
        state.entries = [];
        byId("entryList").replaceChildren(makeElement("div", "error-state", error.message));
        renderHeader();
        renderDetailEmpty("条目详情暂不可用");
      }
    } finally {
      if (requestId === state.entriesRequest) byId("entryList").classList.remove("is-loading");
    }
  }

  function showToast(message) {
    const toast = byId("toast");
    toast.textContent = message;
    toast.classList.add("visible");
    window.clearTimeout(showToast.timer);
    showToast.timer = window.setTimeout(() => toast.classList.remove("visible"), 3600);
  }

  async function refreshState(initial) {
    if (state.polling) return;
    state.polling = true;
    try {
      const payload = await requestJson("/api/state");
      const revisionChanged = state.revision !== null && state.revision !== payload.sync.revision;
      state.categories = payload.categories || [];
      state.overall = payload.overall || { completed: 0, total: 0 };
      state.metadata = payload.metadata || {};
      state.sync = payload.sync || null;
      state.revision = payload.sync ? payload.sync.revision : null;
      renderCategories();
      renderProgress();
      renderSource();
      renderSync();
      renderFilters();
      renderSearchControls();
      renderMainView();

      if (state.category === "recipes") {
        await loadRecipePlans();
      } else if (initial || revisionChanged || !state.loaded) {
        await loadEntries();
      } else {
        renderHeader();
      }
      state.loaded = true;
      if (revisionChanged) showToast("检测到存档变化，图鉴已自动同步");
    } catch (error) {
      setStatusNode(byId("syncStatus"), "error", "本地服务连接失败");
      setStatusNode(byId("headerSync"), "error", "本地服务连接失败");
      if (!state.loaded) {
        byId("entryList").replaceChildren(makeElement("div", "error-state", error.message));
      }
    } finally {
      state.polling = false;
    }
  }

  function notifyLocalServerOfPageExit(event) {
    if (event.persisted) return;
    const closeUrl = `/api/client/closed?client_id=${encodeURIComponent(CLIENT_ID)}`;
    if (navigator.sendBeacon && navigator.sendBeacon(closeUrl)) return;
    void fetch(closeUrl, {
      method: "POST",
      cache: "no-store",
      keepalive: true,
    }).catch(() => {});
  }

  function bindEvents() {
    byId("categoryNav").addEventListener("click", (event) => {
      const button = event.target.closest("[data-category]");
      if (!button) return;
      const category = button.dataset.category;
      if (!category || category === state.category) return;
      state.category = category;
      state.selectedKey = null;
      renderCategories();
      renderSearchControls();
      renderMainView();
      if (category === "recipes") loadRecipePlans();
      else loadEntries();
    });

    byId("filterGroup").addEventListener("click", (event) => {
      const button = event.target.closest("[data-filter]");
      if (!button || button.dataset.filter === state.completion) return;
      state.completion = button.dataset.filter;
      state.selectedKey = null;
      renderFilters();
      if (state.category !== "recipes") loadEntries();
    });

    function scheduleSearch() {
      window.clearTimeout(bindEvents.searchTimer);
      bindEvents.searchTimer = window.setTimeout(() => {
        state.selectedKey = null;
        if (state.category !== "recipes") loadEntries();
      }, 180);
    }

    byId("nameSearchInput").addEventListener("input", (event) => {
      state.nameSearch = event.target.value;
      scheduleSearch();
    });

    byId("materialSearchInput").addEventListener("input", (event) => {
      state.materialSearch = event.target.value;
      scheduleSearch();
    });

    byId("clearTextFilters").addEventListener("click", () => {
      state.nameSearch = "";
      state.materialSearch = "";
      state.selectedKey = null;
      byId("nameSearchInput").value = "";
      byId("materialSearchInput").value = "";
      if (state.category !== "recipes") loadEntries();
    });

    byId("recipeSaveSelect").addEventListener("change", (event) => {
      if (!state.recipePlan) return;
      state.recipeSaveSelection = event.target.value || "";
      resetRecipeScrollPositions();
      renderRecipeSaves(state.recipePlan);
    });

    function selectEntry(target) {
      if (!target) return;
      state.selectedKey = target.dataset.entryKey;
      renderEntries();
      loadDetail(state.selectedKey);
    }

    byId("entryList").addEventListener("click", (event) => {
      const target = event.target instanceof Element ? event.target : null;
      selectEntry(target && target.closest("[data-entry-key]"));
    });

    byId("entryList").addEventListener("keydown", (event) => {
      if (event.key !== "Enter" && event.key !== " ") return;
      const target = event.target instanceof Element ? event.target.closest("[data-entry-key]") : null;
      if (!target) return;
      event.preventDefault();
      selectEntry(target);
    });

    document.addEventListener("visibilitychange", () => {
      if (document.visibilityState === "visible") refreshState(false);
    });
    window.addEventListener("pageshow", () => refreshState(false));
    window.addEventListener("pagehide", notifyLocalServerOfPageExit);
  }

  bindEvents();
  refreshState(true);
  window.setInterval(() => refreshState(false), FALLBACK_POLL_INTERVAL);
})();
