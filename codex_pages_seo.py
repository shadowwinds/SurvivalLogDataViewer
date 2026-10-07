"""Render crawlable public codex pages without JavaScript or new dependencies."""

from __future__ import annotations

import json
import re
from collections import Counter, defaultdict
from html import escape
from pathlib import Path, PurePosixPath
from typing import Any
from urllib.parse import quote, urlsplit, urlunsplit
from xml.etree.ElementTree import Element, SubElement, tostring


DEFAULT_SITE_URL = "https://shadowwinds.github.io/SurvivalLogDataViewer/"
SITE_NAME = "生存日志 · 幸存者图鉴"
HOME_TITLE = "生存日志图鉴｜食材档位、烹饪配方与菜肴效果 · Survival Log"
HOME_DESCRIPTION = "Survival Log 生存日志玩家图鉴：按食材档位和烹饪等级查配方，查询食品的使用次数、饱腹、心态、精力、健康、生命属性与食用标签，比较菜肴各品质的可吃次数和每次效果。"
CATEGORY_INTROS = {
    "food": ("烹饪食材", "查询可烹饪食材的每份使用次数、五项属性、食品标签与可用菜肴。"),
    "ready-food": ("即食食品", "查询不能用于烹饪的食品与饮品，查看每份食用次数、属性与标签。"),
    "dish": ("菜肴与效果", "查看配方食材和制作要求，比较完美、优良、普通、失败品质的成品效果。"),
    "plant": ("植物", "查看植物、种子、收获物与各等级配置。"),
    "prey": ("猎物", "查看猎物的属性、食品标签与关联配置。"),
    "craft": ("制造", "查看制造材料、等级要求、产物与失败产物。"),
    "furniture": ("家具", "查看家具功能、材料及相关配置。"),
    "books": ("书籍", "查询可阅读书籍的阅读效果、心态与技能加成说明。"),
    "achievements": ("成就", "查询成就完成条件、方法、角色限制和注意事项。"),
}


def browse_categories(payload: dict[str, Any]) -> list[dict[str, Any]]:
    categories = []
    for category in payload["categories"]:
        if category["id"] == "food":
            categories.append({**category, "entries": [e for e in category["entries"] if e["food"]["cookable"]]})
            categories.append({"id": "ready-food", "label": "即食食品",
                               "entries": [e for e in category["entries"] if not e["food"]["cookable"]]})
        else:
            categories.append(category)
    return categories


def normalize_site_url(value: str) -> str:
    parsed = urlsplit(value.strip())
    if (parsed.scheme not in {"http", "https"} or not parsed.hostname
            or parsed.username is not None or parsed.password is not None
            or parsed.query or parsed.fragment or "\\" in value
            or re.search(r"[\s<>\"']", value)):
        raise ValueError("--site-url 必须是没有查询参数、片段或登录信息的完整 HTTP(S) 网址")
    # Validate the port and reject paths whose interpretation differs across clients.
    parsed.port
    if any(part in {".", ".."} for part in parsed.path.split("/")) or "%" in parsed.path:
        raise ValueError("--site-url 不能包含相对路径段或百分号编码")
    path = parsed.path.rstrip("/") + "/"
    return urlunsplit((parsed.scheme, parsed.netloc, path, "", ""))


def clean_text(value: Any) -> str:
    text = "" if value is None else str(value)
    return re.sub(r"</?(?:color|size|b|i)(?:=[^>]*)?>", "", text, flags=re.IGNORECASE).strip()


def h(value: Any) -> str:
    return escape(clean_text(value), quote=True)


def stat_value(value: Any) -> str:
    if value is None:
        return "未提供"
    if isinstance(value, (int, float)):
        return f"{value:+g}" if value > 0 else f"{value:g}"
    return clean_text(value)


def entry_routes(payload: dict[str, Any]) -> dict[str, str]:
    routes: dict[str, str] = {}
    for category in payload["categories"]:
        category_id = category["id"]
        if category_id not in CATEGORY_INTROS:
            raise ValueError(f"静态目录包含未知分类：{category_id}")
        for entry in category["entries"]:
            entry_id = entry["id"]
            if not isinstance(entry_id, int) or entry_id < 0:
                raise ValueError(f"图鉴条目 ID 无效：{entry_id}")
            # Food and prey can share Config_Item: keep one authoritative detail URL.
            routes.setdefault(entry["key"], f"guide/{category_id}/{entry_id}/")
    return routes


def public_image(base: str, icon: str) -> str:
    return base + icon[2:] if re.fullmatch(r"\./icons/[a-f0-9]{20}\.png", icon) else ""


