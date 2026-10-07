#!/usr/bin/env python3
"""Export verified trade rules and the public items needed by the trade planner."""

from __future__ import annotations

import argparse
import json
import math
from pathlib import Path
from typing import Any

from codex_parser import load_config_table, parse_config_table
from codex_recipe import read_global_settings


ITEM_ICON_FIELDS = ("Icon", "ICON", "WebIcon", "WebSmallIcon")
CATEGORY_TEXT_PREFIX = "SR_Web_TradeUI_Cat_"


def decode_mappoint_trade_rows(raw: bytes) -> list[dict[str, Any]]:
    return [point_entry(row.values) for row in parse_config_table(raw, "Config_MapPoint")
            if row.values["PointCategory"] == 3]


def point_entry(raw: dict[str, Any]) -> dict[str, Any]:
    return {"id": raw["ID"], "name": raw["Name_Local"] or raw["Name"] or f"ID:{raw['ID']}",
            "chapter": raw["ChapterID"], "shop_id": raw["ShelfShopId"],
            "half_value_cat": raw["TradeCategory"], "unlock_key": raw["UnlockHint"],
            "hint": raw["UnlockHint_Local"] or ""}


def decode_shop_rows(raw: bytes) -> tuple[list[dict[str, Any]], list[int]]:
    rows = [row.values for row in parse_config_table(raw, "Config_Shop")]
    return rows, []


