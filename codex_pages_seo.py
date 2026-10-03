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
HOME_TITLE = "生存日志图鉴｜食材属性、食品标签与菜肴效果 · Survival Log"
HOME_DESCRIPTION = "Survival Log 生存日志玩家图鉴：查询食材的饱食、心态、精力、健康、生命属性与食品标签，比较完美、良好、普通、失败品质的菜肴效果，并查找植物、猎物、制造、家具和成就。"
CATEGORY_INTROS = {
    "food": ("食材与食品", "查询食材的五项食用属性、食品标签、烹饪分类与可用菜肴。"),
    "dish": ("菜肴与效果", "查看配方食材和制作要求，比较完美、良好、普通、失败品质的成品效果。"),
    "plant": ("植物", "查看植物、种子、收获物与各等级配置。"),
    "prey": ("猎物", "查看猎物的属性、食品标签与关联配置。"),
    "craft": ("制造", "查看制造材料、等级要求、产物与失败产物。"),
    "furniture": ("家具", "查看家具功能、材料及相关配置。"),
    "achievements": ("成就", "查询成就完成条件、方法、角色限制和注意事项。"),
}


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
    return '<nav class="directory-links" aria-label="完整图鉴分类">' + "".join(
        f'<a href="{h(prefix)}guide/{category["id"]}/">{h(CATEGORY_INTROS[category["id"]][0])}</a>'
        for category in payload["categories"]) + "</nav>"


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
          crumbs: list[tuple[str, str]], version: str, icon: str = "", collection: bool = False) -> str:
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
  </head>
  <body>
    <header class="guide-header"><a href="{root}">{h(SITE_NAME)}</a><a href="{root}guide/">完整图鉴</a></header>
    <main>{breadcrumb}{body}</main>
    <footer><p>数据版本：{h(version)}。属性来自公开静态配置，实际效果以游戏为准。</p><a href="{root}">打开筛选图鉴</a> · <a href="{root}guide/">浏览分类</a> · <a href="{root}sitemap.xml">站点地图</a></footer>
  </body>
