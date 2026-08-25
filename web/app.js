(function () {
  "use strict";

  const FALLBACK_POLL_INTERVAL = 5000;
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
      headers: { Accept: "application/json" },
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
        `${category.completed}/${category.total}`,
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
    byId("gameVersion").textContent = `游戏版本 ${version}`;
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
      body.append(
        makeElement("div", "entry-name", entry.name),
        makeElement("div", "entry-meta", `${entry.source_table} · ID ${entry.source_id}`),
      );
      if (entry.highlight_summary) {
        body.append(makeElement("div", "entry-highlight", entry.highlight_summary));
      }

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

      if (initial || revisionChanged || !state.loaded) {
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
      loadEntries();
    });

    byId("filterGroup").addEventListener("click", (event) => {
      const button = event.target.closest("[data-filter]");
      if (!button || button.dataset.filter === state.completion) return;
      state.completion = button.dataset.filter;
      state.selectedKey = null;
      renderFilters();
      loadEntries();
    });

    function scheduleSearch() {
      window.clearTimeout(bindEvents.searchTimer);
      bindEvents.searchTimer = window.setTimeout(() => {
        state.selectedKey = null;
        loadEntries();
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
  }

  bindEvents();
  refreshState(true);
  window.setInterval(() => refreshState(false), FALLBACK_POLL_INTERVAL);
})();
