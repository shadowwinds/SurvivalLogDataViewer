#!/usr/bin/env python3
"""Serve the offline Survival Log codex through a standard-library web app."""

from __future__ import annotations

import argparse
import json
import re
import sqlite3
import sys
import threading
import time
import urllib.parse
import webbrowser
from collections import Counter
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any

from codex_database import (
    CATEGORY_LABELS,
    CATEGORY_ORDER,
    CompletionSyncResult,
    get_achievement,
    get_achievement_summary,
    get_category_summaries,
    get_entry,
    get_entry_relations,
    get_metadata,
    get_overall_summary,
    get_runtime_cache,
    open_database,
    query_achievements,
    query_entries,
    resolve_default_database_path,
    resolve_default_runtime_database_path,
    set_runtime_cache,
    sync_game_completion,
)
from codex_save import SaveParseError, default_save_file
from codex_parser import FIELD_LABELS, format_scalar
from codex_recipe import (
    RECIPE_PLAN_CACHE_VERSION,
    RecipeConfigError,
    build_recipe_error,
    build_recipe_plan,
)


POLL_INTERVAL_SECONDS = 5
PAGE_CLOSE_GRACE_SECONDS = 30
# A lost pagehide/beacon must not leave the local server alive forever. This
# is deliberately longer than the normal close grace so background tabs can
# continue to send throttled polling requests without being mistaken for a
# closed page.
CLIENT_IDLE_GRACE_SECONDS = 90
DEFAULT_PORT = 8501
CATEGORY_EMOJI = {
    "food": "🍞",
    "dish": "🍳",
    "plant": "🌱",
    "prey": "🐾",
    "craft": "🔧",
    "furniture": "🛋️",
    "achievements": "🏆",
    "recipes": "🍲",
}
DETAIL_RELATION_PREFIXES = {
    "food": ("关联植物", "目标家具"),
    "prey": ("关联植物", "目标家具"),
    "dish": ("具体食材", "食材分类"),
    "craft": ("制造材料",),
    "furniture": ("制造材料", "制造要求等级"),
}
STATIC_FILES = {
    "/": ("index.html", "text/html; charset=utf-8"),
    "/index.html": ("index.html", "text/html; charset=utf-8"),
    "/app.js": ("app.js", "text/javascript; charset=utf-8"),
    "/styles.css": ("styles.css", "text/css; charset=utf-8"),
}


def default_database_path() -> Path:
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent / "SurvivalLogDataViewer.sqlite3"
    return resolve_default_database_path()


def default_runtime_database_path() -> Path | None:
    if getattr(sys, "frozen", False):
        return None
    return resolve_default_runtime_database_path()


def static_root() -> Path:
    candidates = [Path(__file__).resolve().parent / "web"]
    candidates.append(Path(sys.executable).resolve().parent / "web")
    bundle_root = getattr(sys, "_MEIPASS", None)
    if bundle_root:
        candidates.append(Path(bundle_root) / "web")
    for candidate in candidates:
        if candidate.is_dir():
            return candidate
    raise FileNotFoundError("找不到本地网页资源目录：web")


def _first_query_value(values: dict[str, list[str]], name: str, default: str = "") -> str:
    return values.get(name, [default])[0]


def _client_id(value: str) -> str | None:
    if re.fullmatch(r"[A-Za-z0-9_-]{1,128}", value):
        return value
    return None


def _json_safe_entry(entry: dict[str, Any]) -> dict[str, Any]:
    return {key: value for key, value in entry.items() if key != "raw_json"}


def _json_string_list(value: object) -> list[str]:
    try:
        parsed = json.loads(str(value or "[]"))
    except (TypeError, ValueError, json.JSONDecodeError):
        return []
    if not isinstance(parsed, list):
        return []
    return [str(item) for item in parsed if str(item).strip()]


def _json_number_list(value: object) -> list[float]:
    try:
        parsed = json.loads(str(value or "[]"))
    except (TypeError, ValueError, json.JSONDecodeError):
        return []
    if not isinstance(parsed, list):
        return []
    numbers: list[float] = []
    for item in parsed:
        if isinstance(item, (int, float)) and not isinstance(item, bool):
            numbers.append(float(item))
    return numbers


