#!/usr/bin/env python3
"""Build and query the offline Survival Log codex SQLite database."""

from __future__ import annotations

import argparse
import json
import os
import sqlite3
import sys
import tempfile
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

from codex_parser import (
    AUXILIARY_TABLES,
    ConfigRow,
    ExtractionContext,
    config_row_name,
    build_extraction_context,
    resolve_default_game_root,
    select_category_rows,
)
from codex_achievements import (
    CONDITION_SCHEMA_VERSION,
    AchievementConditionError,
    load_achievement_conditions,
    validate_achievement_conditions,
)
from codex_recipe import (
    RecipeConfigError,
    load_recipe_static_data,
    populate_recipe_tables,
    storage_furniture_specs_from_rows,
)
from codex_save import (
    CODEX_CATEGORY_SOURCE_TABLES,
    SaveParseError,
    build_save_diagnostic,
    default_save_file,
    read_codex_save,
    write_save_diagnostic,
)


if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")
if hasattr(sys.stderr, "reconfigure"):
    sys.stderr.reconfigure(encoding="utf-8")


DATABASE_SCHEMA_VERSION = 9
RUNTIME_SCHEMA_VERSION = 2
PROJECT_DIR = Path(__file__).resolve().parent
DATA_DIR = PROJECT_DIR / "data"
DEFAULT_DATABASE_PATH = PROJECT_DIR / "survival_log_codex.sqlite3"
DEFAULT_RUNTIME_DATABASE_PATH = PROJECT_DIR / "survival_log_codex_runtime.sqlite3"
LEGACY_DATABASE_PATH = DATA_DIR / "survival_log_codex.sqlite3"
CATEGORY_LABELS = {
    "food": "食品",
    "dish": "菜肴",
    "plant": "植物",
    "prey": "猎物",
    "craft": "制造",
    "furniture": "家具",
}
CATEGORY_ORDER = tuple(CATEGORY_LABELS)
STATIC_TABLES = (
    "metadata",
    "codex_categories",
    "codex_entries",
    "codex_entry_categories",
    "entry_relations",
    "auxiliary_rows",
    "recipe_items",
    "recipe_tier_rules",
    "storage_furniture",
    "achievements",
)
RUNTIME_TABLES = (
    "metadata",
    "completion",
    "category_completion",
    "achievement_completion",
    "runtime_cache",
)


def _sqlite_integrity_ok(database_path: Path) -> bool:
    """Return whether a copied SQLite file passes a read-only integrity check."""

    try:
        connection = sqlite3.connect(str(database_path), timeout=2)
    except sqlite3.Error:
        return False
    try:
        row = connection.execute("PRAGMA integrity_check").fetchone()
        return bool(row and row[0] == "ok")
    except sqlite3.Error:
        return False
    finally:
        connection.close()


def _schema_table(schema: str, table: str) -> str:
    return table if schema == "main" else f"{schema}.{table}"


def _database_schemas(connection: sqlite3.Connection) -> set[str]:
    return {str(row[1]) for row in connection.execute("PRAGMA database_list")}


def _runtime_schema(connection: sqlite3.Connection) -> str:
    return "runtime" if "runtime" in _database_schemas(connection) else "main"


def _sqlite_table_names(connection: sqlite3.Connection) -> set[str]:
    return {
        str(row[0])
        for row in connection.execute(
            "SELECT name FROM sqlite_master WHERE type = 'table'"
        )
    }


def _runtime_schema_sql(schema: str = "main") -> str:
    prefix = "" if schema == "main" else f"{schema}."
    return f"""
CREATE TABLE IF NOT EXISTS {prefix}metadata (
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS {prefix}completion (
    entry_key TEXT PRIMARY KEY,
    completed INTEGER NOT NULL DEFAULT 0 CHECK (completed IN (0, 1)),
    updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS {prefix}category_completion (
    entry_key TEXT NOT NULL,
    category TEXT NOT NULL,
    completed INTEGER NOT NULL DEFAULT 0 CHECK (completed IN (0, 1)),
    updated_at TEXT NOT NULL,
    PRIMARY KEY (entry_key, category)
);

CREATE TABLE IF NOT EXISTS {prefix}achievement_completion (
    achievement_id INTEGER PRIMARY KEY,
    completed INTEGER NOT NULL DEFAULT 0 CHECK (completed IN (0, 1)),
    updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS {prefix}runtime_cache (
    cache_key TEXT PRIMARY KEY,
    signature TEXT NOT NULL,
    value_json TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS {prefix}idx_category_completion_category
    ON category_completion(category, completed);
CREATE INDEX IF NOT EXISTS {prefix}idx_achievement_completion_completed
    ON achievement_completion(completed);
"""


def _copy_legacy_runtime_rows(
    legacy: sqlite3.Connection,
    runtime: sqlite3.Connection,
    legacy_tables: set[str],
) -> None:
    if "completion" in legacy_tables:
        runtime.executemany(
            "INSERT OR REPLACE INTO completion(entry_key, completed, updated_at) VALUES (?, ?, ?)",
            legacy.execute(
                "SELECT entry_key, completed, updated_at FROM completion"
            ).fetchall(),
        )
    if "category_completion" in legacy_tables:
        runtime.executemany(
            """
            INSERT OR REPLACE INTO category_completion(
                entry_key, category, completed, updated_at
            ) VALUES (?, ?, ?, ?)
            """,
            legacy.execute(
                "SELECT entry_key, category, completed, updated_at FROM category_completion"
            ).fetchall(),
        )
    if "achievement_completion" in legacy_tables:
        try:
            runtime.executemany(
                """
                INSERT OR REPLACE INTO achievement_completion(
                    achievement_id, completed, updated_at
                ) VALUES (?, ?, ?)
                """,
                legacy.execute(
                    "SELECT achievement_id, completed, updated_at FROM achievement_completion"
                ).fetchall(),
            )
        except sqlite3.OperationalError:
            pass
    if "runtime_cache" in legacy_tables:
        try:
            runtime.executemany(
                """
                INSERT OR REPLACE INTO runtime_cache(
                    cache_key, signature, value_json, updated_at
                ) VALUES (?, ?, ?, ?)
                """,
                legacy.execute(
                    "SELECT cache_key, signature, value_json, updated_at FROM runtime_cache"
                ).fetchall(),
            )
        except sqlite3.OperationalError:
            pass
    if "metadata" in legacy_tables:
        runtime.executemany(
            """
            INSERT INTO metadata(key, value) VALUES (?, ?)
            ON CONFLICT(key) DO UPDATE SET value=excluded.value
            """,
            legacy.execute(
                "SELECT key, value FROM metadata WHERE key LIKE 'save_%'"
            ).fetchall(),
        )