def seo_head(title: str, description: str, url: str, base: str,
             schemas: list[dict[str, Any]], icon: str = "") -> str:
    image = public_image(base, icon)
    image_meta = ""
    if image:
        image_meta = f'''<meta property="og:image" content="{h(image)}">
    <meta property="og:image:alt" content="{h(title)}">
    <meta name="twitter:image" content="{h(image)}">'''
    structured = json.dumps({"@context": "https://schema.org", "@graph": schemas},
                            ensure_ascii=False, separators=(",", ":"), allow_nan=False)
    structured = structured.replace("<", "\\u003c").replace(">", "\\u003e").replace("&", "\\u0026")
    return f'''<meta name="robots" content="index,follow,max-image-preview:large">
    <link rel="canonical" href="{h(url)}">
    <link rel="sitemap" type="application/xml" href="{h(base)}sitemap.xml">
    <meta property="og:type" content="website">
    <meta property="og:locale" content="zh_CN">
    <meta property="og:site_name" content="{h(SITE_NAME)}">
    <meta property="og:title" content="{h(title)}">
    <meta property="og:description" content="{h(description)}">
    <meta property="og:url" content="{h(url)}">
    <meta name="twitter:card" content="summary">
    <meta name="twitter:title" content="{h(title)}">
    <meta name="twitter:description" content="{h(description)}">
    {image_meta}
    <script type="application/ld+json">{structured}</script>'''


def page_schema(title: str, description: str, url: str, base: str,
                crumbs: list[tuple[str, str]], collection: bool = False) -> list[dict[str, Any]]:
    result = [{"@type": "CollectionPage" if collection else "WebPage", "@id": url,
               "url": url, "name": clean_text(title), "description": clean_text(description),
               "inLanguage": "zh-CN", "isPartOf": {"@id": base + "#website"}}]
    if crumbs:
        result.append({"@type": "BreadcrumbList", "itemListElement": [
            {"@type": "ListItem", "position": index, "name": clean_text(name), "item": href}
            for index, (name, href) in enumerate(crumbs, 1)]})
    return result


def directory_links(payload: dict[str, Any], prefix: str = "./") -> str:
    routes = entry_routes(payload)
    return f'<p><a href="{h(prefix)}recommendations/">生存补给计划</a> · <a href="{h(prefix)}trade/">交易行情</a></p>' + "".join(
        f'<details><summary>{h(CATEGORY_INTROS[category["id"]][0])}</summary><nav class="directory-links">' + "".join(
            f'<a href="{h(prefix + routes[entry["key"]])}">{h(entry["name"])}</a>'
            for entry in category["entries"]) + '</nav></details>'
        for category in browse_categories(payload))


def home_seo(payload: dict[str, Any], template: str, base: str) -> str:
    schemas = [{"@type": "WebSite", "@id": base + "#website", "url": base,
                "name": SITE_NAME, "alternateName": "Survival Log 图鉴", "inLanguage": "zh-CN"}]
    schemas.extend(page_schema(HOME_TITLE, HOME_DESCRIPTION, base, base, []))
    icon = next((entry.get("icon", "") for category in payload["categories"]
                 for entry in category["entries"] if entry.get("icon")), "")
    head = seo_head(HOME_TITLE, HOME_DESCRIPTION, base, base, schemas, icon)
    template = re.sub(r"<title>.*?</title>", f"<title>{h(HOME_TITLE)}</title>", template, count=1)
    template = re.sub(r'<meta name="description" content="[^"]*">',
                      f'<meta name="description" content="{h(HOME_DESCRIPTION)}">', template, count=1)
    return template.replace("<!-- SEO_HEAD -->", head).replace(
        "<!-- SEO_DIRECTORY -->", directory_links(payload))


def shell(title: str, description: str, path: str, base: str, body: str,
          crumbs: list[tuple[str, str]], version: str, icon: str = "", collection: bool = False,
          extra_head: str = "") -> str:
    depth = len(PurePosixPath(path).parts)
    root = "../" * depth
    url = base + path
    breadcrumb = '<nav class="breadcrumbs" aria-label="当前位置">' + " / ".join(
        f'<a href="{h(href)}">{h(name)}</a>' for name, href in crumbs[:-1]) + "</nav>"
    head = seo_head(title, description, url, base,
                    page_schema(title, description, url, base, crumbs, collection), icon)
    return f'''<!doctype html>
<html lang="zh-CN">
  <head>
    <meta charset="utf-8">
    <meta name="viewport" content="width=device-width, initial-scale=1">
    <title>{h(title)}</title>
    <meta name="description" content="{h(description)}">
    {head}
    <link rel="icon" href="{root}favicon.svg" type="image/svg+xml">
    <link rel="stylesheet" href="{root}guide.css">
    <link rel="stylesheet" href="{root}game-theme.css">
    <script src="{root}i18n.js" defer></script>
    {extra_head}
  </head>
  <body>
    <header class="guide-header"><a href="{root}">{h(SITE_NAME)}</a><nav><a href="{root}">图鉴查询</a> · <a href="{root}recommendations/">补给推荐</a> · <a href="{root}trade/">交易行情</a></nav><label class="language-switch"><span>Language / 语言</span><select data-language-select aria-label="Language / 语言" disabled><option value="zh-CN">简体中文</option><option value="en">English</option></select></label></header>
    <main>{breadcrumb}{body}</main>
    <footer><p>数据版本：{h(version)}。属性来自公开静态配置，实际效果以游戏为准。</p><a href="{root}">返回图鉴查询</a> · <a href="{root}recommendations/">补给推荐</a> · <a href="{root}trade/">交易行情</a> · <a href="{root}sitemap.xml">站点地图</a></footer>
  </body>
</html>
'''


