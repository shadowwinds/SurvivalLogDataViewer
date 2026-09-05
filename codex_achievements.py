#!/usr/bin/env python3
"""Load and validate the human-readable Survival Log achievement conditions."""

from __future__ import annotations

import json
import math
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable, Mapping


CONDITION_CATALOG_FILENAME = "achievement_conditions.json"
CONDITION_SCHEMA_VERSION = 1


class AchievementConditionError(ValueError):
    """Raised when the condition catalog cannot be matched safely to game data."""


@dataclass(frozen=True)
class AchievementCondition:
    achievement_id: int
    name: str
    category: str
    hidden_in_text: bool
    condition: str
    method: str
    role_restriction: str
    notes: tuple[str, ...]
    common_notes: tuple[str, ...]
    numeric_threshold: float | None
    value_parameters: tuple[float, ...]
    exclusions: tuple[str, ...]
    config_references: tuple[str, ...]

    def as_json(self) -> dict[str, Any]:
        return {
            "id": self.achievement_id,
            "name": self.name,
            "category": self.category,
            "hidden_in_text": self.hidden_in_text,
            "condition": self.condition,
            "method": self.method,
            "role_restriction": self.role_restriction,
            "notes": list(self.notes),
            "common_notes": list(self.common_notes),
            "numeric_threshold": self.numeric_threshold,
            "value_parameters": list(self.value_parameters),
            "exclusions": list(self.exclusions),
            "config_references": list(self.config_references),
        }


def _condition_catalog_candidates() -> tuple[Path, ...]:
    candidates = [Path(__file__).resolve().parent / CONDITION_CATALOG_FILENAME]
    candidates.append(Path(sys.executable).resolve().parent / CONDITION_CATALOG_FILENAME)
    bundle_root = getattr(sys, "_MEIPASS", None)
    if bundle_root:
        candidates.append(Path(bundle_root) / CONDITION_CATALOG_FILENAME)
    unique: list[Path] = []
    seen: set[Path] = set()
    for candidate in candidates:
        resolved = candidate.expanduser().resolve()
        if resolved not in seen:
            seen.add(resolved)
            unique.append(resolved)
    return tuple(unique)


def condition_catalog_path(path: Path | None = None) -> Path:
    if path is not None:
        resolved = path.expanduser().resolve()
        if not resolved.is_file():
            raise AchievementConditionError(f"找不到成就条件说明文件：{resolved}")
        return resolved
    for candidate in _condition_catalog_candidates():
        if candidate.is_file():
            return candidate
    searched = "、".join(str(candidate) for candidate in _condition_catalog_candidates())
    raise AchievementConditionError(f"找不到成就条件说明文件；已检查：{searched}")


def _text(value: object, field: str, achievement_id: int) -> str:
    if not isinstance(value, str):
        raise AchievementConditionError(
            f"成就 {achievement_id} 的条件字段 {field} 必须是字符串"
        )
    return value.strip()


def _string_list(value: object, field: str, achievement_id: int) -> tuple[str, ...]:
    if not isinstance(value, list) or not all(isinstance(item, str) for item in value):
        raise AchievementConditionError(
            f"成就 {achievement_id} 的 {field} 必须是字符串列表"
        )
    return tuple(item.strip() for item in value if item.strip())


def _number_list(value: object, field: str, achievement_id: int) -> tuple[float, ...]:
    if not isinstance(value, list) or not all(
        isinstance(item, (int, float)) and not isinstance(item, bool)
        and math.isfinite(float(item))
        for item in value
    ):
        raise AchievementConditionError(
            f"成就 {achievement_id} 的 {field} 必须是有限数字列表"
        )
    return tuple(float(item) for item in value)


def _optional_number(value: object, field: str, achievement_id: int) -> float | None:
    if value is None:
        return None
    if (
        not isinstance(value, (int, float))
        or isinstance(value, bool)
        or not math.isfinite(float(value))
    ):
        raise AchievementConditionError(
            f"成就 {achievement_id} 的 {field} 必须是有限数字或 null"
        )
    return float(value)