def _split_legacy_database(
    legacy_database: Path,
    static_database: Path,
    runtime_database: Path,
) -> None:
    """Split a validated v6 combined database into static and runtime files."""

    legacy_database = legacy_database.expanduser().resolve()
    static_database = static_database.expanduser().resolve()
    runtime_database = runtime_database.expanduser().resolve()
    if len({legacy_database, static_database, runtime_database}) != 3:
        raise ValueError("旧数据库、静态库和 runtime 库必须是三个不同的文件")
    if static_database.exists() or runtime_database.exists():
        raise FileExistsError("静态库或 runtime 库已存在，拒绝覆盖")
    sidecars = (
        Path(f"{legacy_database}-wal"),
        Path(f"{legacy_database}-shm"),
    )
    if any(path.exists() for path in sidecars):
        raise RuntimeError("旧数据库存在 SQLite WAL/SHM 旁车文件，请先关闭正在使用它的程序")
    if not _sqlite_integrity_ok(legacy_database):
        raise sqlite3.DatabaseError("旧数据库完整性检查失败")

    static_database.parent.mkdir(parents=True, exist_ok=True)
    runtime_database.parent.mkdir(parents=True, exist_ok=True)
    temp_paths: list[Path] = []
    static_installed = False
    runtime_installed = False
    legacy = sqlite3.connect(str(legacy_database), timeout=30)
    try:
        legacy_tables = _sqlite_table_names(legacy)
        static_fd, static_name = tempfile.mkstemp(
            prefix=f".{static_database.name}.", suffix=".migrating", dir=static_database.parent
        )
        runtime_fd, runtime_name = tempfile.mkstemp(
            prefix=f".{runtime_database.name}.", suffix=".migrating", dir=runtime_database.parent
        )
        os.close(static_fd)
        os.close(runtime_fd)
        static_temp = Path(static_name)
        runtime_temp = Path(runtime_name)
        temp_paths.extend((static_temp, runtime_temp))

        static = sqlite3.connect(str(static_temp), timeout=30)
        runtime = sqlite3.connect(str(runtime_temp), timeout=30)
        try:
            legacy.backup(static)
            static.execute("PRAGMA foreign_keys = ON")
            for table in ("completion", "category_completion", "achievement_completion", "runtime_cache"):
                if table in _sqlite_table_names(static):
                    static.execute(f"DROP TABLE {table}")
            static.execute("DELETE FROM metadata WHERE key LIKE 'save_%'")
            static.execute("DELETE FROM metadata WHERE key = 'runtime_schema_version'")
            static.executescript(STATIC_SCHEMA_SQL)
            _ensure_achievement_columns(static)
            static.execute(
                """
                INSERT INTO metadata(key, value) VALUES ('database_schema_version', ?)
                ON CONFLICT(key) DO UPDATE SET value=excluded.value
                """,
                (str(DATABASE_SCHEMA_VERSION),),
            )
            static.execute(
                """
                INSERT INTO metadata(key, value) VALUES ('database_profile', 'static')
                ON CONFLICT(key) DO UPDATE SET value=excluded.value
                """
            )

            initialize_runtime_database(runtime)
            _copy_legacy_runtime_rows(legacy, runtime, legacy_tables)
            runtime.commit()
            static.commit()
        finally:
            runtime.close()
            static.close()

        if not _sqlite_integrity_ok(static_temp) or not _sqlite_integrity_ok(runtime_temp):
            raise sqlite3.DatabaseError("拆分后的数据库完整性检查失败")
        legacy.close()
        try:
            os.replace(static_temp, static_database)
            static_installed = True
            os.replace(runtime_temp, runtime_database)
            runtime_installed = True
            legacy_database.unlink()
        except Exception:
            if runtime_installed:
                runtime_database.unlink(missing_ok=True)
            if static_installed:
                static_database.unlink(missing_ok=True)
            raise
        temp_paths.clear()
    finally:
        legacy.close()
        for path in temp_paths:
            path.unlink(missing_ok=True)


def resolve_default_database_path() -> Path:
    """Resolve the source static database and migrate the old data file once."""

    if DEFAULT_DATABASE_PATH.is_file():
        return DEFAULT_DATABASE_PATH
    if not LEGACY_DATABASE_PATH.is_file():
        return DEFAULT_DATABASE_PATH
    try:
        _split_legacy_database(
            LEGACY_DATABASE_PATH,
            DEFAULT_DATABASE_PATH,
            DEFAULT_RUNTIME_DATABASE_PATH,
        )
        return DEFAULT_DATABASE_PATH
    except (OSError, sqlite3.Error, RuntimeError) as exc:
        raise RuntimeError(
            f"旧 data 数据库迁移失败，已保留原文件：{exc}"
        ) from exc


def resolve_default_runtime_database_path() -> Path:
    return DEFAULT_RUNTIME_DATABASE_PATH


@dataclass(frozen=True)
class CompletionSyncResult:
    status: str
    changed: bool
    save_path: Path
    category_counts: dict[str, int]
    unknown_ids: dict[str, tuple[int, ...]]
    updated_entries: int
    used_backup: bool
    message: str
    schema_profile: str = ""
    codex_offset: int | None = None
    codex_end_offset: int | None = None
    candidate_count: int = 0
    candidate_score: tuple[int, ...] = ()
    achievement_count: int = 0
    achievement_status_available: bool = False
    unknown_achievement_ids: tuple[int, ...] = ()


STATIC_SCHEMA_SQL = """
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

CREATE TABLE IF NOT EXISTS recipe_items (
    item_id INTEGER PRIMARY KEY,
    name TEXT NOT NULL,
    can_cook INTEGER NOT NULL CHECK (can_cook IN (0, 1)),
    category INTEGER NOT NULL,
    sub_category INTEGER NOT NULL,
    sub_category_name TEXT NOT NULL,
    price REAL NOT NULL,
    raw_json TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS recipe_tier_rules (
    sub_category INTEGER PRIMARY KEY,
    label TEXT NOT NULL,
    high_threshold REAL NOT NULL,
    mid_low_threshold REAL NOT NULL,
    high_source TEXT NOT NULL,
    mid_low_source TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS storage_furniture (
    config_id INTEGER PRIMARY KEY,
    name TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS achievements (
    achievement_id INTEGER PRIMARY KEY,
    sort_order INTEGER NOT NULL,
    name TEXT NOT NULL,
    name_key TEXT NOT NULL,
    description TEXT NOT NULL,
    icon_path TEXT NOT NULL,
    category TEXT NOT NULL,
    is_hidden INTEGER NOT NULL CHECK (is_hidden IN (0, 1)),
    condition_text TEXT NOT NULL,
    method_text TEXT NOT NULL,
    role_restriction TEXT NOT NULL,
    notes_json TEXT NOT NULL,
    common_notes_json TEXT NOT NULL,
    numeric_threshold REAL,
    value_parameters_json TEXT NOT NULL DEFAULT '[]',
    exclusions_json TEXT NOT NULL DEFAULT '[]',
    config_references_json TEXT NOT NULL DEFAULT '[]',
    source_version TEXT NOT NULL,
    raw_json TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_codex_entry_categories_category
    ON codex_entry_categories(category, sort_order);
CREATE INDEX IF NOT EXISTS idx_codex_entries_name
    ON codex_entries(name);
CREATE INDEX IF NOT EXISTS idx_entry_relations_source
    ON entry_relations(source_entry_key);
CREATE INDEX IF NOT EXISTS idx_recipe_items_cookable_category
    ON recipe_items(can_cook, sub_category, price);
CREATE INDEX IF NOT EXISTS idx_storage_furniture_name
    ON storage_furniture(name);
CREATE INDEX IF NOT EXISTS idx_achievements_sort
    ON achievements(sort_order, achievement_id);
CREATE INDEX IF NOT EXISTS idx_achievements_name
    ON achievements(name);
"""

RUNTIME_SCHEMA_SQL = _runtime_schema_sql()
SCHEMA_SQL = STATIC_SCHEMA_SQL + RUNTIME_SCHEMA_SQL


def _ensure_achievement_columns(connection: sqlite3.Connection) -> None:
    """Add condition columns to a v9 database created before their introduction."""

    if "achievements" not in _sqlite_table_names(connection):
        return
    existing = {
        str(row[1]) for row in connection.execute("PRAGMA table_info(achievements)")
    }
    columns = {
        "numeric_threshold": "REAL",
        "value_parameters_json": "TEXT NOT NULL DEFAULT '[]'",
        "exclusions_json": "TEXT NOT NULL DEFAULT '[]'",
        "config_references_json": "TEXT NOT NULL DEFAULT '[]'",
    }
    for name, definition in columns.items():
        if name not in existing:
            connection.execute(f"ALTER TABLE achievements ADD COLUMN {name} {definition}")


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