def _achievement_payload(row: dict[str, Any]) -> dict[str, Any]:
    condition = str(row.get("condition_text") or "").strip()
    method = str(row.get("method_text") or "").strip()
    return {
        "entry_key": str(int(row["achievement_id"])),
        "achievement_id": int(row["achievement_id"]),
        "source_table": "Config_Achievement",
        "source_id": int(row["achievement_id"]),
        "name": str(row.get("name") or ""),
        "name_key": str(row.get("name_key") or ""),
        "description": str(row.get("description") or ""),
        "icon_path": str(row.get("icon_path") or ""),
        "category": str(row.get("category") or ""),
        "is_hidden": bool(row.get("is_hidden")),
        "completed": bool(row.get("completed")),
        "condition": condition,
        "condition_summary": condition,
        "method": method,
        "role_restriction": str(row.get("role_restriction") or "").strip(),
        "notes": _json_string_list(row.get("notes_json")),
        "common_notes": _json_string_list(row.get("common_notes_json")),
        "numeric_threshold": row.get("numeric_threshold"),
        "value_parameters": _json_number_list(row.get("value_parameters_json")),
        "exclusions": _json_string_list(row.get("exclusions_json")),
        "config_references": _json_string_list(row.get("config_references_json")),
        "source_version": str(row.get("source_version") or ""),
    }


def _relation_matches(relation_type: str, prefixes: tuple[str, ...]) -> bool:
    return any(relation_type == prefix or relation_type.startswith(f"{prefix}（") for prefix in prefixes)


def _format_relation_values(
    relations: list[dict[str, Any]],
    *,
    include_group: bool = False,
    include_id: bool = True,
) -> str:
    grouped: dict[str, list[dict[str, Any]]] = {}
    for relation in relations:
        grouped.setdefault(relation["relation_type"], []).append(relation)
    parts: list[str] = []
    for relation_type, values in grouped.items():
        counts = Counter((value["target_id"], value["target_name"]) for value in values)
        items = []
        for (target_id, target_name), count in counts.items():
            quantity = f" × {count}" if count > 1 else ""
            identity = f"（ID {target_id}）" if include_id else ""
            display_name = str(target_name)
            if not include_id and re.fullmatch(r"ID\s*:?\s*\d+", display_name):
                display_name = "未知关联"
            items.append(f"{display_name}{quantity}{identity}")
        text = "、".join(items) or "无"
        display_relation_type = relation_type
        if not include_id:
            display_relation_type = re.sub(r"\s*ID\s*:?\s*\d+", "", display_relation_type)
            display_relation_type = display_relation_type.replace("（）", "")
        parts.append(
            f"{display_relation_type}：{text}" if include_group else text
        )
    return "；".join(parts) or "无"


def _raw_field(raw: dict[str, Any], field: str, label: str | None = None) -> dict[str, str] | None:
    if field not in raw:
        return None
    return {
        "field": field,
        "label": label or FIELD_LABELS.get(field, field),
        "value": format_scalar(raw[field]),
    }


def _build_detail_fields(
    category: str,
    raw: dict[str, Any],
    relations: list[dict[str, Any]],
) -> tuple[list[dict[str, str]], list[dict[str, str]], list[str]]:
    highlights: list[dict[str, str]] = []
    highlighted_fields: set[str] = set()
    highlighted_relation_prefixes = DETAIL_RELATION_PREFIXES.get(category, ())

    if category in {"food", "prey"}:
        acquisition_parts: list[str] = []
        acquisition_text = raw.get("ItemDes1_Local") or raw.get("ItemDes1")
        if acquisition_text:
            acquisition_parts.append(str(acquisition_text))
            highlighted_fields.add("ItemDes1_Local")
            highlighted_fields.add("ItemDes1")
        for prefix in highlighted_relation_prefixes:
            matching = [
                relation
                for relation in relations
                if relation["relation_type"] == prefix
            ]
            if matching:
                acquisition_parts.append(
                    f"{prefix}：{_format_relation_values(matching, include_id=False)}"
                )
        highlights.append(
            {
                "field": "acquisition",
                "label": "获取方法",
                "value": "；".join(acquisition_parts) or "当前配置未提供专门的获取方法",
            }
        )
        if category == "food":
            price = _raw_field(raw, "price", "购买价格")
            if price:
                highlights.append(price)
                highlighted_fields.add("price")

    elif category == "dish":
        ingredients = [
            relation
            for relation in relations
            if relation["relation_type"] in {"具体食材", "食材分类"}
        ]
        highlights.append(
            {
                "field": "ingredients",
                "label": "制作所需食材",
                "value": _format_relation_values(ingredients, include_id=False),
            }
        )
        highlighted_fields.update({"SpecificItems", "TagCombo"})
        level = _raw_field(raw, "MinLevel", "要求等级")
        if level:
            level["value"] = f"{level['value']}级"
            highlights.append(level)
            highlighted_fields.add("MinLevel")

    elif category == "plant":
        for field in ("Size", "LightNeed", "ColdResistance"):
            item = _raw_field(raw, field)
            if item:
                highlights.append(item)
                highlighted_fields.add(field)

    elif category == "craft":
        materials = [
            relation
            for relation in relations
            if relation["relation_type"].startswith("制造材料")
        ]
        highlights.append(
            {
                "field": "materials",
                "label": "制作所需材料",
                "value": _format_relation_values(materials, include_id=False),
            }
        )
        highlighted_fields.add("MaterialList")
        level = _raw_field(raw, "Level", "要求等级")
        if level:
            level["value"] = f"{level['value']}级"
            highlights.append(level)
            highlighted_fields.add("Level")

    elif category == "furniture":
        price = _raw_field(raw, "FurniturePrice", "家具价格")
        if price:
            highlights.append(price)
            highlighted_fields.add("FurniturePrice")
        materials = [
            relation
            for relation in relations
            if relation["relation_type"].startswith("制造材料")
        ]
        highlights.append(
            {
                "field": "materials",
                "label": "制作所需材料",
                "value": _format_relation_values(materials, include_id=False),
            }
        )
        levels = [
            relation
            for relation in relations
            if relation["relation_type"].startswith("制造要求等级")
        ]
        highlights.append(
            {
                "field": "level",
                "label": "要求等级",
                "value": _format_relation_values(levels, include_id=False),
            }
        )

    fields = []
    for field, value in raw.items():
        if field in highlighted_fields:
            continue
        fields.append(
            {
                "field": field,
                "label": FIELD_LABELS.get(field, field),
                "value": format_scalar(value),
            }
        )
    return highlights, fields, list(highlighted_relation_prefixes)