def profile_html(profile: dict[str, Any]) -> str:
    values = profile.get("per_use_stats") or profile["stats"]
    stats = '<dl class="stats">' + "".join(
        f'<div><dt>{h(stat["label"])}</dt><dd>{h(stat_value(stat["value"]))}</dd></div>'
        for stat in values if stat["value"] != 0) + "</dl>"
    tags = "、".join(clean_text(tag["name"]) + (f' ×{tag["count"]}' if tag["count"] > 1 else "")
                     for tag in profile["tags"]) or "无"
    extra = '<details><summary>查看全部五项属性</summary><dl class="fields">' + "".join(
        f'<div><dt>{h(stat["label"])}</dt><dd>{h(stat_value(stat["value"]))}</dd></div>' for stat in values) + '</dl></details>'
    facts = []
    if isinstance(profile.get("weight_grams"), (int, float)):
        facts.append(f'{profile["weight_grams"] / 1000:.2f} kg')
    if isinstance(profile.get("size"), list) and len(profile["size"]) == 2:
        facts.append("×".join(str(value) for value in profile["size"]))
    life = profile.get("shelf_life_days")
    if isinstance(life, (int, float)):
        facts.append(f'基础保质期 {life} 天' if life > 0 else '无保质期')
    return stats + extra + f'<p>食物 · {h(profile["sub_category"])} · 食用标签：{h(tags)}</p><p>{h(" · ".join(facts))}</p>' + (
        f'<p class="food-note">{h(profile["note"])}</p>' if profile["note"] else "")


def item_art(name: str, icon: str, base: str, profile: dict[str, Any] | None = None,
             *, is_dish: bool = False, fixed: bool = False, small: bool = False) -> str:
    image = public_image(base, icon)
    if not image and profile is None:
        return ""
    alt = name + ("游戏图标" if image else "图标占位")
    image = image or base + "favicon.svg"
    size = 72 if small else 192
    badge = ""
    if profile is not None:
        count = profile.get("serving_count" if is_dish else "use_times")
        usable = is_dish or profile.get("cookable") or profile.get("can_use") is not False
        known = usable and isinstance(count, int) and count > 0
        label = f"{count}次" if known else "可变" if is_dish and not fixed else "—"
        if is_dish:
            usage = f"整份可吃 {count} 次" if known else "食用次数未提供" if fixed else "食用次数随食材变化"
        else:
            usage = (f'每份可{"烹饪" if profile.get("cookable") else "食用"} {count} 次' if known
                     else "不可直接食用" if not usable else "配置未提供有效使用次数")
        badge = f'<span class="icon-uses" title="{h(usage)}" aria-label="{h(usage)}">{h(label)}</span>'
    loading = ' loading="lazy"' if small else ""
    return (f'<span class="guide-item-art{" small" if small else ""}">'
            f'<img class="entry-art" src="{h(image)}" width="{size}" height="{size}"'
            f'{loading} alt="{h(alt)}">{badge}</span>')


def fields_html(fields: list[dict[str, Any]]) -> str:
    return '<dl class="fields">' + "".join(
        f'<div><dt data-config-label="{h(field["field"])}">{h(field["label"])}</dt><dd>{h(field["value"])}</dd></div>'
        for field in fields) + "</dl>"


def entry_description(entry: dict[str, Any], label: str) -> str:
    name = clean_text(entry["name"])
    if "food" in entry:
        food = entry["food"]
        stats = "、".join(clean_text(stat["label"]) + stat_value(stat["value"]) for stat in food["stats"])
        tags = "、".join(clean_text(tag["name"]) for tag in food["tags"]) or "无"
        uses = food.get("use_times")
        usage = f'每份可{"烹饪" if food["cookable"] else "食用"}{uses}次。' if isinstance(uses, int) and uses > 0 else ""
        return f"生存日志 {name}。{usage}食用属性：{stats}。食品标签：{tags}。查看烹饪分类、说明和可用菜肴。"
    if "products" in entry:
        ingredients = next((clean_text(field["value"]) for field in entry["highlights"]
                            if field["field"] == "ingredients"), "")
        return f"生存日志 {name}配方" + (f"，食材：{ingredients}" if ingredients else "") + "。比较完美、优良、普通、失败品质的饱腹、心态、精力、健康和生命效果，查看制作要求。"
    detail = clean_text(entry["description"]) or "；".join(
        f'{clean_text(field["label"])}：{clean_text(field["value"])}' for field in entry["highlights"][:2])
    return f"生存日志 {name}{label}图鉴。{detail[:120]} 查看相关属性、要求和关联配置。"


