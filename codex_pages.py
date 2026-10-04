#!/usr/bin/env python3
"""Build a standalone codex from the repository's public static database."""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import shutil
import sqlite3
import struct
import sys
from pathlib import Path
from typing import Any

from codex_database import CATEGORY_LABELS, CATEGORY_ORDER, DATABASE_SCHEMA_VERSION
from codex_parser import FIELD_LABELS, format_scalar
from codex_pages_planting import add_planting_data
from codex_pages_recommendations import build_recommendations, recommendation_document
from codex_pages_seo import DEFAULT_SITE_URL, home_seo, normalize_site_url, seo_documents, validate_output_targets
from codex_server import _achievement_payload, _build_detail_fields


PROJECT_DIR = Path(__file__).resolve().parent
SOURCE_DIR = PROJECT_DIR / "pages"
DEFAULT_GAME_ROOT = Path(r"G:\SteamLibrary\steamapps\common\Survival Log")
PUBLIC_METADATA = ("game_version", "database_schema_version")
ASSETS = ("index.html", "styles.css", "guide.css", "game-theme.css", "app.js", "favicon.svg",
          "recommendations.css", "recommendations.js", "supply.js", "supply-worker.js", "i18n.js", "planting.js", "cooking.js", "locales/en.json", "locales/game-en.json")
STAT_LABELS = ("饱腹", "心态", "精力", "健康", "生命")
PRODUCT_FIELDS = (("PerfectItemID", "完美"), ("GoodItemID", "良好"), ("NormalItemID", "普通"), ("FailItemID", "失败"))
ICON_ITEM_FIELDS = {"Config_CookingRecipe": tuple(field for field, _ in PRODUCT_FIELDS),
                    "Config_Plant": ("Gain", "Perfect_Gain"), "Config_ProductionList": ("ProductID",)}


def icon_asset(raw: dict[str, Any]) -> str:
    return next((raw[field] for field in ("Icon", "ICON", "WebIcon", "WebSmallIcon") if raw.get(field)), "")


def related_icon_items(table: str, raw: dict[str, Any]) -> list[int]:
    ids = []
    for field in ICON_ITEM_FIELDS.get(table, ()):
        value = raw.get(field) or []
        ids.extend([value] if isinstance(value, int) else value)
    return list(dict.fromkeys(item_id for item_id in ids if type(item_id) is int and item_id > 0))


def icon_filename(asset_path: str) -> str:
    path = asset_path.replace("\\", "/").removesuffix(".png").lower()
    return hashlib.sha256(path.encode("utf-8")).hexdigest()[:20] + ".png"


def public_icon(asset_path: str) -> str:
    if not asset_path:
        return ""
    filename = icon_filename(asset_path)
    source = SOURCE_DIR / "icons" / filename
    return f"./icons/{filename}" if source.is_file() and not source.is_symlink() else ""


def ingredient_tier(raw: dict[str, Any], rules: dict[int, dict[str, Any]]) -> int | None:
    rule = rules.get(raw.get("SubCategory"))
    price = raw.get("price")
    if not rule or not isinstance(price, (int, float)) or not math.isfinite(price):
        return None
    return 1 if price >= rule["high_threshold"] else 2 if price >= rule["mid_low_threshold"] else 3


