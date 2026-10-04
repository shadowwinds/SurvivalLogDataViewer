"""Explainable supply recommendations from allowlisted static codex fields."""

from __future__ import annotations

import json
import math
from collections import Counter
from typing import Any, Callable

from codex_pages_seo import entry_routes, h, item_art, shell


STAGES = {1: "前期 · 烹饪 Lv.1", 2: "中期 · 烹饪 Lv.2", 3: "后期 · 烹饪 Lv.3"}
QUALITIES = ("普通", "良好", "完美")
MODELS = {
    "stock": {"value": ("饱食 / 基价", 50), "storage": ("基础保质值", 25),
              "space": ("饱食 / 背包格", 15), "effects": ("辅助恢复 / 基价", 10)},
    "ingredients": {"value": ("每次用量的价格优势", 35), "storage": ("基础保质值", 25),
                    "coverage": ("可做的固定配方数", 25), "menu": ("关联菜肴最高指数", 15)},
    "dishes": {"value": ("成品饱食 / 食材摊销价", 50), "speed": ("饱食 / 烹饪小时", 20),
               "gain": ("饱食增量 / 食材摊销价", 15), "effects": ("辅助恢复 / 食材摊销价", 15)},
    "crops": {"value": ("基础饱食 / 尺寸 / 生长日", 40),
              "uses": ("烹饪用量 / 尺寸 / 生长日", 35), "coverage": ("可用固定配方数", 25)},
}
VIEW_LABELS = {"stock": "即食囤货", "ingredients": "烹饪备料", "dishes": "菜肴推荐", "crops": "作物种植", "trade": "交易取舍"}
VIEW_INTROS = {
    "stock": "优先比较整包饱食与基价，再考虑保质值、占格和辅助恢复。零饱食饮品与无有效购买价物品另列。",
    "ingredients": "从本阶段的具体组合反推备料价值，比较买入与种植；通用菜也纳入用途。",
    "dishes": "前期保饱食，后期重心态。按实际食材与品质计算每日效果，再比较备料、照料和空间成本。",
    "crops": "按整数容器比较每天收获、成熟时间与每天照料，短周期会增加播种收获的频率。",
    "trade": "比较食材换入基值与成品交出估值；交易配餐独立选组合，也显示食用与出售的取舍。",
}


def number(value: Any, *, positive: bool = False) -> float | None:
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
        return None
    return float(value) if not positive or value > 0 else None


def uses(value: Any) -> int | None:
    return value if isinstance(value, int) and not isinstance(value, bool) and value > 0 else None


def effects(stats: list[float]) -> float:
    return stats[1] + .5 * stats[2] + stats[3] + .5 * stats[4]


def harm(stats: list[float], satiety: float) -> float:
    adverse = sum(max(0, -value) * weight for value, weight in zip(stats[1:], (2, 1, 3, 2)))
    return min(30, 100 * adverse / max(1, satiety))


def rate_rows(rows: list[dict[str, Any]], view: str) -> None:
    """Midrank percentiles keep ties equal; filters never change the cohort."""
    valid = [row for row in rows if not row.get("reason")]
    for row in rows:
        row["score"] = None
        row["components"] = []
    for key, (label, weight) in MODELS[view].items():
        values = sorted(row["metrics"][key] for row in valid)
        for row in valid:
            value = row["metrics"][key]
            lower = sum(other < value for other in values)
            equal = values.count(value)
            percentile = 50 if len(values) < 2 else 100 * (lower + (equal - 1) / 2) / (len(values) - 1)
            if value == 0 and all(other >= 0 for other in values):
                percentile = 0
            row["components"].append({"label": label, "weight": weight, "percentile": round(percentile, 2)})
    for row in valid:
        row["penalty"] = round(row.get("penalty", 0), 2)
        row["score"] = round(max(0, sum(c["percentile"] * c["weight"] / 100
                                      for c in row["components"]) - row["penalty"]), 1)