def entry_body(entry: dict[str, Any], category: str, routes: dict[str, str], base: str,
               dishes: list[dict[str, Any]]) -> str:
    name = h(entry["name"])
    art = item_art(entry["name"], entry.get("icon", ""), base, entry.get("food"))
    interactive = base + "#" + category + "/" + quote(entry["key"], safe="")
    body = f'<div class="entry-heading">{art}<div><p class="eyebrow">SURVIVAL LOG · {h(CATEGORY_INTROS[category][0])}</p><h1>{name}</h1><p>配置 ID：{entry["id"]}</p><a class="action-link" href="{h(interactive)}">在图鉴中筛选与比较 →</a></div></div>'
    if entry["description"]:
        body += f'<p class="description">{h(entry["description"])}</p>'
    if entry.get("icon_source"):
        caption = "制造产物" if entry["icon_source"].get("kind") == "product" else "收获物"
        body += f'<p class="image-credit">图片：{h(entry["icon_source"]["name"])}（{caption}）</p>'
    if entry.get("plant"):
        plant = entry["plant"]
        body += '<section><h2>种植条件</h2>' + fields_html([
            {"field": "Size", "label": "占用空间", "value": str(plant["size"]) if plant["size"] is not None else "未提供"},
            {"field": "LightNeed", "label": "光照需求", "value": "≥ " + str(plant["light_need"]) if plant["light_need"] is not None else "未提供"},
            {"field": "ColdResistance", "label": "可承受寒冷", "value": "≤ " + str(plant["cold_resistance"]) if plant["cold_resistance"] is not None else "未提供"},
        ]) + '<p>光照不低于需求、寒冷不高于耐寒值时满足基础环境。寒冷越低越暖；生长时间未计加速与停滞。</p></section>'
    if entry.get("sources"):
        body += '<section><h2>获取来源</h2><ul class="related-list">'
        for source in entry["sources"]:
            target = (base + routes[source["key"]]) if source["category"] == "plant" else base + '#prey/' + quote(source["key"], safe="")
            label = "种植：" if source["category"] == "plant" else "捕获图鉴："
            body += f'<li><a href="{h(target)}">{label}{h(source["name"])}</a></li>'
        body += '</ul></section>'
    if "food" in entry:
        food = entry["food"]
        body += '<section><h2>食用属性与食用标签</h2>' + profile_html(food)
        body += f'<p>烹饪分类：{h(food["sub_category"])} · 可用于烹饪：{"是" if food["cookable"] else "否"}</p></section>'
        related = []
        for dish in dishes:
            exact = any(r["relation_type"] == "具体食材" and r["target_id"] == entry["id"] for r in dish["relations"])
            specific = any(r["relation_type"] == "具体食材" for r in dish["relations"])
            grouped = not specific and food["cookable"] and any(r["relation_type"] == "食材分类" and r["target_id"] == food["sub_category_id"] for r in dish["relations"])
            if exact or grouped:
                related.append((not exact, dish, "指定食材" if exact else "分类可用"))
        if related:
            body += '<section><h2>可用菜肴</h2><p>分类可用表示能占用对应食材槽位，仍需满足其他食材与制作要求。</p><ul class="related-list">'
            body += "".join(f'<li><a href="{h(base + routes[dish["key"]])}">{h(dish["name"])}</a><span>{kind}</span></li>'
                            for _order, dish, kind in sorted(related, key=lambda item: item[0])) + '</ul></section>'
    if "products" in entry:
        body += '<section><h2>各品质菜肴效果</h2><div class="quality-grid">'
        for product in entry["products"]:
            art = item_art(product["name"], product.get("icon", ""), base, product,
                           is_dish=True, fixed=entry.get("portion_model", {}).get("mode") == "fixed", small=True)
            caption = "每次食用属性" if product.get("per_use_stats") else "配置参考属性"
            quality = "优良" if product["quality"] == "良好" else product["quality"]
            body += f'<article class="quality">{art}<h3>{h(quality)}品质</h3><p>{h(product["name"])} · ID:{product["id"]}</p><p>成品分类：{h(product["sub_category"])}</p><p class="portion-note">{caption}</p>' + profile_html(product) + '</article>'
        body += '</div></section>'
        threshold = entry.get("portion_model", {}).get("threshold")
        if threshold:
            body += f'<p>分份标准：{h(threshold)} 饱腹 / 次。可吃次数按整份总饱腹除以标准向上取整，至少 1 次。通用配方的总属性随实际食材、档位与品质变化。</p>'
    if entry.get("effect_chips"):
        body += '<section><h2>设施效果</h2><dl class="fields">' + "".join(
            f'<div><dt>{h(chip["label"])}</dt><dd>{h(chip["value"])}'
            + (f' <span class="muted">（{h(chip["title"])}）</span>' if chip.get("title") else "")
            + '</dd></div>'
            for chip in entry["effect_chips"]) + '</dl></section>'
    highlights = [field for field in entry["highlights"] if not entry.get("plant") or field["field"] not in {"Size", "LightNeed", "ColdResistance"}]
    if entry.get("craft_recipes"):
        body += '<section><h2>制造配方</h2>'
        for group in entry["craft_recipes"]:
            materials = "、".join(f"{item['name']} × {item['count']}" if item["count"] > 1 else item["name"]
                                  for item in group["materials"]) or "未提供"
            options = []
            for option in group["options"]:
                label = "原色" if not option["dyes"] else "、".join(dye["name"] for dye in option["dyes"])
                target = (option.get("link") or {}).get("key")
                text = h(label)
                if target in routes:
                    text = f'<a href="{h(base + routes[target])}">{text}</a>'
                options.append(f'{text} <span class="muted">（{h(option["name"])} · 配方 ID {option["recipe_id"]}）</span>')
            level = "无" if group["level"] == 0 else f'{group["level"]}级' if group["level"] is not None else "未提供"
            body += (f'<p>材料：{h(materials)} · 要求等级：{h(level)}</p>'
                     f'<p>染料配色：{"、".join(options)}</p>')
        body += '</section>'
    if highlights:
        heading = "完成条件与方法" if category == "achievements" else "制作要求与主要信息" if category in {"dish", "craft"} else "主要信息"
        body += f'<section><h2>{heading}</h2>' + fields_html(highlights) + '</section>'
    groups: dict[str, list[str]] = defaultdict(list)
    for relation in entry["relations"]:
        target = relation.get("link", {}).get("key")
        text = h(relation["target_name"] or f'ID:{relation["target_id"]}')
        if target in routes:
            text = f'<a href="{h(base + routes[target])}">{text}</a>'
        groups[relation["relation_type"]].append(f'{text} <span class="muted">(ID:{relation["target_id"]})</span>')
    if groups:
        heading = "食材与关联条目" if category == "dish" else "关联条目"
        body += f'<section><h2>{heading}</h2><dl class="fields">' + "".join(
            f'<div><dt>{h(kind)}</dt><dd>{"、".join(values)}</dd></div>' for kind, values in groups.items()) + '</dl></section>'
    for field, heading in (("notes", "注意事项"), ("exclusions", "排除项")):
        if entry.get(field):
            body += f'<section><h2>{heading}</h2><ul>' + "".join(f'<li>{h(note)}</li>' for note in entry[field]) + '</ul></section>'
    body += '<details><summary>查看配置字段</summary>' + fields_html(entry["fields"]) + '</details>'
    return body


