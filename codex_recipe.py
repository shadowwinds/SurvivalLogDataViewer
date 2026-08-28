"""Match cookable recipes against the read-only player save inventories."""

from __future__ import annotations

import json
import math
import re
import sqlite3
from collections import Counter, defaultdict
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Collection, Iterable, Mapping

from codex_parser import ConfigRow, Reader, config_row_name, load_text_asset
from codex_save import (
    InventoryItem,
    SaveHistoryRecord,
    SaveParseError,
    SaveInventoryState,
    STORAGE_FURNITURE_FUNC_ID,
    STORAGE_LOCATION_LABELS,
    StorageContainer,
    read_game_save_inventory,
    read_history_save,
)


SUPPORTED_TIER_SUBCATEGORIES = {
    2: "Meat",
    3: "Custard",
    4: "Fish",
    5: "Vegetable",
    6: "Fruit",
    8: "Seasoning",
    11: "Mushroom",
}
TIER_LABELS = {1: "High", 2: "Mid", 3: "Low"}
TIER_LABELS_ZH = {1: "高档", 2: "中档", 3: "低档"}
TIER_RULE_KEYS = {
    2: ("CookingTier_Price_Meat_High", "CookingTier_Price_Meat_Mid_Low"),
    3: ("CookingTier_Price_Custard_High", "CookingTier_Price_Custard_Mid_Low"),
    4: ("CookingTier_Price_Fish_High", "CookingTier_Price_Fish_Mid_Low"),
    5: ("CookingTier_Price_Veg_High", "CookingTier_Price_Veg_Mid_Low"),
    6: ("CookingTier_Price_Fruit_High", "CookingTier_Price_Fruit_Mid_Low"),
    8: ("CookingTier_Price_Seasoning_High", "CookingTier_Price_Seasoning_Mid_Low"),
    11: ("CookingTier_Price_Mushroom_High", "CookingTier_Price_Mushroom_Mid_Low"),
}
SAVE_FILENAME_RE = re.compile(r"Save_[A-Za-z0-9_-]+\.bytes\Z")


class RecipeConfigError(ValueError):
    """Raised when a recipe or tier configuration cannot be interpreted safely."""


LEGACY_STORAGE_FURNITURE = {15000: "双开门冰箱", 15001: "冰柜"}
RECIPE_PLAN_CACHE_VERSION = 6


@dataclass(frozen=True)
class RecipeItemSpec:
    item_id: int
    name: str
    can_cook: bool
    category: int
    sub_category: int
    sub_category_name: str
    price: float
    raw_json: str
    in_codex: bool = False


@dataclass(frozen=True)
class RecipeSpec:
    recipe_id: int
    name: str
    name_key: str
    tag_combo: tuple[int, ...]
    specific_items: tuple[int, ...]
    tier: int
    raw_json: str


@dataclass(frozen=True)
class _RecipeOutcome:
    kind: str
    tier: int | None
    generic_recipe: RecipeSpec | None = None


@dataclass(frozen=True)
class TierRule:
    sub_category: int
    label: str
    high_threshold: float
    mid_low_threshold: float
    high_source: str
    mid_low_source: str


@dataclass(frozen=True)
class StorageFurnitureSpec:
    config_id: int
    name: str


def _is_cookable_ingredient(spec: RecipeItemSpec | None) -> bool:
    """Mirror the game's ingredient gate: food-category and explicitly cookable."""

    return spec is not None and spec.category == 1 and spec.can_cook


def _has_storage_behavior(values: Mapping[str, object]) -> bool:
    functions = values.get("FurnitureFunc")
    has_storage_function = isinstance(functions, (list, tuple)) and any(
        value == STORAGE_FURNITURE_FUNC_ID
        for value in functions
        if isinstance(value, int) and not isinstance(value, bool)
    )
    show_storage = values.get("ShowStorage")
    has_storage_capacity = (
        isinstance(show_storage, (int, float))
        and not isinstance(show_storage, bool)
        and show_storage > 0
    )
    return has_storage_function or has_storage_capacity


def _as_int(value: object, default: int = 0) -> int:
    return int(value) if isinstance(value, (int, float)) and not isinstance(value, bool) else default


def _as_int_tuple(value: object) -> tuple[int, ...]:
    if value is None:
        return ()
    if not isinstance(value, list):
        raise RecipeConfigError(f"配方字段应为整数列表，实际为：{value!r}")
    result: list[int] = []
    for index, item in enumerate(value):
        if not isinstance(item, int) or isinstance(item, bool):
            raise RecipeConfigError(
                f"配方字段第 {index + 1} 项应为整数，实际为：{item!r}"
            )
        result.append(item)
    return tuple(result)


def recipe_specs_from_rows(rows: Iterable[ConfigRow]) -> tuple[RecipeSpec, ...]:
    result: list[RecipeSpec] = []
    for row in rows:
        values = row.values
        tag_combo = _as_int_tuple(values.get("TagCombo"))
        specific_items = _as_int_tuple(values.get("SpecificItems"))
        if tag_combo and specific_items:
            raise RecipeConfigError(
                f"Config_CookingRecipe ID {row.row_id} 同时设置 SpecificItems 和 TagCombo；"
                "当前工具拒绝静默猜测其匹配语义"
            )
        result.append(
            RecipeSpec(
                recipe_id=row.row_id,
                name=config_row_name(row),
                name_key=str(values.get("RecipeName") or ""),
                tag_combo=tag_combo,
                specific_items=specific_items,
                tier=_as_int(values.get("Tier")),
                raw_json=json.dumps(values, ensure_ascii=False, separators=(",", ":")),
            )
        )
    return tuple(sorted(result, key=lambda recipe: recipe.recipe_id))