def _highlight_items(
    category: str,
    raw: dict[str, Any],
    relations: list[dict[str, Any]],
) -> list[dict[str, str]]:
    highlights, _fields, _prefixes = _build_detail_fields(category, raw, relations)
    return [
        {
            "label": str(field["label"]),
            "value": str(field["value"]),
        }
        for field in highlights
        if str(field["value"])
    ]


def _highlight_summary(items: list[dict[str, str]]) -> str:
    return "；".join(f"{item['label']}：{item['value']}" for item in items)


class CodexService:
    """Serialize database access and avoid parsing the save when its signature is unchanged."""

    def __init__(
        self,
        database_path: Path,
        save_file: Path,
        *,
        runtime_database_path: Path | None = None,
        log_path: Path | None = None,
    ):
        self.database_path = database_path.expanduser().resolve()
        self.runtime_database_path = (
            runtime_database_path.expanduser().resolve()
            if runtime_database_path is not None
            else None
        )
        self.save_file = save_file.expanduser().resolve()
        self.log_path = log_path.expanduser().resolve() if log_path is not None else None
        self.connection = open_database(
            self.database_path,
            self.runtime_database_path,
            check_same_thread=False,
        )
        self._lock = threading.RLock()
        self._last_success_signature: tuple[Any, ...] | None = None
        self._last_sync: CompletionSyncResult | None = None
        self._last_recipe_signature: tuple[Any, ...] | None = None
        self._last_recipe_plan: dict[str, Any] | None = None

    @staticmethod
    def _file_signature(path: Path) -> tuple[Any, ...]:
        try:
            stat = path.stat()
        except OSError:
            return (str(path), False, 0, 0)
        if not path.is_file():
            return (str(path), False, 0, 0)
        return (str(path), True, stat.st_size, stat.st_mtime_ns)

    def _save_signature(self) -> tuple[Any, ...]:
        return (
            self._file_signature(self.save_file),
            self._file_signature(Path(f"{self.save_file}.bak")),
        )

    def _recipe_signature(self) -> tuple[Any, ...]:
        children = []
        for path in sorted(self.save_file.parent.glob("Save_*.bytes"), key=lambda value: value.name):
            if not re.fullmatch(r"Save_[A-Za-z0-9_-]+\.bytes", path.name):
                continue
            children.append(self._file_signature(path))
            children.append(self._file_signature(Path(f"{path}.bak")))
        return self._save_signature() + tuple(children)

    @staticmethod
    def _recipe_cache_signature(
        signature: tuple[Any, ...],
        metadata: dict[str, str],
    ) -> str:
        return json.dumps(
            {
                "recipe_plan_cache_version": RECIPE_PLAN_CACHE_VERSION,
                "save_signature": signature,
                "game_version": metadata.get("game_version", ""),
                "database_schema_version": metadata.get("database_schema_version", ""),
                "imported_at": metadata.get("imported_at", ""),
            },
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            default=str,
        )

    def _store_recipe_plan(
        self,
        payload: dict[str, Any],
        signature: tuple[Any, ...],
        metadata: dict[str, str],
    ) -> dict[str, Any]:
        cache_signature = self._recipe_cache_signature(signature, metadata)
        payload["revision"] = json.dumps(
            {
                "cache_signature": cache_signature,
                "history_source": payload.get("history_source"),
                "status": payload.get("status"),
            },
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            default=str,
        )
        self._last_recipe_signature = signature
        self._last_recipe_plan = payload
        if payload.get("status") != "error":
            set_runtime_cache(
                self.connection,
                "recipe_plans",
                cache_signature,
                payload,
            )
        return payload

    def _targeted_recipe_signature(
        self,
        previous: tuple[Any, ...] | None,
        current: tuple[Any, ...],
        file_name: str,
    ) -> tuple[Any, ...]:
        if previous is None:
            return current
        target = self.save_file.parent / file_name
        target_paths = {str(target), str(Path(f"{target}.bak"))}
        current_by_path = {
            item[0]: item
            for item in current
            if isinstance(item, tuple) and item and isinstance(item[0], str)
        }
        if not any(
            isinstance(item, tuple) and item and item[0] in target_paths
            for item in previous
        ):
            return current
        return tuple(
            current_by_path.get(item[0], item)
            if isinstance(item, tuple) and item and item[0] in target_paths
            else item
            for item in previous
        )

    def _ensure_sync(self) -> CompletionSyncResult:
        signature = self._save_signature()
        with self._lock:
            if (
                self._last_sync is not None
                and self._last_success_signature == signature
                and self._last_sync.status in {"ok", "fallback"}
            ):
                return CompletionSyncResult(
                    status=self._last_sync.status,
                    changed=False,
                    save_path=self._last_sync.save_path,
                    category_counts=self._last_sync.category_counts,
                    unknown_ids=self._last_sync.unknown_ids,
                    updated_entries=0,
                    used_backup=self._last_sync.used_backup,
                    message="存档未变化，完成状态无需更新",
                    schema_profile=self._last_sync.schema_profile,
                    codex_offset=self._last_sync.codex_offset,
                    codex_end_offset=self._last_sync.codex_end_offset,
                    candidate_count=self._last_sync.candidate_count,
                    candidate_score=self._last_sync.candidate_score,
                    achievement_count=self._last_sync.achievement_count,
                    achievement_status_available=self._last_sync.achievement_status_available,
                    unknown_achievement_ids=self._last_sync.unknown_achievement_ids,
                )

            result = sync_game_completion(
                self.connection,
                self.save_file,
                log_path=self.log_path,
            )
            self._last_sync = result
            if result.status in {"ok", "fallback"}:
                self._last_success_signature = signature
            else:
                self._last_success_signature = None
            return result

    def _revision(self, metadata: dict[str, str], result: CompletionSyncResult) -> str:
        return json.dumps(
            {
                "path": metadata.get("save_path", str(result.save_path)),
                "sha256": metadata.get("save_sha256", ""),
                "mtime_ns": metadata.get("save_mtime_ns", ""),
                "status": metadata.get("save_sync_status", result.status),
                "error": metadata.get("save_sync_error", ""),
            },
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        )

    def state(self) -> dict[str, Any]:
        with self._lock:
            result = self._ensure_sync()
            metadata = get_metadata(self.connection)
            summaries = get_category_summaries(self.connection)
            achievement_summary = get_achievement_summary(self.connection)
            summary_by_category = {row["category"]: row for row in summaries}
            categories = [
                {
                    "category": category,
                    "label": CATEGORY_LABELS[category],
                    "emoji": CATEGORY_EMOJI[category],
                    "total": int(summary_by_category.get(category, {}).get("total", 0)),
                    "completed": int(summary_by_category.get(category, {}).get("completed", 0)),
                }
                for category in CATEGORY_ORDER
            ]
            categories.append(
                {
                    "category": "achievements",
                    "label": "成就",
                    "emoji": CATEGORY_EMOJI["achievements"],
                    "total": int(achievement_summary["total"]),
                    "completed": int(achievement_summary["completed"]),
                }
            )
            categories.append(
                {
                    "category": "recipes",
                    "label": "可烹饪菜肴",
                    "emoji": CATEGORY_EMOJI["recipes"],
                    "total": None,
                    "completed": None,
                }
            )
            sync = {
                "status": result.status,
                "changed": result.changed,
                "message": result.message,
                "revision": self._revision(metadata, result),
                "save_path": str(result.save_path),
                "used_backup": result.used_backup,
                "updated_entries": result.updated_entries,
                "category_counts": result.category_counts,
                "schema_profile": result.schema_profile,
                "codex_offset": result.codex_offset,
                "codex_end_offset": result.codex_end_offset,
                "candidate_count": result.candidate_count,
                "candidate_score": list(result.candidate_score),
                "unknown_ids": {
                    category: list(values) for category, values in result.unknown_ids.items()
                },
                "unknown_achievement_ids": list(result.unknown_achievement_ids),
                "achievement_count": result.achievement_count,
                "achievement_status_available": result.achievement_status_available,
            }
            return {
                "categories": categories,
                "overall": get_overall_summary(self.connection),
                "achievement_summary": achievement_summary,
                "metadata": metadata,
                "sync": sync,
                "poll_interval_seconds": POLL_INTERVAL_SECONDS,
                "disconnect_grace_seconds": PAGE_CLOSE_GRACE_SECONDS,
            }

    def recipe_plans(self) -> dict[str, Any]:
        with self._lock:
            self._ensure_sync()
            signature = self._recipe_signature()
            if self._last_recipe_plan is not None and self._last_recipe_signature == signature:
                return self._last_recipe_plan
            metadata = get_metadata(self.connection)
            cache_signature = self._recipe_cache_signature(signature, metadata)
            cached = get_runtime_cache(
                self.connection,
                "recipe_plans",
                cache_signature,
            )
            if cached is not None and isinstance(cached.get("revision"), str):
                self._last_recipe_signature = signature
                self._last_recipe_plan = cached
                return cached
            try:
                payload = build_recipe_plan(self.connection, self.save_file)
            except (OSError, RecipeConfigError, SaveParseError, sqlite3.Error) as exc:
                payload = build_recipe_error(str(exc))
            return self._store_recipe_plan(payload, signature, metadata)

    def refresh_recipe_save(self, file_name: str) -> dict[str, Any]:
        with self._lock:
            current_plan = self._last_recipe_plan
            if current_plan is None:
                current_plan = self.recipe_plans()
            current_saves = {
                str(save.get("file_name")): save
                for save in current_plan.get("saves", [])
                if isinstance(save, dict) and save.get("file_name")
            }
            if file_name not in current_saves:
                raise ValueError(f"当前智能菜谱不存在选中的存档：{file_name}")

            previous_signature = self._last_recipe_signature
            try:
                payload = build_recipe_plan(
                    self.connection,
                    self.save_file,
                    refresh_file_name=file_name,
                    existing_saves=current_saves,
                )
            except (OSError, RecipeConfigError, SaveParseError, sqlite3.Error) as exc:
                raise ValueError(f"存档更新失败：{exc}") from exc

            refreshed = next(
                (
                    save
                    for save in payload.get("saves", [])
                    if isinstance(save, dict) and save.get("file_name") == file_name
                ),
                None,
            )
            if not isinstance(refreshed, dict) or refreshed.get("status") != "ok":
                diagnostics = [
                    str(value).strip()
                    for value in (refreshed or {}).get("diagnostics", [])
                    if str(value).strip()
                ]
                message = diagnostics[0] if diagnostics else "当前存档读取失败"
                raise ValueError(f"存档更新失败：{message}")

            metadata = get_metadata(self.connection)
            current_signature = self._recipe_signature()
            signature = self._targeted_recipe_signature(
                previous_signature,
                current_signature,
                file_name,
            )
            return self._store_recipe_plan(payload, signature, metadata)

    def entries(
        self,
        category: str,
        name_search: str,
        material_search: str,
        completion_filter: str,
    ) -> dict[str, Any]:
        if category not in CATEGORY_ORDER:
            raise ValueError(f"未知图鉴分类：{category}")
        if completion_filter not in {"all", "completed", "pending"}:
            raise ValueError(f"未知完成状态筛选：{completion_filter}")
        with self._lock:
            self._ensure_sync()
            rows = query_entries(
                self.connection,
                category,
                name_search,
                completion_filter,
                limit=None,
                material_search=material_search,
            )
            for row in rows:
                raw = json.loads(row["raw_json"])
                relations = get_entry_relations(self.connection, row["entry_key"])
                highlight_items = _highlight_items(category, raw, relations)
                row["highlight_items"] = highlight_items
                row["highlight_summary"] = _highlight_summary(highlight_items)
            return {
                "category": category,
                "label": CATEGORY_LABELS[category],
                "total": len(rows),
                "name_search": name_search,
                "material_search": material_search,
                "entries": [_json_safe_entry(row) for row in rows],
            }

    def achievements(
        self,
        name_search: str,
        completion_filter: str,
    ) -> dict[str, Any]:
        if completion_filter not in {"all", "completed", "pending"}:
            raise ValueError(f"未知成就状态筛选：{completion_filter}")
        with self._lock:
            self._ensure_sync()
            rows = query_achievements(
                self.connection,
                name_search,
                completion_filter,
                limit=None,
            )
            return {
                "category": "achievements",
                "label": "成就",
                "total": len(rows),
                "name_search": name_search,
                "completion": completion_filter,
                "entries": [_achievement_payload(row) for row in rows],
            }

    def achievement(self, achievement_id: int) -> dict[str, Any] | None:
        if int(achievement_id) <= 0:
            raise ValueError("成就 ID 必须是正整数")
        with self._lock:
            self._ensure_sync()
            row = get_achievement(self.connection, int(achievement_id))
            if row is None:
                return None
            payload = _achievement_payload(row)
            raw = json.loads(row["raw_json"])
            config_fields = [
                {
                    "field": field,
                    "label": FIELD_LABELS.get(field, field),
                    "value": format_scalar(value),
                }
                for field, value in raw.items()
            ]
            method = payload["method"]
            return {
                "achievement": payload,
                "conditions": {
                    "condition": payload["condition"],
                    "method": method,
                    "method_steps": [
                        line.strip() for line in method.splitlines() if line.strip()
                    ],
                    "role_restriction": payload["role_restriction"],
                    "notes": payload["notes"],
                    "common_notes": payload["common_notes"],
                    "numeric_threshold": payload["numeric_threshold"],
                    "value_parameters": payload["value_parameters"],
                    "exclusions": payload["exclusions"],
                    "config_references": payload["config_references"],
                },
                "config_fields": config_fields,
            }

    def entry(self, category: str, entry_key: str) -> dict[str, Any] | None:
        if category not in CATEGORY_ORDER:
            raise ValueError(f"未知图鉴分类：{category}")
        if not entry_key:
            raise ValueError("缺少条目键")
        with self._lock:
            self._ensure_sync()
            row = get_entry(self.connection, entry_key, category)
            if row is None:
                return None
            payload = json.loads(row["raw_json"])
            relations = get_entry_relations(self.connection, entry_key)
            highlights, fields, highlight_relation_prefixes = _build_detail_fields(
                category,
                payload,
                relations,
            )
            return {
                "entry": _json_safe_entry(row),
                "relations": relations,
                "highlight_relation_prefixes": highlight_relation_prefixes,
                "highlights": highlights,
                "fields": fields,
            }

    def close(self) -> None:
        with self._lock:
            self.connection.close()


