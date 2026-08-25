#!/usr/bin/env python3
"""Read the read-only Survival Log HistorySave codex state."""

from __future__ import annotations

import hashlib
import argparse
import struct
import sys
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path


MAX_COLLECTION_LENGTH = 1_000_000
HISTORY_DATA_MEMBER_COUNT = 16
HISTORY_CHILD_MEMBER_COUNT = 26
ENDING_SNAPSHOT_MEMBER_COUNT = 3

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


@dataclass(frozen=True)
class SaveFileInfo:
    path: Path
    sha256: str
    size: int
    mtime_ns: int
    read_at: str
    used_backup: bool = False


@dataclass(frozen=True)
class CodexSaveState:
    file_info: SaveFileInfo
    category_ids: dict[str, tuple[int, ...]]
    raw_category_ids: dict[int, tuple[int, ...]]
    codex_offset: int
    trailing_offset: int

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
        return tuple(self.i32(f"{field}[{index}]") for index in range(count))

    def int_int_map(self, field: str) -> dict[int, int]:
        count = self.collection_count(field)
        if count is None:
            return {}
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


def _read_codex_map(reader: _Reader) -> tuple[dict[int, tuple[int, ...]], int]:
    codex_offset = reader.pos
    field = "PlayerSelectSaveFileMap"
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


def parse_codex_save_bytes(
    data: bytes,
    *,
    source_path: Path | None = None,
    file_info: SaveFileInfo | None = None,
) -> CodexSaveState:
    """Parse the HistoryData prefix that contains CodexUnlocked."""

    reader = _Reader(data)
    reader.object_member_count(HISTORY_DATA_MEMBER_COUNT, "HistoryData")

    history_count = reader.collection_count("HistoryList")
    if history_count is not None:
        for index in range(history_count):
            _skip_history_child(reader, index)

    reader.memorypack_string("LastPlayFileName")
    reader.int_list("UnlockedAchievementIds")
    reader.int_list("UnlockedPlayerSelectIds")
    reader.int_list("ClearedEndings")
    reader.int_int_map("GlobalEasterEggFlags")
    # In the current game schema the category-to-entry mapping is stored in
    # PlayerSelectSaveFileMap. CodexUnlocked itself is a separate int list.
    raw_categories, codex_offset = _read_codex_map(reader)
    reader.int_list("CodexUnlocked")
    reader.int_list("CodexMilestonesClaimed")
    reader.int_list("PendingUnlockNoticeIds")

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
        category: tuple(raw_categories.get(category_id, ()))
        for category_id, category in CODEX_CATEGORY_IDS.items()
    }
    return CodexSaveState(
        file_info=file_info,
        category_ids=category_ids,
        raw_category_ids=raw_categories,
        codex_offset=codex_offset,
        trailing_offset=reader.pos,
    )


def _read_stable_file(path: Path, *, used_backup: bool) -> CodexSaveState:
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
    return parse_codex_save_bytes(data, file_info=file_info)


def read_codex_save(save_file: Path, *, allow_backup: bool = True) -> CodexSaveState:
    """Read the active save, falling back to its .bak copy when necessary."""

    requested = Path(save_file).expanduser()
    candidates = [(requested, False)]
    backup = Path(f"{requested}.bak")
    if allow_backup and backup != requested:
        candidates.append((backup, True))

    errors: list[str] = []
    for candidate, used_backup in candidates:
        if not candidate.exists():
            errors.append(f"{candidate}：文件不存在")
            continue
        try:
            return _read_stable_file(candidate, used_backup=used_backup)
        except SaveParseError as exc:
            errors.append(str(exc))

    raise SaveParseError("无法读取有效的图鉴存档：" + "；".join(errors))


__all__ = [
    "CODEX_CATEGORY_IDS",
    "CODEX_CATEGORY_SOURCE_TABLES",
    "CodexSaveState",
    "SaveFileInfo",
    "SaveParseError",
    "default_save_file",
    "parse_codex_save_bytes",
    "read_codex_save",
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
    if state.file_info.used_backup:
        print("来源：.bak 备份")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