def item_specs_from_rows(
    rows: Iterable[ConfigRow],
    *,
    subcategory_names: Mapping[int, str] | None = None,
) -> tuple[RecipeItemSpec, ...]:
    names = subcategory_names or {}
    result: list[RecipeItemSpec] = []
    for row in rows:
        values = row.values
        result.append(
            RecipeItemSpec(
                item_id=row.row_id,
                name=config_row_name(row),
                can_cook=bool(values.get("CanCook")),
                category=_as_int(values.get("Category")),
                sub_category=_as_int(values.get("SubCategory")),
                sub_category_name=names.get(_as_int(values.get("SubCategory")), ""),
                price=float(values.get("price") or 0),
                raw_json=json.dumps(values, ensure_ascii=False, separators=(",", ":")),
                in_codex=values.get("InCodex") is True,
            )
        )
    return tuple(sorted(result, key=lambda item: item.item_id))


def storage_furniture_specs_from_rows(
    rows: Iterable[ConfigRow],
) -> tuple[StorageFurnitureSpec, ...]:
    """Identify furniture configs by storage behavior instead of display names."""

    result: list[StorageFurnitureSpec] = []
    for row in rows:
        if not _has_storage_behavior(row.values):
            continue
        result.append(StorageFurnitureSpec(config_id=row.row_id, name=config_row_name(row)))
    return tuple(sorted(result, key=lambda item: item.config_id))


def read_global_settings(game_root: Path) -> dict[str, tuple[int, float, str | None]]:
    """Read Config_GlobalSetting with the same strict table/row checks as the parser."""

    asset_path = "Assets/RuntimeAssets/Config/MemoryPack/Default/Config_GlobalSetting.bytes"
    raw, _bundle_name, _version, _bundle_path = load_text_asset(game_root, asset_path)
    reader = Reader(raw)
    count = reader.i32()
    if count < 0 or count > 2_000_000:
        raise RecipeConfigError(f"Config_GlobalSetting 行数非法：{count}")
    result: dict[str, tuple[int, float, str | None]] = {}
    for index in range(count):
        member_count = reader.u8()
        if member_count != 4:
            raise RecipeConfigError(
                f"Config_GlobalSetting schema changed at row {index}: member count={member_count}, expected=4"
            )
        key = reader.memorypack_string()
        params1 = reader.i32()
        params2 = reader.f32()
        params3 = reader.memorypack_string()
        if not key:
            raise RecipeConfigError(f"Config_GlobalSetting row {index} 的 ID 为空")
        if key in result:
            raise RecipeConfigError(f"Config_GlobalSetting 出现重复 ID：{key}")
        result[key] = (params1, params2, params3)
    if reader.pos != len(raw):
        raise RecipeConfigError(
            f"Config_GlobalSetting 解析未到末尾：offset={reader.pos}, total={len(raw)}"
        )
    return result


def tier_rules_from_settings(
    settings: Mapping[str, tuple[int, float, str | None]],
) -> tuple[TierRule, ...]:
    result: list[TierRule] = []
    for sub_category, label in SUPPORTED_TIER_SUBCATEGORIES.items():
        high_key, mid_low_key = TIER_RULE_KEYS[sub_category]
        if high_key not in settings or mid_low_key not in settings:
            raise RecipeConfigError(
                f"Config_GlobalSetting 缺少烹饪档位阈值：{high_key} 或 {mid_low_key}"
            )
        high = float(settings[high_key][1])
        mid_low = float(settings[mid_low_key][1])
        if not math.isfinite(high) or not math.isfinite(mid_low) or high < mid_low:
            raise RecipeConfigError(
                f"烹饪档位阈值非法：{label} high={high}, mid_low={mid_low}"
            )
        result.append(
            TierRule(
                sub_category=sub_category,
                label=label,
                high_threshold=high,
                mid_low_threshold=mid_low,
                high_source=high_key,
                mid_low_source=mid_low_key,
            )
        )
    return tuple(result)


def load_recipe_static_data(game_root: Path, context: Any) -> tuple[tuple[RecipeItemSpec, ...], tuple[RecipeSpec, ...], tuple[TierRule, ...]]:
    recipes = recipe_specs_from_rows(context.tables.get("Config_CookingRecipe", ()))
    items = item_specs_from_rows(
        context.tables.get("Config_Item", ()),
        subcategory_names={
            row.row_id: str(row.values.get("Name_Local") or row.values.get("Name") or "")
            for row in context.tables.get("Config_ItemSubCategory", ())
        },
    )
    rules = tier_rules_from_settings(read_global_settings(game_root))
    return items, recipes, rules


def populate_recipe_tables(
    connection: sqlite3.Connection,
    *,
    items: Iterable[RecipeItemSpec],
    rules: Iterable[TierRule],
    storage_furniture: Iterable[StorageFurnitureSpec] = (),
) -> dict[str, int]:
    item_rows = [
        (
            item.item_id,
            item.name,
            int(item.can_cook),
            item.category,
            item.sub_category,
            item.sub_category_name,
            item.price,
            item.raw_json,
        )
        for item in items
    ]
    rule_rows = [
        (
            rule.sub_category,
            rule.label,
            rule.high_threshold,
            rule.mid_low_threshold,
            rule.high_source,
            rule.mid_low_source,
        )
        for rule in rules
    ]
    storage_rows = [
        (storage.config_id, storage.name)
        for storage in storage_furniture
    ]
    connection.executemany(
        """
        INSERT INTO recipe_items(
            item_id, name, can_cook, category, sub_category,
            sub_category_name, price, raw_json
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """,
        item_rows,
    )
    connection.executemany(
        """
        INSERT INTO recipe_tier_rules(
            sub_category, label, high_threshold, mid_low_threshold,
            high_source, mid_low_source
        ) VALUES (?, ?, ?, ?, ?, ?)
        """,
        rule_rows,
    )
    connection.executemany(
        """
        INSERT INTO storage_furniture(config_id, name)
        VALUES (?, ?)
        """,
        storage_rows,
    )
    return {
        "recipe_items": len(item_rows),
        "recipe_tier_rules": len(rule_rows),
        "storage_furniture": len(storage_rows),
    }