def collect_entries(
    context: ExtractionContext,
) -> tuple[dict[str, ConfigRow], list[tuple[str, str, int]]]:
    entries: dict[str, ConfigRow] = {}
    memberships: list[tuple[str, str, int]] = []
    rows_by_category = select_category_rows(context)
    for category in CATEGORY_ORDER:
        rows = sorted(rows_by_category[category], key=lambda row: row.row_id)
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
    item_furniture_ids = {
        row.row_id: row.values.get("TargetFurnitureID")
        for row in context.tables.get("Config_Item", [])
        if isinstance(row.values.get("TargetFurnitureID"), int)
        and row.values.get("TargetFurnitureID")
    }
    furniture_productions: dict[int, list[ConfigRow]] = {}
    for production in context.tables.get("Config_ProductionList", []):
        for product_id in production.values.get("ProductID") or []:
            furniture_id = item_furniture_ids.get(product_id)
            if isinstance(furniture_id, int) and furniture_id:
                furniture_productions.setdefault(furniture_id, []).append(production)

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
                add_field(row, field, field, field)
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
                ("BagId", "包裹配置", "Config_Bag"),
                ("ElectricalFurnitureID", "电力配置", "Config_FurnitureElectrical"),
                ("RotProductOverride", "腐烂产物覆盖", "Config_Item"),
            ):
                add_field(row, field, relation_type, table_name)
            for production in furniture_productions.get(row.row_id, []):
                recipe_id = production.row_id
                add(row, "制造配方", "Config_ProductionList", recipe_id, recipe_id, recipe_id)
                materials = production.values.get("MaterialList")
                if isinstance(materials, list):
                    material_type = f"制造材料（配方 ID {recipe_id}）"
                    for ordinal, target_id in enumerate(materials):
                        add(row, material_type, "Config_Item", target_id, ordinal, target_id)
                level = production.values.get("Level")
                if isinstance(level, int):
                    relations.append(
                        (
                            source_key(row.table, row.row_id),
                            f"制造要求等级（配方 ID {recipe_id}）",
                            "Config_ProductionList",
                            level,
                            "无" if not level else f"{level}级",
                            0,
                            json_text(level),
                        )
                    )
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
    """Initialize a standalone database containing static and runtime tables."""

    connection.executescript(STATIC_SCHEMA_SQL)
    _ensure_achievement_columns(connection)
    initialize_runtime_database(connection)
    row = connection.execute(
        "SELECT value FROM metadata WHERE key = 'database_schema_version'"
    ).fetchone()
    if row is not None:
        version = int(row[0])
        if version > DATABASE_SCHEMA_VERSION:
            raise RuntimeError(
                f"数据库 schema 版本过高：{row[0]}，当前工具只支持 {DATABASE_SCHEMA_VERSION}"
            )
        if version < DATABASE_SCHEMA_VERSION:
            connection.execute(
                "UPDATE metadata SET value = ? WHERE key = 'database_schema_version'",
                (str(DATABASE_SCHEMA_VERSION),),
            )
    connection.execute(
        """
        INSERT INTO metadata(key, value) VALUES ('database_profile', 'standalone')
        ON CONFLICT(key) DO UPDATE SET value=excluded.value
        """
    )


def initialize_static_database(connection: sqlite3.Connection) -> None:
    connection.executescript(STATIC_SCHEMA_SQL)
    _ensure_achievement_columns(connection)
    unexpected = sorted(_sqlite_table_names(connection) & set(RUNTIME_TABLES[1:]))
    if unexpected:
        raise RuntimeError(
            f"静态数据库包含运行时表：{', '.join(unexpected)}；请先执行 v6 数据库拆分"
        )
    row = connection.execute(
        "SELECT value FROM metadata WHERE key = 'database_schema_version'"
    ).fetchone()
    if row is not None and int(row[0]) > DATABASE_SCHEMA_VERSION:
        raise RuntimeError(
            f"静态数据库 schema 版本过高：{row[0]}，当前工具只支持 {DATABASE_SCHEMA_VERSION}"
        )
    connection.execute(
        """
        INSERT INTO metadata(key, value) VALUES ('database_schema_version', ?)
        ON CONFLICT(key) DO UPDATE SET value=excluded.value
        """,
        (str(DATABASE_SCHEMA_VERSION),),
    )
    connection.execute(
        """
        INSERT INTO metadata(key, value) VALUES ('database_profile', 'static')
        ON CONFLICT(key) DO UPDATE SET value=excluded.value
        """
    )


def initialize_runtime_database(
    connection: sqlite3.Connection,
    schema: str = "main",
) -> None:
    connection.executescript(_runtime_schema_sql(schema))
    metadata_table = _schema_table(schema, "metadata")
    row = connection.execute(
        f"SELECT value FROM {metadata_table} WHERE key = 'runtime_schema_version'"
    ).fetchone()
    if row is not None and int(row[0]) > RUNTIME_SCHEMA_VERSION:
        raise RuntimeError(
            f"runtime 数据库 schema 版本过高：{row[0]}，当前工具只支持 {RUNTIME_SCHEMA_VERSION}"
        )
    connection.execute(
        f"""
        INSERT INTO {metadata_table}(key, value)
        VALUES ('runtime_schema_version', ?)
        ON CONFLICT(key) DO UPDATE SET value=excluded.value
        """,
        (str(RUNTIME_SCHEMA_VERSION),),
    )


def _validate_static_database(connection: sqlite3.Connection) -> None:
    table_names = _sqlite_table_names(connection)
    unexpected = sorted(table_names & set(RUNTIME_TABLES[1:]))
    if unexpected:
        raise RuntimeError(
            f"静态数据库包含运行时表：{', '.join(unexpected)}；请使用独立版单文件模式或先拆分旧库"
        )
    missing = [table for table in STATIC_TABLES if table != "metadata" and table not in table_names]
    if "metadata" not in table_names:
        missing.append("metadata")
    if missing:
        raise RuntimeError(f"静态数据库缺少表：{', '.join(missing)}")
    row = connection.execute(
        "SELECT value FROM metadata WHERE key = 'database_schema_version'"
    ).fetchone()
    if row is None:
        raise RuntimeError("静态数据库缺少 database_schema_version 元数据")
    version = int(row[0])
    if version > DATABASE_SCHEMA_VERSION:
        raise RuntimeError(
            f"静态数据库 schema 版本过高：{version}，当前工具只支持 {DATABASE_SCHEMA_VERSION}"
        )


def _upsert_metadata(
    connection: sqlite3.Connection,
    values: dict[str, str],
    schema: str = "main",
) -> None:
    metadata_table = _schema_table(schema, "metadata")
    connection.executemany(
        f"""
        INSERT INTO {metadata_table}(key, value) VALUES (?, ?)
        ON CONFLICT(key) DO UPDATE SET value=excluded.value
        """,
        values.items(),
    )


def get_runtime_cache(
    connection: sqlite3.Connection,
    cache_key: str,
    signature: str,
) -> dict[str, Any] | None:
    """Read a JSON cache entry only when its source signature still matches."""

    runtime_schema = _runtime_schema(connection)
    table = _schema_table(runtime_schema, "runtime_cache")
    row = connection.execute(
        f"SELECT signature, value_json FROM {table} WHERE cache_key = ?",
        (cache_key,),
    ).fetchone()
    if row is None or str(row[0]) != signature:
        return None
    try:
        value = json.loads(str(row[1]))
    except (TypeError, ValueError):
        return None
    return value if isinstance(value, dict) else None