class CodexHTTPServer(ThreadingHTTPServer):
    # Reusing a listening port on Windows can leave multiple app instances
    # serving different databases behind the same URL.
    allow_reuse_address = False

    def __init__(
        self,
        address: tuple[str, int],
        service: CodexService,
        assets: Path,
        *,
        auto_exit: bool,
    ):
        self._stopping = threading.Event()
        super().__init__(address, CodexRequestHandler)
        self.service = service
        self.assets = assets
        self.auto_exit = auto_exit
        self._lifecycle_lock = threading.Lock()
        self._active_client_ids: set[str] = set()
        self._closed_client_ids: set[str] = set()
        self._client_last_activity: dict[str, float] = {}
        # Start a grace timer immediately; the first API heartbeat cancels it.
        self._shutdown_requested_at: float | None = (
            time.monotonic() if self.auto_exit else None
        )
        if self.auto_exit:
            monitor = threading.Thread(
                target=self._monitor_client,
                name="codex-client-monitor",
                daemon=True,
            )
            monitor.start()

    def note_client_activity(self, client_id: str | None = None) -> None:
        if not client_id:
            return
        now = time.monotonic()
        with self._lifecycle_lock:
            if client_id in self._closed_client_ids:
                return
            self._active_client_ids.add(client_id)
            self._client_last_activity[client_id] = now
            self._shutdown_requested_at = None

    def note_client_closed(self, client_id: str | None = None) -> None:
        if not client_id:
            return
        now = time.monotonic()
        with self._lifecycle_lock:
            self._closed_client_ids.add(client_id)
            self._active_client_ids.discard(client_id)
            self._client_last_activity.pop(client_id, None)
            if self._active_client_ids:
                self._shutdown_requested_at = None
                return
            self._shutdown_requested_at = now

    def _monitor_client(self) -> None:
        while not self._stopping.wait(POLL_INTERVAL_SECONDS):
            now = time.monotonic()
            stop_for_idle_client = False
            with self._lifecycle_lock:
                stale_clients = {
                    client_id
                    for client_id in self._active_client_ids
                    if now - self._client_last_activity.get(client_id, now)
                    >= CLIENT_IDLE_GRACE_SECONDS
                }
                if stale_clients:
                    self._active_client_ids.difference_update(stale_clients)
                    for client_id in stale_clients:
                        self._client_last_activity.pop(client_id, None)
                    if not self._active_client_ids:
                        stop_for_idle_client = True
                close_requested_at = self._shutdown_requested_at
            if (
                stop_for_idle_client
                or (
                    close_requested_at is not None
                    and now - close_requested_at >= PAGE_CLOSE_GRACE_SECONDS
                )
            ):
                self.shutdown()
                return

    def server_close(self) -> None:
        self._stopping.set()
        super().server_close()