def _load_items_from_database(connection: sqlite3.Connection) -> dict[int, RecipeItemSpec]:
    rows = connection.execute(
        """
        SELECT item_id, name, can_cook, category, sub_category,
               sub_category_name, price, raw_json
        FROM recipe_items
        ORDER BY item_id
        """
    ).fetchall()
    return {
        int(row["item_id"]): RecipeItemSpec(
            item_id=int(row["item_id"]),
            name=str(row["name"]),
            can_cook=bool(row["can_cook"]),
            category=int(row["category"]),
            sub_category=int(row["sub_category"]),
            sub_category_name=str(row["sub_category_name"] or ""),
            price=float(row["price"]),
            raw_json=str(row["raw_json"]),
            in_codex=json.loads(str(row["raw_json"])).get("InCodex") is True,
        )
        for row in rows
    }


def _load_storage_furniture_from_database(connection: sqlite3.Connection) -> dict[int, str]:
    storage_table_exists = True
    try:
        rows = connection.execute(
            "SELECT config_id, name FROM storage_furniture ORDER BY config_id"
        ).fetchall()
    except sqlite3.OperationalError as exc:
        if "no such table" not in str(exc).lower():
            raise
        storage_table_exists = False
        rows = ()

    if storage_table_exists:
        result = {
            int(row[0]): str(row[1]).strip() or f"ID:{int(row[0])}"
            for row in rows
            if int(row[0]) > 0
        }
        return result

    # Databases created before storage_furniture existed can still recover
    # current visible furniture rows as a compatibility fallback.
    try:
        config_rows = connection.execute(
            """
            SELECT source_id, name, raw_json
            FROM codex_entries
            WHERE source_table = 'Config_Furniture' AND is_current = 1
            ORDER BY source_id
            """
        ).fetchall()
    except sqlite3.OperationalError as exc:
        if "no such table" not in str(exc).lower():
            raise
        config_rows = ()
    result = {}
    for row in config_rows:
        raw = json.loads(str(row[2]))
        if _has_storage_behavior(raw):
            config_id = int(row[0])
            result[config_id] = str(row[1]).strip() or f"ID:{config_id}"
    return result or dict(LEGACY_STORAGE_FURNITURE)


def _load_rules_from_database(connection: sqlite3.Connection) -> dict[int, TierRule]:
    rows = connection.execute(
        """
        SELECT sub_category, label, high_threshold, mid_low_threshold,
               high_source, mid_low_source
        FROM recipe_tier_rules
        ORDER BY sub_category
        """
    ).fetchall()
    return {
        int(row["sub_category"]): TierRule(
            sub_category=int(row["sub_category"]),
            label=str(row["label"]),
            high_threshold=float(row["high_threshold"]),
            mid_low_threshold=float(row["mid_low_threshold"]),
            high_source=str(row["high_source"]),
            mid_low_source=str(row["mid_low_source"]),
        )
        for row in rows
    }


def _load_recipes_from_database(connection: sqlite3.Connection) -> tuple[RecipeSpec, ...]:
    rows = connection.execute(
        """
        SELECT source_id, name, name_key, raw_json
        FROM codex_entries
        WHERE source_table = 'Config_CookingRecipe' AND is_current = 1
        ORDER BY source_id
        """
    ).fetchall()
    result: list[RecipeSpec] = []
    for row in rows:
        raw = json.loads(str(row["raw_json"]))
        tag_combo = _as_int_tuple(raw.get("TagCombo"))
        specific_items = _as_int_tuple(raw.get("SpecificItems"))
        if tag_combo and specific_items:
            raise RecipeConfigError(
                f"Config_CookingRecipe ID {row['source_id']} 同时设置 SpecificItems 和 TagCombo；"
                "当前工具拒绝静默猜测其匹配语义"
            )
        result.append(
            RecipeSpec(
                recipe_id=int(row["source_id"]),
                name=str(row["name"]),
                name_key=str(row["name_key"]),
                tag_combo=tag_combo,
                specific_items=specific_items,
                tier=_as_int(raw.get("Tier")),
                raw_json=str(row["raw_json"]),
            )
        )
    return tuple(result)


def _item_tier(item: RecipeItemSpec, rule: TierRule) -> int:
    if item.price >= rule.high_threshold:
        return 1
    if item.price >= rule.mid_low_threshold:
        return 2
    return 3


def resolve_cooking_tier(
    item_ids: Collection[int],
    *,
    items: Mapping[int, RecipeItemSpec],
    rules: Mapping[int, TierRule],
) -> int | None:
    """Return the worst tier in the ingredient group (High=1, Mid=2, Low=3)."""

    tiers: list[int] = []
    for item_id in item_ids:
        item = items.get(item_id)
        if not _is_cookable_ingredient(item):
            return None
        rule = rules.get(item.sub_category)
        if rule is not None:
            tiers.append(_item_tier(item, rule))
    return max(tiers) if tiers else None


def _available_item_ids(
    inventory: Collection[InventoryItem],
    *,
    items: Mapping[int, RecipeItemSpec],
) -> tuple[dict[int, int], dict[int, list[InventoryItem]]]:
    counts: dict[int, int] = Counter()
    lots: dict[int, list[InventoryItem]] = defaultdict(list)
    for item in inventory:
        spec = items.get(item.item_config_id)
        if not _is_cookable_ingredient(spec) or item.item_count <= 0:
            continue
        counts[item.item_config_id] += item.item_count
        lots[item.item_config_id].append(item)
    return dict(counts), dict(lots)


def _enumerate_tag_combinations(
    tags: tuple[int, ...],
    available_counts: Mapping[int, int],
    items: Mapping[int, RecipeItemSpec],
) -> list[tuple[int, ...]]:
    ordered_tags = tuple(sorted(tags))
    candidates_by_tag = {
        tag: tuple(
            sorted(
                item_id
                for item_id, spec in items.items()
                if _is_cookable_ingredient(spec)
                and spec.sub_category == tag
                and available_counts.get(item_id, 0) > 0
            )
        )
        for tag in set(ordered_tags)
    }
    if any(not candidates_by_tag.get(tag) for tag in ordered_tags):
        return []

    result: list[tuple[int, ...]] = []
    selected: list[int] = []

    def visit(index: int, remaining: dict[int, int]) -> None:
        if index == len(ordered_tags):
            result.append(tuple(selected))
            return
        tag = ordered_tags[index]
        minimum = selected[index - 1] if index and ordered_tags[index - 1] == tag else None
        for item_id in candidates_by_tag[tag]:
            if minimum is not None and item_id < minimum:
                continue
            if remaining.get(item_id, 0) <= 0:
                continue
            selected.append(item_id)
            remaining[item_id] -= 1
            visit(index + 1, remaining)
            remaining[item_id] += 1
            selected.pop()

    visit(0, dict(available_counts))
    return result


