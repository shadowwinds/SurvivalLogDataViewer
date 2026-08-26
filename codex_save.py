#!/usr/bin/env python3
"""Read the read-only Survival Log HistorySave codex state."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import struct
import sys
from collections.abc import Collection, Mapping
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from threading import Lock


MAX_COLLECTION_LENGTH = 1_000_000
HISTORY_DATA_MEMBER_COUNT = 16
HISTORY_CHILD_MEMBER_COUNT = 26
ENDING_SNAPSHOT_MEMBER_COUNT = 3
POST_CODEX_LIST_COUNT = 3
MAX_DIAGNOSTIC_LOG_BYTES = 2 * 1024 * 1024

CODEX_CATEGORY_IDS = {
    1: "food",
    2: "dish",
    3: "plant",
    4: "prey",
    5: "craft",
    6: "furniture",
}
CODEX_CATEGORY_SOURCE_TABLES = {
    "food": "Config_Item",
    "dish": "Config_CookingRecipe",
    "plant": "Config_Plant",
    "prey": "Config_Item",
    "craft": "Config_ProductionList",
    "furniture": "Config_Furniture",
}


class SaveParseError(ValueError):
    """Raised when a HistorySave file does not match the known wire schema."""

    def __init__(
        self,
        message: str,
        *,
        code: str = "save_parse_error",
        stage: str = "wire_read",
        offset: int | None = None,
        details: Mapping[str, object] | None = None,
    ) -> None:
        super().__init__(message)
        self.code = code
        self.stage = stage
        self.offset = offset
        self.details = dict(details or {})


@dataclass(frozen=True)
class SaveFileInfo:
    path: Path
    sha256: str
    size: int
    mtime_ns: int
    read_at: str
    used_backup: bool = False


@dataclass(frozen=True)
class CodexMapCandidate:
    """A structurally valid codex mapping found at an arbitrary file offset."""

    offset: int
    end_offset: int
    raw_category_ids: dict[int, tuple[int, ...]]
    post_map_end_offset: int
    tail_list_count: int
    known_id_count: int
    unknown_ids: dict[str, tuple[int, ...]]
    score: tuple[int, int, int, int, int]
    layout: str


@dataclass(frozen=True)
class CodexSaveState:
    file_info: SaveFileInfo
    category_ids: dict[str, tuple[int, ...]]
    raw_category_ids: dict[int, tuple[int, ...]]
    codex_offset: int
    trailing_offset: int
    codex_end_offset: int = 0
    schema_profile: str = "unknown"
    candidate_count: int = 1
    candidate_score: tuple[int, ...] = ()
    candidate_offsets: tuple[int, ...] = ()
    unknown_ids: dict[str, tuple[int, ...]] = field(default_factory=dict)

    @property
    def category_counts(self) -> dict[str, int]:
        return {category: len(self.category_ids.get(category, ())) for category in CODEX_CATEGORY_IDS.values()}

    @property
    def total_memberships(self) -> int:
        return sum(self.category_counts.values())


def default_save_file() -> Path:
    """Return the default per-user save location without touching the game directory."""

    return (
        Path.home()
        / "AppData"
        / "LocalLow"
        / "LLS"
        / "SLGame"
        / "Saves"
        / "HistorySave.bytes"
    )


class _Reader:
    def __init__(self, data: bytes):
        self.data = data
        self.pos = 0

    def _need(self, size: int, field: str) -> None:
        if size < 0 or self.pos + size > len(self.data):
            raise SaveParseError(
                f"存档字段 {field} 超出文件范围：offset={self.pos}, need={size}, total={len(self.data)}"
            )

    def u8(self, field: str) -> int:
        self._need(1, field)
        value = self.data[self.pos]
        self.pos += 1
        return value

    def boolean(self, field: str) -> bool:
        value = self.u8(field)
        if value not in (0, 1):
            raise SaveParseError(f"存档字段 {field} 的布尔值非法：{value} at offset={self.pos - 1}")
        return bool(value)

    def i32(self, field: str) -> int:
        self._need(4, field)
        value = struct.unpack_from("<i", self.data, self.pos)[0]
        self.pos += 4
        return value

    def collection_count(self, field: str) -> int | None:
        count = self.i32(field)
        if count == -1:
            return None
        if count < -1 or count > MAX_COLLECTION_LENGTH:
            raise SaveParseError(f"存档字段 {field} 的集合长度非法：{count} at offset={self.pos - 4}")
        return count

    def memorypack_string(self, field: str) -> str | None:
        marker = self.i32(field)
        if marker == -1:
            return None
        if marker == 0:
            return ""
        if marker <= -2:
            utf8_size = ~marker
            utf16_length = self.i32(f"{field}.utf16_length")
            if utf8_size < 0 or utf16_length < 0:
                raise SaveParseError(f"存档字段 {field} 的字符串长度非法")
            self._need(utf8_size, field)
            raw = self.data[self.pos : self.pos + utf8_size]
            self.pos += utf8_size
            try:
                return raw.decode("utf-8")
            except UnicodeDecodeError as exc:
                raise SaveParseError(f"存档字段 {field} 不是有效 UTF-8：offset={self.pos - utf8_size}") from exc
        utf16_size = marker * 2
        self._need(utf16_size, field)
        raw = self.data[self.pos : self.pos + utf16_size]
        self.pos += utf16_size
        try:
            return raw.decode("utf-16-le")
        except UnicodeDecodeError as exc:
            raise SaveParseError(f"存档字段 {field} 不是有效 UTF-16：offset={self.pos - utf16_size}") from exc

    def int_list(self, field: str) -> tuple[int, ...] | None:
        count = self.collection_count(field)
        if count is None:
            return None
        if count > (len(self.data) - self.pos) // 4:
            raise SaveParseError(
                f"存档字段 {field} 的集合长度超出剩余文件范围：count={count}, offset={self.pos}, total={len(self.data)}"
            )
        return tuple(self.i32(f"{field}[{index}]") for index in range(count))

    def int_int_map(self, field: str) -> dict[int, int]:
        count = self.collection_count(field)
        if count is None:
            return {}
        if count > (len(self.data) - self.pos) // 8:
            raise SaveParseError(
                f"存档字段 {field} 的集合长度超出剩余文件范围：count={count}, offset={self.pos}, total={len(self.data)}"
            )
        result: dict[int, int] = {}
        for index in range(count):
            key = self.i32(f"{field}[{index}].key")
            if key in result:
                raise SaveParseError(f"存档字段 {field} 出现重复键：{key}")
            result[key] = self.i32(f"{field}[{index}].value")
        return result

    def int_string_map(self, field: str) -> dict[int, str | None]:
        count = self.collection_count(field)
        if count is None:
            return {}
        result: dict[int, str | None] = {}
        for index in range(count):
            key = self.i32(f"{field}[{index}].key")
            if key in result:
                raise SaveParseError(f"存档字段 {field} 出现重复键：{key}")
            result[key] = self.memorypack_string(f"{field}[{index}].value")
        return result

    def object_member_count(self, expected: int, field: str) -> None:
        actual = self.u8(f"{field}.member_count")
        if actual != expected:
            raise SaveParseError(
                f"存档字段 {field} 的成员数量变化：actual={actual}, expected={expected}, offset={self.pos - 1}"
            )


def _skip_history_child(reader: _Reader, index: int) -> None:
    field = f"HistoryList[{index}]"
    reader.object_member_count(HISTORY_CHILD_MEMBER_COUNT, field)
    reader.memorypack_string(f"{field}.FileName")
    reader.memorypack_string(f"{field}.Name")
    for name in ("PlayerSelectId", "MaxDay", "Turn"):
        reader.i32(f"{field}.{name}")
    reader.boolean(f"{field}.HasProgressMeta")
    for name in ("InitChapterId", "GameTime", "Day", "ExtraCountDownTime"):
        reader.i32(f"{field}.{name}")
    reader.boolean(f"{field}.IsFinished")
    reader.i32(f"{field}.FinishResult")
    reader.boolean(f"{field}.HasProgressMetaV2")
    reader.i32(f"{field}.DifficultyPresetId")
    reader.int_list(f"{field}.DifficultyLevels")
    reader.boolean(f"{field}.HasDifficultyMeta")
    reader.boolean(f"{field}.IsPureEndless")
    reader.i32(f"{field}.EndlessStartDay")
    reader.boolean(f"{field}.HasEndlessMeta")
    reader.i32(f"{field}.SaveOrigin")
    reader.boolean(f"{field}.IsStoryEndless")
    reader.i32(f"{field}.StoryEndlessOriginEnding")
    reader.boolean(f"{field}.HasEndingSnapshot")
    reader.i32(f"{field}.SnapshotEnding")
    reader.i32(f"{field}.SnapshotDay")
    snapshot_count = reader.collection_count(f"{field}.EndingSnapshots")
    if snapshot_count is None:
        return
    for snapshot_index in range(snapshot_count):
        snapshot_field = f"{field}.EndingSnapshots[{snapshot_index}]"
        reader.object_member_count(ENDING_SNAPSHOT_MEMBER_COUNT, snapshot_field)
        reader.i32(f"{snapshot_field}.EndingId")
        reader.i32(f"{snapshot_field}.Day")
        reader.i32(f"{snapshot_field}.TurnIndex")


def _read_codex_map(
    reader: _Reader,
    *,
    field: str = "PlayerSelectSaveFileMap",
) -> tuple[dict[int, tuple[int, ...]], int]:
    codex_offset = reader.pos
    count = reader.collection_count(field)
    if count is None:
        return {}, codex_offset
    if count > len(CODEX_CATEGORY_IDS):
        raise SaveParseError(f"{field} 分类数量超出已知范围：{count}")

    raw_categories: dict[int, tuple[int, ...]] = {}
    for index in range(count):
        category_id = reader.i32(f"{field}[{index}].category_id")
        if category_id not in CODEX_CATEGORY_IDS:
            raise SaveParseError(
                f"{field} 出现未知分类 ID：{category_id} at offset={reader.pos - 4}"
            )
        if category_id in raw_categories:
            raise SaveParseError(f"{field} 出现重复分类 ID：{category_id}")
        ids = reader.int_list(f"{field}[{index}].ids") or ()
        if any(source_id <= 0 for source_id in ids):
            raise SaveParseError(f"{field}[{index}] 包含非法源 ID：{ids!r}")
        if len(set(ids)) != len(ids):
            raise SaveParseError(f"{field}[{index}] 包含重复源 ID")
        raw_categories[category_id] = ids
    return raw_categories, codex_offset


def _read_common_prefix(reader: _Reader) -> int:
    """Read fields whose order is shared before the variable codex region."""

    reader.object_member_count(HISTORY_DATA_MEMBER_COUNT, "HistoryData")

    history_count = reader.collection_count("HistoryList")
    if history_count is not None:
        for index in range(history_count):
            _skip_history_child(reader, index)

    reader.memorypack_string("LastPlayFileName")
    reader.int_list("UnlockedAchievementIds")
    reader.int_list("UnlockedPlayerSelectIds")
    reader.int_list("ClearedEndings")
    return reader.pos


def _normalize_known_category_ids(
    known_category_ids: Mapping[str, Collection[int]] | None,
) -> dict[str, frozenset[int]] | None:
    if known_category_ids is None:
        return None
    return {
        category: frozenset(int(source_id) for source_id in known_category_ids.get(category, ()))
        for category in CODEX_CATEGORY_IDS.values()
    }


def _probe_post_map(data: bytes, offset: int) -> tuple[int, int]:
    """Probe the integer-list chain that follows a codex map."""

    reader = _Reader(data)
    reader.pos = offset
    list_count = 0
    for index in range(POST_CODEX_LIST_COUNT):
        try:
            reader.int_list(f"post_codex_list[{index}]")
        except SaveParseError:
            break
        list_count += 1
    return list_count, reader.pos


def _candidate_unknown_ids(
    raw_category_ids: dict[int, tuple[int, ...]],
    known_category_ids: dict[str, frozenset[int]] | None,
) -> tuple[int, dict[str, tuple[int, ...]]]:
    if known_category_ids is None:
        return 0, {}

    known_count = 0
    unknown_ids: dict[str, tuple[int, ...]] = {}
    for category_id, source_ids in raw_category_ids.items():
        category = CODEX_CATEGORY_IDS[category_id]
        unknown = tuple(
            source_id
            for source_id in source_ids
            if source_id not in known_category_ids.get(category, frozenset())
        )
        known_count += len(source_ids) - len(unknown)
        if unknown:
            unknown_ids[category] = unknown
    return known_count, unknown_ids


def _scan_codex_map_candidates(
    data: bytes,
    start_offset: int,
    *,
    known_category_ids: Mapping[str, Collection[int]] | None = None,
    minimum_tail_lists: int = 1,
    require_full_categories: bool = False,
) -> list[CodexMapCandidate]:
    """Find valid codex maps without assuming an absolute byte offset."""

    normalized_known_ids = _normalize_known_category_ids(known_category_ids)
    candidates: list[CodexMapCandidate] = []
    start = max(1, start_offset)
    end = len(data) - 3
    for offset in range(start, end):
        reader = _Reader(data)
        reader.pos = offset
        try:
            raw_category_ids, _ = _read_codex_map(reader, field=f"CodexMap@{offset}")
        except SaveParseError:
            continue
        if not raw_category_ids:
            continue
        if require_full_categories and len(raw_category_ids) != len(CODEX_CATEGORY_IDS):
            continue
        if len(raw_category_ids) < len(CODEX_CATEGORY_IDS) and not any(raw_category_ids.values()):
            continue

        tail_list_count, post_map_end_offset = _probe_post_map(data, reader.pos)
        if tail_list_count < minimum_tail_lists:
            continue

        total_ids = sum(len(source_ids) for source_ids in raw_category_ids.values())
        known_count, unknown_ids = _candidate_unknown_ids(raw_category_ids, normalized_known_ids)
        unknown_count = total_ids - known_count if normalized_known_ids is not None else 0
        known_ratio = 1000 if total_ids == 0 else (known_count * 1000) // total_ids
        score = (
            tail_list_count,
            len(raw_category_ids),
            known_ratio,
            known_count,
            -unknown_count,
        )
        candidates.append(
            CodexMapCandidate(
                offset=offset,
                end_offset=reader.pos,
                raw_category_ids=raw_category_ids,
                post_map_end_offset=post_map_end_offset,
                tail_list_count=tail_list_count,
                known_id_count=known_count,
                unknown_ids=unknown_ids,
                score=score,
                layout=f"scanned-tail-{tail_list_count}",
            )
        )
    return candidates


def _mapping_signature(raw_category_ids: dict[int, tuple[int, ...]]) -> tuple[tuple[int, tuple[int, ...]], ...]:
    return tuple(sorted(raw_category_ids.items()))


def _format_candidate_summary(candidates: Collection[CodexMapCandidate]) -> str:
    ordered = sorted(candidates, key=lambda candidate: candidate.score, reverse=True)
    return "；".join(
        f"offset={candidate.offset}, end={candidate.end_offset}, score={candidate.score}, categories={len(candidate.raw_category_ids)}"
        for candidate in ordered[:8]
    )


def _select_codex_map_candidate(
    candidates: list[CodexMapCandidate],
    *,
    file_size: int,
    search_start: int,
    prefix_error: SaveParseError | None = None,
) -> CodexMapCandidate:
    if not candidates:
        details = {
            "file_size": file_size,
            "search_start": search_start,
        }
        if prefix_error is not None:
            details["prefix_error"] = str(prefix_error)
        raise SaveParseError(
            f"未找到有效的图鉴映射：stage=codex_map_scan, search_start={search_start}, file_size={file_size}"
            + (f"；公共前缀解析失败：{prefix_error}" if prefix_error is not None else ""),
            code="codex_map_not_found",
            stage="codex_map_scan",
            offset=search_start,
            details=details,
        )

    best_score = max(candidate.score for candidate in candidates)
    best = [candidate for candidate in candidates if candidate.score == best_score]
    mappings = {_mapping_signature(candidate.raw_category_ids) for candidate in best}
    if len(mappings) > 1:
        summary = _format_candidate_summary(best)
        raise SaveParseError(
            f"图鉴映射存在歧义：最高评分={best_score}，候选={summary}",
            code="ambiguous_codex_map",
            stage="codex_map_scan",
            details={
                "file_size": file_size,
                "search_start": search_start,
                "candidate_count": len(candidates),
                "candidates": summary,
            },
        )

    return min(best, key=lambda candidate: (candidate.offset, candidate.end_offset))


def parse_codex_save_bytes(
    data: bytes,
    *,
    source_path: Path | None = None,
    file_info: SaveFileInfo | None = None,
    known_category_ids: Mapping[str, Collection[int]] | None = None,
) -> CodexSaveState:
    """Parse the HistoryData prefix and discover the codex map by structure."""

    prefix_error: SaveParseError | None = None
    reader = _Reader(data)
    try:
        search_start = _read_common_prefix(reader)
    except SaveParseError as exc:
        prefix_error = exc
        search_start = 1

    candidates = _scan_codex_map_candidates(
        data,
        search_start,
        known_category_ids=known_category_ids,
        minimum_tail_lists=POST_CODEX_LIST_COUNT if prefix_error is not None else 1,
        require_full_categories=prefix_error is not None,
    )
    if not candidates:
        candidates = _scan_codex_map_candidates(
            data,
            1,
            known_category_ids=known_category_ids,
            minimum_tail_lists=POST_CODEX_LIST_COUNT,
            require_full_categories=True,
        )
    selected = _select_codex_map_candidate(
        candidates,
        file_size=len(data),
        search_start=search_start,
        prefix_error=prefix_error,
    )

    if file_info is None:
        path = source_path or Path("<memory>")
        file_info = SaveFileInfo(
            path=path,
            sha256=hashlib.sha256(data).hexdigest(),
            size=len(data),
            mtime_ns=0,
            read_at=datetime.now().astimezone().isoformat(timespec="seconds"),
        )

    category_ids = {
        category: tuple(selected.raw_category_ids.get(category_id, ()))
        for category_id, category in CODEX_CATEGORY_IDS.items()
    }
    return CodexSaveState(
        file_info=file_info,
        category_ids=category_ids,
        raw_category_ids=selected.raw_category_ids,
        codex_offset=selected.offset,
        trailing_offset=selected.post_map_end_offset,
        codex_end_offset=selected.end_offset,
        schema_profile=selected.layout,
        candidate_count=len(candidates),
        candidate_score=selected.score,
        candidate_offsets=tuple(candidate.offset for candidate in candidates),
        unknown_ids=selected.unknown_ids,
    )


def _read_stable_file(
    path: Path,
    *,
    used_backup: bool,
    known_category_ids: Mapping[str, Collection[int]] | None = None,
) -> CodexSaveState:
    try:
        before = path.stat()
    except OSError as exc:
        raise SaveParseError(f"无法读取存档文件 {path}：{exc}") from exc
    if not path.is_file():
        raise SaveParseError(f"存档路径不是文件：{path}")

    try:
        data = path.read_bytes()
        after = path.stat()
    except OSError as exc:
        raise SaveParseError(f"读取存档文件失败 {path}：{exc}") from exc
    if before.st_size != after.st_size or before.st_mtime_ns != after.st_mtime_ns:
        raise SaveParseError(f"存档正在写入，读取期间文件发生变化：{path}")

    file_info = SaveFileInfo(
        path=path,
        sha256=hashlib.sha256(data).hexdigest(),
        size=after.st_size,
        mtime_ns=after.st_mtime_ns,
        read_at=datetime.now().astimezone().isoformat(timespec="seconds"),
        used_backup=used_backup,
    )
    return parse_codex_save_bytes(
        data,
        file_info=file_info,
        known_category_ids=known_category_ids,
    )


def read_codex_save(
    save_file: Path,
    *,
    allow_backup: bool = True,
    known_category_ids: Mapping[str, Collection[int]] | None = None,
) -> CodexSaveState:
    """Read the active save, falling back to its .bak copy when necessary."""

    requested = Path(save_file).expanduser()
    candidates = [(requested, False)]
    backup = Path(f"{requested}.bak")
    if allow_backup and backup != requested:
        candidates.append((backup, True))

    errors: list[str] = []
    last_error: SaveParseError | None = None
    for candidate, used_backup in candidates:
        if not candidate.exists():
            errors.append(f"{candidate}：文件不存在")
            continue
        try:
            return _read_stable_file(
                candidate,
                used_backup=used_backup,
                known_category_ids=known_category_ids,
            )
        except SaveParseError as exc:
            errors.append(str(exc))
            last_error = exc

    raise SaveParseError(
        "无法读取有效的图鉴存档：" + "；".join(errors),
        code=last_error.code if last_error is not None else "save_file_unavailable",
        stage=last_error.stage if last_error is not None else "file_open",
        offset=last_error.offset if last_error is not None else None,
        details={
            "attempts": errors,
            **(last_error.details if last_error is not None else {}),
        },
    )


_DIAGNOSTIC_LOG_LOCK = Lock()
_DIAGNOSTIC_LOG_KEYS: set[str] = set()


def _redact_text(value: str) -> str:
    home = str(Path.home().expanduser().resolve())
    text = str(value)
    home_casefold = home.casefold()
    text_casefold = text.casefold()
    if text_casefold == home_casefold or text_casefold.startswith(
        (home + os.sep).casefold()
    ) or text_casefold.startswith((home + "/").casefold()):
        return "%USERPROFILE%" + text[len(home) :]
    return text.replace(home, "%USERPROFILE%")


def _redact_path(path: Path | str | None) -> str | None:
    if path is None:
        return None
    return _redact_text(str(Path(path).expanduser().resolve()))


def _diagnostic_fallback_path(log_path: Path) -> Path:
    local_app_data = os.environ.get("LOCALAPPDATA")
    base = (
        Path(local_app_data)
        if local_app_data
        else Path.home() / "AppData" / "Local"
    )
    return base / "SurvivalLogDataViewer" / log_path.name


def _json_default(value: object) -> object:
    if isinstance(value, Path):
        return _redact_path(value)
    if isinstance(value, tuple):
        return list(value)
    return str(value)


def build_save_diagnostic(
    requested_path: Path,
    *,
    status: str,
    state: CodexSaveState | None = None,
    error: BaseException | None = None,
) -> dict[str, object]:
    """Build a redacted, byte-free diagnostic event for runtime logging."""

    payload: dict[str, object] = {
        "event": "save_sync",
        "status": status,
        "timestamp": datetime.now().astimezone().isoformat(timespec="seconds"),
        "requested_path": _redact_path(requested_path),
    }
    if state is not None:
        payload.update(
            {
                "actual_path": _redact_path(state.file_info.path),
                "size": state.file_info.size,
                "mtime_ns": state.file_info.mtime_ns,
                "sha256": state.file_info.sha256,
                "used_backup": state.file_info.used_backup,
                "schema_profile": state.schema_profile,
                "codex_offset": state.codex_offset,
                "codex_end_offset": state.codex_end_offset,
                "trailing_offset": state.trailing_offset,
                "candidate_count": state.candidate_count,
                "candidate_score": list(state.candidate_score),
                "candidate_offsets": list(state.candidate_offsets),
                "category_counts": state.category_counts,
                "unknown_ids": {
                    category: list(values)
                    for category, values in state.unknown_ids.items()
                },
            }
        )
    else:
        try:
            requested = requested_path.expanduser()
            data = requested.read_bytes()
            stat = requested.stat()
        except OSError:
            data = b""
            stat = None
        payload.update(
            {
                "actual_path": None,
                "size": stat.st_size if stat is not None else None,
                "mtime_ns": stat.st_mtime_ns if stat is not None else None,
                "sha256": hashlib.sha256(data).hexdigest() if stat is not None else "",
                "used_backup": False,
            }
        )
    if error is not None:
        payload["error"] = _redact_text(str(error))
        if isinstance(error, SaveParseError):
            payload.update(
                {
                    "error_code": error.code,
                    "error_stage": error.stage,
                    "error_offset": error.offset,
                    "error_details": {
                        key: _redact_text(value) if isinstance(value, str) else value
                        for key, value in error.details.items()
                    },
                }
            )
    return payload


def write_save_diagnostic(
    log_path: Path | None,
    payload: Mapping[str, object],
    *,
    dedupe_key: str | None = None,
) -> Path | None:
    """Append one diagnostic event, returning the actual log path if written."""

    if log_path is None:
        return None
    requested_log_path = log_path.expanduser().resolve()
    candidates = [requested_log_path, _diagnostic_fallback_path(requested_log_path)]
    unique_paths: list[Path] = []
    seen: set[str] = set()
    for candidate in candidates:
        key = os.path.normcase(str(candidate))
        if key not in seen:
            seen.add(key)
            unique_paths.append(candidate)

    serialized = json.dumps(
        dict(payload),
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        default=_json_default,
    )
    dedupe_payload = {
        key: value for key, value in dict(payload).items() if key != "timestamp"
    }
    event_key = dedupe_key or json.dumps(
        dedupe_payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        default=_json_default,
    )
    with _DIAGNOSTIC_LOG_LOCK:
        if event_key in _DIAGNOSTIC_LOG_KEYS:
            return None
        for candidate in unique_paths:
            try:
                candidate.parent.mkdir(parents=True, exist_ok=True)
                if candidate.is_file() and candidate.stat().st_size >= MAX_DIAGNOSTIC_LOG_BYTES:
                    rotated = Path(f"{candidate}.1")
                    candidate.replace(rotated)
                with candidate.open("a", encoding="utf-8", newline="\n") as handle:
                    handle.write(serialized)
                    handle.write("\n")
            except OSError:
                continue
            if len(_DIAGNOSTIC_LOG_KEYS) >= 2048:
                _DIAGNOSTIC_LOG_KEYS.clear()
            _DIAGNOSTIC_LOG_KEYS.add(event_key)
            return candidate
    return None


__all__ = [
    "CODEX_CATEGORY_IDS",
    "CODEX_CATEGORY_SOURCE_TABLES",
    "CodexMapCandidate",
    "CodexSaveState",
    "SaveFileInfo",
    "SaveParseError",
    "build_save_diagnostic",
    "default_save_file",
    "parse_codex_save_bytes",
    "read_codex_save",
    "write_save_diagnostic",
]


def main() -> int:
    parser = argparse.ArgumentParser(description="读取 Survival Log HistorySave 图鉴完成状态")
    parser.add_argument(
        "--save-file",
        type=Path,
        default=default_save_file(),
        help="HistorySave.bytes 存档路径",
    )
    args = parser.parse_args()
    try:
        state = read_codex_save(args.save_file)
    except SaveParseError as exc:
        print(f"存档解析失败：{exc}", file=sys.stderr)
        return 1
    print(f"存档：{state.file_info.path}")
    print("；".join(f"{category}={count}" for category, count in state.category_counts.items()))
    print(f"分类完成映射：{state.total_memberships}")
    print(
        f"图鉴映射：offset={state.codex_offset}, end={state.codex_end_offset}, "
        f"candidates={state.candidate_count}, score={state.candidate_score}, "
        f"profile={state.schema_profile}"
    )
    if state.file_info.used_backup:
        print("来源：.bak 备份")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