class CodexRequestHandler(BaseHTTPRequestHandler):
    server: CodexHTTPServer

    def _send_bytes(self, status: int, content_type: str, body: bytes) -> None:
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.end_headers()
        self.wfile.write(body)

    def _send_json(self, status: int, payload: dict[str, Any]) -> None:
        body = json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
        self._send_bytes(status, "application/json; charset=utf-8", body)

    def _send_error_json(self, status: int, message: str) -> None:
        self._send_json(status, {"error": message})

    def _serve_static(self, path: str) -> None:
        asset = STATIC_FILES.get(path)
        if asset is None:
            self._send_error_json(HTTPStatus.NOT_FOUND, "找不到网页资源")
            return
        filename, content_type = asset
        asset_path = self.server.assets / filename
        try:
            body = asset_path.read_bytes()
        except OSError as exc:
            self._send_error_json(HTTPStatus.INTERNAL_SERVER_ERROR, f"读取网页资源失败：{exc}")
            return
        self._send_bytes(HTTPStatus.OK, content_type, body)

    def _handle_api(self, path: str, query: dict[str, list[str]]) -> None:
        service = self.server.service
        if path == "/api/state":
            self._send_json(HTTPStatus.OK, service.state())
            return
        if path == "/api/recipe-plans":
            self._send_json(HTTPStatus.OK, service.recipe_plans())
            return
        if path == "/api/achievements":
            name_search = _first_query_value(query, "name_search")
            if not name_search:
                name_search = _first_query_value(query, "search")
            completion = _first_query_value(query, "completion", "all")
            self._send_json(
                HTTPStatus.OK,
                service.achievements(name_search, completion),
            )
            return
        achievement_prefix = "/api/achievements/"
        if path.startswith(achievement_prefix):
            raw_id = urllib.parse.unquote(path[len(achievement_prefix) :])
            if not re.fullmatch(r"[0-9]+", raw_id):
                raise ValueError("成就 ID 必须是正整数")
            result = service.achievement(int(raw_id))
            if result is None:
                self._send_error_json(HTTPStatus.NOT_FOUND, "找不到成就")
            else:
                self._send_json(HTTPStatus.OK, result)
            return
        if path == "/api/entries":
            category = _first_query_value(query, "category", "furniture")
            name_search = _first_query_value(query, "name_search")
            if not name_search:
                name_search = _first_query_value(query, "search")
            material_search = _first_query_value(query, "material_search")
            completion = _first_query_value(query, "completion", "all")
            self._send_json(
                HTTPStatus.OK,
                service.entries(category, name_search, material_search, completion),
            )
            return
        prefix = "/api/entries/"
        if path.startswith(prefix):
            entry_key = urllib.parse.unquote(path[len(prefix) :])
            category = _first_query_value(query, "category", "furniture")
            result = service.entry(category, entry_key)
            if result is None:
                self._send_error_json(HTTPStatus.NOT_FOUND, "找不到图鉴条目")
            else:
                self._send_json(HTTPStatus.OK, result)
            return
        self._send_error_json(HTTPStatus.NOT_FOUND, "找不到 API 接口")

    def do_GET(self) -> None:  # noqa: N802 - required by BaseHTTPRequestHandler
        parsed = urllib.parse.urlsplit(self.path)
        query = urllib.parse.parse_qs(parsed.query, keep_blank_values=True)
        try:
            if parsed.path.startswith("/api/"):
                self.server.note_client_activity(_client_id(self.headers.get("X-SurvivalLog-Client", "")))
                self._handle_api(parsed.path, query)
            else:
                self._serve_static(parsed.path)
        except ValueError as exc:
            self._send_error_json(HTTPStatus.BAD_REQUEST, str(exc))
        except Exception as exc:  # Keep API failures visible without exposing a traceback in the browser.
            print(f"本地网页请求失败：{exc}", file=sys.stderr)
            self._send_error_json(HTTPStatus.INTERNAL_SERVER_ERROR, f"本地服务处理失败：{exc}")

    def do_POST(self) -> None:  # noqa: N802 - required by BaseHTTPRequestHandler
        parsed = urllib.parse.urlsplit(self.path)
        query = urllib.parse.parse_qs(parsed.query, keep_blank_values=True)
        try:
            if parsed.path == "/api/client/closed":
                self.server.note_client_closed(_client_id(_first_query_value(query, "client_id")))
                self._send_json(HTTPStatus.OK, {"status": "accepted"})
                return
            if parsed.path == "/api/recipe-plans/refresh":
                self.server.note_client_activity(_client_id(self.headers.get("X-SurvivalLog-Client", "")))
                file_name = _first_query_value(query, "file_name")
                self._send_json(HTTPStatus.OK, self.server.service.refresh_recipe_save(file_name))
                return
            self._send_error_json(HTTPStatus.NOT_FOUND, "找不到 API 接口")
        except ValueError as exc:
            self._send_error_json(HTTPStatus.BAD_REQUEST, str(exc))
        except Exception as exc:  # Keep API failures visible without exposing a traceback in the browser.
            print(f"本地网页请求失败：{exc}", file=sys.stderr)
            self._send_error_json(HTTPStatus.INTERNAL_SERVER_ERROR, f"本地服务处理失败：{exc}")

    def log_message(self, format: str, *args: Any) -> None:
        print(f"{self.address_string()} - {format % args}", file=sys.stderr)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="启动 Survival Log 生存图鉴本地网页")
    parser.add_argument(
        "--port",
        type=int,
        default=DEFAULT_PORT,
        help="本地服务端口；默认端口被占用时自动选择空闲端口",
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
        "--headless",
        action="store_true",
        help="启动服务但不自动打开浏览器",
    )
    return parser.parse_args()