def _recipes_by_tier(
    recipes: Collection[RecipeSpec],
    *,
    excluded_recipe_ids: Collection[int] = (),
) -> dict[int, list[RecipeSpec]]:
    """Index generic recipes by the tier selected by the game resolver."""

    excluded = frozenset(int(recipe_id) for recipe_id in excluded_recipe_ids)
    result: dict[int, list[RecipeSpec]] = defaultdict(list)
    for recipe in recipes:
        if recipe.recipe_id in excluded or recipe.tier not in TIER_LABELS:
            continue
        result[recipe.tier].append(recipe)
    for tier in result:
        result[tier].sort(key=lambda recipe: recipe.recipe_id)
    return dict(result)


def _specific_recipe_index(
    recipes: Collection[RecipeSpec],
    *,
    items: Mapping[int, RecipeItemSpec],
) -> dict[tuple[int, ...], tuple[RecipeSpec, ...]]:
    """Index valid SpecificItems recipes by their unordered ingredient multiset."""

    result: dict[tuple[int, ...], list[RecipeSpec]] = defaultdict(list)
    for recipe in sorted(recipes, key=lambda value: value.recipe_id):
        if not recipe.specific_items:
            continue
        required = Counter(recipe.specific_items)
        if any(
            not _is_cookable_ingredient(items.get(item_id))
            for item_id in required
        ):
            continue
        result[tuple(sorted(required.elements()))].append(recipe)
    return {key: tuple(value) for key, value in result.items()}


def _resolve_actual_recipe_outcome(
    combo: tuple[int, ...],
    *,
    tag_combo: tuple[int, ...] | None,
    generic_by_tier: Mapping[int, Collection[RecipeSpec]],
    specific_by_combo: Mapping[tuple[int, ...], Collection[RecipeSpec]],
    items: Mapping[int, RecipeItemSpec],
    rules: Mapping[int, TierRule],
) -> _RecipeOutcome | None:
    """Resolve one complete input using the game's specific-then-generic order."""

    if not combo or any(
        not _is_cookable_ingredient(items.get(item_id)) for item_id in combo
    ):
        return None
    if tag_combo is not None and Counter(
        items[item_id].sub_category for item_id in combo
    ) != Counter(tag_combo):
        return None

    specific_recipes = tuple(specific_by_combo.get(tuple(sorted(combo)), ()))
    if specific_recipes:
        return _RecipeOutcome(
            kind="specific",
            tier=resolve_cooking_tier(combo, items=items, rules=rules),
        )
    if tag_combo is None:
        return None

    tier = resolve_cooking_tier(combo, items=items, rules=rules)
    if tier is None:
        return None
    tier_candidates = generic_by_tier.get(tier, ())
    if not tier_candidates:
        return None
    selected = min(tier_candidates, key=lambda recipe: recipe.recipe_id)
    return _RecipeOutcome(
        kind="generic",
        tier=tier,
        generic_recipe=selected,
    )


def _representative_items(
    item_ids: tuple[int, ...],
    *,
    items: Mapping[int, RecipeItemSpec],
    lots: Mapping[int, Collection[InventoryItem]],
) -> list[dict[str, object]]:
    used: dict[int, int] = Counter()
    result: list[dict[str, object]] = []
    for item_id in item_ids:
        spec = items[item_id]
        lot_list = lots.get(item_id, ())
        lot_index = used[item_id]
        remaining_index = lot_index
        selected_lot: InventoryItem | None = None
        for lot in lot_list:
            if remaining_index < lot.item_count:
                selected_lot = lot
                break
            remaining_index -= lot.item_count
        if selected_lot is None and lot_list:
            selected_lot = lot_list[0]
        used[item_id] += 1
        result.append(
            {
                "item_id": item_id,
                "name": spec.name,
                "source": selected_lot.source if selected_lot else "未知来源",
                "container": selected_lot.container if selected_lot else "unknown",
                "category": spec.category,
                "sub_category": spec.sub_category,
                "sub_category_name": spec.sub_category_name or f"ID:{spec.sub_category}",
                "price": spec.price,
            }
        )
    return result


def _match_payload(
    recipe: RecipeSpec,
    *,
    combo: tuple[int, ...],
    candidate_recipe_ids: Collection[int],
    tier: int,
    combination_count: int,
    items: Mapping[int, RecipeItemSpec],
    lots: Mapping[int, Collection[InventoryItem]],
) -> dict[str, object]:
    return {
        "recipe_id": recipe.recipe_id,
        "name": recipe.name,
        "name_key": recipe.name_key,
        "candidate_group": list(recipe.tag_combo) if recipe.tag_combo else "SpecificItems",
        "candidate_recipe_ids": sorted(int(recipe_id) for recipe_id in candidate_recipe_ids),
        "specific_items": list(recipe.specific_items),
        "tag_combo": list(recipe.tag_combo),
        "recipe_kind": "generic" if recipe.tag_combo else "specific",
        "recipe_kind_label_zh": "通用菜肴" if recipe.tag_combo else "特色菜肴",
        "tier": tier,
        "tier_label": TIER_LABELS.get(tier, "指定食材"),
        "tier_label_zh": TIER_LABELS_ZH.get(tier, "指定食材"),
        "representative_combination": _representative_items(combo, items=items, lots=lots),
        "other_combination_count": max(0, combination_count - 1),
    }