def query_redirect(base: str, category: str = "") -> str:
    target = base + (f"#{category}/" if category else "")
    return f'''<!doctype html>
<html lang="zh-CN"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<title>图鉴查询 · Survival Log</title><meta name="robots" content="noindex,follow">
<link rel="canonical" href="{h(base)}"><meta http-equiv="refresh" content="0;url={h(target)}"></head>
<body><p><a href="{h(target)}">进入图鉴查询</a></p></body></html>
'''


def seo_documents(payload: dict[str, Any], base: str, extra_documents: dict[str, str] | None = None) -> dict[str, str]:
    routes = entry_routes(payload)
    version = payload["metadata"].get("game_version", "未提供")
    dishes = next((category["entries"] for category in payload["categories"] if category["id"] == "dish"), [])
    docs: dict[str, str] = dict(extra_documents or {})
    crumbs = [(SITE_NAME, base)]
    categories = browse_categories(payload)
    for category in categories:
        category_id = category["id"]
        label = CATEGORY_INTROS[category_id][0]
        source_entries = next(c["entries"] for c in payload["categories"] if c["id"] == "food") if category_id in {"food", "ready-food"} else category["entries"]
        name_counts = Counter(clean_text(entry["name"]) for entry in source_entries)
        category_crumbs = [*crumbs, (label, base + f"#{category_id}/")]
        for entry in category["entries"]:
            route = routes[entry["key"]]
            if route + "index.html" not in docs:
                topic = "属性与标签" if category_id in {"food", "ready-food", "prey"} else "配方与各品质效果" if category_id == "dish" else "条件与方法" if category_id == "achievements" else f" · {label}图鉴"
                name = clean_text(entry["name"])
                qualifier = f'（ID:{entry["id"]}）' if name_counts[name] > 1 else ""
                title = f'{name}{qualifier}{topic} | 生存日志 Survival Log'
                docs[route + "index.html"] = shell(title, entry_description(entry, label), route, base,
                    entry_body(entry, category_id, routes, base, dishes),
                    [*category_crumbs, (entry["name"], base + route)], version, entry.get("icon", ""))
    namespace = "http://www.sitemaps.org/schemas/sitemap/0.9"
    sitemap = Element("urlset", xmlns=namespace)
    urls = [base, *(base + name.removesuffix("index.html") for name in docs)]
    for url in urls:
        SubElement(SubElement(sitemap, "url"), "loc").text = url
    docs["sitemap.xml"] = tostring(sitemap, encoding="utf-8", xml_declaration=True).decode("utf-8")
    # Replace former directories without breaking bookmarks or indexing duplicate lists.
    docs["guide/index.html"] = query_redirect(base)
    for category in categories:
        docs[f'guide/{category["id"]}/index.html'] = query_redirect(base, category["id"])
    return docs


def validate_output_targets(output_dir: Path, names: list[str]) -> None:
    for name in names:
        target = output_dir / name
        for path in (target, *target.parents):
            if path == output_dir:
                break
            if path.is_symlink():
                raise ValueError(f"静态页面输出路径不能是符号链接：{name}")
            if path.exists() and ((path == target and not path.is_file()) or
                                  (path != target and not path.is_dir())):
                raise ValueError(f"静态页面输出路径类型不正确：{name}")