def set_runtime_cache(
    connection: sqlite3.Connection,
    cache_key: str,
    signature: str,
    value: dict[str, Any],
) -> None:
    runtime_schema = _runtime_schema(connection)
    table = _schema_table(runtime_schema, "runtime_cache")
    with connection:
        connection.execute(
            f"""
            INSERT INTO {table}(cache_key, signature, value_json, updated_at)
            VALUES (?, ?, ?, ?)
            ON CONFLICT(cache_key) DO UPDATE SET
                signature=excluded.signature,
                value_json=excluded.value_json,
                updated_at=excluded.updated_at
            """,
            (cache_key, signature, json_text(value), utc_now()),
        )


def _current_category_entries(
    connection: sqlite3.Connection,
) -> tuple[dict[str, dict[int, str]], set[str]]:
    category_entries: dict[str, dict[int, str]] = {
        category: {} for category in CATEGORY_ORDER
    }
    current_entry_keys: set[str] = set()
    rows = connection.execute(
        """
        SELECT ec.category, e.entry_key, e.source_table, e.source_id
        FROM codex_entry_categories ec
        JOIN codex_entries e ON e.entry_key = ec.entry_key
        WHERE e.is_current = 1
        """
    ).fetchall()
    for category, entry_key, source_table, source_id in rows:
        expected_table = CODEX_CATEGORY_SOURCE_TABLES.get(category)
        if expected_table is None:
            raise RuntimeError(f"数据库包含未知图鉴分类：{category}")
        if source_table != expected_table:
            raise RuntimeError(
                f"图鉴分类映射 schema 不匹配：{category} 应使用 {expected_table}，实际为 {source_table}"
            )
        if source_id in category_entries[category] and category_entries[category][source_id] != entry_key:
            raise RuntimeError(f"图鉴分类 {category} 出现重复源 ID：{source_id}")
        category_entries[category][source_id] = entry_key
        current_entry_keys.add(entry_key)
    return category_entries, current_entry_keys


def _current_achievement_ids(connection: sqlite3.Connection) -> set[int]:
    return {
        int(row[0])
        for row in connection.execute(
            "SELECT achievement_id FROM achievements"
        ).fetchall()
    }