def match_inventory(
    inventory: Collection[InventoryItem],
    recipes: Collection[RecipeSpec],
    items: Mapping[int, RecipeItemSpec],
    rules: Mapping[int, TierRule],
    *,
    completed_recipe_ids: Collection[int] = (),
) -> tuple[list[dict[str, object]], list[str]]:
    """Return pending recipes that are actually cookable from one inventory.

    SpecificItems and TagCombo results are kept independent, but every complete
    TagCombo input uses the game's specific-first outcome precedence instead of
    reserving shared ingredients between result groups.
    """

    completed = frozenset(int(recipe_id) for recipe_id in completed_recipe_ids)
    diagnostics: list[str] = []
    counts, lots = _available_item_ids(inventory, items=items)
    tag_groups: dict[tuple[int, ...], list[RecipeSpec]] = defaultdict(list)
    specific_recipes: list[RecipeSpec] = []
    for recipe in sorted(recipes, key=lambda value: value.recipe_id):
        if recipe.tag_combo and recipe.specific_items:
            raise RecipeConfigError(
                f"Config_CookingRecipe ID {recipe.recipe_id} 同时设置 SpecificItems 和 TagCombo；"
                "当前工具拒绝静默猜测其匹配语义"
            )
        if recipe.tag_combo:
            tag_groups[tuple(sorted(recipe.tag_combo))].append(recipe)
        elif recipe.specific_items:
            specific_recipes.append(recipe)

    matches: list[dict[str, object]] = []
    specific_by_combo = _specific_recipe_index(specific_recipes, items=items)
    for recipe in specific_recipes:
        required = Counter(recipe.specific_items)
        if any(counts.get(item_id, 0) < count for item_id, count in required.items()):
            continue
        if any(not _is_cookable_ingredient(items.get(item_id)) for item_id in required):
            continue
        combo = tuple(recipe.specific_items)
        tier = resolve_cooking_tier(combo, items=items, rules=rules)
        matches.append(
            _match_payload(
                recipe,
                combo=combo,
                candidate_recipe_ids=(recipe.recipe_id,),
                tier=tier or 0,
                combination_count=1,
                items=items,
                lots=lots,
            )
        ) if recipe.recipe_id not in completed else None

    for tag_combo, group in sorted(tag_groups.items()):
        combinations = _enumerate_tag_combinations(tag_combo, counts, items)
        if not combinations:
            continue
        candidate_by_tier = _recipes_by_tier(
            group,
            excluded_recipe_ids=completed,
        )
        combinations_by_recipe: dict[int, list[tuple[int, ...]]] = defaultdict(list)
        for combo in combinations:
            outcome = _resolve_actual_recipe_outcome(
                combo,
                tag_combo=tag_combo,
                generic_by_tier=candidate_by_tier,
                specific_by_combo=specific_by_combo,
                items=items,
                rules=rules,
            )
            if outcome is None:
                tier = resolve_cooking_tier(combo, items=items, rules=rules)
                if tier is None:
                    diagnostics.append(
                        f"食材组合 {combo!r} 无法计算 CookingTierResolver 档位；已跳过候选组 {tag_combo!r}"
                    )
                elif not candidate_by_tier.get(tier):
                    diagnostics.append(
                        f"候选组 {tag_combo!r} 缺少 Tier={tier} 菜谱；已保留配置诊断"
                    )
                continue
            if outcome.kind != "generic" or outcome.generic_recipe is None:
                continue
            combinations_by_recipe[outcome.generic_recipe.recipe_id].append(combo)
        recipes_by_id = {recipe.recipe_id: recipe for recipe in group}
        for recipe_id in sorted(combinations_by_recipe):
            selected = recipes_by_id[recipe_id]
            recipe_combinations = combinations_by_recipe[recipe_id]
            representative = min(recipe_combinations)
            selected_tier = resolve_cooking_tier(representative, items=items, rules=rules)
            if selected_tier is None:
                continue
            matches.append(
                _match_payload(
                    selected,
                    combo=representative,
                    candidate_recipe_ids=[recipe.recipe_id for recipe in group],
                    tier=selected_tier,
                    combination_count=len(recipe_combinations),
                    items=items,
                    lots=lots,
                )
            )

    by_recipe_id: dict[int, dict[str, object]] = {}
    for match in matches:
        recipe_id = int(match["recipe_id"])
        existing = by_recipe_id.get(recipe_id)
        if existing is None:
            by_recipe_id[recipe_id] = match
            continue
        current_combo = tuple(
            int(item["item_id"])
            for item in existing.get("representative_combination", [])
            if isinstance(item, dict)
        )
        new_combo = tuple(
            int(item["item_id"])
            for item in match.get("representative_combination", [])
            if isinstance(item, dict)
        )
        if new_combo < current_combo:
            existing["representative_combination"] = match["representative_combination"]
        existing["other_combination_count"] = max(
            int(existing.get("other_combination_count", 0)),
            int(match.get("other_combination_count", 0)),
        )
    return [by_recipe_id[key] for key in sorted(by_recipe_id)], sorted(set(diagnostics))


def _static_item_payload(
    spec: RecipeItemSpec,
    *,
    count: int = 1,
) -> dict[str, object]:
    return {
        "item_id": spec.item_id,
        "name": spec.name,
        "count": count,
        "source": "尚未拥有",
        "container": "unknown",
        "category": spec.category,
        "sub_category": spec.sub_category,
        "sub_category_name": spec.sub_category_name or f"ID:{spec.sub_category}",
        "price": spec.price,
    }


def _near_match_payload(
    recipe: RecipeSpec,
    *,
    combo: tuple[int, ...],
    candidate_recipe_ids: Collection[int],
    tier: int,
    items: Mapping[int, RecipeItemSpec],
    lots: Mapping[int, Collection[InventoryItem]],
    missing_items: Collection[RecipeItemSpec] = (),
    missing_item_candidates: Collection[RecipeItemSpec] = (),
    missing_sub_category: int | None = None,
) -> dict[str, object]:
    payload = _match_payload(
        recipe,
        combo=combo,
        candidate_recipe_ids=candidate_recipe_ids,
        tier=tier,
        combination_count=1,
        items=items,
        lots=lots,
    )
    payload["available_combination"] = payload.pop("representative_combination")
    payload["missing_items"] = [
        _static_item_payload(spec)
        for spec in sorted(missing_items, key=lambda value: value.item_id)
    ]
    payload["missing_item_candidates"] = [
        _static_item_payload(spec)
        for spec in sorted(missing_item_candidates, key=lambda value: value.item_id)
    ]
    missing_category_name = f"ID:{missing_sub_category}"
    if missing_sub_category is not None:
        for spec in sorted(items.values(), key=lambda value: value.item_id):
            if spec.sub_category == missing_sub_category:
                missing_category_name = spec.sub_category_name or missing_category_name
                break
    payload["missing_sub_category"] = (
        {
            "sub_category": missing_sub_category,
            "name": missing_category_name,
            "count": 1,
        }
        if missing_sub_category is not None
        else None
    )
    return payload