def run_local_server(
    database_path: Path,
    save_file: Path,
    port: int = DEFAULT_PORT,
    headless: bool = False,
    *,
    runtime_database_path: Path | None = None,
    log_path: Path | None = None,
) -> None:
    service = CodexService(
        database_path,
        save_file,
        runtime_database_path=runtime_database_path,
        log_path=log_path,
    )
    try:
        assets = static_root()
        try:
            server = CodexHTTPServer(
                ("127.0.0.1", port),
                service,
                assets,
                auto_exit=not headless,
            )
        except OSError:
            if port != DEFAULT_PORT:
                raise
            server = CodexHTTPServer(
                ("127.0.0.1", 0),
                service,
                assets,
                auto_exit=not headless,
            )
            print(f"默认端口 {DEFAULT_PORT} 已被占用，已改用端口 {server.server_address[1]}")
    except Exception:
        service.close()
        raise

    actual_port = server.server_address[1]
    url = f"http://127.0.0.1:{actual_port}/"
    print(f"图鉴本地网页：{url}")
    print(f"数据库：{service.database_path}")
    print(f"存档：{service.save_file}")
    if not headless:
        browser_timer = threading.Timer(0.25, webbrowser.open, args=(url,))
        browser_timer.daemon = True
        browser_timer.start()
    try:
        server.serve_forever(poll_interval=0.5)
    finally:
        server.server_close()
        service.close()


def main() -> int:
    try:
        args = parse_args()
        if not 1 <= args.port <= 65535:
            raise ValueError(f"端口必须在 1 到 65535 之间：{args.port}")
        args.database = args.database or default_database_path()
        runtime_database_path = (
            args.runtime_database
            if args.runtime_database is not None
            else default_runtime_database_path()
        )
        run_local_server(
            args.database,
            args.save_file,
            args.port,
            args.headless,
            runtime_database_path=runtime_database_path,
        )
    except KeyboardInterrupt:
        return 0
    except Exception as exc:
        print(f"图鉴本地网页启动失败：{exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