def load_achievement_conditions(
    path: Path | None = None,
) -> tuple[str, tuple[str, ...], dict[int, AchievementCondition]]:
    source = condition_catalog_path(path)
    try:
        payload = json.loads(source.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise AchievementConditionError(f"读取成就条件说明失败：{source}：{exc}") from exc
    if not isinstance(payload, dict):
        raise AchievementConditionError("成就条件说明根节点必须是对象")
    if payload.get("schema_version") != CONDITION_SCHEMA_VERSION:
        raise AchievementConditionError(
            "成就条件说明 schema 版本不受支持："
            f"{payload.get('schema_version')!r}，当前支持 {CONDITION_SCHEMA_VERSION}"
        )
    raw_source_tables = payload.get("source_tables")
    if not isinstance(raw_source_tables, list) or not raw_source_tables or not all(
        isinstance(value, str) and value.strip() for value in raw_source_tables
    ):
        raise AchievementConditionError("成就条件说明的 source_tables 必须是非空字符串列表")
    source_version = payload.get("source_version")
    if not isinstance(source_version, str) or not source_version.strip():
        raise AchievementConditionError("成就条件说明缺少 source_version")
    raw_common_notes = payload.get("common_notes", [])
    if not isinstance(raw_common_notes, list) or not all(
        isinstance(value, str) and value.strip() for value in raw_common_notes
    ):
        raise AchievementConditionError("成就条件说明的 common_notes 必须是非空字符串列表")
    common_notes = tuple(value.strip() for value in raw_common_notes)
    raw_records = payload.get("achievements")
    if not isinstance(raw_records, list):
        raise AchievementConditionError("成就条件说明缺少 achievements 列表")

    result: dict[int, AchievementCondition] = {}
    for index, raw_record in enumerate(raw_records):
        if not isinstance(raw_record, dict):
            raise AchievementConditionError(f"成就条件说明第 {index} 项不是对象")
        achievement_id = raw_record.get("id")
        if not isinstance(achievement_id, int) or isinstance(achievement_id, bool) or achievement_id <= 0:
            raise AchievementConditionError(f"成就条件说明第 {index} 项 ID 非法：{achievement_id!r}")
        if achievement_id in result:
            raise AchievementConditionError(f"成就条件说明出现重复 ID：{achievement_id}")
        notes = raw_record.get("notes", [])
        if not isinstance(notes, list) or not all(isinstance(value, str) for value in notes):
            raise AchievementConditionError(f"成就 {achievement_id} 的 notes 必须是字符串列表")
        hidden_in_text = raw_record.get("hidden_in_text", False)
        if not isinstance(hidden_in_text, bool):
            raise AchievementConditionError(
                f"成就 {achievement_id} 的 hidden_in_text 必须是布尔值"
            )
        numeric_threshold = _optional_number(
            raw_record.get("numeric_threshold"),
            "numeric_threshold",
            achievement_id,
        )
        result[achievement_id] = AchievementCondition(
            achievement_id=achievement_id,
            name=_text(raw_record.get("name"), "name", achievement_id),
            category=_text(raw_record.get("category"), "category", achievement_id),
            hidden_in_text=hidden_in_text,
            condition=_text(raw_record.get("condition"), "condition", achievement_id),
            method=_text(raw_record.get("method", ""), "method", achievement_id),
            role_restriction=_text(
                raw_record.get("role_restriction", ""),
                "role_restriction",
                achievement_id,
            ),
            notes=tuple(value.strip() for value in notes if value.strip()),
            common_notes=common_notes if 1102 <= achievement_id <= 1108 else (),
            numeric_threshold=numeric_threshold,
            value_parameters=_number_list(
                raw_record.get("value_parameters", []),
                "value_parameters",
                achievement_id,
            ),
            exclusions=_string_list(
                raw_record.get("exclusions", []),
                "exclusions",
                achievement_id,
            ),
            config_references=_string_list(
                raw_record.get("config_references", []),
                "config_references",
                achievement_id,
            ),
        )
    return source_version.strip(), common_notes, result


def validate_achievement_conditions(
    config_rows: Iterable[Any],
    package_version: str,
    conditions: Mapping[int, AchievementCondition],
    source_version: str,
) -> None:
    """Validate manual notes against a selected Config_Achievement snapshot.

    The version arguments are retained for API compatibility and metadata
    reporting. Manual condition content is not version-gated.
    """

    del package_version, source_version
    config_by_id: dict[int, Any] = {}
    for row in config_rows:
        row_id = int(row.row_id)
        if row_id in config_by_id:
            raise AchievementConditionError(f"Config_Achievement 出现重复 ID：{row_id}")
        config_by_id[row_id] = row
    config_ids = set(config_by_id)
    condition_ids = set(conditions)
    missing = sorted(config_ids - condition_ids)
    extra = sorted(condition_ids - config_ids)
    if missing or extra:
        parts = []
        if missing:
            parts.append(f"配置中缺少说明 ID：{missing}")
        if extra:
            parts.append(f"说明中存在配置没有的 ID：{extra}")
        raise AchievementConditionError("成就条件说明与 Config_Achievement 不一致；" + "；".join(parts))
    for achievement_id, condition in conditions.items():
        config_values = config_by_id[achievement_id].values
        config_name = str(config_values.get("Name_Local") or config_values.get("Name") or "")
        if config_name != condition.name:
            raise AchievementConditionError(
                f"成就 {achievement_id} 的名称与说明不一致："
                f"配置={config_name!r}，说明={condition.name!r}"
            )
        config_hidden = bool(config_values.get("IsHidden", False))
        if config_hidden != condition.hidden_in_text:
            raise AchievementConditionError(
                f"成就 {achievement_id} 的隐藏标记与说明不一致："
                f"配置={config_hidden}，说明={condition.hidden_in_text}"
            )


__all__ = [
    "AchievementCondition",
    "AchievementConditionError",
    "CONDITION_SCHEMA_VERSION",
    "condition_catalog_path",
    "load_achievement_conditions",
    "validate_achievement_conditions",
]