def find_near_matches(
    inventory: Collection[InventoryItem],
    recipes: Collection[RecipeSpec],
    items: Mapping[int, RecipeItemSpec],
    rules: Mapping[int, TierRule],
    *,
    completed_recipe_ids: Collection[int] = (),
    excluded_recipe_ids: Collection[int] = (),
) -> list[dict[str, object]]:
    """Find pending one-slot recipes using the same complete-input precedence."""

    completed = frozenset(int(recipe_id) for recipe_id in completed_recipe_ids)
    excluded = completed | frozenset(int(recipe_id) for recipe_id in excluded_recipe_ids)
    counts, lots = _available_item_ids(inventory, items=items)
    tag_groups: dict[tuple[int, ...], list[RecipeSpec]] = defaultdict(list)
    all_specific_recipes: list[RecipeSpec] = []
    specific_recipes: list[RecipeSpec] = []
    for recipe in sorted(recipes, key=lambda value: value.recipe_id):
        if recipe.tag_combo and recipe.specific_items:
            raise RecipeConfigError(
                f"Config_CookingRecipe ID {recipe.recipe_id} 同时设置 SpecificItems 和 TagCombo；"
                "当前工具拒绝静默猜测其匹配语义"
            )
        if recipe.tag_combo:
            if recipe.recipe_id in excluded:
                continue
            tag_groups[tuple(sorted(recipe.tag_combo))].append(recipe)
        elif recipe.specific_items:
            all_specific_recipes.append(recipe)
            if recipe.recipe_id in excluded:
                continue
            specific_recipes.append(recipe)

    specific_by_combo = _specific_recipe_index(all_specific_recipes, items=items)
    near_matches: list[dict[str, object]] = []
    for recipe in specific_recipes:
        required = Counter(recipe.specific_items)
        if any(
            not _is_cookable_ingredient(items.get(item_id))
            for item_id in required
        ):
            continue
        missing_ids: list[int] = []
        for item_id, required_count in required.items():
            missing_ids.extend(
                [item_id] * max(0, required_count - counts.get(item_id, 0))
            )
        if len(missing_ids) != 1:
            continue
        missing_id = missing_ids[0]
        available_combo = list(recipe.specific_items)
        available_combo.remove(missing_id)
        tier = resolve_cooking_tier(recipe.specific_items, items=items, rules=rules) or 0
        near_matches.append(
            _near_match_payload(
                recipe,
                combo=tuple(available_combo),
                candidate_recipe_ids=(recipe.recipe_id,),
                tier=tier,
                items=items,
                lots=lots,
                missing_items=(items[missing_id],),
            )
        )

    for tag_combo, group in sorted(tag_groups.items()):
        candidate_by_tier = _recipes_by_tier(group)
        if not candidate_by_tier:
            continue

        # An exact generic combination already proves that its resolved tier
        # is available.  Do not report another pending recipe in that same
        # tier as a one-slot near match.
        matched_tiers: set[int] = set()
        for available_combo in _enumerate_tag_combinations(tag_combo, counts, items):
            outcome = _resolve_actual_recipe_outcome(
                available_combo,
                tag_combo=tag_combo,
                generic_by_tier=candidate_by_tier,
                specific_by_combo=specific_by_combo,
                items=items,
                rules=rules,
            )
            if outcome is not None and outcome.kind == "generic" and outcome.tier is not None:
                matched_tiers.add(outcome.tier)

        pending_candidate_ids = [recipe.recipe_id for recipe in group]
        by_recipe_id: dict[int, dict[str, object]] = {}
        for missing_tag in sorted(set(tag_combo)):
            partial_tags = list(tag_combo)
            partial_tags.remove(missing_tag)
            partial_combinations = _enumerate_tag_combinations(
                tuple(partial_tags), counts, items
            )
            if not partial_combinations:
                continue
            candidates = tuple(
                sorted(
                    (
                        spec
                        for spec in items.values()
                        if _is_cookable_ingredient(spec)
                        and spec.sub_category == missing_tag
                    ),
                    key=lambda spec: spec.item_id,
                )
            )
            if not candidates:
                continue

            for partial_combo in partial_combinations:
                for candidate in candidates:
                    full_combo = tuple(partial_combo) + (candidate.item_id,)
                    if Counter(
                        items[item_id].sub_category for item_id in full_combo
                    ) != Counter(tag_combo):
                        continue
                    outcome = _resolve_actual_recipe_outcome(
                        full_combo,
                        tag_combo=tag_combo,
                        generic_by_tier=candidate_by_tier,
                        specific_by_combo=specific_by_combo,
                        items=items,
                        rules=rules,
                    )
                    if outcome is None or outcome.kind != "generic":
                        continue
                    if outcome.tier is None or outcome.generic_recipe is None:
                        continue
                    tier = outcome.tier
                    if tier in matched_tiers:
                        continue
                    selected = outcome.generic_recipe
                    entry = by_recipe_id.setdefault(
                        selected.recipe_id,
                        {
                            "recipe": selected,
                            "combos": [],
                            "missing_tag": missing_tag,
                            "candidate_items": {},
                        },
                    )
                    entry["combos"].append(tuple(partial_combo))
                    entry["candidate_items"][candidate.item_id] = candidate

        for recipe_id in sorted(by_recipe_id):
            entry = by_recipe_id[recipe_id]
            selected = entry["recipe"]
            combinations = entry["combos"]
            representative = min(combinations)
            near_matches.append(
                _near_match_payload(
                    selected,
                    combo=tuple(representative),
                    candidate_recipe_ids=pending_candidate_ids,
                    tier=selected.tier,
                    items=items,
                    lots=lots,
                    missing_item_candidates=entry["candidate_items"].values(),
                    missing_sub_category=entry["missing_tag"],
                )
            )

    return sorted(near_matches, key=lambda match: int(match["recipe_id"]))


