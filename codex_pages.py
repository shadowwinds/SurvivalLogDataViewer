#!/usr/bin/env python3
"""Build a standalone codex from the repository's public static database."""

from __future__ import annotations

import argparse
import json
import shutil
import sqlite3
import sys
from pathlib import Path
from typing import Any

from codex_database import CATEGORY_LABELS, CATEGORY_ORDER, DATABASE_SCHEMA_VERSION
from codex_parser import FIELD_LABELS, format_scalar
from codex_server import _achievement_payload, _build_detail_fields


PROJECT_DIR = Path(__file__).resolve().parent
SOURCE_DIR = PROJECT_DIR / "pages"
DEFAULT_GAME_ROOT = Path(r"G:\SteamLibrary\steamapps\common\Survival Log")
PUBLIC_METADATA = ("game_version", "database_schema_version")
ASSETS = ("index.html", "styles.css", "app.js", "favicon.svg")


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
        for row in connection.execute(
            """
            SELECT entry_key, source_table, source_id, name, name_key, description, raw_json
            FROM codex_entries WHERE is_current = 1 ORDER BY source_id, entry_key
            """
        ):
            raw = json.loads(row["raw_json"])
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
                }
                category_map[category]["entries"].append(entry)
        achievements = []
        for row in connection.execute("SELECT * FROM achievements ORDER BY sort_order, achievement_id"):
            public = _achievement_payload(dict(row))
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
                    "fields": config_fields(json.loads(row["raw_json"])),
                    "relations": [],
                }
            )
        categories.append({"id": "achievements", "label": "成就", "entries": achievements})
        return {"format_version": 1, "metadata": metadata, "categories": categories}
    finally:
        connection.close()


def build_pages(database_path: Path, output_dir: Path) -> Path:
    output_dir = output_dir.expanduser().resolve()
    database_path = database_path.expanduser().resolve()
    for protected in (DEFAULT_GAME_ROOT.resolve(), SOURCE_DIR.resolve(), database_path):
        if output_dir == protected or output_dir.is_relative_to(protected):
            raise ValueError("输出目录不能位于游戏目录、网页源码目录或数据库文件路径中")
    if database_path.is_relative_to(output_dir) or SOURCE_DIR.is_relative_to(output_dir):
        raise ValueError("输出目录不能包含源数据库或网页源码目录")
    payload = export_data(database_path)
    output_dir.mkdir(parents=True, exist_ok=True)
    for name in (*ASSETS, "data.json", ".nojekyll"):
        if (output_dir / name).is_symlink():
            raise ValueError(f"输出文件不能是符号链接：{name}")
    for name in ASSETS:
        shutil.copyfile(SOURCE_DIR / name, output_dir / name)
    (output_dir / "data.json").write_text(
        json.dumps(payload, ensure_ascii=False, separators=(",", ":"), allow_nan=False),
        encoding="utf-8",
    )
    (output_dir / ".nojekyll").write_text("", encoding="ascii")
    return output_dir


def main() -> int:
    parser = argparse.ArgumentParser(description="从已公开的静态图鉴数据库构建 GitHub Pages 网页")
    parser.add_argument("--database", type=Path, default=PROJECT_DIR / "survival_log_codex.sqlite3")
    parser.add_argument("--output-dir", type=Path, default=PROJECT_DIR / "build" / "pages")
    args = parser.parse_args()
    try:
        output = build_pages(args.database, args.output_dir)
    except (OSError, sqlite3.Error, ValueError, KeyError) as exc:
        print(f"静态网页构建失败：{exc}", file=sys.stderr)
        return 1
    print(f"静态网页已生成：{output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
