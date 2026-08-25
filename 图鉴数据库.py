#!/usr/bin/env python3
"""Build and query the offline Survival Log codex SQLite database."""

from __future__ import annotations

import argparse
import json
import sqlite3
import sys
from datetime import datetime
from pathlib import Path
from typing import Any

from 图鉴解析工具 import (
    AUXILIARY_TABLES,
    ConfigRow,
    ExtractionContext,
    classify_codex_items,
    config_row_name,
    build_extraction_context,
)


if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")
if hasattr(sys.stderr, "reconfigure"):
    sys.stderr.reconfigure(encoding="utf-8")


DATABASE_SCHEMA_VERSION = 1
CATEGORY_LABELS = {
    "food": "食品",
    "dish": "菜肴",
    "plant": "植物",
    "prey": "猎物",
    "craft": "制造",
    "furniture": "家具",
}
CATEGORY_ORDER = tuple(CATEGORY_LABELS)


SCHEMA_SQL = """
PRAGMA foreign_keys = ON;

CREATE TABLE IF NOT EXISTS metadata (
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS codex_categories (
    category TEXT PRIMARY KEY,
    label TEXT NOT NULL,
    sort_order INTEGER NOT NULL
);

CREATE TABLE IF NOT EXISTS codex_entries (
    entry_key TEXT PRIMARY KEY,
    source_table TEXT NOT NULL,
    source_id INTEGER NOT NULL,
    name TEXT NOT NULL,
    name_key TEXT NOT NULL,
    description TEXT NOT NULL,
    icon_path TEXT NOT NULL,
    raw_json TEXT NOT NULL,
    is_current INTEGER NOT NULL DEFAULT 1 CHECK (is_current IN (0, 1)),
    UNIQUE (source_table, source_id)
);

CREATE TABLE IF NOT EXISTS codex_entry_categories (
    entry_key TEXT NOT NULL,
    category TEXT NOT NULL,
    sort_order INTEGER NOT NULL,
    PRIMARY KEY (entry_key, category),
    FOREIGN KEY (entry_key) REFERENCES codex_entries(entry_key),
    FOREIGN KEY (category) REFERENCES codex_categories(category)
);

CREATE TABLE IF NOT EXISTS completion (
    entry_key TEXT PRIMARY KEY,
    completed INTEGER NOT NULL DEFAULT 0 CHECK (completed IN (0, 1)),
    updated_at TEXT NOT NULL,
    FOREIGN KEY (entry_key) REFERENCES codex_entries(entry_key)
);

CREATE TABLE IF NOT EXISTS entry_relations (
    source_entry_key TEXT NOT NULL,
    relation_type TEXT NOT NULL,
    target_table TEXT NOT NULL,
    target_id INTEGER NOT NULL,
    target_name TEXT NOT NULL,
    ordinal INTEGER NOT NULL,
    raw_value TEXT NOT NULL,
    PRIMARY KEY (source_entry_key, relation_type, target_table, ordinal),
    FOREIGN KEY (source_entry_key) REFERENCES codex_entries(entry_key)
);

CREATE TABLE IF NOT EXISTS auxiliary_rows (
    table_name TEXT NOT NULL,
    row_id INTEGER NOT NULL,
    name TEXT NOT NULL,
    raw_json TEXT NOT NULL,
    PRIMARY KEY (table_name, row_id)
);

CREATE INDEX IF NOT EXISTS idx_codex_entry_categories_category
    ON codex_entry_categories(category, sort_order);
CREATE INDEX IF NOT EXISTS idx_codex_entries_name
    ON codex_entries(name);
CREATE INDEX IF NOT EXISTS idx_entry_relations_source
    ON entry_relations(source_entry_key);
"""


def utc_now() -> str:
    return datetime.now().astimezone().isoformat(timespec="seconds")


def source_key(table_name: str, row_id: int) -> str:
    return f"{table_name}:{row_id}"