def extract_trade_model(game_root: Path) -> dict[str, Any]:
    version = None

    def table(name: str) -> list[dict[str, Any]]:
        nonlocal version
        rows, _, current, _ = load_config_table(game_root, name)
        if version is not None and version != current:
            raise ValueError(f"{name} 与交易模型版本不一致")
        version = current
        return [row.values for row in rows]

    item_map = {row["ID"]: row for row in table("Config_Item")}
    text_rows = table("Config_ConstantText")
    categories = {row["ID"][len("ItemType"):]: row["Text_Local"] or row["Text"]
                  for row in text_rows if row["ID"].startswith("ItemType")
                  and row["ID"][len("ItemType"):].isdigit()}
    categories.update({str(row["ID"])[len(CATEGORY_TEXT_PREFIX):]: row["Text_Local"] or row["Text"]
                  for row in text_rows
                  if str(row["ID"]).startswith(CATEGORY_TEXT_PREFIX)
                  and str(row["ID"])[len(CATEGORY_TEXT_PREFIX):].isdigit()})
    categories.setdefault("3", "书籍")
    categories.setdefault("14", "家具包裹")
    categories.setdefault("17", "机器人模块")
    categories.setdefault("21", "装修材料")
    points = [point_entry(row) for row in table("Config_MapPoint") if row["PointCategory"] == 3]
    shops = {row["ID"]: row for row in table("Config_Shop")}
    recipes = [row for row in table("Config_ProductionList") if row["InCodex"] and row["IsUseable"]]
    cooking = table("Config_CookingRecipe")
    wanted = {i for row in recipes for field in ("MaterialList", "ProductID") for i in row[field] or []}
    wanted |= {row[field] for row in cooking for field in ("PerfectItemID", "GoodItemID", "NormalItemID", "FailItemID")
               if row[field] > 0}
    wanted |= {i for row in cooking for i in row["SpecificItems"] or []}
    wanted |= {i for i, row in item_map.items() if row["InCodex"] or row["CanCook"]
               or row["Category"] in (2, 3, 9, 10, 11)}
    wanted |= {i for point in points for i in shops[point["shop_id"]]["ItemIdList"] or []}

    def item_entry(item_id: int, count: int | None = None) -> dict[str, Any]:
        if item_id not in item_map:
            raise ValueError(f"交易模型引用未知物品 ID:{item_id}")
        raw = item_map[item_id]
        cat = raw["Category"]
        codex = "prey" if raw["InCodex"] and raw["Prey_Rarity"] > 0 else \
            "food" if raw["InCodex"] and cat == 1 else "books" if cat == 3 else None
        return {"id": item_id, "name": raw["ItemName_Local"] or raw["ItemName"] or f"ID:{item_id}",
                "cat": cat, "icon": next((raw[k] for k in ITEM_ICON_FIELDS if raw.get(k)), ""),
                "count": count, "trade_value": raw["TradeValue"], "price": raw["price"],
                "use_times": raw["UseTimes"], "sell_rate": raw["TradeSellRate"],
                "cookable": cat == 1 and raw["CanCook"], "codex": codex}

    owners: dict[int, list[int]] = {}
    for point in points:
        shop = shops.get(point["shop_id"])
        if shop is None or shop["RandomID"] or shop["RandomAmount"]:
            raise ValueError(f"据点 {point['id']} 引用的固定货架缺失或变为随机货架")
        ids, counts = shop["ItemIdList"] or [], shop["ItemCountList"] or []
        if len(ids) != len(counts):
            raise ValueError(f"货架 {shop['ID']} 物品与数量列表长度不一致")
        point["items"] = [item_entry(i, count) for i, count in zip(ids, counts)]
        point["offer_cats"] = sorted({item_map[i]["Category"] for i in ids})
        for i in ids:
            owners.setdefault(i, []).append(point["id"])

    # Crafting candidates use ordinary outputs, without assuming a perfect return or a success probability.
    crafts = []
    for row in recipes:
        inputs, outputs = row["MaterialList"] or [], row["ProductID"] or []
        if not inputs or not outputs or any(item_map[i]["UseTimes"] > 1 for i in inputs):
            continue
        if any(item_map[i]["TradeValue"] <= 0 for i in inputs + outputs):
            continue
        crafts.append({"id": row["ID"], "name": row["ShopName_Local"] or row["ShopName"],
                       "level": row["craft_level"], "inputs": inputs, "outputs": outputs,
                       "can_fail": bool(row["FailedID"]), "perfect_returns": bool(row["perfect_item_id"])})

    settings = read_global_settings(game_root)

    def setting(key: str, fallback: float | None = None) -> float:
        if key not in settings and fallback is None:
            raise ValueError(f"交易参数缺失：{key}")
        result = settings[key][1] if key in settings else fallback
        if not isinstance(result, (int, float)) or not math.isfinite(result):
            raise ValueError(f"交易参数非法：{key}")
        return result

    own_rate = setting("StrangerTradeSelfStockValueRate", .5)
    rules = {"self_stock_rate": min(1, own_rate) if own_rate > 0 else .5,
             "demand_boosts": [setting(f"StrangerTradeBoostLv{i}") for i in (1, 2, 3)],
             "demand_boost_max": setting("StrangerTradeDemandBoostMax"),
             "deal_discount": setting("StrangerTradeDealLineDiscount"),
             "deal_discount_max": setting("StrangerTradeDealLineMaxDiscount"),
             "camp_medicine_rate": setting("Endless_TradeTakeMedicineRate")}
    return {"format_version": 2, "game_version": version, "categories": categories, "rules": rules,
            "points": points, "shared": [{**item_entry(i), "points": ps} for i, ps in owners.items() if len(ps) > 1],
            "items": [item_entry(i) for i in sorted(wanted) if item_map[i]["TradeValue"] > 0],
            "crafts": crafts}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--game-root", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    try:
        root, target = args.game_root.expanduser().resolve(), args.output.expanduser().resolve()
        if target.is_relative_to(root) or args.output.is_symlink():
            raise ValueError("交易数据输出不能位于游戏目录或写入符号链接")
        data = extract_trade_model(root)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(json.dumps(data, ensure_ascii=False, separators=(",", ":")) + "\n", encoding="utf-8")
        print(f"交易模型已导出：{data['game_version']}（{len(data['points'])} 据点）")
        return 0
    except (ValueError, KeyError, OSError, RuntimeError) as exc:
        print(f"交易数据导出失败：{exc}")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
