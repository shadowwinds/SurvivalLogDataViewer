(() => {
  "use strict";
  const root = new URL("./", document.currentScript.src);
  const storageKey = "survival-log-language";
  const supported = value => /^en(?:-|$)/i.test(value || "") ? "en" : /^zh(?:-|$)/i.test(value || "") ? "zh-CN" : "";
  let saved = "";
  try { saved = localStorage.getItem(storageKey); } catch { /* Storage can be disabled. */ }
  let language = supported(new URL(location.href).searchParams.get("lang")) || supported(saved) ||
    (navigator.languages || [navigator.language]).map(supported).find(Boolean) || "zh-CN";
  let ui = {}, game = {}, templates = [];
  let available = false;
  const originals = new WeakMap();
  const escapeRegex = value => value.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");

  function english(value, depth = 0) {
    if (Object.hasOwn(ui, value)) return ui[value];
    if (Object.hasOwn(game, value)) return game[value];
    if (depth > 4 || !/[\u3400-\u9fff]/.test(value)) return value;
    for (const template of templates) {
      const match = value.match(template.regex);
      if (match) {
        const vars = Object.fromEntries(template.names.map((name, index) => [name, english(match[index + 1], depth + 1)]));
        return template.target.replace(/\{(\w+)\}/g, (_, name) => vars[name] ?? `{${name}}`);
      }
    }
    const parts = value.split(/(\s* · \s*|、|，|：|；|\s+\+\s+|\s*\/\s*|\s*×\s*|\s*−\s*)/);
    if (parts.length > 1) return parts.map((part, index) => index % 2 ?
      ({"、": ", ", "，": ", ", "：": ": ", "；": "; "}[part] || part) : english(part, depth + 1)).join("");
    const level = value.match(/^(\d+)级$/);
    if (level) return "Lv." + level[1];
    const stat = value.match(/^(饱腹|饱食|心态|精力|健康|生命)([\s+−\-\d.,]+)$/);
    return stat ? english(stat[1], depth + 1) + " " + stat[2].trim() : value;
  }

  function text(value, vars = {}) {
    const source = String(value ?? ""), trimmed = source.trim();
    if (!trimmed) return source;
    const result = language === "en" ? english(trimmed) : trimmed;
    return source.slice(0, source.indexOf(trimmed)) + result.replace(/\{(\w+)\}/g, (_, name) => vars[name] ?? `{${name}}`) +
      source.slice(source.indexOf(trimmed) + trimmed.length);
  }

  function remember(owner, key, value, fallback = "") {
    let records = originals.get(owner);
    if (!records) { records = new Map(); originals.set(owner, records); }
    let record = records.get(key);
    if (!record || (value !== record.last && value !== record.source)) record = {source: value};
    record.last = text(record.source);
    if (language === "en" && record.last === record.source && fallback && /[\u3400-\u9fff]/.test(record.source)) {
      record.last = fallback.replace(/_/g, " ").replace(/([a-z])([A-Z])/g, "$1 $2");
    }
    records.set(key, record);
    return record.last;
  }

  function apply(scope = document) {
    const walker = document.createTreeWalker(scope, NodeFilter.SHOW_TEXT);
    while (walker.nextNode()) {
      const node = walker.currentNode;
      if (!node.parentElement?.closest("script,style,noscript,code,[data-no-i18n]")) {
        node.nodeValue = remember(node, "text", node.nodeValue, node.parentElement?.getAttribute("data-config-label") || "");
      }
    }
    for (const element of scope.querySelectorAll("[placeholder],[title],[aria-label],[alt],meta[name=description],meta[property='og:title'],meta[property='og:description']")) {
      for (const attr of ["placeholder", "title", "aria-label", "alt", "content"]) {
        if (element.hasAttribute(attr)) element.setAttribute(attr, remember(element, attr, element.getAttribute(attr)));
      }
    }
    for (const link of scope.querySelectorAll("a[href]")) {
      if (link.getAttribute("href").startsWith("#")) continue;
      const url = new URL(link.href, location.href);
      if (url.origin === root.origin && url.pathname.startsWith(root.pathname) && !/\.(xml|json|png|svg)$/.test(url.pathname)) {
        url.searchParams.set("lang", language);
        link.href = url.href;
      }
    }
    document.documentElement.lang = language;
    const ogLocale = document.querySelector("meta[property='og:locale']");
    if (ogLocale) ogLocale.content = language === "en" ? "en_US" : "zh_CN";
    for (const select of document.querySelectorAll("[data-language-select]")) select.value = language;
  }

  function setLanguage(value) {
    language = supported(value) || "zh-CN";
    try { localStorage.setItem(storageKey, language); } catch { /* Still usable without persistence. */ }
    const url = new URL(location.href);
    url.searchParams.set("lang", language);
    history.replaceState(null, "", url);
    apply();
    window.dispatchEvent(new Event("languagechange"));
  }

  const ready = Promise.all(["en.json", "game-en.json"].map(async name => {
    const response = await fetch(new URL("locales/" + name, root));
    if (!response.ok) throw new Error(`Locale HTTP ${response.status}`);
    return response.json();
  })).then(([labels, names]) => {
    ui = labels; game = names;
    templates = Object.entries(ui).filter(([source]) => source.includes("{")).map(([source, target]) => {
      const names = [...source.matchAll(/\{(\w+)\}/g)].map(match => match[1]);
      const pattern = source.split(/\{\w+\}/).map(escapeRegex).join("([\\s\\S]+?)");
      return {names, target, regex: new RegExp("^" + pattern + "$"), specificity: source.replace(/\{\w+\}/g, "").length};
    }).sort((a, b) => b.specificity - a.specificity);
    available = true;
  }).catch(() => {
    language = "zh-CN";
    for (const select of document.querySelectorAll("[data-language-select]")) select.title = "语言文件加载失败，请重新加载 / Language files failed to load; please reload";
  }).then(() => {
    apply();
    for (const select of document.querySelectorAll("[data-language-select]")) {
      select.disabled = !available;
      if (available) select.addEventListener("change", () => setLanguage(select.value));
    }
  });
  window.I18n = {text, apply, ready, setLanguage, english: value => english(String(value ?? "")),
    get language() { return language; }, get locale() { return language === "en" ? "en-US" : "zh-CN"; }};
})();