def build_recommendations(categories: list[dict[str, Any]], raw_entries: dict[str, dict[str, Any]],
                          items: dict[int, tuple[str, dict[str, Any]]],
                          profile: Callable[[dict[str, Any]], dict[str, Any]]) -> dict[str, Any]:
    by_category = {c["id"]: c["entries"] for c in categories}
    routes = entry_routes({"categories": categories})
    names = {entry["key"]: entry["name"] for category in categories for entry in category["entries"]}

    def item_info(item_id: int) -> dict[str, Any]:
        key = f"Config_Item:{item_id}"
        name, raw = items.get(item_id, (f"ID:{item_id}", {}))
        name = names.get(key, name)
        raw = raw_entries.get(key, raw)
        food = profile(raw)
        stats = [number(s["value"]) for s in food["stats"]]
        size = raw.get("Size")
        area = (math.prod(size) if isinstance(size, list) and len(size) == 2
                and all(number(n, positive=True) is not None for n in size) else None)
        return {"id": item_id, "name": name, "path": routes.get(key, ""), "icon": food["icon"],
                "cookable": food["cookable"], "can_use": food["can_use"], "category": raw.get("Category"),
                "uses": uses(raw.get("UseTimes")), "stats": stats, "price": number(raw.get("price")),
                "life": number(raw.get("Life")), "area": area, "group": food["sub_category"],
                "tags": food["tags"], "trade_value": number(raw.get("TradeValue")),
                "sell_rate": number(raw.get("TradeSellRate")), "seed_plant": raw.get("Plant")}

    foods = [item_info(entry["id"]) for entry in by_category.get("food", [])]
    stock, ingredients = [], []
    for item in foods:
        row = {**item, "metrics": {}, "reason": ""}
        if item["cookable"]:
            ingredients.append(row)
            continue
        if item["can_use"] is not True:
            row["reason"] = "配置不允许使用，或可用性未知"
        elif item["uses"] is None or any(s is None for s in item["stats"]):
            row["reason"] = "使用次数或恢复属性不完整"
        elif number(item["price"], positive=True) is None:
            row["reason"] = "无有效购买基价；不按免费商品推荐"
        elif item["stats"][0] <= 0:
            row["reason"] = "非饱食补给；可在图鉴查看专项恢复用途"
        elif number(item["life"], positive=True) is None or item["area"] is None:
            row["reason"] = "保质值或背包尺寸不完整"
        else:
            row["total"] = [s * item["uses"] for s in item["stats"]]
            row["cost100"] = 100 * item["price"] / row["total"][0]
            row["metrics"] = {"value": row["total"][0] / item["price"], "storage": item["life"],
                              "space": row["total"][0] / item["area"], "effects": effects(row["total"]) / item["price"]}
            row["penalty"] = harm(row["total"], row["total"][0])
        stock.append(row)
    rate_rows(stock, "stock")

    dishes = []
    groups = {r["target_id"]: r["target_name"] for entry in by_category.get("dish", [])
              for r in entry["relations"] if r["relation_type"] == "食材分类"}
    for entry in by_category.get("dish", []):
        raw = raw_entries[entry["key"]]
        requirements = [dict(item_info(item_id), amount=count) for item_id, count in Counter(raw.get("SpecificItems", [])).items()]
        level = raw.get("MinLevel")
        row = {"id": entry["id"], "name": entry["name"], "path": routes[entry["key"]],
               "level": level if isinstance(level, int) and 1 <= level <= 3 else None,
               "seconds": number(raw.get("CookTime"), positive=True), "ingredients": requirements,
               "groups": [{"name": groups.get(group, f"ID:{group}"), "amount": count}
                          for group, count in Counter(raw.get("TagCombo", [])).items()],
               "tier": raw.get("Tier"), "qualities": {}, "ratings": {}}
        costs_known = bool(requirements) and all(number(i["price"], positive=True) is not None
                                                and i["uses"] and i["category"] == 1 and i["cookable"]
                                                for i in requirements)
        inputs_known = bool(requirements) and all(i["stats"][0] is not None for i in requirements)
        row["cost"] = sum(i["price"] / i["uses"] * i["amount"] for i in requirements) if costs_known else None
        row["basket"] = sum(i["price"] * math.ceil(i["amount"] / i["uses"]) for i in requirements) if costs_known else None
        row["input_satiety"] = sum(i["stats"][0] * i["amount"] for i in requirements) if inputs_known else None
        for product in entry["products"]:
            if product["quality"] not in QUALITIES:
                continue
            values = [number(s["value"]) for s in product["stats"]]
            total = [math.ceil(v) for v in values] if requirements and all(v is not None for v in values) else None
            result = {"icon": product["icon"], "servings": product["serving_count"], "total": total,
                      "per_use": [s["value"] for s in product["per_use_stats"]] if product["per_use_stats"] else None,
                      "trade_value": item_info(product.get("id", 0))["trade_value"],
                      "sell_rate": item_info(product.get("id", 0))["sell_rate"]}
            row["qualities"][product["quality"]] = result
        if not requirements:
            row["reason"] = "通用配方的成本、总恢复和次数取决于实际食材" if row["groups"] else "无指定食材，兜底结果不作主动制作推荐"
        elif row["level"] is None:
            row["reason"] = "制作等级不完整"
        elif not costs_known or not inputs_known:
            row["reason"] = "食材价格、使用次数或原始饱食不完整"
        elif row["seconds"] is None:
            row["reason"] = "烹饪时间不完整"
        else:
            row["reason"] = ""
        dishes.append(row)

    crops = []
    for entry in by_category.get("plant", []):
        raw = raw_entries[entry["key"]]
        harvest = [dict(item_info(item_id), amount=count) for item_id, count in Counter(raw.get("Gain", [])).items()]
        edible = [i for i in harvest if i["category"] == 1 and (i["cookable"] or i["can_use"] is True)]
        crop = {"id": entry["id"], "name": entry["name"], "path": routes[entry["key"]], "harvest": harvest,
                "icon": next((i["icon"] for i in harvest if i["icon"]), ""),
                "seconds": number(raw.get("GrowthTime"), positive=True), "size": number(raw.get("Size"), positive=True),
                "seed_rate": number(raw.get("Seed_Rate")), "ratings": {},
                "care": {"pest": number(raw.get("Pest")), "weed": number(raw.get("Weed")), "water": number(raw.get("Dry"))},
                "plant": entry.get("plant", {}),
                "perfect_harvest": [dict(item_info(item_id), amount=count) for item_id, count in Counter(raw.get("Perfect_Gain", [])).items()],
                "seeds": [item_info(item_id) for item_id, (_, item) in items.items()
                          if item.get("Plant") == entry["id"]]}
        if not edible:
            crop["reason"] = "基础收获不属于食用或烹饪补给"
        elif len(edible) != len(harvest) or any(i["uses"] is None or i["stats"][0] is None for i in edible):
            crop["reason"] = "基础收获属性不完整"
        elif crop["seconds"] is None or crop["size"] is None:
            crop["reason"] = "基础生长时间或尺寸不完整"
        else:
            crop["reason"] = ""
            crop["satiety"] = sum(i["stats"][0] * i["uses"] * i["amount"] for i in edible if i["can_use"] is True)
            crop["cook_uses"] = sum(i["uses"] * i["amount"] for i in edible if i["cookable"])
            days_size = crop["seconds"] / 86400 * crop["size"]
            crop["daily_satiety"] = crop["satiety"] / days_size
            crop["daily_uses"] = crop["cook_uses"] / days_size
        crops.append(crop)

    for stage in STAGES:
        for quality in QUALITIES:
            key = f"{stage}:{quality}"
            candidates = []
            for dish in dishes:
                if dish["level"] is not None and dish["level"] > stage:
                    continue
                output = dish["qualities"].get(quality, {})
                total = output.get("total")
                reason = dish["reason"]
                if not reason and (total is None or not output.get("servings") or total[0] <= 0):
                    reason = "该品质的有效饱食或分份数据不完整"
                rating = {"id": dish["id"], "reason": reason, "metrics": {}}
                if not reason:
                    rating["metrics"] = {"value": total[0] / dish["cost"], "speed": total[0] / (dish["seconds"] / 3600),
                                         "gain": (total[0] - dish["input_satiety"]) / dish["cost"],
                                         "effects": effects(total) / dish["cost"]}
                    rating["penalty"] = harm(total, total[0])
                    rating["cost100"] = 100 * dish["cost"] / total[0]
                candidates.append(rating)
                dish["ratings"][key] = rating
            rate_rows(candidates, "dishes")
            active = [d for d in dishes if d["ratings"].get(key, {}).get("score") is not None]

            def menu(item_ids: set[int]) -> dict[str, Any]:
                matches = sorted((d for d in active if any(i["id"] in item_ids for i in d["ingredients"])),
                                 key=lambda d: (-d["ratings"][key]["score"], d["id"]))
                return {"coverage": len(matches), "menu": matches[0]["ratings"][key]["score"] if matches else 0,
                        "recipes": [{"name": d["name"], "path": d["path"], "score": d["ratings"][key]["score"]}
                                    for d in matches[:3]]}

            ingredient_ratings = []
            for ingredient in ingredients:
                coverage = menu({ingredient["id"]})
                valid = (number(ingredient["price"], positive=True) is not None and ingredient["uses"]
                         and number(ingredient["life"], positive=True) is not None)
                rating = {**coverage, "reason": "" if valid and coverage["coverage"] else
                          "当前阶段无可计分的固定配方；通用配方用途可查图鉴" if valid else "购买价、使用次数或保质值不完整",
                          "metrics": {}}
                if not rating["reason"]:
                    rating["unit_cost"] = ingredient["price"] / ingredient["uses"]
                    rating["metrics"] = {"value": 1 / rating["unit_cost"], "storage": ingredient["life"],
                                         "coverage": coverage["coverage"], "menu": coverage["menu"]}
                ingredient.setdefault("ratings", {})[key] = rating
                ingredient_ratings.append(rating)
            rate_rows(ingredient_ratings, "ingredients")

            crop_ratings = []
            for crop in crops:
                coverage = menu({i["id"] for i in crop["harvest"]})
                rating = {**coverage, "reason": crop["reason"], "metrics": {}}
                if not rating["reason"]:
                    rating["metrics"] = {"value": crop["daily_satiety"], "uses": crop["daily_uses"], "coverage": coverage["coverage"]}
                crop["ratings"][key] = rating
                crop_ratings.append(rating)
            rate_rows(crop_ratings, "crops")
    return {"stages": STAGES, "qualities": QUALITIES, "models": MODELS,
            "stock": stock, "ingredients": ingredients, "dishes": dishes, "crops": crops,
            "resources": [item_info(item_id) for item_id, (_, item) in items.items()
                          if item.get("Category") == 1 and item.get("CanCook") is True]}