def _inventory_payload(
    inventory: SaveInventoryState,
    *,
    items: Mapping[int, RecipeItemSpec],
) -> tuple[list[dict[str, object]], list[str]]:
    merged: dict[int, dict[str, object]] = {}
    source_values: dict[int, list[str]] = {}
    container_values: dict[int, list[str]] = {}
    diagnostics = list(inventory.diagnostics)
    for item in inventory.items:
        spec = items.get(item.item_config_id)
        if spec is None:
            diagnostics.append(f"库存中的未知物品 ID {item.item_config_id} 已排除")
            continue
        if not _is_cookable_ingredient(spec) or not spec.in_codex:
            continue
        item_id = int(item.item_config_id)
        current = merged.get(item_id)
        if current is None:
            merged[item_id] = {
                "item_id": item_id,
                "name": spec.name,
                "count": int(item.item_count),
                "source": item.source,
                "container": item.container,
                "category": spec.category,
                "sub_category": spec.sub_category,
                "sub_category_name": spec.sub_category_name or f"ID:{spec.sub_category}",
                "price": spec.price,
            }
            source_values[item_id] = []
            container_values[item_id] = []
        else:
            current["count"] = int(current["count"]) + int(item.item_count)
        for value, values in (
            (str(item.source).strip(), source_values[item_id]),
            (str(item.container).strip(), container_values[item_id]),
        ):
            if value and value not in values:
                values.append(value)

    result = []
    for item_id, payload in merged.items():
        sources = source_values[item_id]
        containers = container_values[item_id]
        payload["source"] = "、".join(sources) or "未知来源"
        payload["container"] = "、".join(containers) or "unknown"
        result.append(payload)
    return result, sorted(set(diagnostics))


def _storage_container_payload(container: StorageContainer) -> dict[str, object]:
    return {
        "config_id": container.config_id,
        "name": container.name,
        "instance_id": container.instance_id,
        "map_config_id": container.map_config_id,
        "home_map_config_id": container.home_map_config_id,
        "chapter_map_key": container.chapter_map_key,
        "chapter_id": container.chapter_id,
        "slot_pos_point": container.slot_pos_point,
        "location": container.location,
        "location_label": STORAGE_LOCATION_LABELS.get(container.location, "位置未知"),
        "is_home": container.is_home,
        "item_stack_count": container.item_stack_count,
    }


def _matchable_inventory(
    inventory: SaveInventoryState,
    *,
    items: Mapping[int, RecipeItemSpec],
) -> tuple[InventoryItem, ...]:
    return tuple(
        item
        for item in inventory.items
        if _is_cookable_ingredient(spec := items.get(item.item_config_id))
        and item.item_count > 0
    )


def _history_save_name(record: SaveHistoryRecord) -> str:
    return record.name or Path(record.file_name).stem.removeprefix("Save_")


def _validate_save_filename(file_name: str) -> None:
    if (
        not file_name
        or Path(file_name).name != file_name
        or "/" in file_name
        or "\\" in file_name
        or not SAVE_FILENAME_RE.fullmatch(file_name)
    ):
        raise RecipeConfigError(f"HistorySave 子存档文件名非法：{file_name!r}")


def _file_info_payload(info: Any) -> dict[str, object]:
    return {
        "path": str(info.path),
        "sha256": info.sha256,
        "size": info.size,
        "mtime_ns": info.mtime_ns,
        "read_at": info.read_at,
        "used_backup": info.used_backup,
    }


def _save_payload_base(record: SaveHistoryRecord) -> dict[str, object]:
    mode = "剧情无尽模式" if record.is_story_endless else "纯无尽模式" if record.is_pure_endless else "剧情模式"
    return {
        "file_name": record.file_name,
        "name": _history_save_name(record),
        "player_select_id": record.player_select_id,
        "role_name": None,
        "resolved_player_select_id": None,
        "leading_role_config_id": None,
        "home_map_config_id": None,
        "role_resolution_source": "unresolved",
        "role_diagnostics": [],
        "resolved_chapter_map_key": None,
        "chapter_resolution_source": "unresolved",
        "chapter_diagnostics": [],
        "max_day": record.max_day,
        "turn": record.turn,
        "is_finished": record.is_finished,
        "finish_result": record.finish_result,
        "difficulty_preset_id": record.difficulty_preset_id,
        "difficulty_levels": list(record.difficulty_levels),
        "is_story_endless": record.is_story_endless,
        "is_pure_endless": record.is_pure_endless,
        "endless_start_day": record.endless_start_day,
        "mode": mode,
    }


