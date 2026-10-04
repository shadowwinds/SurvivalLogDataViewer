(() => {
  "use strict";

  const $ = (id) => document.getElementById(id);
  const i18n = window.I18n;
  const locale = () => i18n?.locale || "zh-CN";
  const mobile = matchMedia("(max-width: 720px)");
  const state = { categories: [], category: "food", key: "", entries: [], effect: "", debounce: null, ingredients: [], materials: [], group: "", tier: "", planters: [] };
  const qualities = ["普通", "良好", "完美", "失败"];
  const statLabels = ["饱腹", "心态", "精力", "健康", "生命"];
  const tierLabels = { 1: "高档", 2: "中档", 3: "低档" };
  const qualityName = (value) => value === "良好" ? "优良" : value;
  const titles = { food: "烹饪食材", "ready-food": "即食食品", dish: "菜肴与效果", plant: "种植手册", prey: "猎物图鉴", craft: "制造手册", furniture: "家具与设施", achievements: "成就指南" };
  const intros = {
    food: "看属性、查标签，掌握每份食材的可用次数。",
    "ready-food": "不用于烹饪的食品与饮品，直接查看食用次数与效果。",
    dish: "先看吃完的效果，再决定今天做什么。",
    plant: "了解生长条件，把收获留给下一餐。",
    prey: "查找猎物的属性与获取信息。",
    craft: "材料与产物，一次查清。",
    furniture: "从生活设施到生存据点。",
    achievements: "查条件、看方法，补齐你的生存记录。",
  };
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

  function category(id = state.category) {
    return state.categories.find((item) => item.id === id);
  }

  function urlFor(categoryId, key) {
    return "#" + categoryId + "/" + encodeURIComponent(key);
  }

  function setUrl() {
    history.replaceState(null, "", urlFor(state.category, state.key));
  }

  function profile(entry) {
    if (entry.food) return entry.food;
    const product = entry.products?.find((item) => item.quality === $("qualitySelect").value);
    return product?.per_use_stats ? { ...product, stats: product.per_use_stats } : product;
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
        state.materials.push(material);
        $("entryList").scrollTop = 0;
        render();
      });
      options.push(button);
    };
    for (const [id, name] of groups) if ((!groupFilter || id === Number(groupFilter)) && !tierFilter && searchIndex([name]).includes(query)) {
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

  function renderFacets() {
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
    const chip = (label, count, active, action, extra = "") => {
      const button = node("button", "facet-chip " + extra);
      button.type = "button";
      button.dataset.facet = label;
      button.classList.toggle("active", active);
      button.setAttribute("aria-pressed", String(active));
      button.append(node("span", "", label), node("small", "", count));
      button.addEventListener("click", action);
      return button;
    };
    const groupChips = [chip("全部分类", entries.length, !state.group, () => { state.group = ""; render(); })];
    for (const [id, group] of [...groups].sort((a, b) => a[0] - b[0])) {
      groupChips.push(chip(group.name, group.count, state.group === String(id), () => {
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
    const tierChips = [chip("全部档位", inGroup.length, !state.tier, () => { state.tier = ""; render(); })];
    for (const tier of [1, 2, 3, "none"]) {
      const count = inGroup.filter(entry => tier === "none" ? entry.food.tier === null : entry.food.tier === tier).length;
      if (count) tierChips.push(chip(tierLabels[tier] || "不影响档位", count, state.tier === String(tier), () => {
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
    $("selectedMaterials").hidden = !isDish || !state.materials.length;
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
    for (const id of ["food", "ready-food", "dish", "plant", "prey", "craft", "furniture", "achievements"]) {
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
    const isFood = ["food", "ready-food", "prey"].includes(state.category);
    const isDish = state.category === "dish";
    $("categoryTitle").textContent = titles[state.category];
    $("categoryIntro").textContent = intros[state.category];
    $("searchLabel").textContent = state.category === "ready-food" ? "找食品与饮品" : isFood ? "找食材" : isDish ? "找一道菜" : "搜索图鉴";
    $("nameSearch").placeholder = isFood ? "搜索名称、标签或食用说明" : isDish ? "搜索菜名或成品说明" : "搜索名称或 ID";
    $("materialField").hidden = !["craft", "furniture"].includes(state.category);
    $("ingredientField").hidden = !isDish;
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
    $("sortSelect").replaceChildren(...sorts);
    $("sortSelect").value = defaultSort();
  }

  function defaultSort() {
    return ["food", "ready-food", "dish", "prey"].includes(state.category) ? "ValueDisplay1" : "default";
  }

  function clearFilters() {
    clearTimeout(state.debounce);
    $("nameSearch").value = "";
    $("materialSearch").value = "";
    $("ingredientSearch").value = "";
    $("ingredientGroupSelect").value = "";
    $("ingredientTierSelect").value = "";
    state.group = "";
    state.tier = "";
    $("planterSelect").value = "";
    $("planterPower").value = "on";
    $("plantLight").value = "";
    $("plantCold").value = "";
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
    const light = read("plantLight"), cold = read("plantCold");
    const powered = planter?.needs_power && $("planterPower").value === "on";
    const lightBonus = (planter?.light_bonus || 0) + (powered ? planter.electric_light || 0 : 0);
    const heatBonus = (planter?.heat_bonus || 0) + (powered ? planter.electric_heat || 0 : 0);
    return {planter, light: light === null ? null : light + lightBonus,
      cold: cold === null ? null : cold - heatBonus,
      valid: (light === null || (Number.isFinite(light) && light >= 0)) && (cold === null || Number.isFinite(cold))};
  }

  function matchesPlanting(entry, conditions) {
    const plant = entry.plant;
    if (!conditions.valid) return false;
    if (conditions.planter && (!Number.isFinite(plant?.size) || plant.size <= 0 ||
        !Number.isFinite(conditions.planter.capacity) || plant.size > conditions.planter.capacity)) return false;
    if (conditions.light !== null && (!Number.isFinite(plant?.light_need) || conditions.light < plant.light_need)) return false;
    if (conditions.cold !== null && (!Number.isFinite(plant?.cold_resistance) || conditions.cold > plant.cold_resistance)) return false;
    return true;
  }

  function renderPlantingConditions() {
    if (state.category !== "plant") return;
    const conditions = plantingConditions();
    $("planterPower").disabled = !conditions.planter?.needs_power;
    const captions = [];
    if (conditions.planter) captions.push("容器容量 " + conditions.planter.capacity);
    if (conditions.light !== null) captions.push("有效光照 " + number(conditions.light));
    if (conditions.cold !== null) captions.push("有效寒冷 " + number(conditions.cold));
    $("plantingSummary").textContent = !conditions.valid ? "请输入有效的环境数值" : captions.join(" · ") || "选择容器或环境值，筛选可种植物";
    $("planterLink").hidden = !conditions.planter;
    if (conditions.planter) $("planterLink").href = urlFor("furniture", conditions.planter.key);
  }

  const number = value => Number.isFinite(value) ? new Intl.NumberFormat(locale(), {maximumFractionDigits: 2}).format(value) : "未提供";
  const growthHours = seconds => Number.isFinite(seconds) ? number(seconds / 3600) : "未提供";

  function filteredEntries() {
    const name = normalize($("nameSearch").value);
    const materials = $("materialField").hidden ? [] : normalize($("materialSearch").value).split(/[\s,，、]+/).filter(Boolean);
    const tag = $("tagField").hidden ? "" : $("tagSelect").value;
    const cookable = !$("cookableField").hidden && $("cookableOnly").checked;
    const specificOnly = state.category === "dish" && $("specificRecipesOnly").checked;
    const renewableOnly = state.category === "food" && $("renewableOnly").checked;
    const level = $("cookingLevelSelect").value;
    const planting = state.category === "plant" ? plantingConditions() : null;
    const entries = category().entries.filter((entry) =>
      (!planting || matchesPlanting(entry, planting)) &&
      (!renewableOnly || entry.sources?.some(source => ["plant", "prey"].includes(source.category))) &&
      (state.category !== "food" || !state.group || entry.food?.sub_category_id === Number(state.group)) &&
      (state.category !== "food" || !state.tier || (state.tier === "none" ? entry.food?.tier === null : entry.food?.tier === Number(state.tier))) &&
      (!specificOnly || entry.hasSpecificIngredients) &&
      entry.nameIndex.includes(name) && (state.category === "dish" ? matchesSelectedMaterials(entry) : materials.every((term) => entry.materialIndex.includes(term))) &&
      (state.category !== "dish" || level === "" || (Number.isInteger(entry.recipe?.min_level) && entry.recipe.min_level <= Number(level))) &&
      (!tag || entry.food?.tags.some((item) => item.key === tag)) &&
      (!cookable || entry.food?.cookable) && (!state.effect || statValue(entry, state.effect) > 0));
    const sort = $("sortSelect").value;
    if (sort !== "default") entries.sort((a, b) => {
      const av = statValue(a, sort), bv = statValue(b, sort);
      const difference = (typeof bv === "number" ? bv : -Infinity) - (typeof av === "number" ? av : -Infinity);
      return Number.isNaN(difference) || difference === 0 ? a.id - b.id : difference;
    });
    return entries;
  }

  function renderList() {
    const fragment = document.createDocumentFragment();
    for (const entry of state.entries) {
      const button = node("button", "entry-card");
      button.type = "button";
      button.dataset.key = entry.key;
      button.classList.toggle("active", entry.key === state.key);
      button.setAttribute("aria-pressed", String(entry.key === state.key));
      const player = profile(entry);
      const statsText = player?.stats.map((stat) => stat.label + signed(stat.value)).join("，");
      button.setAttribute("aria-label", entry.name + (player ? "，" + usageText(player, state.category === "dish", entry.portion_model?.mode === "fixed") : "") + (statsText ? "，" + statsText : "") + "，查看详情");
      const top = node("span", "card-top");
      const heading = node("span", "card-heading");
      const meta = node("span", "entry-meta");
      meta.append(node("span", "", player ? "分类：" + player.sub_category : entry.hidden ? "隐藏成就" : entry.group || category().label));
      if (state.category === "dish") {
        meta.append(node("span", "quality-label", qualityName($("qualitySelect").value) + "品质"));
        if (Number.isInteger(entry.recipe?.min_level)) meta.append(node("span", "", "烹饪 Lv." + entry.recipe.min_level));
      }
      else if (entry.food?.cookable) meta.append(node("span", "", "可烹饪"));
      const name = node("span", "entry-name-row");
      name.append(node("span", "entry-name", entry.name));
      if (entry.food?.cookable) name.append(tierBadge(entry.food.tier));
      heading.append(name, meta);
      top.append(addUsage(art(player?.icon || entry.icon), player, state.category === "dish", entry.portion_model?.mode === "fixed"), heading);
      button.append(top);
      if (player) {
        button.append(node("span", "card-tags", foodTagLine(player)),
          node("span", "card-stat-caption", state.category === "dish" && !player.per_use_stats ? "整份配置参考 · 实际随食材变化" : "每次食用"), statGrid(player.stats, true));
        if (state.category === "dish") button.append(node("span", "entry-description material-preview", entry.highlights.find((field) => field.field === "ingredients")?.value || "未配置食材"));
      } else if (entry.plant) {
        const facts = node("span", "plant-facts");
        facts.append(node("span", "", "空间 " + number(entry.plant.size)),
          node("span", "", "光照 ≥ " + number(entry.plant.light_need)),
          node("span", "", "寒冷 ≤ " + number(entry.plant.cold_resistance)));
        button.append(facts, node("span", "entry-description", "基础生长 " + growthHours(entry.plant.growth_seconds) + " 小时"));
      } else {
        button.append(node("span", "entry-description", entry.highlights.map((field) => field.label + "：" + field.value).join(" · ") || entry.description));
      }
      button.addEventListener("click", () => selectEntry(entry.key, true));
      fragment.append(button);
    }
    $("entryList").replaceChildren(fragment);
    $("entryList").setAttribute("aria-busy", "false");
    $("emptyState").hidden = state.entries.length !== 0;
    $("resultCount").textContent = state.entries.length + " / " + category().entries.length + (state.category === "dish" ? " 道料理" : " 个条目");
    $("filterSummary").textContent = state.category === "dish" ? qualityName($("qualitySelect").value) + "品质" + ($("cookingLevelSelect").value ? " · 烹饪 Lv." + $("cookingLevelSelect").value + " 及以下" : "") + ($("specificRecipesOnly").checked ? " · 仅专用菜谱" : "") + (state.materials.length ? " · 已按食材槽位与档位筛选" : "") : ["food", "ready-food", "prey"].includes(state.category) ? "绿色为增益 · 红色为减益" : "";
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
        const item = node(relation.link ? "a" : "span", "relation-item");
        const target = state.categories.flatMap((item) => item.entries).find((entry) => entry.key === relation.link?.key);
        if (target?.icon) item.append(art(target.icon, relation.link.category));
        item.append(node("span", "", (relation.target_name || "ID:" + relation.target_id) + (relation.quantity > 1 ? " × " + relation.quantity : "")));
        item.title = relation.target_table + " / ID " + relation.target_id;
        if (relation.link) item.href = urlFor(relation.link.category, relation.link.key);
        values.append(item);
      }
      group.append(values);
      block.append(group);
    }
    container.append(block);
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
    const permalink = node("a", "detail-permalink", "打开独立详情页 ↗");
    permalink.href = entry.detailPath;
    text.append(permalink);
    if (entry.icon_source) text.append(node("p", "image-credit", "图片：" + entry.icon_source.name + "（收获物）"));
    if (player) text.append(node("div", "item-tag-line", foodTagLine(player)));
    hero.append(addUsage(art(player?.icon || entry.icon, state.category, true), player, state.category === "dish", entry.portion_model?.mode === "fixed"), text);
    fragment.append(hero);
    if (player) fragment.append(foodFacts(player, state.category === "dish", entry.portion_model?.mode === "fixed"));
    if (state.category === "dish") {
      const fixed = entry.portion_model?.mode === "fixed";
      const block = section(fixed ? "每次食用的效果" : "配置参考效果", "按成品品质查看");
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
        if (player.note) block.append(node("p", "food-note", player.note));
      } else block.append(node("p", "stat-help", "当前数据未提供这一品质的成品效果。"));
      block.append(node("p", "stat-help", fixed ? "按整份属性与可吃次数分摊，显示每次食用的基础效果；未叠加角色或状态修正。" : "通用配方的整份属性由实际食材、档位与品质生成；这里是成品配置参考值，不能作为固定食用次数。"));
      const threshold = entry.portion_model?.threshold;
      if (Number.isInteger(threshold) && threshold > 0) {
        block.append(node("p", "stat-help", "分份标准：" + threshold + " 饱腹 / 次。次数 = 整份总饱腹 ÷ " + threshold + "，向上取整，至少 1 次。"));
        if (!fixed) {
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
        block.append(node("p", "stat-help", "同类食材也分档位。取参与计算的食材中最高档，主食等分类不影响档位；选择完整材料后按该档位筛选，指定食材配方优先。"));
        fragment.append(block);
      }
    } else if (player) {
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
    }
    renderPlantDetails(fragment, entry);
    if (entry.description) fragment.append(node("p", "detail-description", entry.description));
    const usefulHighlights = entry.highlights.filter((field) => !(player && ["acquisition", "ingredients"].includes(field.field)) &&
      !(entry.plant && ["Size", "LightNeed", "ColdResistance"].includes(field.field)));
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
    fragment.append(details, node("div", "detail-source", entry.source_table + " / " + (entry.name_key || "ID:" + entry.id) + (entry.source_version ? " · 说明参考版本 " + entry.source_version : "")));
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

  function render(preserveDetailScroll = false) {
    if (!category()) return;
    if (location.hash) document.title = titles[state.category] + " · 生存日志 Survival Log";
    document.querySelectorAll(".category-button").forEach((button) => {
      const active = button.dataset.category === state.category;
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
    if (!state.entries.some((entry) => entry.key === state.key)) state.key = state.entries[0]?.key || "";
    setUrl();
    renderList();
    renderDetail(preserveDetailScroll);
    renderFacets();
    renderPlantingConditions();
    i18n?.apply();
  }

  function resetSearch() {
    clearFilters();
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
    if (key && category().entries.some((entry) => entry.key === key) && !filteredEntries().some((entry) => entry.key === key)) clearFilters();
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
      state.planters = data.planters || [];
      const planterOptions = [node("option", "", "不限容器")];
      planterOptions[0].value = "";
      for (const planter of state.planters) {
        const option = node("option", "", planter.name); option.value = planter.id; planterOptions.push(option);
      }
      $("planterSelect").replaceChildren(...planterOptions);
      const groupOptions = [node("option", "", "全部分类")];
      groupOptions[0].value = "";
      for (const [id, name] of new Map(state.ingredients.map(item => [item.sub_category_id, item.sub_category]))) {
        const option = node("option", "", name); option.value = id; groupOptions.push(option);
      }
      $("ingredientGroupSelect").replaceChildren(...groupOptions);
      state.ingredients.sort((a, b) => a.sub_category_id - b.sub_category_id || a.name.localeCompare(b.name, "zh-CN") || a.id - b.id);
      const foods = state.ingredients;
      for (const item of state.categories) {
        for (const entry of item.entries) {
          entry.nameIndex = searchIndex([entry.name, entry.name_key, entry.id, entry.food?.sub_category, entry.food?.note,
            entry.icon_source?.name,
            ...(entry.food?.tags || []).map((tag) => tag.name), ...(entry.products || []).map((product) => product.note)]);
          const materialRelations = entry.relations.filter((relation) => /^(具体食材|食材分类|制造材料)/.test(relation.relation_type));
          const specific = materialRelations.filter((relation) => relation.relation_type === "具体食材");
          entry.hasSpecificIngredients = specific.length > 0;
          const groups = new Set(materialRelations.filter((relation) => relation.relation_type === "食材分类").map((relation) => relation.target_id));
          const eligible = specific.length ? foods.filter((food) => specific.some((r) => r.target_id === food.id)) :
            foods.filter((food) => groups.has(food.sub_category_id));
          entry.ingredientIds = new Set([...specific.map((r) => r.target_id), ...eligible.map((food) => food.id)]);
          entry.materialIndex = searchIndex([...materialRelations.flatMap((r) => [r.target_name, r.target_id]), ...eligible.flatMap((food) => [food.name, food.id])]);
        }
      }
      $("gameVersion").textContent = "数据 " + (data.metadata.game_version || "未标注");
      $("footerVersion").textContent = "数据版本 " + (data.metadata.game_version || "未标注");
      $("gameVersion").title = "图鉴效果来自仓库静态库；图标单独提取，不会改变图鉴数值";
      buildNav();
      renderIngredientOptions();
      configureControls();
      readHash(Boolean(location.hash));
      ["nameSearch", "materialSearch", "ingredientSearch", "resetSearch"].forEach((id) => { $(id).disabled = false; });
    } catch (error) {
      $("loadError").hidden = false;
      $("errorMessage").textContent = error.message + "。请稍后重试。";
      $("resultCount").textContent = "加载失败";
      $("entryList").setAttribute("aria-busy", "false");
      i18n?.apply();
    }
  }

  ["nameSearch", "materialSearch"].forEach((id) => $(id).addEventListener("input", () => {
    clearTimeout(state.debounce);
    state.debounce = setTimeout(() => { $("entryList").scrollTop = 0; render(); }, 100);
  }));
  $("ingredientSearch").addEventListener("input", renderIngredientOptions);
  ["ingredientGroupSelect", "ingredientTierSelect"].forEach(id => $(id).addEventListener("change", renderIngredientOptions));
  $("ingredientGroupFilter").addEventListener("change", () => { state.group = $("ingredientGroupFilter").value; render(); });
  $("ingredientTierFilter").addEventListener("change", () => { state.tier = $("ingredientTierFilter").value; render(); });
  ["tagSelect", "cookableOnly", "renewableOnly", "specificRecipesOnly", "sortSelect", "qualitySelect", "cookingLevelSelect", "tierFloorSelect"].forEach((id) => $(id).addEventListener("change", () => render()));
  ["planterSelect", "planterPower"].forEach(id => $(id).addEventListener("change", () => { $("entryList").scrollTop = 0; render(); }));
  ["plantLight", "plantCold"].forEach(id => $(id).addEventListener("input", () => { $("entryList").scrollTop = 0; render(); }));
  $("ingredientPicker").addEventListener("keydown", (event) => {
    if (event.key === "Escape") { $("ingredientPicker").open = false; $("ingredientSummary").focus(); }
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