</html>
'''


def profile_html(profile: dict[str, Any]) -> str:
    stats = '<dl class="stats">' + "".join(
        f'<div><dt>{h(stat["label"])}</dt><dd>{h(stat_value(stat["value"]))}</dd></div>'
        for stat in profile["stats"]) + "</dl>"
    tags = "、".join(clean_text(tag["name"]) + (f' ×{tag["count"]}' if tag["count"] > 1 else "")
                     for tag in profile["tags"]) or "无"
    return stats + f'<p>食品标签：{h(tags)}</p>' + (
        f'<p class="food-note">{h(profile["note"])}</p>' if profile["note"] else "")


def fields_html(fields: list[dict[str, Any]]) -> str:
    return '<dl class="fields">' + "".join(
        f'<div><dt>{h(field["label"])}</dt><dd>{h(field["value"])}</dd></div>'
        for field in fields) + "</dl>"


def entry_description(entry: dict[str, Any], label: str) -> str:
    name = clean_text(entry["name"])
    if "food" in entry:
        food = entry["food"]
        stats = "、".join(clean_text(stat["label"]) + stat_value(stat["value"]) for stat in food["stats"])
        tags = "、".join(clean_text(tag["name"]) for tag in food["tags"]) or "无"
        return f"生存日志 {name}的食用属性：{stats}。食品标签：{tags}。查看烹饪分类、食用说明和可用菜肴。"
    if "products" in entry:
        ingredients = next((clean_text(field["value"]) for field in entry["highlights"]
                            if field["field"] == "ingredients"), "")
        return f"生存日志 {name}配方" + (f"，食材：{ingredients}" if ingredients else "") + "。比较完美、良好、普通、失败品质的饱食、心态、精力、健康和生命效果，查看制作要求。"
    detail = clean_text(entry["description"]) or "；".join(
        f'{clean_text(field["label"])}：{clean_text(field["value"])}' for field in entry["highlights"][:2])
    return f"生存日志 {name}{label}图鉴。{detail[:120]} 查看相关属性、要求和关联配置。"


def entry_body(entry: dict[str, Any], category: str, routes: dict[str, str], base: str,
               dishes: list[dict[str, Any]]) -> str:
    name = h(entry["name"])
    icon = public_image(base, entry.get("icon", ""))
    art = f'<img class="entry-art" src="{h(icon)}" width="192" height="192" alt="{name}游戏图标">' if icon else ""
    interactive = base + "#" + category + "/" + quote(entry["key"], safe="")
    body = f'<div class="entry-heading">{art}<div><p class="eyebrow">SURVIVAL LOG · {h(CATEGORY_INTROS[category][0])}</p><h1>{name}</h1><p>配置 ID：{entry["id"]}</p><a class="action-link" href="{h(interactive)}">在图鉴中筛选与比较 →</a></div></div>'
    if entry["description"]:
        body += f'<p class="description">{h(entry["description"])}</p>'
    if "food" in entry:
        food = entry["food"]
        body += '<section><h2>食用属性与食品标签</h2>' + profile_html(food)
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
            body += f'<article class="quality"><h3>{h(product["quality"])}品质</h3><p>{h(product["name"])} · ID:{product["id"]}</p>' + profile_html(product) + '</article>'
        body += '</div></section>'
    if entry["highlights"]:
        heading = "完成条件与方法" if category == "achievements" else "制作要求与主要信息" if category in {"dish", "craft"} else "主要信息"
        body += f'<section><h2>{heading}</h2>' + fields_html(entry["highlights"]) + '</section>'
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


def seo_documents(payload: dict[str, Any], base: str) -> dict[str, str]:
    routes = entry_routes(payload)
    version = payload["metadata"].get("game_version", "未提供")
    dishes = next((category["entries"] for category in payload["categories"] if category["id"] == "dish"), [])
    docs: dict[str, str] = {}
    crumbs = [(SITE_NAME, base), ("完整图鉴", base + "guide/")]
    cards = "".join(f'<a class="category-card" href="{h(base)}guide/{c["id"]}/"><h2>{h(CATEGORY_INTROS[c["id"]][0])}</h2><p>{h(CATEGORY_INTROS[c["id"]][1])}</p><span>{len(c["entries"])} 个条目 →</span></a>'
                    for c in payload["categories"])
    docs["guide/index.html"] = shell("生存日志完整图鉴目录 · Survival Log", HOME_DESCRIPTION,
                                     "guide/", base, '<h1>完整图鉴目录</h1><p>按分类浏览每个条目的属性和关联信息，也可以打开筛选图鉴搜索与比较。</p><div class="category-grid">' + cards + '</div>', crumbs, version, collection=True)
    for category in payload["categories"]:
        category_id = category["id"]
        label, intro = CATEGORY_INTROS[category_id]
        name_counts = Counter(clean_text(entry["name"]) for entry in category["entries"])
        path = f"guide/{category_id}/"
        category_crumbs = [*crumbs, (label, base + path)]
        cards = ""
        for entry in category["entries"]:
            icon = public_image(base, entry.get("icon", ""))
            art = f'<img src="{h(icon)}" width="72" height="72" loading="lazy" alt="{h(entry["name"])}游戏图标">' if icon else ""
            cards += f'<a class="catalog-card" href="{h(base + routes[entry["key"]])}">{art}<div><h2>{h(entry["name"])}</h2><p>{h(entry_description(entry, label))}</p><span>ID:{entry["id"]}</span></div></a>'
            route = routes[entry["key"]]
            if route + "index.html" not in docs:
                topic = "属性与标签" if category_id in {"food", "prey"} else "配方与各品质效果" if category_id == "dish" else "条件与方法" if category_id == "achievements" else f" · {label}图鉴"
                name = clean_text(entry["name"])
                qualifier = f'（ID:{entry["id"]}）' if name_counts[name] > 1 else ""
                title = f'{name}{qualifier}{topic} | 生存日志 Survival Log'
                docs[route + "index.html"] = shell(title, entry_description(entry, label), route, base,
                    entry_body(entry, category_id, routes, base, dishes),
                    [*category_crumbs, (entry["name"], base + route)], version, entry.get("icon", ""))
        docs[path + "index.html"] = shell(f'{label}图鉴 | 生存日志 Survival Log', f'生存日志 {label}完整图鉴。{intro}',
            path, base, f'<h1>{h(label)}</h1><p>{h(intro)}</p><p>{len(category["entries"])} 个条目</p><div class="catalog-grid">{cards}</div>', category_crumbs, version, collection=True)
    namespace = "http://www.sitemaps.org/schemas/sitemap/0.9"
    sitemap = Element("urlset", xmlns=namespace)
    urls = [base, *(base + name.removesuffix("index.html") for name in docs)]
    for url in urls:
        SubElement(SubElement(sitemap, "url"), "loc").text = url
    docs["sitemap.xml"] = tostring(sitemap, encoding="utf-8", xml_declaration=True).decode("utf-8")
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