def fmt(value: Any) -> str:
    return f"{value:,.2f}".rstrip("0").rstrip(".") if isinstance(value, (int, float)) else "—"


def rating_for(row: dict[str, Any], view: str, stage: int, quality: str) -> dict[str, Any]:
    return row if view == "stock" else row["ratings"].get(f"{stage}:{quality}", {"score": None, "reason": "等级未解锁"})


def recommendation_card(row: dict[str, Any], view: str, stage: int, quality: str, rank: int, base: str) -> str:
    rating = rating_for(row, view, stage, quality)
    score = rating.get("score")
    output = row.get("qualities", {}).get(quality, {})
    count = output.get("servings") if view == "dishes" else row.get("uses")
    art_profile = {"serving_count": count} if view == "dishes" else {"use_times": count, "cookable": view == "ingredients"}
    art = item_art(row["name"], output.get("icon") or row.get("icon", ""), base,
                   art_profile if view != "crops" else None, is_dish=view == "dishes", fixed=bool(row.get("ingredients")), small=True)
    if view == "stock":
        facts = [("整包基价", row["price"]), ("整包饱食", row.get("total", [None])[0]),
                 ("每 100 饱食成本", row.get("cost100")), ("基础保质值", row["life"])]
    elif view == "ingredients":
        facts = [("整包基价", row["price"]), ("每次用量摊销价", rating.get("unit_cost")),
                 ("可用固定配方", rating.get("coverage")), ("基础保质值", row["life"])]
    elif view == "dishes":
        facts = [("每锅食材摊销价", row["cost"]), ("每锅总饱食", (output.get("total") or [None])[0]),
                 ("每次食用饱食", (output.get("per_use") or [None])[0]), ("烹饪小时", row["seconds"] / 3600 if row["seconds"] else None)]
    else:
        facts = [("基础成熟 / 小时", row["seconds"] / 3600 if row["seconds"] else None), ("每轮烹饪用量", row.get("cook_uses")),
                 ("每轮生食饱食", row.get("satiety")), ("配置尺寸", row["size"])]
    facts_html = '<dl class="rec-facts">' + "".join(f'<div><dt>{h(label)}</dt><dd>{h(fmt(value))}</dd></div>' for label, value in facts) + '</dl>'
    detail = ""
    if view == "dishes":
        detail += '<p>食材需求（每锅消耗用量）：' + "、".join(f'{h(i["name"])} ×{i["amount"]}' for i in row["ingredients"]) + '</p>'
        if row["groups"]:
            detail += '<p>分类条件：' + "、".join(f'{h(i["name"])} ×{i["amount"]}' for i in row["groups"]) + f'；档位 {h(row["tier"])}</p>'
        if row["cost"] is not None:
            detail += f'<p>从零整包购买：{fmt(row["basket"])}；食材原始饱食：{fmt(row["input_satiety"])}。每锅 1 件成品，可吃 {fmt(count)} 次。</p>'
        if output.get("total"):
            detail += '<p>整锅恢复：' + " · ".join(f'{label} {fmt(v)}' for label, v in zip(("饱食", "心态", "精力", "健康", "生命"), output["total"])) + '</p>'
    elif view == "crops":
        detail += '<p>普通收获：' + "、".join(f'{h(i["name"])} ×{i["amount"]}' for i in row["harvest"]) + '</p>'
        detail += f'<p>每尺寸单位 / 生长日：饱食 {fmt(row.get("daily_satiety"))}，烹饪用量 {fmt(row.get("daily_uses"))}。返种配置概率 {fmt(row["seed_rate"])}。</p>'
    else:
        detail += '<p>每次原始恢复：' + " · ".join(f'{label} {fmt(v)}' for label, v in zip(("饱食", "心态", "精力", "健康", "生命"), row["stats"])) + '</p>'
    if rating.get("recipes"):
        detail += '<p>可搭配：' + "、".join(f'<a href="{h(base + r["path"])}">{h(r["name"])}</a>' for r in rating["recipes"]) + '</p>'
    if score is not None:
        detail += '<ul class="rec-components">' + "".join(
            f'<li>{h(c["label"])}：相对分 {fmt(c["percentile"])} × {c["weight"]}%</li>' for c in rating["components"]) + '</ul>'
        detail += f'<p>负面恢复扣分：{fmt(rating.get("penalty", 0))}；综合指数：{fmt(score)} / 100。</p>'
    name = f'<a href="{h(base + row["path"])}">{h(row["name"])}</a>' if row["path"] else h(row["name"])
    badge = f'Lv.{row["level"]} · {h(quality)}品质' if view == "dishes" and row["level"] else '基础普通收获' if view == "crops" else h(row.get("group", ""))
    reason = rating.get("reason") or (' · '.join(r["name"] for r in rating.get("recipes", [])[:2]) or '按基价、饱食与补给效率比较')
    return (f'<article class="rec-card"><div class="rec-card-top"><span class="rec-rank">{rank:02d}</span>{art}'
            f'<div class="rec-name"><p>{badge}</p><h3>{name}</h3><span>{h(reason)}</span></div>'
            f'<div class="rec-score"><strong>{fmt(score)}</strong><span>{"推荐指数" if score is not None else "暂不计分"}</span></div></div>'
            + facts_html + f'<details><summary>食材、恢复与评分明细</summary>{detail}</details></article>')