def build_recipe_plan(connection: sqlite3.Connection, history_path: Path) -> dict[str, object]:
    """Build the complete global-and-per-save recipe plan without persisting inventory."""

    history = read_history_save(history_path)
    items = _load_items_from_database(connection)
    rules = _load_rules_from_database(connection)
    recipes = _load_recipes_from_database(connection)
    storage_furniture = _load_storage_furniture_from_database(connection)
    if len(items) == 0:
        raise RecipeConfigError("数据库未包含 recipe_items；请先重建数据库")
    if len(rules) != len(SUPPORTED_TIER_SUBCATEGORIES):
        raise RecipeConfigError(
            f"数据库烹饪档位阈值不完整：actual={len(rules)}, expected={len(SUPPORTED_TIER_SUBCATEGORIES)}"
        )
    if len(recipes) != 496:
        raise RecipeConfigError(f"数据库菜谱数量不完整：actual={len(recipes)}, expected=496")
    completed = frozenset(history.category_ids.get("dish", ()))
    pending = [recipe for recipe in recipes if recipe.recipe_id not in completed]
    pending_payload = [
        {"recipe_id": recipe.recipe_id, "name": recipe.name, "name_key": recipe.name_key}
        for recipe in pending
    ]
    thresholds_payload = [
        {
            "sub_category": rule.sub_category,
            "label": rule.label,
            "high_threshold": rule.high_threshold,
            "mid_low_threshold": rule.mid_low_threshold,
            "high_source": rule.high_source,
            "mid_low_source": rule.mid_low_source,
        }
        for rule in sorted(rules.values(), key=lambda value: value.sub_category)
    ]
    all_diagnostics: list[str] = []
    saves: list[dict[str, object]] = []
    seen_names: set[str] = set()
    root = Path(history.file_info.path).parent
    history_file_names = {record.file_name for record in history.history_records}
    selected_save_file = (
        history.last_play_file_name
        if history.last_play_file_name in history_file_names
        else history.history_records[0].file_name if history.history_records else None
    )
    for record in history.history_records:
        payload = _save_payload_base(record)
        try:
            _validate_save_filename(record.file_name)
        except RecipeConfigError as exc:
            payload.update({"status": "error", "container_counts": {}, "storage_containers": [], "inventory": [], "matches": [], "near_matches": [], "diagnostics": [str(exc)]})
            saves.append(payload)
            all_diagnostics.append(str(exc))
            continue
        if record.file_name in seen_names:
            message = f"HistorySave 重复列出子存档：{record.file_name}"
            payload.update({"status": "error", "container_counts": {}, "storage_containers": [], "inventory": [], "matches": [], "near_matches": [], "diagnostics": [message]})
            saves.append(payload)
            all_diagnostics.append(message)
            continue
        seen_names.add(record.file_name)
        requested = root / record.file_name
        try:
            inventory = read_game_save_inventory(
                requested,
                storage_furniture=storage_furniture,
                player_select_id=record.player_select_id,
            )
        except SaveParseError as exc:
            message = str(exc)
            payload.update({"status": "missing" if not requested.exists() else "error", "container_counts": {}, "storage_containers": [], "inventory": [], "matches": [], "near_matches": [], "diagnostics": [message]})
            saves.append(payload)
            all_diagnostics.append(message)
            continue
        inventory_payload, inventory_diagnostics = _inventory_payload(inventory, items=items)
        eligible_inventory = _matchable_inventory(inventory, items=items)
        matches, match_diagnostics = match_inventory(
            eligible_inventory,
            recipes,
            items,
            rules,
            completed_recipe_ids=completed,
        )
        near_matches = find_near_matches(
            eligible_inventory,
            recipes,
            items,
            rules,
            completed_recipe_ids=completed,
            excluded_recipe_ids={int(match["recipe_id"]) for match in matches},
        )
        diagnostics = sorted(set(inventory_diagnostics + match_diagnostics))
        role_context = inventory.role_context
        payload.update(
            {
                "status": "ok",
                "source_file": _file_info_payload(inventory.file_info),
                "role_name": role_context.role_name if role_context is not None else None,
                "resolved_player_select_id": (
                    role_context.resolved_player_select_id
                    if role_context is not None
                    else None
                ),
                "leading_role_config_id": (
                    role_context.leading_role_config_id
                    if role_context is not None
                    else None
                ),
                "home_map_config_id": (
                    role_context.home_map_config_id
                    if role_context is not None
                    else None
                ),
                "role_resolution_source": (
                    role_context.resolution_source
                    if role_context is not None
                    else "unresolved"
                ),
                "role_diagnostics": (
                    list(role_context.diagnostics)
                    if role_context is not None
                    else []
                ),
                "resolved_chapter_map_key": (
                    role_context.resolved_chapter_map_key
                    if role_context is not None
                    else None
                ),
                "chapter_resolution_source": (
                    role_context.chapter_resolution_source
                    if role_context is not None
                    else "unresolved"
                ),
                "chapter_diagnostics": (
                    list(role_context.chapter_diagnostics)
                    if role_context is not None
                    else []
                ),
                "container_counts": inventory.container_counts,
                "storage_containers": [
                    _storage_container_payload(container)
                    for container in inventory.storage_containers
                ],
                "inventory": inventory_payload,
                "matches": matches,
                "near_matches": near_matches,
                "diagnostics": diagnostics,
            }
        )
        saves.append(payload)
        all_diagnostics.extend(diagnostics)
    return {
        "status": "partial" if all_diagnostics else "ok",
        "history_source": _file_info_payload(history.file_info),
        "default_save_file": selected_save_file,
        "selected_save_file": selected_save_file,
        "completed_dish_ids": sorted(completed),
        "completed_dish_count": len(completed),
        "pending_dish_count": len(pending_payload),
        "pending_dishes": pending_payload,
        "thresholds": thresholds_payload,
        "saves": saves,
        "diagnostics": sorted(set(all_diagnostics)),
    }


def build_recipe_error(message: str, *, diagnostics: Collection[str] = ()) -> dict[str, object]:
    return {
        "status": "error",
        "history_source": None,
        "completed_dish_ids": [],
        "completed_dish_count": 0,
        "pending_dish_count": 0,
        "pending_dishes": [],
        "thresholds": [],
        "saves": [],
        "storage_containers": [],
        "default_save_file": None,
        "selected_save_file": None,
        "diagnostics": sorted(set([message, *diagnostics])),
    }


__all__ = [
    "RecipeConfigError",
    "RecipeItemSpec",
    "RecipeSpec",
    "RECIPE_PLAN_CACHE_VERSION",
    "StorageFurnitureSpec",
    "SUPPORTED_TIER_SUBCATEGORIES",
    "TIER_LABELS",
    "TIER_LABELS_ZH",
    "TierRule",
    "build_recipe_error",
    "build_recipe_plan",
    "find_near_matches",
    "item_specs_from_rows",
    "load_recipe_static_data",
    "match_inventory",
    "populate_recipe_tables",
    "recipe_specs_from_rows",
    "resolve_cooking_tier",
    "storage_furniture_specs_from_rows",
    "tier_rules_from_settings",
]