def json_text(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"))


def row_name_key(row: ConfigRow) -> str:
    for field in (
        "ItemName", "RecipeName", "Name", "ShopName", "BtnName", "TagName", "Info",
    ):
        value = row.values.get(field)
        if value:
            return str(value)
    return ""


def row_description(row: ConfigRow) -> str:
    for field in (
        "ItemDes1_Local", "Des_Local", "Info_Local", "BtnTips_Local",
        "ConfirmInfo_Local", "ItemDes1", "Des", "Info",
    ):
        value = row.values.get(field)
        if value:
            return str(value)
    return ""


def row_icon_path(row: ConfigRow) -> str:
    for field in ("WebIcon", "ICON", "Icon", "IT_Icon", "BtnIcon", "IconKey"):
        value = row.values.get(field)
        if value:
            return str(value)
    return ""


def category_rows(context: ExtractionContext) -> dict[str, list[ConfigRow]]:
    food, prey = classify_codex_items(context)
    return {
        "food": food,
        "dish": list(context.tables["Config_CookingRecipe"]),
        "plant": [row for row in context.tables["Config_Plant"] if row.values.get("InCodex")],
        "prey": prey,
        "craft": [
            row for row in context.tables["Config_ProductionList"] if row.values.get("InCodex")
        ],
        "furniture": [
            row for row in context.tables["Config_Furniture"] if row.values.get("InCodex")
        ],
    }


def collect_entries(
    context: ExtractionContext,
) -> tuple[dict[str, ConfigRow], list[tuple[str, str, int]]]:
    entries: dict[str, ConfigRow] = {}
    memberships: list[tuple[str, str, int]] = []
    for category in CATEGORY_ORDER:
        rows = sorted(category_rows(context)[category], key=lambda row: row.row_id)
        for sort_order, row in enumerate(rows):
            key = source_key(row.table, row.row_id)
            entries.setdefault(key, row)
            memberships.append((key, category, sort_order))
    return entries, memberships


def target_name(context: ExtractionContext, table_name: str, target_id: int) -> str:
    if not target_id:
        return "无"
    if table_name == "Config_Item":
        return context.item_names.get(target_id) or f"ID:{target_id}"
    if table_name == "Config_ItemSubCategory":
        return context.subcategory_names.get(target_id) or f"ID:{target_id}"
    if table_name == "Config_FoodType":
        return context.food_type_names.get(target_id) or f"ID:{target_id}"
    if table_name == "Config_CookingRecipe":
        return context.dish_names.get(target_id) or f"ID:{target_id}"
    table_rows = context.tables.get(table_name, [])
    for row in table_rows:
        if row.row_id == target_id:
            name = config_row_name(row)
            if not name.startswith("ID:"):
                return name
            break
    return f"ID:{target_id}"


def build_relations(
    context: ExtractionContext,
    entries: dict[str, ConfigRow],
) -> list[tuple[str, str, str, int, str, int, str]]:
    relations: list[tuple[str, str, str, int, str, int, str]] = []

    def add(
        row: ConfigRow,
        relation_type: str,
        table_name: str,
        target_id: Any,
        ordinal: int,
        raw_value: Any,
    ) -> None:
        if not isinstance(target_id, int) or target_id == 0:
            return
        relations.append(
            (
                source_key(row.table, row.row_id),
                relation_type,
                table_name,
                target_id,
                target_name(context, table_name, target_id),
                ordinal,
                json_text(raw_value),
            )
        )

    def add_field(row: ConfigRow, field: str, relation_type: str, table_name: str) -> None:
        value = row.values.get(field)
        if isinstance(value, list):
            for ordinal, target_id in enumerate(value):
                add(row, relation_type, table_name, target_id, ordinal, target_id)
        else:
            add(row, relation_type, table_name, value, 0, value)

    for row in entries.values():
        if row.table == "Config_Item":
            add_field(row, "SubCategory", "子分类", "Config_ItemSubCategory")
            for field in ("FoodTag1", "FoodTag2", "FoodTag3"):
                add_field(row, field, field, "Config_FoodType")
            add_field(row, "It_Rot_Product_Id", "腐烂产物", "Config_Item")
            add_field(row, "Plant", "关联植物", "Config_Plant")
            add_field(row, "TargetFurnitureID", "目标家具", "Config_Furniture")
            add_field(row, "CutProductId", "切割产物", "Config_Item")
        elif row.table == "Config_CookingRecipe":
            add_field(row, "SpecificItems", "具体食材", "Config_Item")
            add_field(row, "TagCombo", "食材分类", "Config_ItemSubCategory")
            for field, relation_type in (
                ("PerfectItemID", "完美产物"),
                ("GoodItemID", "良好产物"),
                ("NormalItemID", "普通产物"),
                ("FailItemID", "失败产物"),
            ):
                add_field(row, field, relation_type, "Config_Item")
        elif row.table == "Config_Plant":
            for field, relation_type in (
                ("Gain", "收获产物"),
                ("Perfect_Gain", "完美收获"),
                ("Gain_Seed", "种子产物"),
                ("WitheredGain", "枯萎产物"),
            ):
                add_field(row, field, relation_type, "Config_Item")
        elif row.table == "Config_ProductionList":
            for field, relation_type in (
                ("MaterialList", "制造材料"),
                ("ProductID", "制造产物"),
                ("FailedID", "失败产物"),
                ("perfect_item_id", "完美产物"),
            ):
                add_field(row, field, relation_type, "Config_Item")
        elif row.table == "Config_Furniture":
            for field, relation_type, table_name in (
                ("FurnitureFunc", "家具功能", "Config_FurnitureFunc"),
                ("RemoveFunc", "拆除功能", "Config_FurnitureFunc"),
                ("MoveFunc", "移动功能", "Config_FurnitureFunc"),
                ("RemoveGet", "拆除获得", "Config_Item"),
                ("PlantFurnitureID", "种植配置", "Config_FurniturePlant"),
                ("CookFurnitureID", "烹饪配置", "Config_FurnitureCook"),
                ("BagId", "包裹物品", "Config_Item"),
                ("ElectricalFurnitureID", "电力配置", "Config_FurnitureElectrical"),
                ("RotProductOverride", "腐烂产物覆盖", "Config_Item"),
            ):
                add_field(row, field, relation_type, table_name)
    return relations


def ensure_database_outside_game_root(game_root: Path, database_path: Path) -> None:
    resolved_game_root = game_root.resolve()
    resolved_database = database_path.resolve()
    try:
        resolved_database.relative_to(resolved_game_root)
    except ValueError:
        return
    raise ValueError(f"拒绝将数据库写入游戏安装目录：{resolved_database}")


def initialize_database(connection: sqlite3.Connection) -> None:
    connection.executescript(SCHEMA_SQL)
    row = connection.execute(
        "SELECT value FROM metadata WHERE key = 'database_schema_version'"
    ).fetchone()
    if row is not None and int(row[0]) > DATABASE_SCHEMA_VERSION:
        raise RuntimeError(
            f"数据库 schema 版本过高：{row[0]}，当前工具只支持 {DATABASE_SCHEMA_VERSION}"
        )


def build_database(game_root: Path, database_path: Path) -> dict[str, int]:
    ensure_database_outside_game_root(game_root, database_path)
    context = build_extraction_context(game_root)
    entries, memberships = collect_entries(context)
    relations = build_relations(context, entries)
    database_path.parent.mkdir(parents=True, exist_ok=True)

    connection = sqlite3.connect(str(database_path), timeout=30)
    try:
        connection.execute("PRAGMA foreign_keys = ON")
        initialize_database(connection)
        imported_at = utc_now()
        with connection:
            connection.execute("UPDATE codex_entries SET is_current = 0")
            connection.execute("DELETE FROM codex_entry_categories")
            connection.execute("DELETE FROM entry_relations")
            connection.execute("DELETE FROM auxiliary_rows")

            for sort_order, (category, label) in enumerate(CATEGORY_LABELS.items()):
                connection.execute(
                    """
                    INSERT INTO codex_categories(category, label, sort_order)
                    VALUES (?, ?, ?)
                    ON CONFLICT(category) DO UPDATE SET label=excluded.label, sort_order=excluded.sort_order
                    """,
                    (category, label, sort_order),
                )

            for key, row in entries.items():
                connection.execute(
                    """
                    INSERT INTO codex_entries(
                        entry_key, source_table, source_id, name, name_key,
                        description, icon_path, raw_json, is_current
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, 1)
                    ON CONFLICT(entry_key) DO UPDATE SET
                        source_table=excluded.source_table,
                        source_id=excluded.source_id,
                        name=excluded.name,
                        name_key=excluded.name_key,
                        description=excluded.description,
                        icon_path=excluded.icon_path,
                        raw_json=excluded.raw_json,
                        is_current=1
                    """,
                    (
                        key,
                        row.table,
                        row.row_id,
                        config_row_name(row),
                        row_name_key(row),
                        row_description(row),
                        row_icon_path(row),
                        json_text(row.values),
                    ),
                )
                connection.execute(
                    "INSERT OR IGNORE INTO completion(entry_key, completed, updated_at) VALUES (?, 0, ?)",
                    (key, imported_at),
                )

            connection.executemany(
                "INSERT INTO codex_entry_categories(entry_key, category, sort_order) VALUES (?, ?, ?)",
                memberships,
            )
            connection.executemany(
                """
                INSERT INTO entry_relations(
                    source_entry_key, relation_type, target_table, target_id,
                    target_name, ordinal, raw_value
                ) VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                relations,
            )

            auxiliary_rows = []
            for table_name, _title in AUXILIARY_TABLES:
                for row in context.tables[table_name]:
                    auxiliary_rows.append(
                        (table_name, row.row_id, config_row_name(row), json_text(row.values))
                    )
            connection.executemany(
                "INSERT INTO auxiliary_rows(table_name, row_id, name, raw_json) VALUES (?, ?, ?, ?)",
                auxiliary_rows,
            )

            metadata = {
                "database_schema_version": str(DATABASE_SCHEMA_VERSION),
                "game_version": context.package_version,
                "bundle_name": context.bundle_name,
                "bundle_file": context.bundle_path.name,
                "imported_at": imported_at,
                "main_entry_count": str(len(entries)),
                "category_mapping_count": str(len(memberships)),
            }
            connection.executemany(
                """
                INSERT INTO metadata(key, value) VALUES (?, ?)
                ON CONFLICT(key) DO UPDATE SET value=excluded.value
                """,
                metadata.items(),
            )

        return {
            "entries": len(entries),
            "category_mappings": len(memberships),
            "relations": len(relations),
            "auxiliary_rows": sum(len(context.tables[name]) for name, _title in AUXILIARY_TABLES),
            **{
                category: len(rows)
                for category, rows in category_rows(context).items()
            },
        }
    finally:
        connection.close()


def open_database(database_path: Path) -> sqlite3.Connection:
    if not database_path.exists():
        raise FileNotFoundError(f"找不到图鉴数据库：{database_path}")
    connection = sqlite3.connect(str(database_path), timeout=30)
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA foreign_keys = ON")
    try:
        initialize_database(connection)
    except Exception:
        connection.close()
        raise
    return connection


def get_metadata(connection: sqlite3.Connection) -> dict[str, str]:
    return {
        row["key"]: row["value"]
        for row in connection.execute("SELECT key, value FROM metadata")
    }


def get_category_summaries(connection: sqlite3.Connection) -> list[dict[str, Any]]:
    rows = connection.execute(
        """
        SELECT c.category, c.label,
               COUNT(DISTINCT e.entry_key) AS total,
               COUNT(DISTINCT CASE WHEN co.completed = 1 THEN e.entry_key END) AS completed
        FROM codex_categories c
        LEFT JOIN codex_entry_categories ec ON ec.category = c.category
        LEFT JOIN codex_entries e ON e.entry_key = ec.entry_key AND e.is_current = 1
        LEFT JOIN completion co ON co.entry_key = e.entry_key
        GROUP BY c.category, c.label, c.sort_order
        ORDER BY c.sort_order
        """
    ).fetchall()
    return [dict(row) for row in rows]


def get_overall_summary(connection: sqlite3.Connection) -> dict[str, int]:
    summaries = get_category_summaries(connection)
    return {
        "total": sum(int(row["total"]) for row in summaries),
        "completed": sum(int(row["completed"]) for row in summaries),
    }


def query_entries(
    connection: sqlite3.Connection,
    category: str,
    search: str = "",
    completion_filter: str = "all",
    limit: int = 24,
    offset: int = 0,
) -> list[dict[str, Any]]:
    clauses = ["ec.category = ?", "e.is_current = 1"]
    params: list[Any] = [category]
    if search.strip():
        clauses.append("(e.name LIKE ? OR e.name_key LIKE ? OR CAST(e.source_id AS TEXT) LIKE ?)")
        pattern = f"%{search.strip()}%"
        params.extend([pattern, pattern, pattern])
    if completion_filter == "completed":
        clauses.append("co.completed = 1")
    elif completion_filter == "pending":
        clauses.append("co.completed = 0")
    if completion_filter not in {"all", "completed", "pending"}:
        raise ValueError(f"未知完成状态筛选：{completion_filter}")
    params.extend([max(1, min(limit, 100)), max(0, offset)])
    rows = connection.execute(
        f"""
        SELECT e.entry_key, e.source_table, e.source_id, e.name, e.name_key,
               e.description, e.icon_path, e.raw_json, co.completed
        FROM codex_entry_categories ec
        JOIN codex_entries e ON e.entry_key = ec.entry_key
        JOIN completion co ON co.entry_key = e.entry_key
        WHERE {' AND '.join(clauses)}
        ORDER BY e.name COLLATE NOCASE, e.source_id
        LIMIT ? OFFSET ?
        """,
        params,
    ).fetchall()
    return [dict(row) for row in rows]


def count_entries(
    connection: sqlite3.Connection,
    category: str,
    search: str = "",
    completion_filter: str = "all",
) -> int:
    rows = query_entries(connection, category, search, completion_filter, limit=100, offset=0)
    if len(rows) < 100:
        return len(rows)
    clauses = ["ec.category = ?", "e.is_current = 1"]
    params: list[Any] = [category]
    if search.strip():
        clauses.append("(e.name LIKE ? OR e.name_key LIKE ? OR CAST(e.source_id AS TEXT) LIKE ?)")
        pattern = f"%{search.strip()}%"
        params.extend([pattern, pattern, pattern])
    if completion_filter == "completed":
        clauses.append("co.completed = 1")
    elif completion_filter == "pending":
        clauses.append("co.completed = 0")
    elif completion_filter != "all":
        raise ValueError(f"未知完成状态筛选：{completion_filter}")
    row = connection.execute(
        f"""
        SELECT COUNT(*)
        FROM codex_entry_categories ec
        JOIN codex_entries e ON e.entry_key = ec.entry_key
        JOIN completion co ON co.entry_key = e.entry_key
        WHERE {' AND '.join(clauses)}
        """,
        params,
    ).fetchone()
    return int(row[0])


def get_entry(connection: sqlite3.Connection, entry_key: str) -> dict[str, Any] | None:
    row = connection.execute(
        """
        SELECT e.entry_key, e.source_table, e.source_id, e.name, e.name_key,
               e.description, e.icon_path, e.raw_json, e.is_current, co.completed
        FROM codex_entries e
        JOIN completion co ON co.entry_key = e.entry_key
        WHERE e.entry_key = ?
        """,
        (entry_key,),
    ).fetchone()
    return dict(row) if row else None


def get_entry_relations(connection: sqlite3.Connection, entry_key: str) -> list[dict[str, Any]]:
    rows = connection.execute(
        """
        SELECT relation_type, target_table, target_id, target_name, ordinal, raw_value
        FROM entry_relations
        WHERE source_entry_key = ?
        ORDER BY relation_type, ordinal
        """,
        (entry_key,),
    ).fetchall()
    return [dict(row) for row in rows]


def set_completion(connection: sqlite3.Connection, entry_key: str, completed: bool) -> None:
    with connection:
        cursor = connection.execute(
            "UPDATE completion SET completed = ?, updated_at = ? WHERE entry_key = ?",
            (1 if completed else 0, utc_now(), entry_key),
        )
    if cursor.rowcount != 1:
        raise KeyError(f"找不到图鉴条目完成状态：{entry_key}")


def main() -> int:
    parser = argparse.ArgumentParser(description="构建 Survival Log 图鉴 SQLite 数据库")
    parser.add_argument(
        "--game-root",
        type=Path,
        default=Path(r"G:\SteamLibrary\steamapps\common\Survival Log"),
        help="游戏安装目录",
    )
    parser.add_argument(
        "--database",
        type=Path,
        default=Path(__file__).resolve().parent / "SurvivalLog图鉴.sqlite3",
        help="SQLite 数据库路径",
    )
    args = parser.parse_args()
    try:
        counts = build_database(args.game_root, args.database)
        print(f"数据库：{args.database}")
        for category in CATEGORY_ORDER:
            print(f"{CATEGORY_LABELS[category]}：{counts[category]} 条")
        print(
            f"主条目：{counts['entries']}，分类映射：{counts['category_mappings']}，"
            f"关联：{counts['relations']}，辅助配置：{counts['auxiliary_rows']}"
        )
        print("数据库构建完成")
    except Exception as exc:
        print(f"数据库构建失败：{exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