def recommendation_document(payload: dict[str, Any], base: str) -> str:
    data = payload["recommendations"]
    body = '''<div class="rec-hero"><div><p class="eyebrow">SURVIVAL LOG / SUPPLY PLAN</p><h1>生存补给计划</h1><p>囤什么 · 做什么 · 种什么</p><p class="rec-subtitle">吃饱、补心态，也给每天留出时间。</p></div><a class="rec-stamp" href="#method">公开评分依据<br><strong>0—100</strong><span>相对推荐指数</span></a></div>
<form id="rec-controls" class="rec-controls" hidden>
<label>生存阶段<select id="rec-stage"><option value="1">前期 · 烹饪 Lv.1</option><option value="2">中期 · 烹饪 Lv.2</option><option value="3">后期 · 烹饪 Lv.3</option></select></label>
<label>成品品质<select id="rec-quality"><option value="普通">普通</option><option value="良好">优良</option><option value="完美">完美</option></select></label>
<label>本次侧重点<select id="rec-focus"><option value="auto">随阶段调整</option><option value="satiety">优先饱食</option><option value="morale">优先心态</option><option value="ease">少照料，留时间</option></select></label>
<label id="rec-life-label">基础保质值至少<select id="rec-life"><option value="0">不限制</option><option value="7" selected>7</option><option value="30">30</option><option value="90">90</option></select></label>
<label class="rec-search">找物品或食材<input id="rec-search" type="search" placeholder="例如：米、土豆、鸡蛋" autocomplete="off"></label>
<label>排序<select id="rec-sort"><option value="score">综合指数</option><option value="cost">每 100 饱食成本</option><option value="satiety">总饱食</option><option value="morale">心态 / 100 饱食</option><option value="time">照料时间优势</option><option value="trade">交易净基值</option></select></label>
<button type="reset">重置</button><label class="rec-stage-only" id="rec-stage-only-label" hidden><input id="rec-stage-only" type="checkbox">只看本阶段新增配方</label><label class="rec-stage-only" id="rec-fit-label" hidden><input id="rec-fit" type="checkbox">仅展示每日预算与容量内的菜肴</label><label class="rec-stage-only" id="rec-mood-label" hidden><input id="rec-mood" type="checkbox">仅展示达到每日补心态目标的菜肴</label></form>
<details class="rec-settings" id="rec-settings" hidden><summary>我的时间、种植与交易条件</summary>
<div class="rec-setting-grid">
<label>食材获取<select id="rec-source"><option value="mixed">种植与买入择优</option><option value="buy">全部买入</option><option value="grow">可种的自己种</option></select></label>
<label>计价基准<select id="rec-currency"><option value="trade">交易基值</option><option value="price">购买基价</option></select></label>
<label>每日饱食需求<input id="rec-satiety" type="number" min="1" max="1000" value="100"></label>
<label>希望每日补心态<input id="rec-morale" type="number" min="1" max="1000" value="20"></label>
<label>每日均摊预算<input id="rec-cash" type="number" min="1" max="10000" value="100"></label>
<label>每日照料预算 / 分钟<input id="rec-care" type="number" min="1" max="1440" value="60"></label>
<label>可用种植容量<input id="rec-capacity" type="number" min="1" max="1000" value="8"></label>
<label>备料等待容忍 / 日<input id="rec-horizon" type="number" min="1" max="100" value="7"></label>
<label>种植容器<select id="rec-planter"></select></label>
<label>种植等级<select id="rec-plantLevel"><option value="1">Lv.1</option><option value="2">Lv.2</option><option value="3">Lv.3</option><option value="4">Lv.4</option><option value="5">Lv.5</option></select></label>
<label>额外生长速度 / %<input id="rec-growth" type="number" min="0" max="500" value="0"></label>
<label>动作耗时倍率 / %<input id="rec-action" type="number" min="10" max="500" value="100"></label>
<label>收获情景<select id="rec-harvest"><option value="normal">普通收获</option><option value="perfect">完美收获（情景）</option></select></label>
<label>烹饪等待计作占用 / %<input id="rec-cookActive" type="number" min="0" max="100" value="0"></label>
<label>心态排名口径<select id="rec-moraleMode"><option value="supply">长期补给价值</option><option value="settlement">当天结算条件</option></select></label>
<label>不吃这组菜的结算前心态<input id="rec-moraleNow" type="number" min="0" max="1000" value="50"></label>
<label>当前角色心态上限（按游戏填写）<input id="rec-moraleMax" type="number" min="1" max="1000" value="100"></label>
<label>兑换 1 点所需心态<input id="rec-pointStep" type="number" min="1" max="100" value="5"></label>
<label>交出估值情景<select id="rec-sellChannel"><option value="normal">原始基值</option><option value="discount">应用商人配置折价</option></select></label>
<label class="rec-stage-only"><input id="rec-powered" type="checkbox" checked>种植设施通电</label>
</div><p>照料为及时处理异常的平均估计，未计走动、缺水、异常停长和跨楼层。先在种植手册核对光照、耐寒；这里比较满足环境后的产出。参数保留在网址中，可复制分享。</p></details>
<section class="rec-brief" id="rec-brief" hidden aria-live="polite"></section>
<nav class="rec-tabs" aria-label="推荐分类">'''
    body += "".join(f'<a href="#{view}" data-view="{view}"><span>0{index}</span>{label}</a>'
                    for index, (view, label) in enumerate(VIEW_LABELS.items(), 1)) + '</nav>'
    body += '<p class="rec-context" id="rec-context">默认：前期 Lv.1、普通品质。中后期包含此前等级配方；指数只在同类候选中比较。</p><p id="rec-status" role="status"></p>'
    for view, label in VIEW_LABELS.items():
        rows = [r for r in data.get(view, []) if rating_for(r, view, 1, "普通").get("score") is not None]
        rows.sort(key=lambda r: (-rating_for(r, view, 1, "普通")["score"], r["id"]))
        cards = "".join(recommendation_card(row, view, 1, "普通", rank, base) for rank, row in enumerate(rows, 1))
        body += f'<section class="rec-section" id="{view}"><div class="rec-section-title"><p class="eyebrow">SUPPLY / {view.upper()}</p><h2>{label}</h2><p>{VIEW_INTROS[view]}</p></div><div class="rec-list">{cards or "<p>当前条件没有可计分候选。</p>"}</div></section>'
    body += '''<noscript><p>无脚本简表仅比较前期固定配方的购买价与饱食。启用 JavaScript 可计算通用配方、心态、种植照料与交易排名。</p></noscript>
<section id="method" class="rec-method"><p class="eyebrow">HOW WE COMPARE</p><h2>指数怎么算</h2>
<div id="rec-model-summary"><p>完整组合排名启用后，前期以饱食为主，中期兼顾心态，后期以心态与照料效率为主。</p></div>
<details><summary>烹饪、照料与交易的计算口径</summary><ul>
<li>指定配方优先；通用配方按实际食材、最高档位和所选品质计算。通用菜心态、精力取品质成品配置；饱食、健康、生命来自实际食材。每锅和每次食用分别展示，不将分份次数再乘到整锅恢复。</li>
<li>在全部公开可烹饪食材中枚举组合，每道菜独立推荐。配置存在不等于商店有售、已经解锁或库存充足；实际库存可到图鉴的“按冰箱食材配餐”确认。</li>
<li>收益按每日饱食、心态目标归一化；负担按每日预算、照料分钟、可用种植容量和等待容忍归一化。收益 ÷（1 + 加权负担）得到效率，再转成同类候选的并列百分位，负面恢复最多扣 30 分。长期补给按基础心态收益比较，当天结算按当前上限扣除溢出；搜索与排序不改变评分池。</li>
<li>每次食材购买价 = 整包 price ÷ UseTimes；每次交易换入基值 = TradeValue。两种单位不混用。种植计新种子的成本，不把返种当免费；未计肥料、电力、燃料、获取路程和设备购置。</li>
<li>按所选容器种满计算：种子数 = floor(容量 ÷ 作物尺寸)。生长时间按设施、等级和额外速度的乘积缩短。普通与完美收获独立选择，不推断完美概率或无限再生。特殊温室的每日施肥、再生作物不参与基础排名。</li>
<li>基础播种 15 分钟、收获 5 分钟；除虫、除草、浇水各 5 分钟。生长期每个容器每日检查一次，概率 = max(0, 植物基础值 + 设施修正) × max(0, 1 − 等级减免)，三项合计大于 1 时一起归一化。这里只估计及时处理的次数，随机波动、处理延迟和雨水自动浇灌会改变实际耗时。</li>
<li>短周期增加每日播种和收获次数；不只按产量排名。每日方案按整数食用次数满足饱食需求，显示心态缺口、饱食超出、均摊锅数和预算。种植容器按整数向上取整，共享同种作物的收获不重复占地；每天照料和种子成本按这些整容器计，多余收获不抵扣成本。容量是容器内部的种植空间，设备实际地面占格仍需在游戏中安排。</li>
<li>基础心态结算 = max(0, floor((结算前心态 − 50) ÷ 5))，兑换后会扣去对应心态。输入“不吃这组菜”的结算前心态与角色上限，比较食用前后差值；已计上限，未计其他当天事件。天赋改变兑换步长时可手填。</li>
<li>每锅交出估值 = 品质成品 TradeValue × 实际分份次数。商人折价情景只使用正且小于 1 的 TradeSellRate；原始基值不折价。净基值 = 成品交出估值 − 原料换入基值，不等于现金利润或保证成交；需求、鉴价、好感、折扣、货架和交易渠道限制另行影响实际成交。</li>
</ul></details><p><a href="../?lang=zh-CN#dish/">按冰箱里的实际食材配餐 →</a> · <a href="../?lang=zh-CN#plant/">核对当前种植环境 →</a></p>
</section>'''
    document = shell("生存日志补给推荐｜囤货、前中后期菜肴与作物排行 · Survival Log",
                     "按真实烹饪组合、品质、每日心态与生存点、成熟时间、照料和种植空间，比较前中后期备料、菜肴与交易取舍。",
                     "recommendations/", base, body,
                     [("幸存者图鉴", base), ("生存补给计划", base + "recommendations/")],
                     payload["metadata"].get("game_version", "未提供"), collection=True)
    embedded = json.dumps(data, ensure_ascii=False, separators=(",", ":"), allow_nan=False).replace("<", "\\u003c").replace("&", "\\u0026")
    return document.replace('</head>', '<link rel="stylesheet" href="../recommendations.css">\n</head>').replace(
        '</body>', f'<script id="rec-data" type="application/json">{embedded}</script><script src="../cooking.js" defer></script><script src="../supply.js" defer></script><script src="../recommendations.js" defer></script>\n</body>')