def sync_game_completion(
    connection: sqlite3.Connection,
    save_file: Path | None = None,
    *,
    force: bool = False,
    log_path: Path | None = None,
) -> CompletionSyncResult:
    """Synchronize completion.completed from the read-only HistorySave file."""

    requested_path = Path(save_file or default_save_file()).expanduser()
    runtime_schema = _runtime_schema(connection)
    completion_table = _schema_table(runtime_schema, "completion")
    category_completion_table = _schema_table(runtime_schema, "category_completion")
    achievement_completion_table = _schema_table(runtime_schema, "achievement_completion")
    category_entries, current_entry_keys = _current_category_entries(connection)
    current_achievement_ids = _current_achievement_ids(connection)
    known_category_ids = {
        category: set(source_ids)
        for category, source_ids in category_entries.items()
    }
    try:
        state = read_codex_save(
            requested_path,
            known_category_ids=known_category_ids,
        )
    except (OSError, SaveParseError) as exc:
        message = str(exc)
        write_save_diagnostic(
            log_path,
            build_save_diagnostic(requested_path, status="error", error=exc),
        )
        existing = get_metadata(connection)
        if (
            existing.get("save_sync_status") != "error"
            or existing.get("save_sync_error") != message
        ):
            with connection:
                _upsert_metadata(
                    connection,
                    {
                        "save_requested_path": str(requested_path.resolve()),
                        "save_sync_status": "error",
                        "save_sync_error": message,
                        "save_last_attempt_at": utc_now(),
                    },
                    runtime_schema,
                )
        return CompletionSyncResult(
            status="error",
            changed=False,
            save_path=requested_path,
            category_counts={},
            unknown_ids={},
            updated_entries=0,
            used_backup=False,
            message=message,
        )

    metadata = get_metadata(connection)
    unknown_achievement_ids = tuple(
        sorted(achievement_id for achievement_id in state.achievement_ids
               if achievement_id not in current_achievement_ids)
    ) if state.achievement_status_available else ()
    desired_achievement_ids = (
        set(state.achievement_ids) & current_achievement_ids
        if state.achievement_status_available else set()
    )
    category_completion_rows = int(
        connection.execute(f"SELECT COUNT(*) FROM {category_completion_table}").fetchone()[0]
    )
    expected_category_completion_rows = int(
        connection.execute(
            """
            SELECT COUNT(*)
            FROM codex_entry_categories ec
            JOIN codex_entries e ON e.entry_key = ec.entry_key
            WHERE e.is_current = 1
            """
        ).fetchone()[0]
    )
    achievement_completion_rows = int(
        connection.execute(f"SELECT COUNT(*) FROM {achievement_completion_table}").fetchone()[0]
    )
    expected_achievement_completion_rows = len(current_achievement_ids)
    achievement_cache_valid = (
        achievement_completion_rows == expected_achievement_completion_rows
        and metadata.get("save_achievement_status_available", "0")
        == ("1" if state.achievement_status_available else "0")
    )
    if (
        not force
        and metadata.get("save_sha256") == state.file_info.sha256
        and metadata.get("save_path") == str(state.file_info.path)
        and metadata.get("save_sync_status") in {"ok", "fallback"}
        and metadata.get("save_schema_profile") == state.schema_profile
        and metadata.get("save_codex_offset") == str(state.codex_offset)
        and metadata.get("save_codex_end_offset") == str(state.codex_end_offset)
        and metadata.get("save_candidate_count") == str(state.candidate_count)
        and metadata.get("save_candidate_score") == json_text(list(state.candidate_score))
        and category_completion_rows == expected_category_completion_rows
        and achievement_cache_valid
    ):
        write_save_diagnostic(
            log_path,
            build_save_diagnostic(
                requested_path,
                status=metadata.get("save_sync_status", "ok"),
                state=state,
            ),
        )
        return CompletionSyncResult(
            status=metadata.get("save_sync_status", "ok"),
            changed=False,
            save_path=state.file_info.path,
            category_counts=state.category_counts,
            unknown_ids={},
            updated_entries=0,
            used_backup=state.file_info.used_backup,
            message="存档未变化，完成状态无需更新",
            schema_profile=state.schema_profile,
            codex_offset=state.codex_offset,
            codex_end_offset=state.codex_end_offset,
            candidate_count=state.candidate_count,
            candidate_score=state.candidate_score,
            achievement_count=len(desired_achievement_ids),
            achievement_status_available=state.achievement_status_available,
            unknown_achievement_ids=unknown_achievement_ids,
        )

    current_category_pairs: set[tuple[str, str]] = set()
    desired_entry_keys: set[str] = set()
    desired_category_keys: dict[str, set[str]] = {
        category: set() for category in CATEGORY_ORDER
    }
    unknown_ids: dict[str, tuple[int, ...]] = {}
    for category in CATEGORY_ORDER:
        source_ids = state.category_ids.get(category, ())
        known_ids = category_entries[category]
        unknown = tuple(sorted(source_id for source_id in source_ids if source_id not in known_ids))
        if unknown:
            unknown_ids[category] = unknown
        desired_category_keys[category].update(
            known_ids[source_id] for source_id in source_ids if source_id in known_ids
        )
        desired_entry_keys.update(desired_category_keys[category])
        current_category_pairs.update(
            (entry_key, category) for entry_key in known_ids.values()
        )

    now = utc_now()
    updated_entries = 0
    with connection:
        connection.executemany(
            f"""
            INSERT OR IGNORE INTO {completion_table}(entry_key, completed, updated_at)
            VALUES (?, 0, ?)
            """,
            ((entry_key, now) for entry_key in sorted(current_entry_keys)),
        )
        connection.executemany(
            f"""
            INSERT OR IGNORE INTO {category_completion_table}(
                entry_key, category, completed, updated_at
            ) VALUES (?, ?, 0, ?)
            """,
            ((entry_key, category, now) for entry_key, category in current_category_pairs),
        )
        connection.execute(
            f"""
            DELETE FROM {achievement_completion_table}
            WHERE achievement_id NOT IN (
                SELECT achievement_id FROM achievements
            )
            """
        )
        connection.executemany(
            f"""
            INSERT OR IGNORE INTO {achievement_completion_table}(
                achievement_id, completed, updated_at
            ) VALUES (?, 0, ?)
            """,
            ((achievement_id, now) for achievement_id in sorted(current_achievement_ids)),
        )
        if state.achievement_status_available:
            cursor = connection.execute(
                f"""
                UPDATE {achievement_completion_table}
                SET completed = 0, updated_at = ?
                WHERE achievement_id IN (
                    SELECT achievement_id FROM achievements
                ) AND completed <> 0
                """,
                (now,),
            )
            updated_entries += max(0, cursor.rowcount)
            if desired_achievement_ids:
                placeholders = ",".join("?" for _ in desired_achievement_ids)
                cursor = connection.execute(
                    f"""
                    UPDATE {achievement_completion_table}
                    SET completed = 1, updated_at = ?
                    WHERE achievement_id IN ({placeholders}) AND completed <> 1
                    """,
                    (now, *sorted(desired_achievement_ids)),
                )
                updated_entries += max(0, cursor.rowcount)
        for category in CATEGORY_ORDER:
            cursor = connection.execute(
                f"""
                UPDATE {category_completion_table}
                SET completed = 0, updated_at = ?
                WHERE category = ? AND entry_key IN (
                    SELECT ec.entry_key
                    FROM codex_entry_categories ec
                    JOIN codex_entries e ON e.entry_key = ec.entry_key
                    WHERE ec.category = ? AND e.is_current = 1
                ) AND completed <> 0
                """,
                (now, category, category),
            )
            updated_entries += max(0, cursor.rowcount)
            category_keys = desired_category_keys[category]
            if category_keys:
                placeholders = ",".join("?" for _ in category_keys)
                cursor = connection.execute(
                    f"""
                    UPDATE {category_completion_table}
                    SET completed = 1, updated_at = ?
                    WHERE category = ? AND entry_key IN ({placeholders}) AND completed <> 1
                    """,
                    (now, category, *sorted(category_keys)),
                )
                updated_entries += max(0, cursor.rowcount)
        if current_entry_keys:
            cursor = connection.execute(
                f"""
                UPDATE {completion_table}
                SET completed = 0, updated_at = ?
                WHERE entry_key IN (
                    SELECT entry_key FROM codex_entries WHERE is_current = 1
                ) AND completed <> 0
                """,
                (now,),
            )
            updated_entries += max(0, cursor.rowcount)
        if desired_entry_keys:
            placeholders = ",".join("?" for _ in desired_entry_keys)
            cursor = connection.execute(
                f"""
                UPDATE {completion_table}
                SET completed = 1, updated_at = ?
                WHERE entry_key IN ({placeholders}) AND completed <> 1
                """,
                (now, *sorted(desired_entry_keys)),
            )
            updated_entries += max(0, cursor.rowcount)

        status = "fallback" if state.file_info.used_backup else "ok"
        _upsert_metadata(
            connection,
            {
                "save_requested_path": str(requested_path.resolve()),
                "save_path": str(state.file_info.path),
                "save_sha256": state.file_info.sha256,
                "save_size": str(state.file_info.size),
                "save_mtime_ns": str(state.file_info.mtime_ns),
                "save_read_at": state.file_info.read_at,
                "save_sync_status": status,
                "save_sync_error": "",
                "save_category_counts": json_text(state.category_counts),
                "save_total_memberships": str(state.total_memberships),
                "save_unknown_ids": json_text(unknown_ids),
                "save_achievement_count": str(len(desired_achievement_ids)),
                "save_achievement_status_available": (
                    "1" if state.achievement_status_available else "0"
                ),
                "save_unknown_achievement_ids": json_text(unknown_achievement_ids),
                "save_schema_profile": state.schema_profile,
                "save_codex_offset": str(state.codex_offset),
                "save_codex_end_offset": str(state.codex_end_offset),
                "save_candidate_count": str(state.candidate_count),
                "save_candidate_score": json_text(list(state.candidate_score)),
            },
            runtime_schema,
        )

    write_save_diagnostic(
        log_path,
        build_save_diagnostic(
            requested_path,
            status=status,
            state=state,
        ),
    )
    message = (
        f"已同步游戏存档：{state.total_memberships} 个分类完成状态"
        + ("（使用 .bak 备份）" if state.file_info.used_backup else "")
    )
    if state.achievement_status_available:
        message += (
            f"；成就完成 {len(desired_achievement_ids)}/{len(current_achievement_ids)}"
        )
    else:
        message += "；成就状态不可用，保留上一次有效状态"
    if unknown_ids:
        message += f"；未匹配源 ID：{sum(len(values) for values in unknown_ids.values())} 个"
    if unknown_achievement_ids:
        message += f"；未匹配成就 ID：{len(unknown_achievement_ids)} 个"
    return CompletionSyncResult(
        status=status,
        changed=True,
        save_path=state.file_info.path,
        category_counts=state.category_counts,
        unknown_ids=unknown_ids,
        updated_entries=updated_entries,
        used_backup=state.file_info.used_backup,
        message=message,
        schema_profile=state.schema_profile,
        codex_offset=state.codex_offset,
        codex_end_offset=state.codex_end_offset,
        candidate_count=state.candidate_count,
        candidate_score=state.candidate_score,
        achievement_count=len(desired_achievement_ids),
        achievement_status_available=state.achievement_status_available,
        unknown_achievement_ids=unknown_achievement_ids,
    )