TRADE_TITLE = "生存日志交易行情｜物资换什么、在哪换、加工值不值 · Survival Log"
TRADE_DESCRIPTION = "登记手头物资，比较据点收货折价、联系人需求加价与加工增值，查找目标物品和货架。按玩家输入试算交易价值。"


def trade_item_row(entry: dict[str, Any], base: str, categories: dict[str, str],
                   shared_ids: set[int]) -> str:
    icon = public_image(base, entry.get("icon") or "")
    art = (f'<img class="trade-icon" src="{h(icon)}" width="48" height="48" loading="lazy" alt="">'
           if icon else '<span class="trade-icon trade-icon-empty" aria-hidden="true"></span>')
    name = clean_text(entry["name"])
    codex = entry.get("codex")
    name_cell = (f'<a href="{h(base + "#" + codex + "/" + quote("Config_Item:" + str(entry["id"]), safe=""))}">{h(name)}</a>'
                 if codex else h(name))
    cat = entry.get("cat")
    cat_label = categories.get(str(cat), f"分类 {cat}") if cat is not None else "—"
    count = entry.get("count")
    tv = entry.get("trade_value")
    uses = entry.get("use_times")
    full_value = tv * max(1, uses or 1) if isinstance(tv, (int, float)) else None
    size = entry.get("size")
    area = size[0] * size[1] if (isinstance(size, list) and len(size) == 2
                                and all(isinstance(n, int) and n > 0 for n in size)) else None
    density = full_value / area if full_value is not None and area else None
    badge = '<span class="shared-badge">多据点</span>' if entry["id"] in shared_ids else ""
    return (f'<tr data-cat="{h(str(cat))}" data-tv="{tv if isinstance(tv, (int, float)) else ""}"'
            f' data-uses="{uses if isinstance(uses, (int, float)) else ""}"'
            f' data-name="{h(name)}"{"" if entry["id"] not in shared_ids else " data-shared"}>'
            f'<td class="trade-cell-icon">{art}</td>'
            f'<th scope="row">{name_cell}{badge}</th>'
            f'<td><span class="trade-cat" data-cat="{h(str(cat))}">{h(cat_label)}</span></td>'
            f'<td class="num">{h("—" if count is None else count)}</td>'
            f'<td class="num">{h("—" if not isinstance(tv, (int, float)) else tv)}</td>'
            f'<td class="num">{h("—" if full_value is None else full_value)}</td>'
            f'<td class="num">{h("—" if not uses else uses)}</td>'
            f'<td class="num">{h("—" if area is None else f"{size[0]} × {size[1]} = {area}")}</td>'
            f'<td class="num">{h("—" if density is None else format(density, ".2f"))}</td></tr>')


def trade_table(rows: list[str], shared_header: bool = False) -> str:
    head = ("<tr><th scope=\"col\">图标</th><th scope=\"col\">物品</th><th scope=\"col\">类别</th>"
            "<th scope=\"col\">配置数量</th><th scope=\"col\">每用量基值</th><th scope=\"col\">完整一件基值</th>"
            + ("<th scope=\"col\">在售据点数</th>" if shared_header else "<th scope=\"col\">每份次数</th>")
            + "<th scope=\"col\">占格</th><th scope=\"col\">每格基值</th>"
            + "</tr>")
    return f'<div class="table-scroll"><table class="trade-table">{head}{"".join(rows)}</table></div>'


