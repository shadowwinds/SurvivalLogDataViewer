(() => {
  "use strict";

  const $ = (id) => document.getElementById(id);
  const mobile = matchMedia("(max-width: 650px)");
  const state = { categories: [], category: "food", key: "", entries: [], debounce: null };
  const icons = {
    food: '<path d="M5 10c-4-3-1-7 3-6 2-2 5-2 7 0 4-1 7 3 3 6v9H5z"/><path d="M9 11v4m5-4v4"/>',
    dish: '<path d="M3 12h18a9 9 0 0 1-18 0zM8 21h8M9 3c-3 3 3 3 0 6m6-6c-3 3 3 3 0 6"/>',
    plant: '<path d="M12 21v-9M12 14C4 14 3 10 3 5c7 0 9 3 9 9zM12 11c0-6 3-8 9-8 0 6-3 8-9 8z"/>',
    prey: '<ellipse cx="12" cy="16" rx="5" ry="4"/><ellipse cx="5" cy="9" rx="2" ry="3"/><ellipse cx="10" cy="5" rx="2" ry="3"/><ellipse cx="16" cy="5" rx="2" ry="3"/><ellipse cx="20" cy="10" rx="2" ry="3"/>',
    craft: '<path d="M14 4a6 6 0 0 0-8 8L3 18l3 3 6-3a6 6 0 0 0 8-8l-5 3-4-4z"/>',
    furniture: '<path d="M5 11V6a2 2 0 0 1 2-2h10a2 2 0 0 1 2 2v5M5 17v4m14-4v4M3 11h3v4h12v-4h3v7H3z"/>',
    achievements: '<path d="M7 3h10v7a5 5 0 0 1-10 0zM7 5H3v3a4 4 0 0 0 4 4m10-7h4v3a4 4 0 0 1-4 4M12 15v5m-4 1h8"/>',
  };

  function clean(value) {
    return String(value ?? "").replace(/<\/?(?:color|size|b|i)(?:=[^>]*)?>/gi, "");
  }

  function normalize(value) {
    return clean(value).normalize("NFKC").toLocaleLowerCase("zh-CN").trim();
  }

  function node(tag, className, text) {
    const element = document.createElement(tag);
    if (className) element.className = className;
    if (text !== undefined) element.textContent = clean(text);
    return element;
  }

  function category() {
    return state.categories.find((item) => item.id === state.category);
  }

  function urlFor(categoryId, key) {
    return `#${categoryId}/${encodeURIComponent(key)}`;
  }

  function setUrl() {
    history.replaceState(null, "", urlFor(state.category, state.key));
  }

  function buildNav() {
    const fragment = document.createDocumentFragment();
    for (const item of state.categories) {
      const button = node("button", "category-button");
      button.type = "button";
      button.dataset.category = item.id;
      button.setAttribute("aria-label", `${item.label}，${item.entries.length} 条`);
      const icon = node("span", "nav-icon");
      icon.setAttribute("aria-hidden", "true");
      icon.innerHTML = `<svg viewBox="0 0 24 24">${icons[item.id] || ""}</svg>`;
      button.append(icon, node("span", "category-label", item.label), node("span", "category-count", item.entries.length));
      button.addEventListener("click", () => {
        if (state.category === item.id) return;
        location.hash = urlFor(item.id, item.entries[0]?.key || "");
      });
      fragment.append(button);
    }
    $("categoryNav").replaceChildren(fragment);
  }

  function filteredEntries() {
    const name = normalize($("nameSearch").value);
    const material = $("materialField").hidden ? "" : normalize($("materialSearch").value);
    return category().entries.filter((entry) => entry.nameIndex.includes(name) && entry.materialIndex.includes(material));
  }

  function preview(entry) {
    if (state.category === "achievements") return entry.highlights[0]?.value || entry.description;
    return entry.highlights.map((field) => `${field.label}：${field.value}`).join(" · ") || entry.description;
  }

  function renderList() {
    const fragment = document.createDocumentFragment();
    state.entries.forEach((entry) => {
      const button = node("button", "entry-card");
      button.type = "button";
      button.dataset.key = entry.key;
      button.classList.toggle("active", entry.key === state.key);
      button.setAttribute("aria-pressed", String(entry.key === state.key));
      button.setAttribute("aria-label", `${entry.name}，ID ${entry.id}`);
      const meta = node("span", "entry-meta");
      meta.append(node("span", "", `NO. ${String(entry.id).padStart(4, "0")}`));
      if (entry.hidden) meta.append(node("span", "entry-tag", "隐藏成就"));
      else if (entry.group) meta.append(node("span", "entry-tag", entry.group));
      button.append(meta, node("span", "entry-name", entry.name), node("span", "entry-description", preview(entry)));
      button.addEventListener("click", () => selectEntry(entry.key, true));
      fragment.append(button);
    });
    $("entryList").replaceChildren(fragment);
    $("entryList").setAttribute("aria-busy", "false");
    $("emptyState").hidden = state.entries.length !== 0;
    $("resultCount").textContent = `显示 ${state.entries.length} / ${category().entries.length} 条`;
  }

  function addNotes(container, title, values) {
    if (!values?.length) return;
    const section = node("section", "detail-section");
    section.append(node("h3", "section-title", title));
    const list = node("ul", "notes-list");
    values.forEach((value) => list.append(node("li", "", value)));
    section.append(list);
    container.append(section);
  }

  function renderDetail() {
    const entry = state.entries.find((item) => item.key === state.key);
    if (!entry) {
      const empty = node("div", "detail-placeholder");
      empty.append(node("span", "", "SL"), node("p", "", "选择条目，查看图鉴详情。"));
      $("detailContent").replaceChildren(empty);
      $("detailPosition").textContent = "条目详情 / DETAIL";
      return;
    }
    const fragment = document.createDocumentFragment();
    fragment.append(node("div", "detail-category", `${category().label}${entry.hidden ? " / 隐藏成就" : ""}`));
    const title = node("div", "detail-title-row");
    const heading = node("h2", "", entry.name);
    heading.id = "detailName";
    title.append(heading, node("span", "detail-id", `ID ${entry.id}`));
    fragment.append(title);
    if (entry.description) fragment.append(node("p", "detail-description", entry.description));
    if (entry.highlights.some((field) => field.value)) {
      const highlights = node("dl", "highlights");
      entry.highlights.forEach((field) => {
        if (!field.value) return;
        const row = node("div", "highlight-row");
        row.append(node("dt", "", field.label), node("dd", "", field.value));
        highlights.append(row);
      });
      fragment.append(highlights);
    }
    if (entry.relations.length) {
      const section = node("section", "detail-section");
      section.append(node("h3", "section-title", "关联配置"));
      const groups = new Map();
      for (const relation of entry.relations) {
        if (!groups.has(relation.relation_type)) groups.set(relation.relation_type, new Map());
        const key = `${relation.target_table}:${relation.target_id}`;
        const group = groups.get(relation.relation_type);
        if (group.has(key)) group.get(key).quantity += 1;
        else group.set(key, { ...relation, quantity: 1 });
      }
      for (const [label, relations] of groups) {
        const group = node("div", "relation-group");
        group.append(node("div", "relation-label", label));
        const values = node("div", "relation-values");
        for (const relation of relations.values()) {
          const item = node(relation.link ? "a" : "span", "relation-item");
          item.append(node("span", "", `${relation.target_name || `ID:${relation.target_id}`}${relation.quantity > 1 ? ` × ${relation.quantity}` : ""}`));
          item.append(node("span", "relation-id", `#${relation.target_id}`));
          item.title = `${relation.target_table} / ID ${relation.target_id}`;
          if (relation.link) item.href = urlFor(relation.link.category, relation.link.key);
          values.append(item);
        }
        group.append(values);
        section.append(group);
      }
      fragment.append(section);
    }
    addNotes(fragment, "注意事项", entry.notes);
    addNotes(fragment, "排除项", entry.exclusions);
    addNotes(fragment, "配置引用", entry.references);
    const details = node("details", "raw-details");
    details.append(node("summary", "", `全部配置字段 · ${entry.fields.length}`));
    const fields = node("dl", "config-fields");
    entry.fields.forEach((field) => {
      const row = node("div", "config-row");
      const label = node("dt", "", field.label);
      if (field.field !== field.label) label.append(node("small", "", field.field));
      row.append(label, node("dd", "", field.value));
      fields.append(row);
    });
    details.append(fields);
    fragment.append(details);
    fragment.append(node("div", "detail-source", `${entry.source_table} / ${entry.name_key || `ID:${entry.id}`}${entry.source_version ? ` · 成就说明参考版本 ${entry.source_version}` : ""}`));
    $("detailContent").replaceChildren(fragment);
    $("detailContent").scrollTop = 0;
    $("detailPosition").textContent = `${String(state.entries.indexOf(entry) + 1).padStart(2, "0")} / ${state.entries.length} · 条目详情`;
  }

  function selectEntry(key, openMobile = false) {
    state.key = key;
    setUrl();
    document.querySelectorAll(".entry-card").forEach((button) => {
      const active = button.dataset.key === key;
      button.classList.toggle("active", active);
      button.setAttribute("aria-pressed", String(active));
    });
    renderDetail();
    if (mobile.matches && openMobile) {
      if ($("detailPanel").open) $("detailPanel").close();
      $("detailPanel").showModal();
    }
  }

  function render() {
    const current = category();
    if (!current) return;
    $("categoryTitle").textContent = current.label;
    $("categoryTotal").textContent = current.entries.length;
    document.title = `${current.label} · 生存日志在线图鉴`;
    const materialEnabled = ["dish", "craft", "furniture"].includes(current.id);
    $("materialField").hidden = !materialEnabled;
    $("searchForm").classList.toggle("no-material", !materialEnabled);
    $("searchForm").querySelector(".hint").hidden = !materialEnabled;
    document.querySelectorAll(".category-button").forEach((button) => {
      const active = button.dataset.category === current.id;
      button.classList.toggle("active", active);
      if (active) button.setAttribute("aria-current", "page");
      else button.removeAttribute("aria-current");
    });
    state.entries = filteredEntries();
    if (!state.entries.some((entry) => entry.key === state.key)) state.key = state.entries[0]?.key || "";
    setUrl();
    renderList();
    renderDetail();
  }

  function resetSearch() {
    $("nameSearch").value = "";
    $("materialSearch").value = "";
    render();
    $("nameSearch").focus();
  }

  function readHash(openMobile = false) {
    let categoryId, key;
    try {
      [categoryId, key] = location.hash.slice(1).split("/").map(decodeURIComponent);
    } catch {
      categoryId = "food";
    }
    if (!state.categories.some((item) => item.id === categoryId)) categoryId = "food";
    if (categoryId !== state.category) {
      $("nameSearch").value = "";
      $("materialSearch").value = "";
      $("entryList").scrollTop = 0;
    }
    state.category = categoryId;
    state.key = key || "";
    if (key && category().entries.some((entry) => entry.key === key) && !filteredEntries().some((entry) => entry.key === key)) {
      $("nameSearch").value = "";
      $("materialSearch").value = "";
    }
    render();
    if (mobile.matches && openMobile && key && state.entries.some((entry) => entry.key === key)) {
      selectEntry(key, true);
    }
  }

  async function load() {
    $("loadError").hidden = true;
    $("resultCount").textContent = "正在读取图鉴…";
    $("entryList").setAttribute("aria-busy", "true");
    try {
      const response = await fetch(new URL("./data.json", location.href));
      if (!response.ok) throw new Error(`数据请求失败（HTTP ${response.status}）`);
      const data = await response.json();
      if (data.format_version !== 1 || !Array.isArray(data.categories) || !data.categories.length) throw new Error("图鉴数据格式不匹配");
      state.categories = data.categories;
      for (const item of state.categories) {
        for (const entry of item.entries) {
          entry.nameIndex = normalize(`${entry.name} ${entry.name_key} ${entry.id}`);
          entry.materialIndex = normalize(entry.relations.filter((relation) => /^(具体食材|食材分类|制造材料)/.test(relation.relation_type)).map((relation) => `${relation.target_name} ${relation.target_id}`).join(" "));
        }
      }
      $("gameVersion").textContent = `游戏版本 ${data.metadata.game_version || "未标注"}`;
      $("footerVersion").textContent = `数据版本 ${data.metadata.game_version || "未标注"}`;
      $("gameVersion").title = "此网页使用仓库中的公开数据快照，不会自动跟随本机游戏更新";
      buildNav();
      readHash(Boolean(location.hash));
      ["nameSearch", "materialSearch", "resetSearch"].forEach((id) => { $(id).disabled = false; });
    } catch (error) {
      $("loadError").hidden = false;
      $("errorMessage").textContent = `${error.message}。请稍后重试。`;
      $("resultCount").textContent = "加载失败";
      $("entryList").setAttribute("aria-busy", "false");
    }
  }

  ["nameSearch", "materialSearch"].forEach((id) => $(id).addEventListener("input", () => {
    clearTimeout(state.debounce);
    state.debounce = setTimeout(render, 100);
  }));
  $("searchForm").addEventListener("submit", (event) => event.preventDefault());
  $("resetSearch").addEventListener("click", resetSearch);
  $("emptyReset").addEventListener("click", resetSearch);
  $("closeDetail").addEventListener("click", () => $("detailPanel").close());
  $("detailPanel").addEventListener("close", () => {
    const selected = Array.from(document.querySelectorAll(".entry-card")).find((button) => button.dataset.key === state.key);
    selected?.focus({ preventScroll: true });
  });
  $("retryLoad").addEventListener("click", load);
  window.addEventListener("hashchange", () => { if (state.categories.length) readHash(true); });
  mobile.addEventListener("change", () => {
    if (mobile.matches) $("detailPanel").close();
    else { if ($("detailPanel").open) $("detailPanel").close(); $("detailPanel").show(); }
  });
  if (mobile.matches) $("detailPanel").close();
  load();
})();