def build_database(
    game_root: Path,
    database_path: Path,
    save_file: Path | None = None,
    *,
    sync_save: bool = True,
    runtime_database_path: Path | None = None,
    single_file: bool = False,
    refresh_achievements: bool = True,
) -> dict[str, Any]:
    game_root = game_root.expanduser().resolve()
    database_path = database_path.expanduser().resolve()
    if runtime_database_path is not None:
        runtime_database_path = runtime_database_path.expanduser().resolve()
    if single_file and runtime_database_path is not None:
        raise ValueError("独立版单文件模式不能同时指定 runtime 数据库")
    ensure_database_outside_game_root(game_root, database_path)
    if runtime_database_path is not None:
        ensure_database_outside_game_root(game_root, runtime_database_path)
    context = build_extraction_context(
        game_root,
        include_achievement=refresh_achievements,
    )
    achievement_rows = list(context.tables.get("Config_Achievement", ()))
    achievement_condition_version = ""
    achievement_conditions = {}
    if refresh_achievements:
        try:
            achievement_condition_version, _common_notes, achievement_conditions = (
                load_achievement_conditions()
            )
            validate_achievement_conditions(
                achievement_rows,
                context.package_version,
                achievement_conditions,
                achievement_condition_version,
            )
        except AchievementConditionError:
            raise
    recipe_items, recipe_specs, tier_rules = load_recipe_static_data(game_root, context)
    storage_furniture = storage_furniture_specs_from_rows(
        context.tables.get("Config_Furniture", ())
    )
    if not recipe_specs:
        raise RecipeConfigError(
            "Config_CookingRecipe 未解析到任何菜谱配置"
        )
    entries, memberships = collect_entries(context)
    relations = build_relations(context, entries)
    database_path.parent.mkdir(parents=True, exist_ok=True)
    if runtime_database_path is not None:
        runtime_database_path.parent.mkdir(parents=True, exist_ok=True)

    connection = sqlite3.connect(str(database_path), timeout=30)
    save_sync: CompletionSyncResult | None = None
    try:
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys = ON")
        if single_file:
            initialize_database(connection)
        else:
            initialize_static_database(connection)
        imported_at = utc_now()
        with connection:
            connection.execute("UPDATE codex_entries SET is_current = 0")
            connection.execute("DELETE FROM codex_entry_categories")
            connection.execute("DELETE FROM entry_relations")
            connection.execute("DELETE FROM auxiliary_rows")
            connection.execute("DELETE FROM recipe_items")
            connection.execute("DELETE FROM recipe_tier_rules")
            connection.execute("DELETE FROM storage_furniture")
            if refresh_achievements:
                connection.execute("DELETE FROM achievements")

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
                if single_file:
                    connection.execute(
                        "INSERT OR IGNORE INTO completion(entry_key, completed, updated_at) VALUES (?, 0, ?)",
                        (key, imported_at),
                    )

            connection.executemany(
                "INSERT INTO codex_entry_categories(entry_key, category, sort_order) VALUES (?, ?, ?)",
                memberships,
            )
            if single_file:
                connection.executemany(
                    """
                    INSERT OR IGNORE INTO category_completion(
                        entry_key, category, completed, updated_at
                    ) VALUES (?, ?, 0, ?)
                    """,
                    ((entry_key, category, imported_at) for entry_key, category, _ in memberships),
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
            recipe_table_counts = populate_recipe_tables(
                connection,
                items=recipe_items,
                rules=tier_rules,
                storage_furniture=storage_furniture,
            )

            achievement_insert_rows = []
            if refresh_achievements:
                for row in sorted(
                    achievement_rows,
                    key=lambda item: (int(item.values.get("Order") or 0), item.row_id),
                ):
                    condition = achievement_conditions[row.row_id]
                    achievement_insert_rows.append(
                        (
                            row.row_id,
                            int(row.values.get("Order") or 0),
                            config_row_name(row),
                            row_name_key(row),
                            row_description(row),
                            row_icon_path(row),
                            condition.category,
                            int(bool(row.values.get("IsHidden", False))),
                            condition.condition,
                            condition.method,
                            condition.role_restriction,
                            json_text(list(condition.notes)),
                            json_text(list(condition.common_notes)),
                            condition.numeric_threshold,
                            json_text(list(condition.value_parameters)),
                            json_text(list(condition.exclusions)),
                            json_text(list(condition.config_references)),
                            achievement_condition_version,
                            json_text(row.values),
                        )
                    )
                connection.executemany(
                    """
                    INSERT INTO achievements(
                        achievement_id, sort_order, name, name_key, description, icon_path,
                        category, is_hidden, condition_text, method_text, role_restriction,
                        notes_json, common_notes_json, numeric_threshold, value_parameters_json,
                        exclusions_json, config_references_json, source_version, raw_json
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    achievement_insert_rows,
                )
                if single_file:
                    connection.executemany(
                        """
                        INSERT OR IGNORE INTO achievement_completion(
                            achievement_id, completed, updated_at
                        ) VALUES (?, 0, ?)
                        """,
                        ((row[0], imported_at) for row in achievement_insert_rows),
                    )

            achievement_count = int(
                connection.execute("SELECT COUNT(*) FROM achievements").fetchone()[0]
            )

            metadata = {
                "database_schema_version": str(DATABASE_SCHEMA_VERSION),
                "game_version": context.package_version,
                "bundle_name": context.bundle_name,
                "bundle_file": context.bundle_path.name,
                "imported_at": imported_at,
                "main_entry_count": str(len(entries)),
                "category_mapping_count": str(len(memberships)),
                "recipe_item_count": str(recipe_table_counts["recipe_items"]),
                "recipe_count": str(len(recipe_specs)),
                "recipe_tier_rule_count": str(recipe_table_counts["recipe_tier_rules"]),
                "storage_furniture_count": str(recipe_table_counts["storage_furniture"]),
                "database_profile": "standalone" if single_file else "static",
            }
            if refresh_achievements:
                metadata.update(
                    {
                        "achievement_count": str(achievement_count),
                        "achievement_condition_version": achievement_condition_version,
                        "achievement_condition_schema_version": str(CONDITION_SCHEMA_VERSION),
                    }
                )
            _upsert_metadata(connection, metadata)

        if sync_save and single_file:
            save_sync = sync_game_completion(
                connection,
                save_file or default_save_file(),
                force=True,
                log_path=None,
            )
            if save_sync.status == "error":
                raise RuntimeError(save_sync.message)

    finally:
        connection.close()

    if sync_save and not single_file:
        runtime_path = runtime_database_path or DEFAULT_RUNTIME_DATABASE_PATH
        ensure_database_outside_game_root(game_root, runtime_path)
        runtime_connection = open_database(
            database_path,
            runtime_path,
            check_same_thread=False,
        )
        try:
            save_sync = sync_game_completion(
                runtime_connection,
                save_file or default_save_file(),
                force=True,
                log_path=None,
            )
            if save_sync.status == "error":
                raise RuntimeError(save_sync.message)
        finally:
            runtime_connection.close()

    selected_rows = select_category_rows(context)
    return {
        "entries": len(entries),
        "category_mappings": len(memberships),
        "relations": len(relations),
        "auxiliary_rows": sum(len(context.tables[name]) for name, _title in AUXILIARY_TABLES),
        "recipe_items": len(recipe_items),
        "recipe_count": len(recipe_specs),
        "recipe_tier_rules": len(tier_rules),
        "achievements": achievement_count,
        **{category: len(rows) for category, rows in selected_rows.items()},
        "save_sync": save_sync,
    }


def prepare_packaged_database(source_path: Path, destination_path: Path) -> Path:
    """Create a standalone package database with empty runtime state."""

    source = source_path.expanduser().resolve()
    destination = destination_path.expanduser().resolve()
    if not source.is_file():
        raise FileNotFoundError(f"找不到待打包数据库：{source}")
    if source == destination:
        raise ValueError("打包数据库的源文件和目标文件不能相同")
    destination.parent.mkdir(parents=True, exist_ok=True)
    if not _sqlite_integrity_ok(source):
        raise sqlite3.DatabaseError(f"待打包数据库完整性检查失败：{source}")

    temp_fd, temp_name = tempfile.mkstemp(
        prefix=f".{destination.name}.", suffix=".packaging", dir=destination.parent
    )
    os.close(temp_fd)
    temp_path = Path(temp_name)
    source_connection = sqlite3.connect(
        source.as_uri() + "?mode=ro",
        uri=True,
        timeout=30,
    )
    connection = sqlite3.connect(str(temp_path), timeout=30)
    try:
        source_connection.backup(connection)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys = ON")
        initialize_database(connection)
        with connection:
            for table in ("completion", "category_completion", "achievement_completion", "runtime_cache"):
                connection.execute(f"DELETE FROM {table}")
            connection.execute("DELETE FROM metadata WHERE key GLOB 'save_*'")
            connection.execute(
                """
                INSERT INTO metadata(key, value) VALUES ('database_profile', 'standalone')
                ON CONFLICT(key) DO UPDATE SET value=excluded.value
                """
            )
        if not _sqlite_integrity_ok(temp_path):
            raise sqlite3.DatabaseError("生成的独立版数据库完整性检查失败")
    finally:
        source_connection.close()
        connection.close()
    try:
        os.replace(temp_path, destination)
    finally:
        temp_path.unlink(missing_ok=True)
    return destination


def open_database(
    database_path: Path,
    runtime_database_path: Path | None = None,
    *,
    check_same_thread: bool = True,
) -> sqlite3.Connection:
    database_path = database_path.expanduser().resolve()
    if not database_path.exists():
        raise FileNotFoundError(f"找不到图鉴数据库：{database_path}")

    if runtime_database_path is None:
        connection = sqlite3.connect(
            str(database_path),
            timeout=30,
            check_same_thread=check_same_thread,
        )
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys = ON")
        try:
            initialize_database(connection)
            connection.commit()
        except Exception:
            connection.close()
            raise
        return connection

    runtime_database_path = runtime_database_path.expanduser().resolve()
    if database_path == runtime_database_path:
        raise ValueError("静态数据库和 runtime 数据库不能是同一个文件")
    runtime_database_path.parent.mkdir(parents=True, exist_ok=True)
    connection = sqlite3.connect(
        database_path.as_uri() + "?mode=ro",
        uri=True,
        timeout=30,
        check_same_thread=check_same_thread,
    )
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA foreign_keys = ON")
    try:
        _validate_static_database(connection)
        connection.execute("ATTACH DATABASE ? AS runtime", (str(runtime_database_path),))
        initialize_runtime_database(connection, "runtime")
        connection.commit()
    except Exception:
        connection.close()
        raise
    return connection


def get_metadata(connection: sqlite3.Connection) -> dict[str, str]:
    metadata = {
        row["key"]: row["value"]
        for row in connection.execute("SELECT key, value FROM metadata")
    }
    if "runtime" in _database_schemas(connection):
        metadata.update(
            {
                row["key"]: row["value"]
                for row in connection.execute("SELECT key, value FROM runtime.metadata")
            }
        )
    return metadata


def get_category_summaries(connection: sqlite3.Connection) -> list[dict[str, Any]]:
    category_completion_table = _schema_table(_runtime_schema(connection), "category_completion")
    rows = connection.execute(
        f"""
        SELECT c.category, c.label,
               COUNT(DISTINCT e.entry_key) AS total,
               COUNT(DISTINCT CASE WHEN cc.completed = 1 THEN e.entry_key END) AS completed
        FROM codex_categories c
        LEFT JOIN codex_entry_categories ec ON ec.category = c.category
        LEFT JOIN codex_entries e ON e.entry_key = ec.entry_key AND e.is_current = 1
        LEFT JOIN {category_completion_table} cc
            ON cc.entry_key = e.entry_key AND cc.category = c.category
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


def get_achievement_summary(connection: sqlite3.Connection) -> dict[str, int]:
    completion_table = _schema_table(_runtime_schema(connection), "achievement_completion")
    row = connection.execute(
        f"""
        SELECT COUNT(*) AS total,
               COUNT(CASE WHEN COALESCE(ac.completed, 0) = 1 THEN 1 END) AS completed
        FROM achievements a
        LEFT JOIN {completion_table} ac ON ac.achievement_id = a.achievement_id
        """
    ).fetchone()
    return {
        "total": int(row["total"]),
        "completed": int(row["completed"]),
    }


def query_achievements(
    connection: sqlite3.Connection,
    name_search: str = "",
    completion_filter: str = "all",
    limit: int | None = 200,
    offset: int = 0,
) -> list[dict[str, Any]]:
    if completion_filter not in {"all", "completed", "pending"}:
        raise ValueError(f"未知完成状态筛选：{completion_filter}")
    completion_table = _schema_table(_runtime_schema(connection), "achievement_completion")
    clauses: list[str] = []
    params: list[Any] = []
    search = name_search.strip()
    if search:
        pattern = f"%{search}%"
        clauses.append(
            "(a.name LIKE ? OR a.name_key LIKE ? OR CAST(a.achievement_id AS TEXT) LIKE ? "
            "OR a.description LIKE ? OR a.condition_text LIKE ? OR a.method_text LIKE ? "
            "OR a.role_restriction LIKE ? OR a.notes_json LIKE ?)"
        )
        params.extend([pattern] * 8)
    if completion_filter == "completed":
        clauses.append("COALESCE(ac.completed, 0) = 1")
    elif completion_filter == "pending":
        clauses.append("COALESCE(ac.completed, 0) = 0")
    query = f"""
        SELECT a.achievement_id, a.sort_order, a.name, a.name_key,
               a.description, a.icon_path, a.category, a.is_hidden,
               a.condition_text, a.method_text, a.role_restriction,
               a.notes_json, a.common_notes_json, a.numeric_threshold,
               a.value_parameters_json, a.exclusions_json, a.config_references_json,
               a.source_version, a.raw_json,
               COALESCE(ac.completed, 0) AS completed
        FROM achievements a
        LEFT JOIN {completion_table} ac ON ac.achievement_id = a.achievement_id
        {('WHERE ' + ' AND '.join(clauses)) if clauses else ''}
        ORDER BY a.sort_order, a.achievement_id
    """
    if limit is None:
        if offset:
            query += " LIMIT -1 OFFSET ?"
            params.append(max(0, offset))
    else:
        params.extend([max(1, min(limit, 500)), max(0, offset)])
        query += " LIMIT ? OFFSET ?"
    return [dict(row) for row in connection.execute(query, params).fetchall()]


def get_achievement(
    connection: sqlite3.Connection,
    achievement_id: int,
) -> dict[str, Any] | None:
    completion_table = _schema_table(_runtime_schema(connection), "achievement_completion")
    row = connection.execute(
        f"""
        SELECT a.achievement_id, a.sort_order, a.name, a.name_key,
               a.description, a.icon_path, a.category, a.is_hidden,
               a.condition_text, a.method_text, a.role_restriction,
               a.notes_json, a.common_notes_json, a.numeric_threshold,
               a.value_parameters_json, a.exclusions_json, a.config_references_json,
               a.source_version, a.raw_json,
               COALESCE(ac.completed, 0) AS completed
        FROM achievements a
        LEFT JOIN {completion_table} ac ON ac.achievement_id = a.achievement_id
        WHERE a.achievement_id = ?
        """,
        (int(achievement_id),),
    ).fetchone()
    return dict(row) if row else None


def query_entries(
    connection: sqlite3.Connection,
    category: str,
    name_search: str = "",
    completion_filter: str = "all",
    limit: int | None = 24,
    offset: int = 0,
    material_search: str = "",
) -> list[dict[str, Any]]:
    category_completion_table = _schema_table(_runtime_schema(connection), "category_completion")
    clauses = ["ec.category = ?", "e.is_current = 1"]
    params: list[Any] = [category]
    if name_search.strip():
        clauses.append("(e.name LIKE ? OR e.name_key LIKE ? OR CAST(e.source_id AS TEXT) LIKE ?)")
        pattern = f"%{name_search.strip()}%"
        params.extend([pattern, pattern, pattern])
    if material_search.strip():
        material_prefixes = {
            "dish": ("具体食材", "食材分类"),
            "craft": ("制造材料",),
            "furniture": ("制造材料",),
        }.get(category, ())
        if not material_prefixes:
            clauses.append("0")
        else:
            material_clauses = []
            material_params: list[Any] = []
            pattern = f"%{material_search.strip()}%"
            for prefix in material_prefixes:
                material_clauses.append("r.relation_type = ? OR r.relation_type LIKE ?")
                material_params.extend([prefix, f"{prefix}（%"])
            clauses.append(
                "EXISTS ("
                "SELECT 1 FROM entry_relations r "
                "WHERE r.source_entry_key = e.entry_key "
                f"AND ({' OR '.join(material_clauses)}) "
                "AND (r.target_name LIKE ? OR CAST(r.target_id AS TEXT) LIKE ?)"
                ")"
            )
            params.extend(material_params)
            params.extend([pattern, pattern])
    if completion_filter == "completed":
        clauses.append("cc.completed = 1")
    elif completion_filter == "pending":
        clauses.append("COALESCE(cc.completed, 0) = 0")
    if completion_filter not in {"all", "completed", "pending"}:
        raise ValueError(f"未知完成状态筛选：{completion_filter}")
    query = f"""
        SELECT e.entry_key, e.source_table, e.source_id, e.name, e.name_key,
               e.description, e.icon_path, e.raw_json,
               COALESCE(cc.completed, 0) AS completed
        FROM codex_entry_categories ec
        JOIN codex_entries e ON e.entry_key = ec.entry_key
        LEFT JOIN {category_completion_table} cc
            ON cc.entry_key = e.entry_key AND cc.category = ec.category
        WHERE {' AND '.join(clauses)}
        ORDER BY e.source_id, e.name COLLATE NOCASE
    """
    if limit is None:
        if offset:
            query += " LIMIT -1 OFFSET ?"
            params.append(max(0, offset))
    else:
        params.extend([max(1, min(limit, 100)), max(0, offset)])
        query += " LIMIT ? OFFSET ?"
    rows = connection.execute(query, params).fetchall()
    return [dict(row) for row in rows]


def count_entries(
    connection: sqlite3.Connection,
    category: str,
    name_search: str = "",
    completion_filter: str = "all",
    material_search: str = "",
) -> int:
    category_completion_table = _schema_table(_runtime_schema(connection), "category_completion")
    rows = query_entries(
        connection,
        category,
        name_search,
        completion_filter,
        limit=100,
        offset=0,
        material_search=material_search,
    )
    if len(rows) < 100:
        return len(rows)
    clauses = ["ec.category = ?", "e.is_current = 1"]
    params: list[Any] = [category]
    if name_search.strip():
        clauses.append("(e.name LIKE ? OR e.name_key LIKE ? OR CAST(e.source_id AS TEXT) LIKE ?)")
        pattern = f"%{name_search.strip()}%"
        params.extend([pattern, pattern, pattern])
    if material_search.strip():
        material_prefixes = {
            "dish": ("具体食材", "食材分类"),
            "craft": ("制造材料",),
            "furniture": ("制造材料",),
        }.get(category, ())
        if not material_prefixes:
            clauses.append("0")
        else:
            material_clauses = []
            material_params: list[str] = []
            pattern = f"%{material_search.strip()}%"
            for prefix in material_prefixes:
                material_clauses.append("r.relation_type = ? OR r.relation_type LIKE ?")
                material_params.extend([prefix, f"{prefix}（%"])
            clauses.append(
                "EXISTS ("
                "SELECT 1 FROM entry_relations r "
                "WHERE r.source_entry_key = e.entry_key "
                f"AND ({' OR '.join(material_clauses)}) "
                "AND (r.target_name LIKE ? OR CAST(r.target_id AS TEXT) LIKE ?)"
                ")"
            )
            params.extend(material_params)
            params.extend([pattern, pattern])
    if completion_filter == "completed":
        clauses.append("cc.completed = 1")
    elif completion_filter == "pending":
        clauses.append("COALESCE(cc.completed, 0) = 0")
    elif completion_filter != "all":
        raise ValueError(f"未知完成状态筛选：{completion_filter}")
    row = connection.execute(
        f"""
        SELECT COUNT(*)
        FROM codex_entry_categories ec
        JOIN codex_entries e ON e.entry_key = ec.entry_key
        LEFT JOIN {category_completion_table} cc
            ON cc.entry_key = e.entry_key AND cc.category = ec.category
        WHERE {' AND '.join(clauses)}
        """,
        params,
    ).fetchone()
    return int(row[0])


def get_entry(
    connection: sqlite3.Connection,
    entry_key: str,
    category: str | None = None,
) -> dict[str, Any] | None:
    runtime_schema = _runtime_schema(connection)
    completion_table = _schema_table(runtime_schema, "completion")
    category_completion_table = _schema_table(runtime_schema, "category_completion")
    if category is None:
        row = connection.execute(
            f"""
            SELECT e.entry_key, e.source_table, e.source_id, e.name, e.name_key,
                   e.description, e.icon_path, e.raw_json, e.is_current,
                   COALESCE(co.completed, 0) AS completed
            FROM codex_entries e
            LEFT JOIN {completion_table} co ON co.entry_key = e.entry_key
            WHERE e.entry_key = ?
            """,
            (entry_key,),
        ).fetchone()
    else:
        row = connection.execute(
            f"""
            SELECT e.entry_key, e.source_table, e.source_id, e.name, e.name_key,
                   e.description, e.icon_path, e.raw_json, e.is_current,
                   COALESCE(cc.completed, 0) AS completed
            FROM codex_entries e
            LEFT JOIN {category_completion_table} cc
                ON cc.entry_key = e.entry_key AND cc.category = ?
            WHERE e.entry_key = ?
            """,
            (category, entry_key),
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
    raise RuntimeError("完成状态由游戏 HistorySave 存档同步，不能手动修改")


def main() -> int:
    parser = argparse.ArgumentParser(description="构建 Survival Log 图鉴 SQLite 数据库")
    parser.add_argument(
        "--game-root",
        type=Path,
        default=None,
        help="游戏安装目录；缺省时自动查找 Steam 库",
    )
    parser.add_argument(
        "--database",
        type=Path,
        default=None,
        help="静态（源码）或单文件（独立版）SQLite 数据库路径",
    )
    parser.add_argument(
        "--runtime-database",
        type=Path,
        default=None,
        help="源码模式 runtime SQLite 数据库路径",
    )
    parser.add_argument(
        "--save-file",
        type=Path,
        default=default_save_file(),
        help="HistorySave.bytes 存档路径",
    )
    parser.add_argument(
        "--no-save-sync",
        action="store_true",
        help="只构建静态数据库，不读取游戏存档完成状态",
    )
    parser.add_argument(
        "--package-copy-from",
        type=Path,
        default=None,
        help="复制并清空完成状态/存档元数据，用于生成独立版数据库",
    )
    args = parser.parse_args()
    try:
        game_root = args.game_root or resolve_default_game_root()
        database_path = args.database or resolve_default_database_path()
        if args.package_copy_from is not None:
            destination = prepare_packaged_database(args.package_copy_from, database_path)
            print(f"打包数据库：{destination}")
            print("完成状态：已清空；save_* 元数据：已清除")
            return 0
        runtime_database_path = (
            args.runtime_database or resolve_default_runtime_database_path()
        )
        counts = build_database(
            game_root,
            database_path,
            args.save_file,
            sync_save=not args.no_save_sync,
            runtime_database_path=runtime_database_path,
        )
        print(f"数据库：{database_path}")
        print(f"runtime 数据库：{runtime_database_path}")
        for category in CATEGORY_ORDER:
            print(f"{CATEGORY_LABELS[category]}：{counts[category]} 条")
        print(
            f"主条目：{counts['entries']}，分类映射：{counts['category_mappings']}，"
            f"关联：{counts['relations']}，辅助配置：{counts['auxiliary_rows']}"
        )
        if counts["save_sync"] is not None:
            save_sync: CompletionSyncResult = counts["save_sync"]
            print(f"存档同步：{save_sync.message}")
        else:
            print("存档同步：已跳过（--no-save-sync）")
        print("数据库构建完成")
    except Exception as exc:
        print(f"数据库构建失败：{exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