def food_profile(raw: dict[str, Any], tags: dict[str, dict[int, str]], groups: dict[int, str],
                 rules: dict[int, dict[str, Any]] | None = None) -> dict[str, Any]:
    return {
        "stats": [{"field": f"ValueDisplay{index}", "label": label, "value": raw.get(f"ValueDisplay{index}")}
                  for index, label in enumerate(STAT_LABELS, 1)],
        "tags": [{"id": raw[field], "field": field, "key": f"{field}:{raw[field]}",
                  "name": tags.get(field, {}).get(raw[field], f"ID:{raw[field]}"), "count": 1}
                 for field in ("FoodTag1", "FoodTag2") if raw.get(field)],
        "sub_category_id": raw.get("SubCategory", 0),
        "sub_category": groups.get(raw.get("SubCategory", 0), f"ID:{raw['SubCategory']}" if raw.get("SubCategory") else "未分类"),
        "cookable": raw.get("CanCook", False),
        "use_times": raw.get("UseTimes"),
        "can_use": not raw["CantUse"] if "CantUse" in raw else None,
        "weight_grams": raw.get("weight"),
        "size": raw.get("Size"),
        "shelf_life_days": raw.get("Life"),
        "tier": ingredient_tier(raw, rules or {}) if raw.get("CanCook") else None,
        "note": raw.get("ItemDes2_Local") or raw.get("ItemDes2") or "",
        "icon": public_icon(icon_asset(raw)),
    }


def dish_servings(product: dict[str, Any], threshold: int | None, fixed: bool) -> tuple[int | None, list[dict[str, Any]] | None]:
    stats = product["stats"]
    if not fixed or not isinstance(threshold, int) or threshold <= 0:
        return None, None
    total = stats[0]["value"]
    if not isinstance(total, (int, float)) or not math.isfinite(total):
        return None, None
    # Native CalcProductVD ceilings each value; CalcSplit divides float32 values.
    rounded = math.ceil(total)
    quotient = struct.unpack("<f", struct.pack("<f", rounded / threshold))[0]
    count = max(1, math.ceil(quotient))
    per_use = [{**stat, "value": struct.unpack("<f", struct.pack("<f", math.ceil(stat["value"]) / count))[0]
                if isinstance(stat["value"], (int, float)) and math.isfinite(stat["value"]) else None}
               for stat in stats]
    return count, per_use


def config_fields(raw: dict[str, Any]) -> list[dict[str, str]]:
    return [
        {"field": key, "label": FIELD_LABELS.get(key, key), "value": format_scalar(value)}
        for key, value in raw.items()
    ]