def trade_document(model: dict[str, Any] | None, base: str, version: str) -> str:
    crumbs = [("生存日志 · 幸存者图鉴", base), ("交易行情", base + "trade/")]
    if not model:
        body = ('<div class="entry-heading"><div><p class="eyebrow">SURVIVAL LOG / TRADE</p>'
                '<h1>交易行情</h1></div></div>'
                '<p>当前公开数据版本没有匹配的交易据点模型文件。请用与本站静态库一致的游戏版本运行'
                ' <code>python codex_pages_trade.py</code> 重新生成后重建网页。</p>')
        return shell(TRADE_TITLE, TRADE_DESCRIPTION, "trade/", base, body, crumbs, version)

    shared_ids = {entry["id"] for entry in model.get("shared", [])}
    categories = {str(key): value for key, value in (model.get("categories") or {}).items()}
    body = '''<div class="trade-hero"><p class="eyebrow">SURVIVAL LOG / TRADE DESK</p><h1>让手头物资换得更多</h1>
<p class="trade-subtitle">先留下生存必需品，把愿意拿去换的余量填进来。比较直接交换，再看加工有没有增值。</p>
<p class="trade-assumption">按配置与填写条件试算 · 当前货架、需求与加成由你确认</p></div>
<div id="trade-planner" hidden>
<div class="trade-workbench">
<section class="trade-input"><h2><span class="trade-step">01</span> 我有什么可以换</h2>
<p class="trade-help">数量按件 / 包填写；已用过的物品调整剩余比例。只填愿意投入的数量。</p>
<div class="trade-controls"><label>找物资<input id="stock-search" type="search" placeholder="名称或 ID，例如：铁皮、香米"></label>
<label>类别<select id="stock-cat"><option value="">全部类别</option></select></label></div>
<div id="stock-catalog" class="trade-catalog"></div><p id="stock-status" class="trade-help"></p>
<details class="trade-settings"><summary>物资很多？按行批量登记</summary>
<p class="trade-help">每行填写“名称或 ID，件数，剩余百分比”，百分比可省略。同物品会更新数量与剩余比例。</p>
<label for="stock-bulk">批量物资</label><textarea id="stock-bulk" rows="4" placeholder="铁皮，20&#10;生态香米，2，50"></textarea>
<button id="stock-import" type="button">登记这些物资</button><p id="stock-import-status" class="trade-help" role="status"></p></details>
<div class="trade-basket-heading"><h3>待交换清单</h3><button id="stock-example" type="button">试填铁皮与香米</button><button id="stock-clear" type="button">清空</button></div>
<div id="stock-basket"></div><p class="trade-help">清单保存在此浏览器，刷新后可继续使用。</p></section>
<section class="trade-output"><h2><span class="trade-step">02</span> 去哪里，能换多少</h2>
<div class="trade-controls"><label>交易对象<select id="trade-destination"><option value="all">比较所有据点</option><option value="contact">陌生人 / 联系人</option></select></label>
<label>找目标物品<input id="trade-target-search" type="search" placeholder="名称或 ID"></label>
<label>我想换回<select id="trade-target"><option value="">只比较交出价值</option></select></label>
<label>目标数量<input id="trade-target-count" type="number" value="1" min="1" max="9999" step="1"></label></div>
<details class="trade-settings" id="trade-point-settings"><summary>选择已经解锁的据点</summary><div id="trade-enabled-points" class="trade-demand"></div></details>
<div id="trade-contact" hidden><p class="trade-help">照着游戏当前需求勾选类别；加价只作用于勾选的物资。</p><div id="trade-demand" class="trade-demand"></div>
<label>需求程度<select id="trade-urgency"><option value="0">无需求加价</option></select></label></div>
<details class="trade-settings"><summary>鉴价、谈判与特殊状态</summary><div class="trade-controls">
<label>鉴价加成 / %<input id="trade-appraisal" type="number" min="0" max="1000" value="0" step="1"></label>
<label>谈判减免 / 价值点<input id="trade-discount" type="number" min="0" value="0" step="1"></label>
<label class="trade-check"><input id="trade-camp" type="checkbox">无尽模式：营地特殊状态药品加价</label></div>
<p class="trade-help">按本次交易的游戏显示填写。谈判减的是成交门槛的价值点；营地勾选项仅影响换入药品。</p></details>
<div id="trade-summary" class="trade-summary" role="status"></div>
<div id="trade-comparison"></div><div id="trade-breakdown"></div>
<p class="trade-help">换入数量是估值上限，成交还需当前有货、双方物品能装进无人机。本页不推测装箱和实时库存。</p></section>
</div>
<section class="trade-cargo"><h2><span class="trade-step">03</span> 格子有限，先带哪些</h2>
<p class="trade-help">每格交出价值 = 一件物资的交出估值 ÷ 占格数。会应用当前对象的折价、需求、鉴价和清单剩余比例；指定目标时，只比较能换到目标的对象。</p>
<div class="trade-controls"><label>携带范围<select id="cargo-scope"><option value="stock">只看清单余量</option><option value="all">全部物品，找携带方向</option></select></label>
<label>找高价值物资<input id="cargo-search" type="search" placeholder="物品名称或 ID"></label>
<label>类别<select id="cargo-cat"><option value="">全部类别</option></select></label>
<label>排序<select id="cargo-sort"><option value="density">每格交出价值最高</option><option value="value">单件交出价值最高</option></select></label></div>
<p id="cargo-status" class="trade-help" role="status"></p><div id="cargo-results"></div>
<button id="cargo-more" type="button" hidden>再看 20 种物资</button>
<p class="trade-help">全部物品按完整一件计算；清单余量按填写的剩余比例计算。所需件数是假设只交出该物资，不会自动扣减清单。格数为面积合计，仍需核对无人机的宽高、摆放和负重。</p></section>
<section class="trade-processing"><h2><span class="trade-step">04</span> 要不要先加工</h2>
<p class="trade-help">看加工比直接交换多赚多少价值。比较所有据点时，原料按各自最优据点的直接交换价计成本。每行是独立方案，材料不能在多行里重复投入。</p>
<div class="trade-controls"><label>备料范围<select id="process-scope"><option value="stock">只看清单里能做的</option><option value="all">全部配方，找备料方向</option></select></label>
<label>加工方式<select id="process-kind"><option value="">烹饪与制造</option><option value="cook">烹饪</option><option value="craft">制造</option></select></label>
<label>烹饪等级<select id="process-cook-level"><option value="1">1级</option><option value="2">2级</option><option value="3">3级</option></select></label>
<label>制造等级<select id="process-craft-level"><option value="1">1级</option><option value="2">2级</option><option value="3">3级</option><option value="4">4级</option><option value="5">5级</option></select></label>
<label>菜肴品质<select id="process-quality"><option>普通</option><option>良好</option><option>完美</option></select></label>
<label>排序<select id="process-sort"><option value="gain">每次加工增值最多</option><option value="ratio">原料增值比例最高</option><option value="total">现有余量总增值最多</option><option value="density">成品每格价值最高</option></select></label>
<label>找配方<input id="process-search" type="search" placeholder="配方、成品或原料名称"></label>
<label class="trade-check"><input id="process-positive" type="checkbox" checked>只看有增值</label></div>
<p id="process-status" class="trade-help" role="status"></p><div id="process-results"></div>
<button id="process-more" type="button" hidden>再看 20 个方案</button>
<p class="trade-help">菜肴品质是所选结果的情景；制造按普通成功产物。未计成功概率、完美返料、燃料、精力、设备和路程。配方还需在游戏内解锁；含多次使用图纸的制造暂不排名。</p>
</section></div>
<noscript><p>启用 JavaScript 可登记物资、比较交换与加工收益。下方可直接查阅配置货架。</p></noscript>
<details class="trade-shelves" id="trade-shelves"><summary>查货架 / 校正当前无货</summary>
<p class="trade-help">默认按配置货架仍有货计算拒收。游戏里某物已不在当前可见货架上时，勾选“当前无货”，该物就可重新估值。配置数量不是实时库存。</p>
<div class="trade-controls"><label>找货架物品<input id="shelf-search" type="search" placeholder="物品名称或 ID"></label></div>'''
    body += '<nav class="trade-points-nav" aria-label="据点跳转">' + "".join(
        f'<a href="#p{h(str(point["id"]))}">{h(clean_text(point["name"]))}</a>' for point in model["points"]) + '</nav>'
    for point in model["points"]:
        rows = [trade_item_row(entry, base, categories, shared_ids).replace('</tr>',
                f'<td class="shelf-state"><label><input type="checkbox" data-absent-point="{point["id"]}" '
                f'data-absent-item="{entry["id"]}">当前无货</label></td></tr>') for entry in point["items"]]
        offer = "、".join(categories.get(str(cat), f"分类 {cat}") for cat in point.get("offer_cats") or [])
        body += f'<section class="trade-point" id="p{h(str(point["id"]))}">'
        body += (f'<h2>{h(clean_text(point["name"]))}<span class="trade-shop-id">货架 {h(str(point["shop_id"]))}</span></h2>')
        if point.get("hint"):
            body += f'<p class="trade-hint">解锁提示：{h(clean_text(point["hint"]))}</p>'
        if offer:
            body += f'<p class="trade-offer">货架分类：{h(offer)}</p>'
        half_cat = categories.get(str(point.get("half_value_cat")), f"分类 {point.get('half_value_cat')}")
        body += f'<p class="trade-offer">{h(half_cat)}交出时按同类折价；当前货架已有的同物品拒收。</p>'
        body += trade_table(rows).replace('</tr>', '<th scope="col">货架校正</th></tr>', 1)
        body += '</section>'
    body += '''</details><details class="trade-mechanics"><summary>怎么看这些价值与增值</summary>
<p>交换用的是交易价值，不是灾前价格。完整一件基值 = TradeValue × max(1, 配置 UseTimes)。已用物品再乘“剩余次数 / 实例最大次数”；菜肴分份不额外增加完整一锅的交易基值。</p>
<p>据点：同类物资应用该据点折价系数，再应用有效 TradeSellRate；当前可见货架仍有的同物品拒收。联系人：需求物资应用需求加价，不应用据点专用 TradeSellRate。鉴价与需求加成相加。</p>
<p>加工增值 = 成品交出估值 − 原料直接交换估值。比较所有据点时，原料按各自最优据点计成本；指定对象时按该对象计成本。原料若在比较范围内都被拒收，保守按原始基值计成本，不能当免费材料。谈判减免只用于本次交换，不计入每锅增值。</p>
<p>关系进度 NextNeed 是下一关系档的门槛，不是轮换需求，也不作为普遍估值倍率。没有把赠礼或补给上限套到普通交换。当前无货只校正拒收，不代表可换入库存。</p>
<p>试算覆盖普通双向交易。援助、捐赠、派遣、损坏或特殊货架的限制请按游戏界面确认。不同配方不会联合分配库存；排序帮助选加工方向，不承诺整仓物资的全局最优路线。</p></details>'''
    # 与补给推荐页一致：JSON 合法的 unicode 转义防止 </script> 截断，不做 HTML 转义。
    data_json = json.dumps(model, ensure_ascii=False, separators=(",", ":"), allow_nan=False) \
        .replace("<", "\\u003c").replace("&", "\\u0026")
    body += f'<script id="trade-data" type="application/json">{data_json}</script>'
    return shell(TRADE_TITLE, TRADE_DESCRIPTION, "trade/", base, body, crumbs, version,
                 extra_head='<link rel="stylesheet" href="../trade.css"><script src="../cooking.js" defer></script><script src="../trade.js" defer></script>')
