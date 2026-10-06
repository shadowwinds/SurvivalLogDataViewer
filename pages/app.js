(() => {
  "use strict";

  const $ = (id) => document.getElementById(id);
  const i18n = window.I18n;
  const locale = () => i18n?.locale || "zh-CN";
  const mobile = matchMedia("(max-width: 720px)");
  const state = { categories: [], category: "food", key: "", entries: [], effect: "", debounce: null, ingredients: [], materials: [], group: "", tier: "", craftGroup: "", materialId: null, materialUses: new Map(), craftNoteNames: {}, furniturePageNames: {}, planters: [], plantingEnvironment: null, stock: {}, cookingModel: null, pantryPlans: new Map(), pantryPlanKey: "", dataVersion: "", preyModel: null, preyModelPromise: null, preyModelFailed: false, preyById: new Map(), trapById: new Map(), baitById: new Map(), roomById: new Map() };
  const preyModes = new Set(["prey", "traps", "baits", "cages"]);
  const preyModeHelp = {
    prey: "先看哪些陷阱能抓到、放什么诱饵最有效；食用属性移到了后面。",
    traps: "比较耐久、检查间隔与各猎物的基础概率；点击猎物可查看推荐诱饵。",
    baits: "搜索手头的食物或专用诱饵，看它对哪些猎物更有效。",
    cages: "活捉笼抓到的活鼠放进老鼠笼，投喂食物就能持续发电。",
  };
  const qualities = ["普通", "良好", "完美", "失败"];
  const statLabels = ["饱腹", "心态", "精力", "健康", "生命"];
  const tierLabels = { 1: "高档", 2: "中档", 3: "低档" };
  const qualityName = (value) => value === "良好" ? "优良" : value;
  const titles = { food: "烹饪食材", "ready-food": "即食食品", dish: "菜肴与效果", plant: "种植手册", prey: "猎物图鉴", traps: "陷阱图鉴", baits: "诱饵图鉴", cages: "老鼠笼发电", craft: "制造手册", furniture: "家具与设施", books: "书籍列表", achievements: "成就指南" };
  const intros = {
    food: "看属性、查标签，掌握每份食材的可用次数。",
    "ready-food": "不用于烹饪的食品与饮品，直接查看食用次数与效果。",
    dish: "先看吃完的效果，再决定今天做什么。",
    plant: "选天气、位置与供暖，查现在能种什么。",
    prey: "先看哪些陷阱能抓到、放什么诱饵最有效。",
    traps: "比较耐久、检查间隔与各猎物的基础概率。",
    baits: "搜索手头的食物或专用诱饵，看它对哪些猎物更有效。",
    cages: "活鼠跑笼发电：容量、电力与饲养消耗。",
    craft: "材料与产物，一次查清。",
    furniture: "从生活设施到生存据点。",
    books: "可阅读的书籍：技能、属性与染料手记。",
    achievements: "查条件、看方法，补齐你的生存记录。",
  };
  const icons = {
    food: '<path d="M5 10c-4-3-1-7 3-6 2-2 5-2 7 0 4-1 7 3 3 6v9H5z"/><path d="M9 11v4m5-4v4"/>',
    dish: '<path d="M3 12h18a9 9 0 0 1-18 0zM8 21h8M9 3c-3 3 3 3 0 6m6-6c-3 3 3 3 0 6"/>',
    plant: '<path d="M12 21v-9M12 14C4 14 3 10 3 5c7 0 9 3 9 9zM12 11c0-6 3-8 9-8 0 6-3 8-9 8z"/>',
    prey: '<ellipse cx="12" cy="16" rx="5" ry="4"/><ellipse cx="5" cy="9" rx="2" ry="3"/><ellipse cx="10" cy="5" rx="2" ry="3"/><ellipse cx="16" cy="5" rx="2" ry="3"/><ellipse cx="20" cy="10" rx="2" ry="3"/>',
    craft: '<path d="M14 4a6 6 0 0 0-8 8L3 18l3 3 6-3a6 6 0 0 0 8-8l-5 3-4-4z"/>',
    furniture: '<path d="M5 11V6a2 2 0 0 1 2-2h10a2 2 0 0 1 2 2v5M5 17v4m14-4v4M3 11h3v4h12v-4h3v7H3z"/>',
    books: '<path d="M5 19.5V6a2 2 0 0 1 2-2h12v14H7a2 2 0 0 0-2 1.5zm0 0A2.5 2.5 0 0 0 7.5 22H19v-4"/>',
    achievements: '<path d="M7 3h10v7a5 5 0 0 1-10 0zM7 5H3v3a4 4 0 0 0 4 4m10-7h4v3a4 4 0 0 1-4 4M12 15v5m-4 1h8"/>',
  };

  function clean(value) {
    return String(value ?? "").replace(/<\/?(?:color|size|b|i)(?:=[^>]*)?>/gi, "");
  }

  function normalize(value) {
    return clean(value).normalize("NFKC").toLocaleLowerCase("zh-CN").trim();
  }

  function searchIndex(values) {
    return normalize(values.filter(value => value !== undefined && value !== null)
      .flatMap(value => [value, i18n?.english(value) || value]).join(" "));
  }

  function tierBadge(tier) {
    return node("span", "tier-badge tier-" + (tier || "none"), tierLabels[tier] || "不影响档位");
  }

  function node(tag, className, text) {
    const element = document.createElement(tag);
    if (className) element.className = className;
    if (text !== undefined) element.textContent = clean(text);
    return element;
  }

  function icon(categoryId) {
    const span = node("span", "nav-icon");
    span.setAttribute("aria-hidden", "true");
    span.innerHTML = '<svg viewBox="0 0 24 24">' + (icons[categoryId] || icons.food) + "</svg>";
    return span;
  }

  function art(src, categoryId = state.category, detail = false) {
    const wrapper = node("span", "entry-art" + (detail ? " detail-art" : ""));
    wrapper.setAttribute("aria-hidden", "true");
    const fallback = () => {
      const badge = wrapper.querySelector(".icon-uses");
      wrapper.replaceChildren(icon(categoryId));
      if (badge) wrapper.append(badge);
      wrapper.title = badge?.title || "暂无物品图标";
    };
    if (/^\.\/icons\/[a-f0-9]{20}\.png$/.test(src || "")) {
      const image = node("img");
      image.src = src;
      image.alt = "";
      image.loading = detail ? "eager" : "lazy";
      image.decoding = "async";
      image.addEventListener("error", fallback, { once: true });
      wrapper.append(image);
    } else fallback();
    return wrapper;
  }

  const percent = (value) => Number.isFinite(value) ? Math.round(value * 100) + "%" : "—";
  const stars = (rarity) => rarity > 0 ? "★".repeat(rarity) : "";

  function ensurePreyModel() {
    if (state.preyModel || state.preyModelFailed) return Promise.resolve();
    if (!state.preyModelPromise) {
      state.preyModelPromise = fetch(new URL("./prey-model.json", location.href))
        .then((response) => response.ok ? response.json() : Promise.reject(new Error(String(response.status))))
        .then((model) => {
          if (!model || model.format_version !== 1 || model.game_version !== state.dataVersion) {
            throw new Error("prey model version mismatch");
          }
          state.preyModel = model;
          state.preyById = new Map(model.prey.map((entry) => [entry.id, entry]));
          state.trapById = new Map(model.traps.map((trap) => [trap.id, trap]));
          state.baitById = new Map(model.baits.map((bait) => [bait.id, bait]));
          state.roomById = new Map(model.rooms.map((room) => [room.id, room]));
          state.categories.push(
            { id: "traps", label: "陷阱图鉴", entries: model.traps.map((trap) => ({
                key: "Trap:" + trap.id, id: trap.id, source_table: "Config_Trap", name: trap.name,
                description: trap.description, icon: trap.icon, trap,
                highlights: [], relations: [], fields: [],
                nameIndex: searchIndex([trap.name, trap.id, trap.description]) })) },
            { id: "baits", label: "诱饵图鉴", entries: model.baits.map((bait) => ({
                key: "Bait:" + bait.id, id: bait.id, source_table: "Config_TrapBait", name: bait.name,
                icon: model.bait_icons[bait.icon] || "", bait,
                highlights: [], relations: [], fields: [],
                nameIndex: searchIndex([bait.name, bait.id]) })) },
            { id: "cages", label: "老鼠笼发电", entries: model.cages.map((cage) => ({
                key: "Cage:" + cage.id, id: cage.id, source_table: "Config_Furniture", name: cage.name,
                description: cage.description, icon: cage.icon, cage,
                highlights: [], relations: [], fields: [],
                nameIndex: searchIndex([cage.name, cage.id, cage.description]) })) },
          );
          buildNav();
          configureControls();
          readHash(false);
        })
        .catch(() => { state.preyModelFailed = true; });
    }
    return state.preyModelPromise;
  }

  function category(id = state.category) {
    return state.categories.find((item) => item.id === id);
  }

  function craftGroupId(categoryId, entry) {
    return categoryId === "craft" ? entry.note_category : categoryId === "furniture" ? entry.shop_page : null;
  }

  function craftGroupName(categoryId, entry) {
    const names = categoryId === "craft" ? state.craftNoteNames : state.furniturePageNames;
    return names[craftGroupId(categoryId, entry)] || "";
  }

  function urlFor(categoryId, key) {
    return "#" + categoryId + "/" + encodeURIComponent(key);
  }

  function setUrl() {
    history.replaceState(null, "", urlFor(state.category, state.key));
  }

  function profile(entry) {
    if (entry.food) return entry.food;
    const estimate = isPantry() ? state.pantryPlans.get(entry.key) : null;
    if (estimate) return {...estimate.product, stats: estimate.total.map((value, index) => ({field: "ValueDisplay" + (index + 1), label: statLabels[index], value})),
      per_use_stats: estimate.perUse.map((value, index) => ({field: "ValueDisplay" + (index + 1), label: statLabels[index], value})), serving_count: estimate.servings};
    const product = entry.products?.find((item) => item.quality === $("qualitySelect").value);
    return product?.per_use_stats ? { ...product, stats: product.per_use_stats } : product;
  }

  function isPantry() { return state.category === "dish" && $("cookingMode").value === "pantry"; }

  function savePantry() {
    try { localStorage.setItem("survival-log-pantry-v1", JSON.stringify(state.stock)); } catch { /* Storage is optional. */ }
  }

  function restorePantry() {
    try {
      const stored = JSON.parse(localStorage.getItem("survival-log-pantry-v1") || "{}");
      for (const item of state.ingredients) if (Number.isInteger(stored?.[item.id]) && stored[item.id] > 0 && stored[item.id] <= 9999) state.stock[item.id] = stored[item.id];
    } catch { /* A damaged local preference does not prevent loading. */ }
  }

  function preparePantry() {
    if (!isPantry()) return;
    const goal = Math.max(0, statLabels.findIndex((_, index) => $("sortSelect").value === "ValueDisplay" + (index + 1)));
    const cacheKey = JSON.stringify([state.stock, $("qualitySelect").value, goal, $("tierFloorSelect").value]);
    if (cacheKey === state.pantryPlanKey) return;
    state.pantryPlans = window.Cooking.plan(category("dish").entries, state.ingredients, state.stock,
      $("qualitySelect").value, goal, Number($("tierFloorSelect").value), state.cookingModel);
    state.pantryPlanKey = cacheKey;
  }

  function comboText(estimate) {
    const counts = new Map();
    for (const item of estimate.ingredients) counts.set(item.id, {item, count: (counts.get(item.id)?.count || 0) + 1});
    return [...counts.values()].map(({item, count}) => (i18n?.language === "en" ? i18n.english(item.name) : item.name) + " × " + count).join(" + ");
  }

  function possiblePots(estimate) {
    const counts = new Map();
    for (const item of estimate.ingredients) counts.set(item.id, (counts.get(item.id) || 0) + 1);
    return Math.min(...[...counts].map(([id, count]) => Math.floor(state.stock[id] / count)));
  }

  function renderPantry() {
    const active = isPantry();
    $("pantryMaterials").hidden = !active;
    $("pantrySummary").hidden = !active;
    $("ingredientFieldLabel").textContent = active ? "冰箱里有哪些食材" : "我想用这些材料";
    $("cookingModeHelp").textContent = active ? "登记两台冰箱的食材与剩余可烹饪次数，自动选组合；排序比较每锅总恢复。" : "所选材料都要用进这一锅；未选满时，结果包含需要补齐的配方。";
    if (!active) return;
    const stocked = state.ingredients.filter(item => state.stock[item.id] > 0);
    $("ingredientSummary").textContent = stocked.length ? "已登记 " + stocked.length + " 种 · 添加食材" : "登记冰箱食材";
    const chips = [];
    for (const item of stocked) {
      const row = node("div", "pantry-item"), label = node("label"), input = node("input");
      input.type = "number"; input.min = "1"; input.max = "9999"; input.step = "1"; input.value = state.stock[item.id];
      input.setAttribute("aria-label", item.name + "可烹饪次数");
      input.addEventListener("input", () => {
        if (!input.validity.valid || !Number.isInteger(input.valueAsNumber)) return;
        state.stock[item.id] = input.valueAsNumber; savePantry(); render(false, true);
      });
      input.addEventListener("change", () => {
        if (!input.validity.valid || !Number.isInteger(input.valueAsNumber)) { input.value = state.stock[item.id]; return; }
      });
      const remove = node("button", "", "×"); remove.type = "button"; remove.setAttribute("aria-label", "移除" + item.name);
      remove.addEventListener("click", () => { delete state.stock[item.id]; savePantry(); render(); renderIngredientOptions(); });
      label.append(node("span", "", item.name), input); row.append(art(item.icon, "food"), label, remove); chips.push(row);
    }
    if (stocked.length) {
      const clear = node("button", "material-chip", "清空冰箱登记"); clear.type = "button";
      clear.addEventListener("click", () => { state.stock = {}; savePantry(); render(); renderIngredientOptions(); }); chips.push(clear);
    }
    $("pantryMaterials").replaceChildren(...chips);
    $("pantrySummary").textContent = stocked.length ? "数量填剩余可烹饪次数，例：野兔 2/3 填 2。各道菜独立比较，共用食材没有扣减；品质按所选情景估算。" : "先登记手头食材，再选烹饪等级和想恢复的属性；食材登记自动保存在本机。";
    if (!state.cookingModel) $("pantrySummary").append(node("span", "", "通用配方计算参数版本不匹配，当前仅推荐效果可确定的专用配方。"));
  }

  function renderCookingRules() {
    const groups = new Map(state.ingredients.filter(item => item.tier_thresholds).map(item => [item.sub_category_id, item]));
    $("cookingThresholds").replaceChildren(...[...groups.values()].sort((a, b) => a.sub_category_id - b.sub_category_id).map(item => {
      const row = node("tr");
      row.append(node("td", "", item.sub_category), node("td", "", item.tier_thresholds.high), node("td", "", item.tier_thresholds.mid));
      return row;
    }));
    $("cookingCoefficients").textContent = state.cookingModel ? "档位系数：高档 1.7 / 中档 1.4 / 低档 1.1；品质系数：失败 0.5 / 普通 0.9 / 优良 1.2 / 完美 1.5。先按游戏 float32 运算再取整，分份后每次属性 = 总属性 ÷ 食用次数。" : "通用配方计算参数版本不匹配，当前仅推荐效果可确定的专用配方。";
  }

  function statValue(entry, field) {
    return profile(entry)?.stats.find((stat) => stat.field === field)?.value;
  }

  function usageText(player, isDish = false, fixed = false) {
    if (!player) return "次数未提供";
    if (isDish) return Number.isInteger(player.serving_count) ? "整份可食用 " + player.serving_count + " 次" : fixed ? "食用次数未提供" : "食用份数随材料变化";
    if (!player.cookable && player.can_use === false) return "不可直接食用";
    const times = player.use_times;
    return Number.isInteger(times) && times > 0 ? "每份可" + (player.cookable ? "烹饪 " : "食用 ") + times + " 次" : "次数未提供";
  }

  function addUsage(picture, player, isDish = false, fixed = false) {
    if (!player) return picture;
    const times = isDish ? player.serving_count : player.use_times;
    const usable = isDish || player.cookable || player.can_use !== false;
    const label = usable && Number.isInteger(times) && times > 0 ? times + "次" : isDish && !fixed ? "可变" : "—";
    const badge = node("span", "icon-uses", label);
    badge.title = usageText(player, isDish, fixed);
    picture.title = badge.title;
    picture.append(badge);
    return picture;
  }

  function signed(value) {
    if (typeof value !== "number" || !Number.isFinite(value)) return "—";
    const text = new Intl.NumberFormat(locale(), { maximumFractionDigits: 2 }).format(value);
    return value > 0 ? "+" + text : text;
  }

  function valueClass(value) {
    return typeof value !== "number" || value === 0 ? "zero" : value < 0 ? "negative" : "";
  }

  function tagList(tags, interactive = false) {
    const list = node("div", "tag-list");
    list.setAttribute("aria-label", "食用标签");
    for (const tag of tags || []) {
      const badge = node(interactive ? "button" : "span", "tag", tag.name);
      if (tag.count > 1) badge.append(node("span", "tag-count", "×" + tag.count));
      badge.title = tag.field + " / ID " + tag.id;
      if (interactive) {
        badge.type = "button";
        badge.addEventListener("click", () => {
          $("tagSelect").value = tag.key;
          if (mobile.matches) $("detailPanel").close();
          render();
        });
      }
      list.append(badge);
    }
    return list;
  }

  function statGrid(stats, compact = false) {
    const list = node(compact ? "div" : "dl", compact ? "card-stats" : "stat-grid");
    const shown = (stats || []).filter((stat) => stat.value !== 0);
    if (!shown.length) list.append(node("span", "stat-help", "五项属性均为 0"));
    for (const stat of shown) {
      const row = node(compact ? "span" : "div", compact ? "card-stat" : "stat-tile " + valueClass(stat.value));
      row.dataset.field = stat.field;
      const label = node(compact ? "span" : "dt", "", stat.label);
      const value = node(compact ? "b" : "dd", compact ? valueClass(stat.value) : "", signed(stat.value));
      row.append(label, value);
      row.setAttribute("aria-label", stat.label + " " + signed(stat.value));
      list.append(row);
    }
    return list;
  }

  function foodFacts(player, isDish = false, fixed = false) {
    const facts = node("div", "food-facts");
    const weight = player.weight_grams;
    const size = player.size;
    if (typeof weight === "number") facts.append(node("span", "", (weight / 1000).toFixed(2) + " kg"));
    if (Array.isArray(size) && size.length === 2) facts.append(node("span", "", size.join("×")));
    facts.append(node("span", "", usageText(player, isDish, fixed)));
    const life = player.shelf_life_days;
    if (typeof life === "number") facts.append(node("span", "", life > 0 ? "基础保质期 " + life + " 天" : "无保质期"));
    if (player.cookable && player.tier) facts.append(node("b", "tier-label", tierLabels[player.tier] + "食材"));
    return facts;
  }

  function foodTagLine(player) {
    return ["食物", player.sub_category, ...player.tags.map((tag) => tag.name)].join(" · ");
  }

  function addFullStats(container, stats) {
    const details = node("details", "secondary-stats");
    details.append(node("summary", "", "查看全部五项属性"));
    const list = node("dl", "highlights");
    for (const stat of stats || []) {
      const row = node("div", "highlight-row");
      row.append(node("dt", "", stat.label), node("dd", "", signed(stat.value)));
      list.append(row);
    }
    details.append(list);
    container.append(details);
  }

  function renderIngredientOptions() {
    const query = normalize($("ingredientSearch").value);
    const groupFilter = $("ingredientGroupSelect").value;
    const tierFilter = $("ingredientTierSelect").value;
    const options = [];
    const groups = new Map(state.ingredients.map((item) => [item.sub_category_id, item.sub_category]));
    const addOption = (material, label, caption, ingredient = null) => {
      const button = node("button", "ingredient-option");
      button.type = "button";
      button.dataset.material = material.key;
      button.setAttribute("aria-label", "添加" + label);
      if (ingredient) button.append(art(ingredient.icon, "food"));
      const text = node("span", "ingredient-option-text");
      text.append(node("span", "", label), node("small", "", caption));
      if (ingredient) text.append(tierBadge(ingredient.tier));
      button.append(text);
      button.addEventListener("click", () => {
        if (isPantry()) { state.stock[ingredient.id] = Math.min(9999, (state.stock[ingredient.id] || 0) + 1); savePantry(); }
        else state.materials.push(material);
        $("entryList").scrollTop = 0;
        render();
      });
      options.push(button);
    };
    for (const [id, name] of groups) if (!isPantry() && (!groupFilter || id === Number(groupFilter)) && !tierFilter && searchIndex([name]).includes(query)) {
      addOption({ key: "group:" + id, group: id, name: "任意" + name }, "任意" + name, "按分类选择");
    }
    for (const item of state.ingredients) if ((!groupFilter || item.sub_category_id === Number(groupFilter)) &&
        (!tierFilter || (tierFilter === "none" ? item.tier === null : item.tier === Number(tierFilter))) &&
        searchIndex([item.name, item.id, item.sub_category]).includes(query)) {
      addOption({ key: "item:" + item.id, id: item.id, name: item.name }, item.name,
        item.sub_category, item);
    }
    if (!options.length) options.push(node("p", "stat-help", "没有找到食材，试试名称、分类或 ID。"));
    $("ingredientOptions").replaceChildren(...options);
    i18n?.apply($("ingredientOptions"));
  }

  function facetChip(label, count, active, action, extra = "") {
    const button = node("button", "facet-chip " + extra);
    button.type = "button";
    button.dataset.facet = label;
    button.classList.toggle("active", active);
    button.setAttribute("aria-pressed", String(active));
    button.append(node("span", "", label), node("small", "", count));
    button.addEventListener("click", action);
    return button;
  }

  function renderFacets() {
    renderIngredientFacets();
    renderCraftFacets();
  }

  function renderCraftFacets() {
    const visible = state.category === "craft" || state.category === "furniture";
    $("craftFacets").hidden = !visible;
    if (!visible) return;
    const entries = category().entries;
    const groups = new Map();
    for (const entry of entries) {
      const id = craftGroupId(state.category, entry);
      const group = groups.get(id) || {name: craftGroupName(state.category, entry) || "未分类", count: 0};
      group.count += 1;
      groups.set(id, group);
    }
    const sorted = [...groups].sort((a, b) => (a[0] ?? 99) - (b[0] ?? 99));
    const groupChips = [facetChip("全部分类", entries.length, !state.craftGroup, () => { state.craftGroup = ""; render(); })];
    for (const [id, group] of sorted) {
      groupChips.push(facetChip(group.name, group.count, String(id) === state.craftGroup, () => {
        state.craftGroup = state.craftGroup === String(id) ? "" : String(id); render();
      }));
    }
    $("craftGroups").replaceChildren(...groupChips);
    const groupOptions = [node("option", "", "全部分类")]; groupOptions[0].value = "";
    for (const [id, group] of sorted) {
      const option = node("option", "", group.name); option.value = String(id); groupOptions.push(option);
    }
    $("craftGroupFilter").replaceChildren(...groupOptions);
    $("craftGroupFilter").value = state.craftGroup;
  }

  function renderIngredientFacets() {
    const visible = state.category === "food";
    $("ingredientFacets").hidden = !visible;
    if (!visible) return;
    const focus = document.activeElement?.dataset.facet;
    const groupScroll = $("ingredientCategories").scrollLeft;
    const tierScroll = $("ingredientTiers").scrollLeft;
    const entries = category().entries;
    const groups = new Map();
    for (const entry of entries) {
      const food = entry.food;
      const group = groups.get(food.sub_category_id) || {name: food.sub_category, count: 0};
      group.count += 1;
      groups.set(food.sub_category_id, group);
    }
    const groupChips = [facetChip("全部分类", entries.length, !state.group, () => { state.group = ""; render(); })];
    for (const [id, group] of [...groups].sort((a, b) => a[0] - b[0])) {
      groupChips.push(facetChip(group.name, group.count, state.group === String(id), () => {
        state.group = state.group === String(id) ? "" : String(id); render();
      }));
    }
    $("ingredientCategories").replaceChildren(...groupChips);
    const groupOptions = [node("option", "", "全部分类")]; groupOptions[0].value = "";
    for (const [id, group] of [...groups].sort((a, b) => a[0] - b[0])) {
      const option = node("option", "", group.name); option.value = id; groupOptions.push(option);
    }
    $("ingredientGroupFilter").replaceChildren(...groupOptions);
    $("ingredientGroupFilter").value = state.group;
    $("ingredientTierFilter").value = state.tier;
    const inGroup = entries.filter(entry => !state.group || entry.food.sub_category_id === Number(state.group));
    const tierChips = [facetChip("全部档位", inGroup.length, !state.tier, () => { state.tier = ""; render(); })];
    for (const tier of [1, 2, 3, "none"]) {
      const count = inGroup.filter(entry => tier === "none" ? entry.food.tier === null : entry.food.tier === tier).length;
      if (count) tierChips.push(facetChip(tierLabels[tier] || "不影响档位", count, state.tier === String(tier), () => {
        state.tier = state.tier === String(tier) ? "" : String(tier); render();
      }, "tier-" + tier));
    }
    $("ingredientTiers").replaceChildren(...tierChips);
    $("ingredientCategories").scrollLeft = groupScroll;
    $("ingredientTiers").scrollLeft = tierScroll;
    if (focus) [...$("ingredientFacets").querySelectorAll("button")].find(button => button.dataset.facet === focus)?.focus({preventScroll: true});
  }

  function renderSelectedMaterials() {
    const isDish = state.category === "dish";
    $("selectedMaterials").hidden = !isDish || isPantry() || !state.materials.length;
    if (isPantry()) return;
    $("ingredientSummary").textContent = state.materials.length ? "已选 " + state.materials.length + " 份 · 继续添加" : "选择食材或分类";
    const counts = new Map();
    state.materials.forEach((material) => counts.set(material.key, { ...material, count: (counts.get(material.key)?.count || 0) + 1 }));
    const chips = [];
    for (const material of counts.values()) {
      const button = node("button", "material-chip", material.name + (material.count > 1 ? " × " + material.count : "") + " −");
      button.type = "button";
      button.setAttribute("aria-label", "移除一份" + material.name);
      button.addEventListener("click", () => {
        state.materials.splice(state.materials.findIndex((item) => item.key === material.key), 1);
        render();
      });
      chips.push(button);
    }
    chips.push(node("span", "material-help", "每份占一个配方槽位，可重复添加"));
    $("selectedMaterials").replaceChildren(...chips);
  }

  function matchesSelectedMaterials(entry, materials = state.materials) {
    if (!materials.length) return true;
    const recipe = entry.recipe;
    if (!recipe) return false;
    const specific = recipe.specific_items?.length > 0;
    const slots = specific ? recipe.specific_items.map((id) => state.ingredients.filter((item) => item.id === id)) :
      (recipe.tag_combo || []).map((group) => state.ingredients.filter((item) => item.sub_category_id === group));
    if (materials.length > slots.length) return false;
    const floor = Number($("tierFloorSelect").value);
    const tierFor = (item) => item.tier === null ? null : floor ? Math.min(item.tier, 4 - floor) : item.tier;
    const assigned = new Map();
    const matches = (item, material) => material.id !== undefined ? item.id === material.id : item.sub_category_id === material.group;
    const finish = () => {
      if (specific) return true;
      const possible = slots.map((items, index) => (assigned.has(index) ? items.filter((item) => matches(item, assigned.get(index))) : items)
        .filter((item) => tierFor(item) === null || tierFor(item) >= recipe.tier));
      if (possible.some((items) => !items.length) || !possible.some((items) => items.some((item) => tierFor(item) === recipe.tier))) return false;
      if (materials.length === slots.length && materials.every((item) => item.id !== undefined)) {
        const combo = materials.map((item) => item.id).sort((a, b) => a - b).join(",");
        if (category("dish").entries.some((dish) => dish.recipe?.specific_items?.length &&
            [...dish.recipe.specific_items].sort((a, b) => a - b).join(",") === combo)) return false;
        const tagCombo = [...recipe.tag_combo].sort((a, b) => a - b).join(",");
        if (category("dish").entries.some((dish) => dish.id < entry.id && dish.recipe?.tier === recipe.tier &&
            [...(dish.recipe.tag_combo || [])].sort((a, b) => a - b).join(",") === tagCombo)) return false;
      }
      return true;
    };
    const assign = (index) => {
      if (index === materials.length) return finish();
      return slots.some((items, slot) => {
        if (assigned.has(slot) || !items.some((item) => matches(item, materials[index]))) return false;
        assigned.set(slot, materials[index]);
        const result = assign(index + 1);
        assigned.delete(slot);
        return result;
      });
    };
    return assign(0);
  }

  function buildNav() {
    const fragment = document.createDocumentFragment();
    for (const id of ["food", "ready-food", "dish", "plant", "prey", "craft", "furniture", "books", "achievements"]) {
      const item = category(id);
      if (!item) continue;
      if (id === "food" || id === "plant") fragment.append(node("div", "nav-caption", id === "food" ? "吃什么 · 怎么做" : "更多生存手册"));
      const button = node("button", "category-button");
      button.type = "button";
      button.dataset.category = id;
      button.setAttribute("aria-label", titles[id] + "，" + item.entries.length + " 条");
      button.append(icon(id), node("span", "category-label", titles[id]), node("span", "category-count", item.entries.length));
      button.addEventListener("click", () => {
        if (state.category === id) return;
        location.hash = urlFor(id, "");
      });
      fragment.append(button);
    }
    $("categoryNav").replaceChildren(fragment);
  }

  function configureControls() {
    const isFood = ["food", "ready-food"].includes(state.category);
    const isDish = state.category === "dish";
    const preyFamily = preyModes.has(state.category);
    $("categoryTitle").textContent = titles[state.category];
    $("categoryIntro").textContent = intros[state.category];
    $("pageHelp").querySelector("p").textContent = state.category === "plant" ?
      "选择当前天气、寒潮强度、种植位置与正在运行的供暖设备。勾选只看当前可种；取消后可查看光照、寒冷或空间不满足的原因。默认食用作物优先，再按基础收获时间排列。" :
      state.category === "prey" ? "每个猎物列出能抓住它的陷阱、推荐诱饵和房间倾向；数值为配置原始值，实际概率由陷阱、诱饵、房间和陷阱技能共同决定。" :
      "选择食材查配方；同种食材可重复添加。完整组合按食材档位匹配，专用配方优先。品质影响效果；技能与状态的档位保底另行选择。";
    $("searchLabel").textContent = state.category === "ready-food" ? "找食品与饮品" : isFood ? "找食材" : isDish ? "找一道菜" : state.category === "baits" ? "找诱饵" : state.category === "books" ? "找一本书" : "搜索图鉴";
    $("nameSearch").placeholder = isFood ? "搜索名称、标签或食用说明" : isDish ? "搜索菜名或成品说明" : "搜索名称或 ID";
    $("preyModeField").hidden = !preyFamily || !state.preyModel;
    if (preyFamily && state.preyModel) {
      $("preyMode").value = state.category;
      $("preyModeHelp").textContent = preyModeHelp[state.category];
    }
    $("materialField").hidden = !["craft", "furniture"].includes(state.category);
    $("ingredientField").hidden = !isDish;
    $("cookingModeField").hidden = !isDish;
    $("cookingRules").hidden = !isDish;
    $("materialSearch").placeholder = "材料名称或 ID";
    $("qualityField").hidden = !isDish;
    $("playerFilters").hidden = !isFood && !isDish;
    $("plantingFilters").hidden = state.category !== "plant";
    $("tagField").hidden = !isFood;
    $("cookableField").hidden = state.category !== "prey";
    $("renewableField").hidden = state.category !== "food";
    $("specificRecipeField").hidden = !isDish;
    $("cookingLevelField").hidden = !isDish;
    $("tierFloorField").hidden = !isDish;
    const levelOptions = [node("option", "", "不限等级")];
    levelOptions[0].value = "";
    const maxLevel = Math.max(1, ...category("dish").entries.map((entry) => entry.recipe?.min_level || 0));
    for (let level = 0; level <= maxLevel; level += 1) {
      const option = node("option", "", "Lv." + level + " 及以下配方");
      option.value = level;
      levelOptions.push(option);
    }
    $("cookingLevelSelect").replaceChildren(...levelOptions);
    const tags = new Map();
    category().entries.forEach((entry) => entry.food?.tags.forEach((tag) => tags.set(tag.key, tag.name)));
    const tagOptions = [node("option", "", "全部标签")];
    tagOptions[0].value = "";
    for (const [id, name] of tags) {
      const option = node("option", "", name);
      option.value = id;
      tagOptions.push(option);
    }
    $("tagSelect").replaceChildren(...tagOptions);
    const effects = statLabels.map((label, index) => {
      const button = node("button", "filter-chip", label + " +");
      button.type = "button";
      button.dataset.effect = "ValueDisplay" + (index + 1);
      button.title = "只显示" + label + "为正的条目，可再次点击取消";
      button.setAttribute("aria-pressed", "false");
      button.addEventListener("click", () => {
        state.effect = state.effect === button.dataset.effect ? "" : button.dataset.effect;
        if (isPantry() && state.effect) $("sortSelect").value = state.effect;
        render();
      });
      return button;
    });
    $("effectFilters").replaceChildren(...effects);
    const sorts = [node("option", "", "图鉴顺序")];
    sorts[0].value = "default";
    if (isFood || isDish) statLabels.forEach((label, index) => {
      const option = node("option", "", label + "最高优先");
      option.value = "ValueDisplay" + (index + 1);
      sorts.push(option);
    });
    if (state.category === "plant") for (const [value, label] of [["plant-food", "食用优先 · 收获最快"],
        ["plant-growth", "基础收获最快"], ["plant-space", "占用空间最少"], ["plant-cold", "耐寒最高优先"], ["plant-light", "光照需求最低"]]) {
      const option = node("option", "", label); option.value = value; sorts.push(option);
    }
    $("sortSelect").replaceChildren(...sorts);
    $("sortSelect").value = defaultSort();
  }

  function defaultSort() {
    if (state.category === "plant") return "plant-food";
    return ["food", "ready-food", "dish"].includes(state.category) ? "ValueDisplay1" : "default";
  }

  function clearFilters(resetPlanting = false) {
    clearTimeout(state.debounce);
    $("nameSearch").value = "";
    $("materialSearch").value = "";
    $("ingredientSearch").value = "";
    $("ingredientGroupSelect").value = "";
    $("ingredientTierSelect").value = "";
    state.group = "";
    state.tier = "";
    state.craftGroup = "";
    state.materialId = null;
    if (resetPlanting) {
      for (const [id, value] of Object.entries({planterSelect: "", planterPower: "on", plantLight: "", plantCold: "",
          plantWeather: "sunny", plantColdWave: "0", plantLocation: "first", plantHeating: "none"})) $(id).value = value;
      $("plantManual").checked = false;
      $("plantOnlySuitable").checked = true;
      savePlantingChoices();
    }
    $("ingredientPicker").open = false;
    $("cookingLevelSelect").value = "";
    $("tierFloorSelect").value = "0";
    state.materials = [];
    renderIngredientOptions();
    $("tagSelect").value = "";
    $("cookableOnly").checked = false;
    $("renewableOnly").checked = false;
    $("specificRecipesOnly").checked = false;
    $("sortSelect").value = defaultSort();
    state.effect = "";
  }

  function plantingConditions() {
    const planter = state.planters.find(item => String(item.id) === $("planterSelect").value);
    const read = id => {
      const input = $(id);
      if (input.validity?.badInput) return NaN;
      if (input.value === "") return null;
      return input.validity?.valid === false ? NaN : Number(input.value);
    };
    const heating = $("plantHeating").value;
    return window.Planting.conditions(state.plantingEnvironment, {
      weather: $("plantWeather").value, cold_wave: $("plantColdWave").value, location: $("plantLocation").value,
      ac: ["ac", "both"].includes(heating), stove: ["stove", "both"].includes(heating), power: $("planterPower").value,
    }, planter, $("plantManual").checked || !state.plantingEnvironment ? {light: read("plantLight"), cold: read("plantCold")} : null);
  }

  function matchesPlanting(entry, conditions) {
    return window.Planting.problems(entry, conditions).length === 0;
  }

  const plantingChoiceIds = ["plantWeather", "plantColdWave", "plantLocation", "plantHeating", "planterSelect", "planterPower", "plantOnlySuitable", "plantManual", "plantLight", "plantCold"];
  function savePlantingChoices() {
    try { localStorage.setItem("survival-log-planting-v1", JSON.stringify(Object.fromEntries(plantingChoiceIds.map(id =>
      [id, $(id).type === "checkbox" ? $(id).checked : $(id).value])))); } catch { /* Preferences are optional. */ }
  }
  function restorePlantingChoices() {
    try {
      const saved = JSON.parse(localStorage.getItem("survival-log-planting-v1") || "{}");
      for (const id of plantingChoiceIds) {
        const input = $(id), value = saved[id];
        if (input.type === "checkbox" && typeof value === "boolean") input.checked = value;
        else if (typeof value === "string" && (input.tagName !== "SELECT" || [...input.options].some(option => option.value === value))) input.value = value;
      }
    } catch { /* Ignore corrupt or unavailable storage. */ }
  }

  function renderPlantingConditions() {
    if (state.category !== "plant") return;
    const conditions = plantingConditions();
    $("planterPower").disabled = !conditions.planter?.needs_power;
    const manual = $("plantManual").checked || !state.plantingEnvironment;
    $("plantManualControls").hidden = !manual;
    for (const select of $("plantScenarioControls").querySelectorAll("select")) select.disabled = manual;
    $("plantHeating").disabled = manual || conditions.location?.device_heat === false;
    const captions = [];
    if (conditions.scenario) captions.push(conditions.scenario.name + " · " + conditions.location.name);
    if (conditions.planter) captions.push("容器容量 " + conditions.planter.capacity);
    if (conditions.light !== null) captions.push("有效光照 " + number(conditions.light));
    if (conditions.cold !== null) captions.push("有效寒冷 " + number(conditions.cold));
    $("plantingSummary").textContent = !conditions.valid ? "请输入有效的环境数值" : captions.join(" · ") || "选择容器或环境值，筛选可种植物";
    if (!conditions.planter) $("plantingSummary").append(document.createTextNode(" · "), node("span", "planting-unchecked", "未选容器，尚未核对空间"));
    $("plantEnvironmentBreakdown").textContent = conditions.scenario ?
      "天气光照 " + number(conditions.scenario.light) + " × 区域系数 " + number(conditions.parameters.light_multiplier) +
      " + 容器补光 " + number(conditions.lightBonus) + " = " + number(conditions.light) + "；天气寒冷 " +
      number(conditions.scenario.cold) + " − 区域保温 " + number(conditions.parameters.heat) + " − 设备供暖 " +
      number(conditions.deviceHeat) + " − 容器加热 " + number(conditions.heatBonus) + " → " + number(conditions.cold) :
      state.plantingEnvironment ? "已使用手动环境值" : "环境预设版本不匹配，请手动填写环境值";
    $("planterLink").hidden = !conditions.planter;
    if (conditions.planter) $("planterLink").href = urlFor("furniture", conditions.planter.key);
  }

  const number = value => Number.isFinite(value) ? new Intl.NumberFormat(locale(), {maximumFractionDigits: 2}).format(value) : "未提供";
  const growthHours = seconds => Number.isFinite(seconds) ? number(seconds / 3600) : "未提供";

  function filteredEntries() {
    preparePantry();
    const name = normalize($("nameSearch").value);
    const materials = $("materialField").hidden ? [] : normalize($("materialSearch").value).split(/[\s,，、]+/).filter(Boolean);
    const tag = $("tagField").hidden ? "" : $("tagSelect").value;
    const cookable = !$("cookableField").hidden && $("cookableOnly").checked;
    const specificOnly = state.category === "dish" && $("specificRecipesOnly").checked;
    const renewableOnly = state.category === "food" && $("renewableOnly").checked;
    const level = $("cookingLevelSelect").value;
    const planting = state.category === "plant" ? plantingConditions() : null;
    const entries = category().entries.filter((entry) =>
      (!planting || (planting.valid && (!$("plantOnlySuitable").checked || matchesPlanting(entry, planting)))) &&
      (!renewableOnly || entry.sources?.some(source => ["plant", "prey"].includes(source.category))) &&
      (state.category !== "food" || !state.group || entry.food?.sub_category_id === Number(state.group)) &&
      (state.category !== "food" || !state.tier || (state.tier === "none" ? entry.food?.tier === null : entry.food?.tier === Number(state.tier))) &&
      (state.category !== "craft" && state.category !== "furniture" || !state.craftGroup || String(craftGroupId(state.category, entry)) === state.craftGroup) &&
      (state.category !== "craft" && state.category !== "furniture" || !state.materialId || entry.materialIds?.has(state.materialId)) &&
      (!specificOnly || entry.hasSpecificIngredients) &&
      entry.nameIndex.includes(name) && (state.category === "dish" ? (isPantry() ? state.pantryPlans.has(entry.key) : matchesSelectedMaterials(entry)) : materials.every((term) => entry.materialIndex.includes(term))) &&
      (state.category !== "dish" || level === "" || (Number.isInteger(entry.recipe?.min_level) && entry.recipe.min_level <= Number(level))) &&
      (!tag || entry.food?.tags.some((item) => item.key === tag)) &&
      (!cookable || entry.food?.cookable) && (!state.effect || statValue(entry, state.effect) > 0));
    const sort = $("sortSelect").value;
    if (planting && sort.startsWith("plant-")) entries.sort((a, b) => window.Planting.compare(a, b, sort, planting));
    else if (sort !== "default") entries.sort((a, b) => {
      const av = statValue(a, sort), bv = statValue(b, sort);
      const difference = (typeof bv === "number" ? bv : -Infinity) - (typeof av === "number" ? av : -Infinity);
      return Number.isNaN(difference) || difference === 0 ? a.id - b.id : difference;
    });
    return entries;
  }

  function renderList() {
    const fragment = document.createDocumentFragment();
    const preyCards = state.category === "prey" && state.preyModel;
    for (const entry of state.entries) {
      const button = node("button", "entry-card");
      button.type = "button";
      button.dataset.key = entry.key;
      button.classList.toggle("active", entry.key === state.key);
      button.setAttribute("aria-pressed", String(entry.key === state.key));
      const player = profile(entry);
      const statsText = player?.stats.map((stat) => stat.label + signed(stat.value)).join("，");
      button.setAttribute("aria-label", entry.name + (player && !preyCards ? "，" + usageText(player, state.category === "dish", entry.portion_model?.mode === "fixed") : "") + (statsText && !preyCards ? "，" + statsText : "") + "，查看详情");
      const top = node("span", "card-top");
      const heading = node("span", "card-heading");
      const meta = node("span", "entry-meta");
      const name = node("span", "entry-name-row");
      name.append(node("span", "entry-name", entry.name));
      if (preyCards) {
        const model = state.preyById.get(entry.id);
        if (model?.rarity) meta.append(node("span", "prey-rarity", stars(model.rarity)));
        meta.append(node("span", "", model ? (model.traps.map((trap) => state.trapById.get(trap.id)?.name || "ID:" + trap.id).join(" · ") || "没有陷阱能捕获") : "陷阱数据未加载"));
        heading.append(name, meta);
        top.append(addUsage(art(player?.icon || entry.icon), player, false, false), heading);
        button.append(top);
        const baitLine = (model?.top_baits || []).slice(0, 3).map(([baitId, coefficient]) => {
          const bait = state.baitById.get(baitId);
          return (bait?.name || "ID:" + baitId) + " " + coefficient;
        }).join(" · ");
        button.append(node("span", "entry-description", baitLine ? "推荐诱饵：" + baitLine : "没有匹配的诱饵数据"));
      } else if (state.category === "traps" && entry.trap) {
        const trap = entry.trap;
        meta.append(node("span", "", "耐久 " + number(trap.durability) + " · 每 " + number(trap.interval_hours) + " 小时检查"));
        heading.append(name, meta);
        top.append(art(entry.icon), heading);
        button.append(top);
        button.append(node("span", "entry-description", (trap.description || "") + (trap.description ? " · " : "") + "可捕 " + trap.prey.length + " 种猎物"));
      } else if (state.category === "baits" && entry.bait) {
        const bait = entry.bait;
        meta.append(node("span", "", state.preyModel.bait_effects[bait.effect] || "诱饵"));
        heading.append(name, meta);
        top.append(art(entry.icon), heading);
        button.append(top);
        const line = bait.uniform ? "对各类猎物效果相同" :
          (bait.top || []).map(([preyId, coefficient]) => (state.preyById.get(preyId)?.name || "ID:" + preyId) + " " + coefficient).join(" · ");
        button.append(node("span", "entry-description", line || "对猎物的吸引系数未提供"));
      } else if (state.category === "books") {
        const price = entry.highlights.find((field) => field.field === "price")?.value;
        if (price) meta.append(node("span", "", "价格 " + price));
        heading.append(name, meta);
        top.append(art(entry.icon), heading);
        button.append(top);
        button.append(node("span", "entry-description", entry.description || ""));
      } else if (state.category === "cages" && entry.cage) {
        const cage = entry.cage;
        meta.append(node("span", "", "容纳 " + number(cage.capacity_mice) + " 只 · 每只 " + number(cage.power_per_mouse) + " 电力"));
        heading.append(name, meta);
        top.append(art(entry.icon), heading);
        button.append(top);
        button.append(node("span", "entry-description", "价格 " + number(cage.price) + " · 饲料仓 " + number(cage.bag_slots) + " 格"));
      } else {
        meta.append(node("span", "", entry.plant ? (entry.plant.food_harvest ? "食用收获" : "其他收获") :
          player ? "分类：" + player.sub_category :
          state.category === "craft" || state.category === "furniture" ? craftGroupName(state.category, entry) || category().label :
          entry.hidden ? "隐藏成就" : entry.group || category().label));
        if (state.category === "dish") {
          meta.append(node("span", "quality-label", qualityName($("qualitySelect").value) + "品质"));
          if (Number.isInteger(entry.recipe?.min_level)) meta.append(node("span", "", "烹饪 Lv." + entry.recipe.min_level));
        }
        else if (entry.food?.cookable) meta.append(node("span", "", "可烹饪"));
        if (entry.food?.cookable) name.append(tierBadge(entry.food.tier));
        heading.append(name, meta);
        top.append(addUsage(art(player?.icon || entry.icon), player, state.category === "dish", entry.portion_model?.mode === "fixed"), heading);
        button.append(top);
        if (player) {
          button.append(node("span", "card-tags", foodTagLine(player)),
            node("span", "card-stat-caption", isPantry() ? "每锅总恢复" : state.category === "dish" && !player.per_use_stats ? "整份配置参考 · 实际随食材变化" : "每次食用"), statGrid(player.stats, true));
          if (state.category === "dish") {
            const estimate = isPantry() ? state.pantryPlans.get(entry.key) : null;
            if (estimate) button.append(node("span", "pantry-recipe", comboText(estimate)),
              node("span", "entry-description", "这组材料最多可做 " + possiblePots(estimate) + " 锅"));
            else button.append(node("span", "entry-description material-preview", entry.highlights.find((field) => field.field === "ingredients")?.value || "未配置食材"));
          }
        } else if (entry.plant) {
          const reasons = window.Planting.problems(entry, plantingConditions());
          button.append(node("span", "plant-verdict " + (reasons.length ? "blocked" : "suitable"),
            reasons.length ? reasons.join(" · ") : "满足当前条件"));
          const facts = node("span", "plant-facts");
          facts.append(node("span", "", "空间 " + number(entry.plant.size)),
            node("span", "", "光照 ≥ " + number(entry.plant.light_need)),
            node("span", "", "寒冷 ≤ " + number(entry.plant.cold_resistance)));
          button.append(facts, node("span", "entry-description", "基础生长 " + growthHours(entry.plant.growth_seconds) + " 小时"));
        } else if (state.category === "furniture") {
          const facts = node("span", "plant-facts entry-effects");
          furnitureEffectChips(entry).forEach((chip) => {
            const chipNode = node("span", "effect-chip", chip.label + (chip.value ? " " : ""));
            if (chip.value) chipNode.append(node("b", "", chip.value));
            if (chip.title) chipNode.title = chip.title;
            facts.append(chipNode);
          });
          button.append(facts);
          const materials = furnitureMaterials(entry);
          if (materials) button.append(materials);
        } else {
          button.append(node("span", "entry-description", entry.highlights.map((field) => field.label + "：" + field.value).join(" · ") || entry.description));
        }
      }
      button.addEventListener("click", () => selectEntry(entry.key, true));
      fragment.append(button);
    }
    $("entryList").replaceChildren(fragment);
    $("entryList").setAttribute("aria-busy", "false");
    $("emptyState").hidden = state.entries.length !== 0;
    $("emptyState").querySelector("p").textContent = isPantry() ? "先添加冰箱食材和剩余用量；没有结果时，检查烹饪等级、品质或其他筛选条件。" : "换个关键词，或减少标签和属性筛选。";
    $("resultCount").textContent = state.entries.length + " / " + category().entries.length + (state.category === "dish" ? " 道料理" : " 个条目");
    $("filterSummary").textContent = state.category === "dish" ? qualityName($("qualitySelect").value) + "品质" + ($("cookingLevelSelect").value ? " · 烹饪 Lv." + $("cookingLevelSelect").value + " 及以下" : "") + ($("specificRecipesOnly").checked ? " · 仅专用菜谱" : "") + (isPantry() ? " · 按冰箱配餐 · 每锅总量" : state.materials.length ? " · 已按食材槽位与档位筛选" : "") : ["food", "ready-food"].includes(state.category) ? "绿色为增益 · 红色为减益" : ["craft", "furniture"].includes(state.category) ? [state.craftGroup ? "已按分类筛选" : "", state.materialId ? "已按材料筛选" : ""].filter(Boolean).join(" · ") : "";
  }

  function section(title, caption = "") {
    const element = node("section", "detail-section");
    const heading = node("h3", "section-heading", title);
    if (caption) heading.append(node("span", "", caption));
    element.append(heading);
    return element;
  }

  function addNotes(container, title, values) {
    if (!values?.length) return;
    const block = section(title);
    const list = node("ul", "notes-list");
    values.forEach((value) => list.append(node("li", "", value)));
    block.append(list);
    container.append(block);
  }

  function renderSources(container, entry) {
    const sources = (entry.sources || []).filter(source => source.category !== state.category || source.key !== entry.key);
    if (!sources.length) return;
    const block = section("获取来源");
    const links = node("div", "source-links");
    for (const source of sources) {
      const link = node("a", "source-link");
      link.href = urlFor(source.category, source.key);
      link.append(icon(source.category), node("span", "", (source.category === "plant" ? "种植：" : "捕获图鉴：") + source.name), node("span", "", "→"));
      links.append(link);
    }
    block.append(links);
    container.append(block);
  }

  function renderPlantDetails(container, entry) {
    const plant = entry.plant;
    if (!plant) return;
    const block = section("种植条件", "基础需求");
    const current = plantingConditions(), reasons = window.Planting.problems(entry, current);
    block.append(node("p", "plant-verdict " + (reasons.length ? "blocked" : "suitable"),
      reasons.length ? "当前条件：" + reasons.join(" · ") : "满足当前条件"));
    const list = node("dl", "plant-requirements");
    for (const [label, value] of [["占用空间", number(plant.size)], ["光照需求", "≥ " + number(plant.light_need)],
        ["可承受寒冷", "≤ " + number(plant.cold_resistance)]]) {
      const row = node("div"); row.append(node("dt", "", label), node("dd", "", value)); list.append(row);
    }
    block.append(list, node("p", "stat-help", "基础生长 " + growthHours(plant.growth_seconds) + " 小时"),
      node("p", "stat-help", "光照不低于需求、寒冷不高于耐寒值时满足基础环境。寒冷越低越暖；生长时间未计加速与停滞。"));
    const planter = plantingConditions().planter;
    if (planter && Number.isFinite(plant.size) && plant.size > 0) {
      block.append(node("p", "plant-seeds", "当前容器需种满：" + Math.floor(planter.capacity / plant.size) + " 份种子"));
    }
    container.append(block);
  }

  function renderRelations(container, relations, title) {
    if (!relations.length) return;
    const block = section(title);
    const groups = new Map();
    for (const relation of relations) {
      if (!groups.has(relation.relation_type)) groups.set(relation.relation_type, new Map());
      const group = groups.get(relation.relation_type);
      const key = relation.target_table + ":" + relation.target_id;
      if (group.has(key)) group.get(key).quantity += 1;
      else group.set(key, { ...relation, quantity: 1 });
    }
    for (const [label, relationsById] of groups) {
      const group = node("div", "ingredient-group");
      const readable = label === "具体食材" ? "指定食材" : label === "食材分类" ? "按食材分类搭配" : label;
      group.append(node("div", "ingredient-label", readable));
      const values = node("div", "relation-values");
      for (const relation of relationsById.values()) {
        const clickable = !relation.link && relation.target_table === "Config_Item" &&
          (state.category === "craft" || state.category === "furniture");
        const item = node(relation.link ? "a" : clickable ? "button" : "span", "relation-item");
        const target = state.categories.flatMap((item) => item.entries).find((entry) => entry.key === relation.link?.key);
        if (target?.icon) item.append(art(target.icon, relation.link.category));
        item.append(node("span", "", (relation.target_name || "ID:" + relation.target_id) + (relation.quantity > 1 ? " × " + relation.quantity : "")));
        item.title = relation.target_table + " / ID " + relation.target_id;
        if (relation.link) item.href = urlFor(relation.link.category, relation.link.key);
        if (clickable) {
          item.type = "button";
          item.title = "查看能用「" + (relation.target_name || "该材料") + "」制造的配方";
          item.addEventListener("click", () => viewMaterial(relation.target_id, relation.target_name));
        }
        values.append(item);
      }
      group.append(values);
      block.append(group);
    }
    container.append(block);
  }

  function materialChips(materials) {
    const values = node("div", "relation-values");
    for (const material of materials) {
      const id = material.target_id ?? material.id;
      const name = material.target_name || material.name || "ID:" + id;
      const chip = node("button", "relation-item material-link");
      chip.type = "button";
      if (material.icon) chip.append(art(material.icon, "craft"));
      chip.append(node("span", "", name + (material.count > 1 ? " × " + material.count : "")));
      chip.title = "查看能用「" + name + "」制造的配方";
      chip.addEventListener("click", () => viewMaterial(id, name));
      values.append(chip);
    }
    return values;
  }

  function viewMaterial(id, name) {
    if (mobile.matches) $("detailPanel").close();
    state.category = "craft";
    clearFilters();
    configureControls();
    state.materialId = id;
    $("materialSearch").value = name || String(id);
    state.key = "";
    render();
    $("entryList").scrollTop = 0;
  }

  function furnitureEffectChips(entry, { includePrice = true } = {}) {
    const chips = Array.isArray(entry.effect_chips) ? entry.effect_chips : [];
    if (!includePrice) return chips;
    const price = Number(entry.highlights.find((field) => field.field === "FurniturePrice")?.value);
    return Number.isFinite(price) && price > 0
      ? [{ label: "家具价格", value: price }, ...chips] : chips;
  }

  function furnitureMaterials(entry) {
    const groups = entry.craft_recipes || [];
    if (!groups.length) return null;
    const block = node("span", "entry-materials");
    for (const group of groups) {
      if (groups.length > 1) {
        block.append(node("span", "entry-materials-level",
          "要求等级 " + (group.level === 0 ? "无" : group.level != null ? group.level + "级" : "未提供")));
      }
      for (const material of group.materials || []) {
        const row = node("span", "entry-material");
        if (material.icon) row.append(art(material.icon, "craft"));
        row.append(node("span", "entry-material-name", material.name));
        if (material.count > 1) row.append(node("b", "entry-material-count", "× " + material.count));
        block.append(row);
      }
    }
    const dyeCount = groups.reduce(
      (sum, group) => sum + (group.options || []).filter((option) => option.dyes?.length).length, 0);
    if (dyeCount) block.append(node("span", "entry-material-note", "另有 " + dyeCount + " 种染料配色"));
    return block;
  }

  function furnitureEffectsBlock(entry) {
    const chips = furnitureEffectChips(entry, { includePrice: false });
    if (!chips.length) return null;
    const block = section("设施效果", "按当前配置整理");
    const list = node("dl", "highlights");
    for (const chip of chips) {
      const row = node("div", "highlight-row");
      const value = node("dd", "", chip.value || "有");
      if (chip.title) value.title = chip.title;
      row.append(node("dt", "", chip.label), value);
      list.append(row);
    }
    block.append(list);
    return block;
  }

  function furnitureRecipesBlock(groups) {
    const block = section("制造配方", "只差染料颜色的配方已合并展示");
    for (const group of groups) {
      const groupBlock = node("div", "recipe-group");
      const head = node("div", "recipe-group-head");
      const levelBadge = node("span", "recipe-level");
      levelBadge.append(node("span", "", "要求等级"),
        node("span", "", group.level === 0 ? "无" : group.level != null ? group.level + "级" : "未提供"));
      head.append(levelBadge);
      if (group.materials?.length) head.append(materialChips(group.materials));
      groupBlock.append(head);
      if (group.options?.length && group.options.some((option) => option.dyes?.length)) {
        const dyeRow = node("div", "dye-row");
        dyeRow.append(node("span", "dye-label", "染料配色"));
        const values = node("div", "relation-values");
        for (const option of group.options) {
          const label = option.dyes?.length ? option.dyes.map((dye) => dye.name).join("、") : "原色";
          const chip = node(option.link ? "a" : "span", "dye-chip");
          chip.append(node("span", "", label));
          chip.title = option.name + " · 配方 ID " + option.recipe_id;
          if (option.link) chip.href = urlFor(option.link.category, option.link.key);
          values.append(chip);
        }
        dyeRow.append(values);
        groupBlock.append(dyeRow);
      }
      block.append(groupBlock);
    }
    return block;
  }

  function showMaterialUses(container, entry) {
    const productIds = entry.relations.filter((relation) => relation.relation_type === "制造产物").map((relation) => relation.target_id);
    if (!productIds.length) return;
    const uses = new Map();
    for (const id of productIds) for (const use of state.materialUses.get(id) || [])
      if (use.key !== entry.key) uses.set(use.category + "|" + use.key, use);
    if (!uses.size) return;
    const block = section("这个材料能做什么", uses.size + " 个配方使用它");
    for (const use of [...uses.values()].slice(0, 6)) {
      const link = node("a", "recipe-link");
      link.href = urlFor(use.category, use.key);
      const name = node("span", "recipe-name", use.name);
      name.append(node("span", "recipe-hint", use.category === "craft" ? "制造配方" : "家具制造"));
      link.append(name);
      block.append(link);
    }
    if (uses.size > 6) block.append(node("p", "stat-help", "已显示前 6 条，其余可用下方按钮查询。"));
    const more = node("button", "more-recipes", "用「" + entry.name + "」查全部配方 →");
    more.type = "button";
    more.addEventListener("click", () => viewMaterial(productIds[0], entry.name));
    block.append(more);
    container.append(block);
  }

  function craftRecipeLink(craftKey) {
    if (!craftKey || !category("craft")?.entries.some((item) => item.key === craftKey)) return null;
    const block = section("制作配方");
    const link = node("a", "recipe-link");
    link.href = urlFor("craft", craftKey);
    const name = node("span", "recipe-name", category("craft").entries.find((item) => item.key === craftKey)?.name || craftKey);
    name.append(node("span", "recipe-hint", "制造手册 · 陷阱狩猎"));
    link.append(name);
    block.append(link);
    return block;
  }

  function renderPreyCapture(container, entry) {
    const model = state.preyById.get(entry.id);
    if (!model) {
      container.append(node("p", "stat-help", "陷阱狩猎数据未加载或版本不匹配，以下仅显示食用属性。"));
      return;
    }
    const trapsBlock = section("捕获渠道", "各陷阱针对该猎物的基础率（配置值）");
    const links = node("div", "source-links");
    for (const trap of model.traps) {
      const link = node("a", "source-link");
      link.href = urlFor("traps", "Trap:" + trap.id);
      const label = (state.trapById.get(trap.id)?.name || "ID:" + trap.id) + " · 基础率 " + percent(trap.base_rate);
      link.append(node("span", "", label), node("span", "", "→"));
      links.append(link);
    }
    trapsBlock.append(links);
    container.append(trapsBlock);
    const baitBlock = section("推荐诱饵", "对这种猎物吸引系数最高");
    const baits = node("div", "relation-values");
    for (const [baitId, coefficient] of model.top_baits) {
      const bait = state.baitById.get(baitId);
      const chip = node("a", "relation-item");
      chip.href = urlFor("baits", "Bait:" + baitId);
      if (bait?.icon) chip.append(art(bait.icon, "prey"));
      chip.append(node("span", "", (bait?.name || "ID:" + baitId) + " ×" + coefficient));
      if (bait) chip.title = state.preyModel.bait_effects[bait.effect] || "";
      baits.append(chip);
    }
    if (baits.children.length) baitBlock.append(baits);
    else baitBlock.append(node("p", "stat-help", "没有找到有效诱饵。"));
    baitBlock.append(node("p", "stat-help", "系数越高越容易吸引；系数相同的诱饵效果相同。实际概率还受陷阱、房间与陷阱技能影响。"));
    container.append(baitBlock);
    const roomBlock = section("房间倾向", "各房间的环境系数");
    const rooms = node("div", "relation-values");
    for (const room of model.rooms) {
      const chip = node("span", "relation-item", (state.roomById.get(room.id)?.name || "ID:" + room.id) + " " + room.coefficient);
      chip.title = state.roomById.get(room.id)?.description || "";
      rooms.append(chip);
    }
    roomBlock.append(rooms);
    roomBlock.append(node("p", "stat-help", "系数为 0 表示该房间几乎不会出现这种猎物；把陷阱放在系数更高的房间更划算。"));
    container.append(roomBlock);
  }

  function renderTrapDetails(container, entry) {
    const trap = entry.trap;
    const block = section("陷阱属性", "配置原始值");
    const list = node("dl", "highlights");
    const rows = [["耐久", number(trap.durability)], ["每次捕获消耗耐久", number(trap.capture_cost)],
      ["检查间隔", number(trap.interval_hours) + " 小时"], ["空手权重", number(trap.empty_weight)],
      ["可放置房间", trap.rooms.join("、") || "未提供"],
      ["诱饵位", trap.bait_capacity > 0 ? number(trap.bait_capacity) : "手动放一个诱饵"],
      ["容纳猎物", trap.prey_capacity > 0 ? number(trap.prey_capacity) + " 只" : "1 只（捕获后收取）"],
      ["回收获得", trap.trap_get.join("、") || "无"]];
    for (const [label, value] of rows) {
      const row = node("div", "highlight-row");
      row.append(node("dt", "", label), node("dd", "", value));
      list.append(row);
    }
    block.append(list);
    block.append(node("p", "stat-help", "空手权重是“什么都没抓到”的抽取权重，越低越容易捕获；陷阱技能可以降低它，稀有猎物权重由技能提升。"));
    container.append(block);
    const craft = craftRecipeLink(trap.craft_key);
    if (craft) container.append(craft);
    const preyBlock = section("可捕获猎物", "基础率（配置值）· 从高到低");
    const values = node("div", "relation-values");
    for (const prey of [...trap.prey].sort((a, b) => b.base_rate - a.base_rate)) {
      const chip = node("a", "relation-item");
      chip.href = urlFor("prey", "Config_Item:" + prey.id);
      const target = state.preyById.get(prey.id);
      if (target?.icon) chip.append(art(target.icon, "prey"));
      chip.append(node("span", "", prey.name + " " + percent(prey.base_rate)));
      chip.title = "捕获图鉴经验 " + prey.discovery_exp;
      values.append(chip);
    }
    preyBlock.append(values);
    const slots = state.preyModel.slots || [];
    if (slots.length) preyBlock.append(node("p", "stat-help",
      "全屋可放置陷阱位：" + slots.map((slot) => slot.name + " " + slot.count + " 处").join(" · ")));
    container.append(preyBlock);
    const levels = state.preyModel.trap_levels || [];
    if (levels.length) {
      const details = node("details", "secondary-stats");
      details.append(node("summary", "", "陷阱技能加成（所有陷阱共享）"));
      const levelList = node("dl", "highlights");
      for (const level of levels) {
        const row = node("div", "highlight-row");
        row.append(node("dt", "", "Lv." + level.lv + " · 经验 " + number(level.exp)),
          node("dd", "", level.info.split("\n").join("；")));
        levelList.append(row);
      }
      details.append(levelList);
      container.append(details);
    }
  }

  function renderBaitDetails(container, entry) {
    const bait = entry.bait;
    const effectText = state.preyModel.bait_effects[bait.effect] || "";
    const block = section("对各猎物的吸引系数", bait.uniform ? "对全部猎物相同" : "从高到低");
    const values = node("div", "relation-values");
    for (const [preyId, coefficient] of bait.top || []) {
      const chip = node("a", "relation-item");
      chip.href = urlFor("prey", "Config_Item:" + preyId);
      const target = state.preyById.get(preyId);
      if (target?.icon) chip.append(art(target.icon, "prey"));
      chip.append(node("span", "", (target?.name || "ID:" + preyId) + " ×" + coefficient));
      values.append(chip);
    }
    if (values.children.length) block.append(values);
    else block.append(node("p", "stat-help", "这种物品没有列出有效的吸引系数。"));
    block.append(node("p", "stat-help", (effectText ? effectText + "。" : "") +
      "系数是配置相对值：同一陷阱、同一房间里系数越高越容易被吸引；未列出的猎物系数更低，但被打包在完整系数表内。"));
    container.append(block);
  }

  function renderCageDetails(container, entry) {
    const cage = entry.cage;
    const block = section("发电属性", "配置原始值");
    const list = node("dl", "highlights");
    const rows = [["容纳活鼠", number(cage.capacity_mice) + " 只"], ["每只电力", number(cage.power_per_mouse)],
      ["饲养消耗系数", String(cage.fuel_rate ?? "未提供")], ["价格", number(cage.price)],
      ["安装时间", number(cage.install_time)], ["耐久", number(cage.hp)],
      ["饲料仓", cage.bag_size ? cage.bag_size.join("×") + "（" + cage.bag_slots + " 格）" : "未提供"]];
    for (const [label, value] of rows) {
      const row = node("div", "highlight-row");
      row.append(node("dt", "", label), node("dd", "", value));
      list.append(row);
    }
    block.append(list);
    block.append(node("p", "stat-help", "把活捉笼抓到的活鼠放进老鼠笼并投喂食物，老鼠跑笼就会持续发电。饲养消耗系数是游戏原始配置值，配置未标注单位。"));
    container.append(block);
    const craft = craftRecipeLink(cage.craft_key);
    if (craft) container.append(craft);
  }

  function relatedDishes(entry) {
    if (!entry.food?.cookable) return [];
    return (category("dish")?.entries || []).filter((dish) => dish.ingredientIds.has(entry.id) && matchesSelectedMaterials(dish, [{ id: entry.id }])).sort((a, b) => {
      const exactA = a.relations.some((r) => r.relation_type === "具体食材" && r.target_id === entry.id);
      const exactB = b.relations.some((r) => r.relation_type === "具体食材" && r.target_id === entry.id);
      return Number(exactB) - Number(exactA) || a.id - b.id;
    });
  }

  function showRelatedDishes(container, entry) {
    if (!entry.food?.cookable) return;
    const dishes = relatedDishes(entry);
    const block = section("这个食材能做什么", dishes.length + " 道相关配方");
    if (!dishes.length) {
      block.append(node("p", "stat-help", "当前图鉴中没有匹配到相关配方。"));
    } else {
      for (const dish of dishes.slice(0, 5)) {
        const link = node("a", "recipe-link");
        link.href = urlFor("dish", dish.key);
        const exact = dish.relations.some((r) => r.relation_type === "具体食材" && r.target_id === entry.id);
        const name = node("span", "recipe-name", dish.name);
        name.append(node("span", "recipe-hint", exact ? "配方指定食材" : "符合食材分类 · 仍需搭配"));
        const product = dish.products?.find((item) => item.quality === $("qualitySelect").value);
        const satiety = (product?.per_use_stats || product?.stats)?.find((stat) => stat.field === "ValueDisplay1")?.value;
        link.append(name, node("span", "recipe-effect", (product?.per_use_stats ? "每次 " : "参考 ") + signed(satiety) + " 饱腹 ↗"));
        block.append(link);
      }
      block.append(node("p", "stat-help", $("qualitySelect").value + "品质效果。分类配方还需满足其余食材及档位要求；指定食材配方优先。"));
      const more = node("button", "more-recipes", "用「" + entry.name + "」查全部配方 →");
      more.type = "button";
      more.addEventListener("click", () => {
        if (mobile.matches) $("detailPanel").close();
        state.category = "dish";
        $("cookingMode").value = "recipes";
        clearFilters();
        configureControls();
        state.materials = [{ key: "item:" + entry.id, id: entry.id, name: entry.name }];
        state.key = "";
        render();
        $("entryList").scrollTop = 0;
      });
      block.append(more);
    }
    container.append(block);
  }

  function renderDetail(preserveScroll = false) {
    const scroll = $("detailContent").scrollTop;
    const expanded = preserveScroll ? [...$("detailContent").querySelectorAll("details[open]")].map(element => element.className) : [];
    const portion = preserveScroll ? $("detailContent").querySelector(".portion-form input")?.value : undefined;
    const entry = state.entries.find((item) => item.key === state.key);
    if (!entry) {
      const placeholder = node("div", "detail-placeholder");
      placeholder.append(node("p", "", "没有匹配的条目，试试减少筛选条件。"));
      $("detailContent").replaceChildren(placeholder);
      $("detailPanel").removeAttribute("aria-labelledby");
      $("detailPosition").textContent = "条目详情";
      return;
    }
    const fragment = document.createDocumentFragment();
    const player = profile(entry);
    const hero = node("div", "detail-hero");
    const text = node("div", "detail-hero-text");
    const heading = node("h2", "", entry.name);
    heading.id = "detailName";
    text.append(node("div", "detail-category", titles[state.category] + (entry.hidden ? " / 隐藏成就" : "")), heading, node("div", "detail-id", "ID " + entry.id));
    if (entry.detailPath) {
      const permalink = node("a", "detail-permalink", "打开独立详情页 ↗");
      permalink.href = entry.detailPath;
      text.append(permalink);
    }
    if (entry.icon_source) text.append(node("p", "image-credit", "图片：" + entry.icon_source.name +
      (entry.icon_source.kind === "product" ? "（制造产物）" : "（收获物）")));
    if (player && state.category !== "prey") text.append(node("div", "item-tag-line", foodTagLine(player)));
    hero.append(addUsage(art(player?.icon || entry.icon, state.category, true), player, state.category === "dish", entry.portion_model?.mode === "fixed"), text);
    fragment.append(hero);
    if (player && state.category !== "prey") fragment.append(foodFacts(player, state.category === "dish", entry.portion_model?.mode === "fixed"));
    if (state.category === "dish") {
      const fixed = entry.portion_model?.mode === "fixed";
      const estimate = isPantry() ? state.pantryPlans.get(entry.key) : null;
      if (estimate) {
        const method = section("这锅怎么做", "这组材料最多可做 " + possiblePots(estimate) + " 锅");
        method.append(node("p", "food-note", comboText(estimate)));
        for (const item of [...new Map(estimate.ingredients.map(item => [item.id, item])).values()]) {
          method.append(node("p", "stat-help", item.name + " · " + (tierLabels[item.tier] || "不影响档位") +
            (item.tier_thresholds ? " · 配置基价 " + item.price + "；高档 ≥ " + item.tier_thresholds.high + "，中档 ≥ " + item.tier_thresholds.mid : "")));
        }
        method.append(node("p", "stat-help", fixed ? "命中指定食材的专用配方，效果取该品质成品配置。" : "按分类匹配；最高参与档位决定菜名，技能与状态保底按所选条件应用。"));
        fragment.append(method);
      }
      const block = section(estimate ? "每锅总恢复" : fixed ? "每次食用的效果" : "配置参考效果", "按成品品质查看");
      const tabs = node("div", "quality-tabs");
      tabs.setAttribute("role", "group");
      tabs.setAttribute("aria-label", "成品品质");
      for (const quality of qualities) {
        const button = node("button", "quality-tab", qualityName(quality));
        button.type = "button";
        button.dataset.quality = quality;
        button.classList.toggle("active", $("qualitySelect").value === quality);
        button.setAttribute("aria-pressed", String($("qualitySelect").value === quality));
        button.disabled = !entry.products?.some((product) => product.quality === quality);
        button.addEventListener("click", () => {
          $("qualitySelect").value = quality;
          render(true);
          $("detailContent").querySelector('[data-quality="' + quality + '"]')?.focus({ preventScroll: true });
        });
        tabs.append(button);
      }
      block.append(tabs);
      if (player) {
        block.append(node("div", "product-caption", player.name), statGrid(player.stats));
        addFullStats(block, player.stats);
        if (estimate) block.append(node("h4", "", "每次食用"), statGrid(player.per_use_stats),
          node("p", "stat-help", "整份可食用 " + estimate.servings + " 次"));
        if (player.note) block.append(node("p", "food-note", player.note));
      } else block.append(node("p", "stat-help", "当前数据未提供这一品质的成品效果。"));
      block.append(node("p", "stat-help", estimate ? "按所选材料与品质计算基础效果，未叠加角色、状态或设施修正；所选品质不代表必定做出该品质。" : fixed ? "按整份属性与可吃次数分摊，显示每次食用的基础效果；未叠加角色或状态修正。" : "通用配方的整份属性由实际食材、档位与品质生成；这里是成品配置参考值，不能作为固定食用次数。"));
      const threshold = entry.portion_model?.threshold;
      if (Number.isInteger(threshold) && threshold > 0) {
        block.append(node("p", "stat-help", "分份标准：" + threshold + " 饱腹 / 次。次数 = 整份总饱腹 ÷ " + threshold + "，向上取整，至少 1 次。"));
        if (!fixed && !estimate) {
          const form = node("div", "portion-form");
          const label = node("label", "", "整份总饱腹");
          const input = node("input");
          input.type = "number"; input.min = "0"; input.max = "2147483647"; input.step = "1"; input.placeholder = "例如 60";
          input.setAttribute("aria-label", "整份总饱腹");
          const result = node("output", "portion-result", "输入总饱腹，计算可吃次数");
          result.setAttribute("aria-live", "polite");
          input.addEventListener("input", () => {
            const value = input.valueAsNumber;
            result.textContent = input.value && input.validity.valid && Number.isFinite(value) ? "整份可吃 " + Math.max(1, Math.ceil(Math.fround(value / threshold))) + " 次" : "输入总饱腹，计算可吃次数";
            i18n?.apply(form);
          });
          label.append(input); form.append(label, result); block.append(form);
        }
      }
      fragment.append(block);
      renderRelations(fragment, entry.relations.filter((r) => ["具体食材", "食材分类"].includes(r.relation_type)), "怎么做这道菜");
      if (entry.recipe?.tag_combo?.length) {
        const block = section("食材档位", tierLabels[entry.recipe.tier] || "未提供");
        block.append(node("p", "stat-help", "取参与食材中的最高档；只要一个高档食材就可决定高档结果，其余可以是中档或低档。主食等不影响档位，指定食材配方优先。"));
        fragment.append(block);
      }
    } else if (player) {
      if (state.category === "prey") renderPreyCapture(fragment, entry);
      const block = section("直接食用的属性", "增益 + / 减益 −");
      block.append(statGrid(player.stats));
      addFullStats(block, player.stats);
      if (player.note) block.append(node("p", "food-note", player.note));
      block.append(node("p", "stat-help", "配置基础展示值；实际效果可能受角色或食物状态影响。"));
      fragment.append(block);
      const tags = section("食用标签");
      tags.append(tagList(player.tags, true));
      if (!player.tags.length) tags.append(node("p", "stat-help", "没有食用标签"));
      const info = node("div", "food-info");
      info.append(node("span", "", "烹饪分类：" + player.sub_category), node("b", "", player.cookable ? "可以烹饪" : "不可用于烹饪"));
      tags.append(info);
      if (player.tier) tags.append(node("p", "stat-help", tierLabels[player.tier] + "食材；档位按该分类的配置价格阈值判断，不等于成品品质或烹饪等级。"));
      fragment.append(tags);
      renderSources(fragment, entry);
      showRelatedDishes(fragment, entry);
    } else if (state.category === "craft") {
      const materialRelations = entry.relations.filter((relation) => relation.relation_type === "制造材料");
      if (materialRelations.length) {
        const counts = new Map();
        for (const relation of materialRelations) {
          const record = counts.get(relation.target_id) || {target_id: relation.target_id, target_name: relation.target_name, count: 0};
          record.count += 1;
          counts.set(relation.target_id, record);
        }
        const level = entry.highlights.find((field) => field.field === "Level");
        const block = section("制作所需材料", level ? "要求等级 · " + level.value : "");
        block.append(materialChips([...counts.values()]));
        block.append(node("p", "stat-help", "点击材料，查看能用它制造的所有配方。"));
        fragment.append(block);
      }
      showMaterialUses(fragment, entry);
    } else if (state.category === "furniture") {
      if (entry.craft_recipes?.length) fragment.append(furnitureRecipesBlock(entry.craft_recipes));
      const effects = furnitureEffectsBlock(entry);
      if (effects) fragment.append(effects);
    } else if (state.category === "traps" && entry.trap) {
      renderTrapDetails(fragment, entry);
    } else if (state.category === "baits" && entry.bait) {
      renderBaitDetails(fragment, entry);
    } else if (state.category === "cages" && entry.cage) {
      renderCageDetails(fragment, entry);
    }
    renderPlantDetails(fragment, entry);
    if (entry.description) fragment.append(node("p", "detail-description", entry.description));
    const usefulHighlights = entry.highlights.filter((field) => !(player && ["acquisition", "ingredients"].includes(field.field)) &&
      !(entry.plant && ["Size", "LightNeed", "ColdResistance"].includes(field.field)) &&
      !((state.category === "craft" || state.category === "furniture") && ["materials", "level", "Level"].includes(field.field)));
    if (usefulHighlights.length) {
      const block = section(state.category === "dish" ? "制作信息" : "更多信息");
      const list = node("dl", "highlights");
      usefulHighlights.forEach((field) => {
        if (!field.value) return;
        const row = node("div", "highlight-row");
        row.append(node("dt", "", field.label), node("dd", "", field.value));
        list.append(row);
      });
      block.append(list);
      fragment.append(block);
    }
    const otherRelations = entry.relations.filter((r) => {
      if (state.category === "dish") return !["具体食材", "食材分类", "完美产物", "良好产物", "普通产物", "失败产物"].includes(r.relation_type);
      if (state.category === "craft") return r.relation_type !== "制造材料";
      if (player) return !/^FoodTag[123]$/.test(r.relation_type) && r.relation_type !== "子分类";
      return true;
    });
    renderRelations(fragment, otherRelations, "相关物品与用途");
    addNotes(fragment, "注意事项", entry.notes);
    addNotes(fragment, "排除项", entry.exclusions);
    addNotes(fragment, "配置引用", entry.references);
    const details = node("details", "raw-details");
    details.append(node("summary", "", "查看原始配置 · " + entry.fields.length + " 个字段"));
    const fields = node("dl", "config-fields");
    entry.fields.forEach((field) => {
      const row = node("div", "config-row");
      const label = node("dt", "", i18n?.language === "en" ? field.field.replace(/_/g, " ").replace(/([a-z])([A-Z])/g, "$1 $2") : field.label);
      if (field.field !== field.label) label.append(node("small", "", field.field));
      row.append(label, node("dd", "", field.value));
      fields.append(row);
    });
    details.append(fields);
    if (entry.fields.length) fragment.append(details);
    fragment.append(node("div", "detail-source", entry.source_table + " / " + (entry.name_key || "ID:" + entry.id) + (entry.source_version ? " · 说明参考版本 " + entry.source_version : "")));
    $("detailContent").replaceChildren(fragment);
    for (const details of $("detailContent").querySelectorAll("details")) details.open = expanded.includes(details.className);
    const portionInput = $("detailContent").querySelector(".portion-form input");
    if (portionInput && portion !== undefined) {
      portionInput.value = portion;
      portionInput.dispatchEvent(new Event("input"));
    }
    $("detailPanel").setAttribute("aria-labelledby", "detailName");
    $("detailContent").scrollTop = preserveScroll ? scroll : 0;
    $("detailPosition").textContent = state.category === "dish" ? "料理笔记 · " + qualityName($("qualitySelect").value) + "品质" : state.category === "food" ? "食材笔记 · 属性与用途" : category().label + " · 条目详情";
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
    i18n?.apply();
    if (mobile.matches && openMobile && !$("detailPanel").open) $("detailPanel").showModal();
  }

  function render(preserveDetailScroll = false, preservePantryInputs = false) {
    if (!category()) return;
    if (location.hash) document.title = titles[state.category] + " · 生存日志 Survival Log";
    const navId = ({traps: "prey", baits: "prey", cages: "prey"})[state.category] || state.category;
    document.querySelectorAll(".category-button").forEach((button) => {
      const active = button.dataset.category === navId;
      button.classList.toggle("active", active);
      if (active) button.setAttribute("aria-current", "page");
      else button.removeAttribute("aria-current");
    });
    document.querySelectorAll(".filter-chip").forEach((button) => {
      button.classList.toggle("active", button.dataset.effect === state.effect);
      button.setAttribute("aria-pressed", String(button.dataset.effect === state.effect));
    });
    state.entries = filteredEntries();
    renderSelectedMaterials();
    if (!preservePantryInputs) renderPantry();
    if (!state.entries.some((entry) => entry.key === state.key)) state.key = state.entries[0]?.key || "";
    setUrl();
    renderList();
    renderDetail(preserveDetailScroll);
    renderFacets();
    renderPlantingConditions();
    i18n?.apply();
  }

  function resetSearch() {
    clearFilters(state.category === "plant");
    render();
    $("nameSearch").focus();
  }

  function readHash(openMobile = false) {
    let categoryId, key;
    try {
      [categoryId, key] = location.hash.slice(1).split("/").map(decodeURIComponent);
    } catch { categoryId = "food"; }
    if (categoryId === "food" && key && category("ready-food")?.entries.some((entry) => entry.key === key)) categoryId = "ready-food";
    if (!state.categories.some((item) => item.id === categoryId)) categoryId = "food";
    if (categoryId !== state.category) {
      clearFilters();
      state.category = categoryId;
      configureControls();
      $("entryList").scrollTop = 0;
    }
    state.key = key || "";
    if (key && category().entries.some((entry) => entry.key === key) && !filteredEntries().some((entry) => entry.key === key)) {
      if (state.category === "dish") $("cookingMode").value = "recipes";
      clearFilters();
      if (state.category === "plant") $("plantOnlySuitable").checked = false;
    }
    render();
    if (mobile.matches && openMobile && key && state.entries.some((entry) => entry.key === key)) selectEntry(key, true);
  }

  async function load() {
    $("loadError").hidden = true;
    $("resultCount").textContent = "正在读取图鉴…";
    $("entryList").setAttribute("aria-busy", "true");
    try {
      await i18n?.ready;
      const response = await fetch(new URL("./data.json", location.href));
      if (!response.ok) throw new Error("数据请求失败（HTTP " + response.status + "）");
      const data = await response.json();
      if (data.format_version !== 1 || !Array.isArray(data.categories) || !data.categories.length) throw new Error("图鉴数据格式不匹配");
      const detailPaths = new Map();
      for (const item of data.categories) for (const entry of item.entries) {
        if (!detailPaths.has(entry.key)) detailPaths.set(entry.key, "./guide/" + item.id + "/" + entry.id + "/");
        entry.detailPath = detailPaths.get(entry.key);
      }
      state.categories = data.categories.flatMap((item) => item.id === "food" ? [
        { ...item, entries: item.entries.filter((entry) => entry.food?.cookable) },
        { id: "ready-food", label: "即食食品", entries: item.entries.filter((entry) => !entry.food?.cookable) },
      ] : [item]);
      state.ingredients = data.cooking_ingredients || [];
      state.cookingModel = data.cooking_model || null;
      state.craftNoteNames = data.craft_note_categories || {};
      state.furniturePageNames = data.furniture_shop_pages || {};
      state.materialUses = new Map();
      state.stock = {}; state.pantryPlanKey = "";
      restorePantry();
      renderCookingRules();
      state.planters = data.planters || [];
      state.plantingEnvironment = data.planting_environment || null;
      const planterOptions = [node("option", "", "不限容器")];
      planterOptions[0].value = "";
      for (const planter of state.planters) {
        const option = node("option", "", planter.name); option.value = planter.id; planterOptions.push(option);
      }
      $("planterSelect").replaceChildren(...planterOptions);
      restorePlantingChoices();
      const groupOptions = [node("option", "", "全部分类")];
      groupOptions[0].value = "";
      for (const [id, name] of new Map(state.ingredients.map(item => [item.sub_category_id, item.sub_category]))) {
        const option = node("option", "", name); option.value = id; groupOptions.push(option);
      }
      $("ingredientGroupSelect").replaceChildren(...groupOptions);
      state.ingredients.sort((a, b) => a.sub_category_id - b.sub_category_id || a.name.localeCompare(b.name, "zh-CN") || a.id - b.id);
      const foods = state.ingredients;
      for (const item of state.categories) {
        const grouped = item.id === "craft" || item.id === "furniture";
        for (const entry of item.entries) {
          entry.nameIndex = searchIndex([entry.name, entry.name_key, entry.id, entry.food?.sub_category, entry.food?.note,
            entry.icon_source?.name, item.id === "craft" || item.id === "furniture" ? craftGroupName(item.id, entry) : "",
            ...(entry.food?.tags || []).map((tag) => tag.name), ...(entry.products || []).map((product) => product.note)]);
          const materialRelations = entry.relations.filter((relation) => /^(具体食材|食材分类|制造材料)/.test(relation.relation_type));
          const specific = materialRelations.filter((relation) => relation.relation_type === "具体食材");
          entry.hasSpecificIngredients = specific.length > 0;
          const groups = new Set(materialRelations.filter((relation) => relation.relation_type === "食材分类").map((relation) => relation.target_id));
          const eligible = specific.length ? foods.filter((food) => specific.some((r) => r.target_id === food.id)) :
            foods.filter((food) => groups.has(food.sub_category_id));
          entry.ingredientIds = new Set([...specific.map((r) => r.target_id), ...eligible.map((food) => food.id)]);
          const materialSources = item.id === "furniture" ?
            (entry.craft_recipes || []).flatMap((group) => [...(group.materials || []).map((material) => ({id: material.id, name: material.name})),
              ...(group.options || []).flatMap((option) => (option.dyes || []).map((dye) => ({id: dye.id, name: dye.name})))]) :
            materialRelations.map((relation) => ({id: relation.target_id, name: relation.target_name}));
          entry.materialIds = new Set(materialSources.map((material) => material.id));
          entry.materialIndex = searchIndex([...materialSources.flatMap((material) => [material.name, material.id]),
            ...eligible.flatMap((food) => [food.name, food.id])]);
        }
      }
      for (const item of state.categories) if (item.id === "craft" || item.id === "furniture") {
        for (const entry of item.entries) for (const id of entry.materialIds) {
          if (!state.materialUses.has(id)) state.materialUses.set(id, []);
          state.materialUses.get(id).push({category: item.id, key: entry.key, name: entry.name});
        }
      }
      $("gameVersion").textContent = "数据 " + (data.metadata.game_version || "未标注");
      $("footerVersion").textContent = "数据版本 " + (data.metadata.game_version || "未标注");
      $("gameVersion").title = "图鉴效果来自仓库静态库；图标单独提取，不会改变图鉴数值";
      state.dataVersion = data.metadata.game_version || "";
      buildNav();
      renderIngredientOptions();
      configureControls();
      readHash(Boolean(location.hash));
      ["nameSearch", "materialSearch", "ingredientSearch", "resetSearch"].forEach((id) => { $(id).disabled = false; });
      ensurePreyModel();
    } catch (error) {
      $("loadError").hidden = false;
      $("errorMessage").textContent = error.message + "。请稍后重试。";
      $("resultCount").textContent = "加载失败";
      $("entryList").setAttribute("aria-busy", "false");
      i18n?.apply();
    }
  }

  ["nameSearch", "materialSearch"].forEach((id) => $(id).addEventListener("input", () => {
    if (id === "materialSearch") state.materialId = null;
    clearTimeout(state.debounce);
    state.debounce = setTimeout(() => { $("entryList").scrollTop = 0; render(); }, 100);
  }));
  $("ingredientSearch").addEventListener("input", renderIngredientOptions);
  $("cookingMode").addEventListener("change", () => { renderIngredientOptions(); $("entryList").scrollTop = 0; render(); });
  ["ingredientGroupSelect", "ingredientTierSelect"].forEach(id => $(id).addEventListener("change", renderIngredientOptions));
  $("ingredientGroupFilter").addEventListener("change", () => { state.group = $("ingredientGroupFilter").value; render(); });
  $("ingredientTierFilter").addEventListener("change", () => { state.tier = $("ingredientTierFilter").value; render(); });
  $("craftGroupFilter").addEventListener("change", () => { state.craftGroup = $("craftGroupFilter").value; render(); });
  ["tagSelect", "cookableOnly", "renewableOnly", "specificRecipesOnly", "sortSelect", "qualitySelect", "cookingLevelSelect", "tierFloorSelect"].forEach((id) => $(id).addEventListener("change", () => render()));
  plantingChoiceIds.forEach(id => $(id).addEventListener(["plantLight", "plantCold"].includes(id) ? "input" : "change", () => {
    savePlantingChoices(); $("entryList").scrollTop = 0; render();
  }));
  $("ingredientPicker").addEventListener("keydown", (event) => {
    if (event.key === "Escape") { $("ingredientPicker").open = false; $("ingredientSummary").focus(); }
  });
  $("preyMode").addEventListener("change", () => {
    location.hash = urlFor($("preyMode").value, "");
  });
  $("pageHelp").addEventListener("keydown", (event) => {
    if (event.key === "Escape") { $("pageHelp").open = false; $("pageHelp").querySelector("summary").focus(); }
  });
  document.addEventListener("click", (event) => {
    if (!$("ingredientField").contains(event.target)) $("ingredientPicker").open = false;
    if (!$("pageHelp").contains(event.target)) $("pageHelp").open = false;
  });
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
  window.addEventListener("languagechange", () => {
    if (!state.categories.length) return;
    const listScroll = $("entryList").scrollTop;
    renderIngredientOptions();
    render(true);
    $("entryList").scrollTop = listScroll;
  });
  window.addEventListener("keydown", (event) => {
    if (event.key === "/" && !event.ctrlKey && !event.metaKey && !/^(INPUT|TEXTAREA|SELECT)$/.test(event.target.tagName) && !event.target.isContentEditable && !(mobile.matches && $("detailPanel").open)) {
      event.preventDefault();
      $("nameSearch").focus();
    }
  });
  mobile.addEventListener("change", () => {
    if ($("detailPanel").open) $("detailPanel").close();
    if (!mobile.matches) $("detailPanel").show();
  });
  if (mobile.matches) $("detailPanel").close();
  load();
})();