def export_data(database_path: Path) -> dict[str, Any]:
    database_path = database_path.expanduser().resolve()
    if not database_path.is_file():
        raise FileNotFoundError(f"找不到静态图鉴数据库：{database_path}")
    connection = sqlite3.connect(f"{database_path.as_uri()}?mode=ro", uri=True)
    connection.row_factory = sqlite3.Row
    try:
        metadata = {
            row["key"]: row["value"]
            for row in connection.execute(
                "SELECT key, value FROM metadata WHERE key IN (?, ?)", PUBLIC_METADATA
            )
        }
        if metadata.get("database_schema_version") != str(DATABASE_SCHEMA_VERSION):
            raise ValueError("静态库 schema 不匹配，请使用当前项目的静态图鉴数据库")
        categories = [
            {"id": category, "label": CATEGORY_LABELS[category], "entries": []}
            for category in CATEGORY_ORDER
        ]
        category_map = {category["id"]: category for category in categories}
        tags = {field: {row["row_id"]: row["name"] for row in connection.execute(
            "SELECT row_id, name FROM auxiliary_rows WHERE table_name=?", (field,))}
            for field in ("FoodTag1", "FoodTag2")}
        groups = {row["row_id"]: row["name"] for row in connection.execute(
            "SELECT row_id, name FROM auxiliary_rows WHERE table_name='Config_ItemSubCategory'")}
        items = {row["item_id"]: (row["name"], json.loads(row["raw_json"]))
                 for row in connection.execute("SELECT item_id, name, raw_json FROM recipe_items")}
        rules = {row["sub_category"]: dict(row) for row in connection.execute(
            "SELECT sub_category, high_threshold, mid_low_threshold FROM recipe_tier_rules")}
        ingredients = [{"id": item_id, "name": name, "sub_category_id": raw.get("SubCategory", 0),
                        "sub_category": groups.get(raw.get("SubCategory"), f"ID:{raw.get('SubCategory', 0)}"),
                        "tier": ingredient_tier(raw, rules), "icon": public_icon(icon_asset(raw)),
                        "stats": [raw.get(f"ValueDisplay{index}") for index in range(1, 6)],
                        "use_times": raw.get("UseTimes"), "price": raw.get("price"),
                        "tier_thresholds": {"high": rules[raw["SubCategory"]]["high_threshold"],
                                            "mid": rules[raw["SubCategory"]]["mid_low_threshold"]}
                        if raw.get("SubCategory") in rules else None}
                       for item_id, (name, raw) in items.items() if raw.get("Category") == 1 and raw.get("CanCook") is True]
        memberships: dict[str, list[str]] = {}
        for row in connection.execute(
            """
            SELECT ec.entry_key, ec.category
            FROM codex_entry_categories ec
            JOIN codex_entries e ON e.entry_key = ec.entry_key
            WHERE e.is_current = 1
            ORDER BY ec.sort_order, e.source_id
            """
        ):
            if row["category"] not in category_map:
                raise ValueError(f"静态库包含未知分类：{row['category']}")
            memberships.setdefault(row["entry_key"], []).append(row["category"])
        relations: dict[str, list[dict[str, Any]]] = {}
        # Select public columns explicitly, never attach a player's runtime database.
        for row in connection.execute(
            """
            SELECT r.source_entry_key, r.relation_type, r.target_table, r.target_id,
                   r.target_name, r.ordinal
            FROM entry_relations r
            JOIN codex_entries e ON e.entry_key = r.source_entry_key
            WHERE e.is_current = 1
            ORDER BY r.source_entry_key, r.relation_type, r.ordinal
            """
        ):
            relation = dict(row)
            key = relation.pop("source_entry_key")
            target = f"{relation['target_table']}:{relation['target_id']}"
            if target in memberships:
                relation["link"] = {"category": memberships[target][0], "key": target}
            relations.setdefault(key, []).append(relation)
        raw_entries = {}
        for row in connection.execute(
            """
            SELECT entry_key, source_table, source_id, name, name_key, description, raw_json
            FROM codex_entries WHERE is_current = 1 ORDER BY source_id, entry_key
            """
        ):
            raw = json.loads(row["raw_json"])
            raw_entries[row["entry_key"]] = raw
            related = relations.get(row["entry_key"], [])
            for category in memberships.get(row["entry_key"], []):
                highlights, fields, _prefixes = _build_detail_fields(category, raw, related)
                entry = {
                    "key": row["entry_key"],
                    "id": row["source_id"],
                    "source_table": row["source_table"],
                    "name": row["name"] or row["name_key"] or f"ID:{row['source_id']}",
                    "name_key": row["name_key"],
                    "description": row["description"],
                    "highlights": highlights,
                    "fields": fields,
                    "relations": related,
                    "icon": public_icon(icon_asset(raw)),
                }
                if category in {"food", "prey"}:
                    entry["food"] = food_profile(raw, tags, groups, rules)
                elif category == "dish":
                    entry["recipe"] = {"specific_items": raw.get("SpecificItems", []),
                                       "tag_combo": raw.get("TagCombo", []), "tier": raw.get("Tier"),
                                       "min_level": raw.get("MinLevel"), "show_level": raw.get("ShowLevel"),
                                       "cook_time": raw.get("CookTime")}
                    fixed = (bool(raw.get("SpecificItems")) or
                             ("TagCombo" in raw and not raw["TagCombo"]) or
                             any(r["relation_type"] == "具体食材" for r in related))
                    threshold = raw.get("SatietyStandard")
                    entry["portion_model"] = {"mode": "fixed" if fixed else "ingredients", "threshold": threshold}
                    entry["products"] = []
                    for field, quality in PRODUCT_FIELDS:
                        item_id = raw.get(field, 0)
                        if not item_id:
                            continue
                        name, product = items.get(item_id, (f"ID:{item_id}", {}))
                        result = {"id": item_id, "quality": quality, "name": name, **food_profile(product, tags, groups)}
                        result["serving_count"], result["per_use_stats"] = dish_servings(result, threshold, fixed)
                        entry["products"].append(result)
                    entry["icon"] = next((product["icon"] for product in entry["products"] if product["icon"]), "")
                elif category == "craft":
                    for item_id in related_icon_items(row["source_table"], raw):
                        name, product = items.get(item_id, (f"ID:{item_id}", {}))
                        picture = public_icon(icon_asset(product))
                        if picture:
                            entry["icon"] = picture
                            entry["icon_source"] = {"id": item_id, "name": name, "kind": "product"}
                            break
                category_map[category]["entries"].append(entry)
        achievements = []
        for row in connection.execute("SELECT * FROM achievements ORDER BY sort_order, achievement_id"):
            public = _achievement_payload(dict(row))
            raw = json.loads(row["raw_json"])
            achievements.append(
                {
                    "key": f"Config_Achievement:{row['achievement_id']}",
                    "id": row["achievement_id"],
                    "source_table": "Config_Achievement",
                    "name": public["name"] or public["name_key"] or f"ID:{row['achievement_id']}",
                    "name_key": public["name_key"],
                    "description": public["description"],
                    "group": public["category"],
                    "hidden": public["is_hidden"],
                    "highlights": [
                        {"field": "condition", "label": "完成条件", "value": public["condition"]},
                        {"field": "method", "label": "完成方法", "value": public["method"]},
                        {"field": "role", "label": "角色限制", "value": public["role_restriction"] or "无"},
                    ],
                    "notes": public["notes"] + public["common_notes"],
                    "exclusions": public["exclusions"],
                    "references": public["config_references"],
                    "source_version": public["source_version"],
                    "fields": config_fields(raw),
                    "relations": [],
                    "icon": public_icon(icon_asset(raw)),
                }
            )
        categories.append({"id": "achievements", "label": "成就", "entries": achievements})
        planter_configs = {row["row_id"]: json.loads(row["raw_json"]) for row in connection.execute(
            "SELECT row_id, raw_json FROM auxiliary_rows WHERE table_name='Config_FurniturePlant'")}
        planters = add_planting_data(categories, raw_entries, items, planter_configs, public_icon)
        environment = json.loads((SOURCE_DIR / "planting-environment.json").read_text(encoding="utf-8"))
        if environment["format_version"] != 1 or environment["game_version"] != metadata.get("game_version"):
            environment = None
        cooking_model = json.loads((SOURCE_DIR / "cooking-model.json").read_text(encoding="utf-8"))
        if cooking_model["format_version"] != 1 or cooking_model["game_version"] != metadata.get("game_version"):
            cooking_model = None
        recommendations = build_recommendations(categories, raw_entries, items, lambda raw: food_profile(raw, tags, groups))
        supply_model = json.loads((SOURCE_DIR / "supply-model.json").read_text(encoding="utf-8"))
        if supply_model["format_version"] != 1 or supply_model["game_version"] != metadata.get("game_version"):
            supply_model = None
        plant_levels = [json.loads(row["raw_json"]) for row in connection.execute(
            "SELECT raw_json FROM auxiliary_rows WHERE table_name='Config_PlantLv' ORDER BY row_id")]
        recommendations["cooking"] = {"ingredients": ingredients, "model": cooking_model,
            "entries": [{field: entry[field] for field in ("id", "key", "recipe", "portion_model", "products")}
                        for category in categories if category["id"] == "dish" for entry in category["entries"]]}
        recommendations["supply_model"] = supply_model
        recommendations["planters"] = [{**planter, **{public: planter_configs[planter["config_id"]].get(raw)
            for public, raw in (("growth_bonus", "GrowthFaster"), ("pest_control", "PestControl"),
                               ("weed_control", "WeedControl"), ("water_control", "DryControl"))}} for planter in planters]
        recommendations["plant_levels"] = [{"level": raw.get("Lv"), "growth_bonus": raw.get("growth_speed_bonus"),
            "anomaly_reduction": raw.get("pest_rate_reduction")} for raw in plant_levels]
        return {"format_version": 1, "metadata": metadata, "categories": categories,
                "cooking_ingredients": ingredients, "cooking_model": cooking_model, "planters": planters, "planting_environment": environment,
                "recommendations": recommendations}
    finally:
        connection.close()


def build_pages(database_path: Path, output_dir: Path, site_url: str = DEFAULT_SITE_URL) -> Path:
    site_url = normalize_site_url(site_url)
    output_dir = output_dir.expanduser().resolve()
    database_path = database_path.expanduser().resolve()
    for protected in (DEFAULT_GAME_ROOT.resolve(), SOURCE_DIR.resolve(), database_path):
        if output_dir == protected or output_dir.is_relative_to(protected):
            raise ValueError("输出目录不能位于游戏目录、网页源码目录或数据库文件路径中")
    if database_path.is_relative_to(output_dir) or SOURCE_DIR.is_relative_to(output_dir):
        raise ValueError("输出目录不能包含源数据库或网页源码目录")
    payload = export_data(database_path)
    documents = seo_documents(payload, site_url, {
        "recommendations/index.html": recommendation_document(payload, site_url)})
    validate_output_targets(output_dir, [*ASSETS, "data.json", ".nojekyll", *documents])
    output_dir.mkdir(parents=True, exist_ok=True)
    for name in (*ASSETS, "data.json", ".nojekyll"):
        if (output_dir / name).is_symlink():
            raise ValueError(f"输出文件不能是符号链接：{name}")
    for name in ASSETS:
        (output_dir / name).parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(SOURCE_DIR / name, output_dir / name)
    (output_dir / "index.html").write_text(
        home_seo(payload, (SOURCE_DIR / "index.html").read_text(encoding="utf-8"), site_url), encoding="utf-8")
    for name, content in documents.items():
        target = output_dir / name
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(content, encoding="utf-8")
    icons = {entry.get("icon", "") for category in payload["categories"] for entry in category["entries"]}
    icons.update(product["icon"] for category in payload["categories"] for entry in category["entries"]
                 for product in entry.get("products", []))
    icons.update(item["icon"] for item in payload["cooking_ingredients"])
    if icons - {""}:
        icon_dir = output_dir / "icons"
        if icon_dir.is_symlink() or (icon_dir.exists() and not icon_dir.is_dir()):
            raise ValueError("图标输出目录不能是符号链接或普通文件")
        icon_dir.mkdir(exist_ok=True)
        for icon in sorted(icons - {""}):
            filename = Path(icon).name
            target = icon_dir / filename
            if target.is_symlink():
                raise ValueError(f"图标输出文件不能是符号链接：{filename}")
            shutil.copyfile(SOURCE_DIR / "icons" / filename, target)
    (output_dir / "data.json").write_text(
        json.dumps({key: value for key, value in payload.items() if key != "recommendations"},
                   ensure_ascii=False, separators=(",", ":"), allow_nan=False),
        encoding="utf-8",
    )
    (output_dir / ".nojekyll").write_text("", encoding="ascii")
    return output_dir


def main() -> int:
    parser = argparse.ArgumentParser(description="从已公开的静态图鉴数据库构建 GitHub Pages 网页")
    parser.add_argument("--database", type=Path, default=PROJECT_DIR / "survival_log_codex.sqlite3")
    parser.add_argument("--output-dir", type=Path, default=PROJECT_DIR / "build" / "pages")
    parser.add_argument("--site-url", default=DEFAULT_SITE_URL, help="公开站点的完整根网址，用于 canonical、分享信息和站点地图")
    args = parser.parse_args()
    try:
        output = build_pages(args.database, args.output_dir, args.site_url)
    except (OSError, sqlite3.Error, ValueError, KeyError) as exc:
        print(f"静态网页构建失败：{exc}", file=sys.stderr)
        return 1
    print(f"静态网页已生成：{output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
