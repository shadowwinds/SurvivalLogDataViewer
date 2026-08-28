#!/usr/bin/env python3
"""Read the read-only Survival Log HistorySave codex state."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
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
HISTORY_SAVE_FILENAME_RE = re.compile(r"Save_[A-Za-z0-9_-]+\.bytes\Z")

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
# Kept as a public compatibility symbol; storage detection uses config behavior.
ALLOWED_STORAGE_FURNITURE_NAMES = frozenset(
    {
        "双门冰箱",
        "豪华版双门冰箱",
        "双开门冰箱",
        "冰柜",
    }
)
STORAGE_FURNITURE_FUNC_ID = 215
# These prefixes are role-specific.  A save's PlayerSelectId is the source of
# truth; the leading-role config is only a compatibility fallback for older
# fixtures that do not capture PlayerSelectId.
PLAYER_HOME_STORAGE_SLOT_PREFIXES = {
    1: ("homebuildingpos", "home_"),
    2: ("neighborgirlbuildingpos",),
    3: ("warehousepos",),
}
PLAYER_SELECT_ID_BY_AGENT_CONFIG_ID = {1: 1, 1002: 2, 1003: 3}
KNOWN_HOME_STORAGE_SLOT_PREFIXES = frozenset(
    prefix
    for prefixes in PLAYER_HOME_STORAGE_SLOT_PREFIXES.values()
    for prefix in prefixes
)
# Public compatibility symbols retained for callers that imported the old
# role-1 defaults.  Location inference below is role-aware.
HOME_STORAGE_SLOT_PREFIXES = PLAYER_HOME_STORAGE_SLOT_PREFIXES[1]
NON_HOME_STORAGE_SLOT_PREFIXES = ()
STORAGE_LOCATION_HOME = "home"
STORAGE_LOCATION_OTHER = "other"
STORAGE_LOCATION_UNKNOWN = "unknown"
STORAGE_LOCATION_LABELS = {
    STORAGE_LOCATION_HOME: "家中",
    STORAGE_LOCATION_OTHER: "其他位置",
    STORAGE_LOCATION_UNKNOWN: "位置未知",
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
class SaveHistoryRecord:
    """The child-save index stored in HistoryData.HistoryList."""

    file_name: str
    name: str
    player_select_id: int
    max_day: int
    turn: int
    is_finished: bool
    finish_result: int
    difficulty_preset_id: int
    difficulty_levels: tuple[int, ...]
    is_pure_endless: bool
    endless_start_day: int
    is_story_endless: bool
    story_endless_origin_ending: int


@dataclass(frozen=True)
class StorageContainer:
    """One placed storage container and the location inferred from its save fields."""

    config_id: int | None
    name: str
    instance_id: int | None
    map_config_id: int | None
    home_map_config_id: int | None
    chapter_map_key: int | None
    chapter_id: int | None
    slot_pos_point: str
    location: str
    is_home: bool | None
    item_stack_count: int = 0


@dataclass(frozen=True)
class InventoryItem:
    """One ItemSave stack with its original storage location."""

    item_config_id: int
    item_count: int
    source: str
    container: str


@dataclass(frozen=True)
class SaveInventoryState:
    file_info: SaveFileInfo
    items: tuple[InventoryItem, ...]
    diagnostics: tuple[str, ...] = ()
    container_counts: dict[str, int] = field(default_factory=dict)
    storage_containers: tuple[StorageContainer, ...] = ()


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
    history_records: tuple[SaveHistoryRecord, ...] = ()
    last_play_file_name: str = ""

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

    def i64(self, field: str) -> int:
        self._need(8, field)
        value = struct.unpack_from("<q", self.data, self.pos)[0]
        self.pos += 8
        return value

    def f32(self, field: str) -> float:
        self._need(4, field)
        value = struct.unpack_from("<f", self.data, self.pos)[0]
        self.pos += 4
        return value

    def raw(self, size: int, field: str) -> bytes:
        self._need(size, field)
        value = self.data[self.pos : self.pos + size]
        self.pos += size
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


def _read_history_child(reader: _Reader, index: int) -> SaveHistoryRecord:
    field = f"HistoryList[{index}]"
    reader.object_member_count(HISTORY_CHILD_MEMBER_COUNT, field)
    file_name = reader.memorypack_string(f"{field}.FileName") or ""
    name = reader.memorypack_string(f"{field}.Name") or ""
    player_select_id = reader.i32(f"{field}.PlayerSelectId")
    max_day = reader.i32(f"{field}.MaxDay")
    turn = reader.i32(f"{field}.Turn")
    reader.boolean(f"{field}.HasProgressMeta")
    for field_name in ("InitChapterId", "GameTime", "Day", "ExtraCountDownTime"):
        reader.i32(f"{field}.{field_name}")
    is_finished = reader.boolean(f"{field}.IsFinished")
    finish_result = reader.i32(f"{field}.FinishResult")
    reader.boolean(f"{field}.HasProgressMetaV2")
    difficulty_preset_id = reader.i32(f"{field}.DifficultyPresetId")
    difficulty_levels = reader.int_list(f"{field}.DifficultyLevels") or ()
    reader.boolean(f"{field}.HasDifficultyMeta")
    is_pure_endless = reader.boolean(f"{field}.IsPureEndless")
    endless_start_day = reader.i32(f"{field}.EndlessStartDay")
    reader.boolean(f"{field}.HasEndlessMeta")
    reader.i32(f"{field}.SaveOrigin")
    is_story_endless = reader.boolean(f"{field}.IsStoryEndless")
    story_endless_origin_ending = reader.i32(f"{field}.StoryEndlessOriginEnding")
    reader.boolean(f"{field}.HasEndingSnapshot")
    reader.i32(f"{field}.SnapshotEnding")
    reader.i32(f"{field}.SnapshotDay")
    snapshot_count = reader.collection_count(f"{field}.EndingSnapshots")
    if snapshot_count is not None:
        for snapshot_index in range(snapshot_count):
            snapshot_field = f"{field}.EndingSnapshots[{snapshot_index}]"
            reader.object_member_count(ENDING_SNAPSHOT_MEMBER_COUNT, snapshot_field)
            reader.i32(f"{snapshot_field}.EndingId")
            reader.i32(f"{snapshot_field}.Day")
            reader.i32(f"{snapshot_field}.TurnIndex")
    return SaveHistoryRecord(
        file_name=file_name,
        name=name,
        player_select_id=player_select_id,
        max_day=max_day,
        turn=turn,
        is_finished=is_finished,
        finish_result=finish_result,
        difficulty_preset_id=difficulty_preset_id,
        difficulty_levels=tuple(difficulty_levels),
        is_pure_endless=is_pure_endless,
        endless_start_day=endless_start_day,
        is_story_endless=is_story_endless,
        story_endless_origin_ending=story_endless_origin_ending,
    )


def _skip_history_child(reader: _Reader, index: int) -> None:
    _read_history_child(reader, index)


def _read_history_int_list_map(reader: _Reader, field: str) -> dict[int, tuple[int, ...]]:
    count = reader.collection_count(field)
    if count is None:
        return {}
    result: dict[int, tuple[int, ...]] = {}
    for index in range(count):
        entry_field = f"{field}[{index}]"
        key = reader.i32(f"{entry_field}.key")
        if key in result:
            raise SaveParseError(f"存档字段 {field} 出现重复键：{key}")
        result[key] = reader.int_list(f"{entry_field}.value") or ()
    return result


def _read_history_string_bool_map(reader: _Reader, field: str) -> dict[str, bool]:
    count = reader.collection_count(field)
    if count is None:
        return {}
    result: dict[str, bool] = {}
    for index in range(count):
        entry_field = f"{field}[{index}]"
        key = reader.memorypack_string(f"{entry_field}.key") or ""
        if key in result:
            raise SaveParseError(f"存档字段 {field} 出现重复键：{key}")
        result[key] = reader.boolean(f"{entry_field}.value")
    return result


def _read_history_int_string_map(reader: _Reader, field: str) -> dict[int, str]:
    count = reader.collection_count(field)
    if count is None:
        return {}
    result: dict[int, str] = {}
    for index in range(count):
        entry_field = f"{field}[{index}]"
        key = reader.i32(f"{entry_field}.key")
        if key in result:
            raise SaveParseError(f"存档字段 {field} 出现重复键：{key}")
        result[key] = reader.memorypack_string(f"{entry_field}.value") or ""
    return result


def _read_history_best_records(reader: _Reader, field: str) -> None:
    count = reader.collection_count(field)
    if count is None:
        return
    for index in range(count):
        item_field = f"{field}[{index}]"
        reader.object_member_count(5, item_field)
        reader.i32(f"{item_field}.PlayerSelectId")
        reader.i32(f"{item_field}.BestDays")
        reader.i32(f"{item_field}.Tier")
        reader.memorypack_string(f"{item_field}.AchievedDate")
        reader.memorypack_string(f"{item_field}.PayloadJson")


def _read_history_dossier_records(reader: _Reader, field: str) -> None:
    count = reader.collection_count(field)
    if count is None:
        return
    for index in range(count):
        item_field = f"{field}[{index}]"
        reader.object_member_count(7, item_field)
        reader.i32(f"{item_field}.PlayerSelectId")
        reader.i32(f"{item_field}.BestScore")
        reader.memorypack_string(f"{item_field}.BestRank")
        reader.i32(f"{item_field}.BestDays")
        reader.memorypack_string(f"{item_field}.ResultText")
        reader.memorypack_string(f"{item_field}.AchievedDate")
        reader.memorypack_string(f"{item_field}.DimsJson")


def _parse_history_data_strict(
    data: bytes,
    *,
    source_path: Path | None = None,
    file_info: SaveFileInfo | None = None,
) -> CodexSaveState:
    """Read the current HistoryData schema, including its global codex state."""

    reader = _Reader(data)
    reader.object_member_count(HISTORY_DATA_MEMBER_COUNT, "HistoryData")
    history_count = reader.collection_count("HistoryList")
    history_records: list[SaveHistoryRecord] = []
    if history_count is not None:
        for index in range(history_count):
            history_records.append(_read_history_child(reader, index))

    last_play_file_name = reader.memorypack_string("LastPlayFileName") or ""
    reader.int_list("UnlockedAchievementIds")
    reader.int_list("UnlockedPlayerSelectIds")
    _read_history_int_list_map(reader, "ClearedEndings")
    _read_history_string_bool_map(reader, "GlobalEasterEggFlags")
    _read_history_int_string_map(reader, "PlayerSelectSaveFileMap")
    codex_offset = reader.pos
    raw_categories = _read_history_int_list_map(reader, "CodexUnlocked")
    _ = reader.int_list("CodexMilestonesClaimed")
    _ = reader.int_list("PendingUnlockNoticeIds")
    _read_history_best_records(reader, "EndlessBestRecords")
    reader.boolean("EndlessModeUnlocked")
    _read_history_dossier_records(reader, "BestDossierRecords")
    reader.i32("DataOrigin")
    reader.int_list("EndlessCharUnlockedIds")
    reader.int_list("SeenProloguePlayerSelectIds")
    if reader.pos != len(data):
        raise SaveParseError(
            f"HistoryData 未读取到文件末尾：offset={reader.pos}, total={len(data)}",
            code="history_trailing_bytes",
            stage="history_eof",
            offset=reader.pos,
        )

    for category_id, source_ids in raw_categories.items():
        if category_id not in CODEX_CATEGORY_IDS:
            raise SaveParseError(f"CodexUnlocked 出现未知分类 ID：{category_id}")
        if any(source_id <= 0 for source_id in source_ids):
            raise SaveParseError(f"CodexUnlocked[{category_id}] 包含非法源 ID：{source_ids!r}")
        if len(set(source_ids)) != len(source_ids):
            raise SaveParseError(f"CodexUnlocked[{category_id}] 包含重复源 ID")

    for record in history_records:
        if (
            not record.file_name
            or Path(record.file_name).name != record.file_name
            or "/" in record.file_name
            or "\\" in record.file_name
            or not HISTORY_SAVE_FILENAME_RE.fullmatch(record.file_name)
        ):
            raise SaveParseError(
                f"HistoryList 子存档文件名非法：{record.file_name!r}",
                code="history_child_filename",
                stage="history_schema",
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
        category: tuple(raw_categories.get(category_id, ()))
        for category_id, category in CODEX_CATEGORY_IDS.items()
    }
    total_ids = sum(len(ids) for ids in raw_categories.values())
    return CodexSaveState(
        file_info=file_info,
        category_ids=category_ids,
        raw_category_ids=raw_categories,
        codex_offset=codex_offset,
        trailing_offset=reader.pos,
        codex_end_offset=reader.pos,
        schema_profile="historydata-v16",
        candidate_count=1,
        candidate_score=(3, len(raw_categories), 1000, total_ids, 0),
        candidate_offsets=(codex_offset,),
        history_records=tuple(history_records),
        last_play_file_name=last_play_file_name,
    )


_SAVE_SCHEMAS: dict[str, tuple[tuple[str, str], ...]] = {
    "GameSaveData": (
        ("Name", "string"), ("FileName", "string"), ("IsSubGame", "bool"),
        ("InitChapterId", "int"), ("InitPlayerId", "int"), ("InitMapConfigId", "int"),
        ("Event", "int"), ("DynamicNpcList", "List<DynamicNpc>"),
        ("HistoryMaxDay", "int"), ("FaithPoint", "int"), ("TurnIndex", "int"),
        ("RebirthAwakeningPlayed", "bool"), ("CrisisPointMap", "Dictionary<int,CrisisPointSave>"),
        ("TalentData", "TalentSave"), ("SymbolData", "SymbolSave"),
        ("ExploreReward", "ExploreRewardSave"), ("isFinished", "bool"), ("FinishResult", "int"),
        ("History", "List<SaveChildData>"), ("CurSave", "SaveChildData"),
        ("ProficiencyData", "ProficiencySave"), ("VisitedMapPointIds", "List<int>"),
        ("NpcAffinityCarryDict", "Dictionary<int,float>"), ("RushDoneNodeIds", "List<int>"),
        ("MetNpcConfigIds", "List<int>"), ("PlayerSelectId", "int"), ("OwnedVehicleGrade", "int"),
        ("PendingRebirthNotebooks", "Dictionary<int,int>"), ("RebirthLog2AwakeningPlayed", "bool"),
        ("PendingFullLoadBuffId", "int"), ("HasSeenCookingGuide", "bool"),
        ("DifficultyPresetId", "int"), ("DifficultyLevels", "List<int>"),
        ("EndlessActive", "bool"), ("IsPureEndless", "bool"), ("EndlessStartDay", "int"),
        ("FallenMapPointIds", "List<int>"), ("EndlessSetupDone", "bool"),
        ("EndlessLastWaveDay", "int"), ("RebirthChancesUsed", "int"),
        ("FaithSpentThisRound", "int"), ("HpMaxPenaltyStacks", "int"),
        ("DaySnapshotDays", "int[]"), ("RebirthGuideShown", "bool"),
        ("EndlessOriginEnding", "int"), ("StoryEndlessIntroPlayed", "bool"),
        ("EndlessCrises", "List<EndlessCrisisSave>"), ("FurnPlanGuideShown", "int"),
        ("FurnPlanGuideLearned", "bool"), ("ShopTrunkGuideGrade", "int"),
        ("BagTrunkGuideGrade", "int"), ("CookFridgeGuideShown", "bool"),
        ("ToolCabinetGuideShown", "bool"), ("ToolTableCollapsedNoteCats", "int"),
        ("PlantChoreReplantOn", "bool"), ("PendingRoundRestartUpgrade", "bool"),
        ("ToolTableRecentRecipeKeys", "List<string>"),
    ),
    "DynamicNpc": (("PlayerId", "int"), ("InitMapConfigId", "int"), ("StartPosName", "string")),
    "CrisisPointSave": (("ConfigId", "int"), ("TimeStamp", "int"), ("Day", "int"), ("TurnIndex", "int")),
    "TalentSave": (("TalentLevelMap", "Dictionary<int,int>"), ("BuffRefreshApplied", "List<int>")),
    "SymbolSave": (("SymbolMap", "Dictionary<string,bool>"),),
    "ExploreRewardSave": (("Result", "int"), ("NewItems", "List<ItemRewardSave>"), ("MapConfigId", "int")),
    "ProficiencySave": (("LevelMap", "Dictionary<int,int>"), ("ExpMap", "Dictionary<int,int>")),
    "EndlessCrisisSave": (
        ("PoolRowId", "int"), ("StartEventId", "int"), ("EndEventId", "int"),
        ("StartDay", "int"), ("EndDay", "int"), ("WeatherPoolId", "int"),
        ("StartHour", "int"), ("State", "byte"),
    ),
    "SaveChildData": (
        ("LeadingRole", "AgentSave"), ("ChapterAgentMap", "Dictionary<int,List<AgentSave>>"),
        ("Day", "int"), ("GameTime", "int"), ("VitalityHistory", "List<VitalityChangeRecord>"),
        ("LeadingRoleUsedItemsHistory", "List<ItemUsageRecord>"),
        ("LeadingRoleUsedActionsHistory", "List<ActionRecord>"),
        ("LeadingRoleBuffChanges", "List<BuffChangeRecord>"), ("EventLogHistory", "List<EventLogRecord>"),
        ("DataCollectionCount", "int"), ("CurrentWish", "WishData"), ("WishConsecutiveMiss", "int"),
        ("DynamicEventSave", "DynamicEventSave"), ("TagSave", "TagSave"),
        ("Permissions", "PermissionsSave"), ("Power", "PowerSave"),
        ("PromptTriggerSave", "PromptTriggerSave"), ("Statistics", "PreDisasterStatistics"),
        ("IsPerfectPreparation", "bool"), ("DayDescriptionLog_CN", "List<string>"),
        ("DayDescriptionLog_EN", "List<string>"), ("SurvivalPoint", "int"),
        ("SurvivalTotalPoints", "int"), ("CachedFaithPoints", "int"), ("DayCachePoint", "int"),
        ("ItemDailyUsageDict", "Dictionary<int,int>"), ("CompletedWishes", "List<CompletedWishRecord>"),
        ("ToolTableDataList", "List<ToolTableData>"), ("ProductionRecordList", "List<string>"),
        ("PreDisasterPurchaseRecords", "Dictionary<int,int>"),
        ("PaperAirplaneSaveList", "List<PaperAirplaneSaveData>"), ("ExtraCountDownTime", "int"),
        ("DropItemSaveList", "List<DropItemSaveData>"), ("WeatherConfigId", "int"),
        ("PlacedTrapSaveList", "List<PlacedTrapSave>"),
        ("ProficiencyDiscoveryData", "ProficiencyDiscoverySave"),
        ("BasketPendingReturns", "List<BasketScheduledReturn>"), ("NeighborRescueProgress", "int"),
        ("NeighborTodayWishCategories", "List<int>"), ("NeighborMilestoneDone", "List<int>"),
        ("NeighborAffinityOnceFlags", "List<string>"), ("NeighborLastRollDay", "int"),
        ("PhoneSMSConvList", "List<PhoneSMSConvSave>"), ("NpcCommonStateList", "List<NpcCommonState>"),
        ("NeighborAffinity", "int"), ("NeighborLastProactiveGiftDay", "int"),
        ("NeighborAffinitySeeded", "bool"), ("StrangerTradeActiveLastDealDay", "int"),
        ("StrangerTradeDroneDepartSec", "int"), ("StrangerTradeDroneReturnSec", "int"),
        ("StrangerTradeDroneCargoJson", "string"), ("StrangerTradeDroneOwnerId", "long"),
        ("StrangerTradeActiveDealCountToday", "int"), ("GossipLastPushedDay", "int"),
        ("NeighborPendingDeathEventId", "int"), ("NeighborCrisisFiredIdxList", "List<int>"),
        ("NeighborRescueTriggerDay", "int"), ("NeighborActiveRescueLineId", "int"),
        ("PhoneSMSNpcReplyQueue", "List<PhoneSMSNpcReplyTask>"), ("LoanSharkCompromiseTier", "int"),
        ("LoanSharkFedCount", "int"), ("LoanSharkCompromiseDay", "int"),
        ("StrangerTradeDroneTripType", "int"), ("StrangerTradeDroneEncounterDone", "bool"),
        ("VehicleTrunkItems", "List<ItemSave>"), ("DoorBoxItems", "List<ItemSave>"),
        ("GossipTodayPushDay", "int"), ("GossipMorningTopic", "int"), ("GossipEveningTopic", "int"),
        ("GossipDrawnTopicIds", "List<int>"), ("GossipSpokeTopicIds", "List<int>"),
        ("GroupAnger", "int"), ("GossipLastRaidDay", "int"), ("NeighborCrisisActiveIndex", "int"),
        ("NeighborCrisisRequiredCategory", "int"), ("NeighborCrisisDeadlineDay", "int"),
        ("NeighborLastCrisisDay", "int"), ("NeighborLastReturnSmsStamp", "int"),
        ("StrangerTradeNpcStockJson", "string"), ("StrangerTradeDroneIsCharity", "bool"),
        ("PhoneSMSQueuePlanDay", "int"), ("PhoneSMSQueuePlan", "List<PhoneSMSQueuePlanEntry>"),
        ("DoorBoxItems2", "List<ItemSave>"), ("BuildShopStockSnapshot", "Dictionary<int,Dictionary<int,int>>"),
        ("PendingDaySettlement", "bool"), ("PendingSettlement_Day", "int"),
        ("PendingSettlement_HistoryMaxDay", "int"), ("PendingSettlement_Morale", "int"),
        ("PendingSettlement_DailyPoints", "int"), ("PendingSettlement_Points", "int[]"),
        ("PendingSettlement_WishCount", "int"), ("PendingSettlement_SurvivalPlanIds", "List<int>"),
        ("IsFaithSettled", "bool"), ("FaithSettledTotal", "int"), ("FaithSettledStages", "int[]"),
        ("GameCounterDict", "Dictionary<string,int>"), ("FoodPollutionFurnitureIds", "List<long>"),
        ("FoodPollutionLastResetDay", "int"), ("CityChatPushedStamp", "int"),
        ("SeenProductionRecipeKeys", "List<string>"), ("CraftUnlockedProductionIds", "List<int>"),
        ("CompanionRescueProgress", "int"), ("CompanionAffinity", "int"),
        ("CompanionTodayWishCategories", "List<int>"), ("CompanionMilestoneDone", "List<int>"),
        ("CompanionAffinityOnceFlags", "List<string>"), ("CompanionLastRollDay", "int"),
        ("CompanionLastProactiveGiftDay", "int"), ("CompanionAffinitySeeded", "bool"),
        ("CompanionPendingDeathEventId", "int"), ("CompanionCrisisFiredIdxList", "List<int>"),
        ("CompanionRescueTriggerDay", "int"), ("CompanionActiveRescueLineId", "int"),
        ("CompanionCrisisActiveIndex", "int"), ("CompanionCrisisRequiredCategory", "int"),
        ("CompanionCrisisDeadlineDay", "int"), ("CompanionLastCrisisDay", "int"),
        ("CompanionLastReturnSmsStamp", "int"),
        ("GroundLootBatchMap", "Dictionary<int,List<GroundLootEntrySave>>"),
        ("DossierPayloadJson", "string"), ("StrangerSupportJson", "string"),
        ("TowerDefenseSave", "TowerDefenseSaveData"), ("NeighborLastCompanionSmsDay", "int"),
        ("CompanionLastCompanionSmsDay", "int"), ("EndlessSettlementJson", "string"),
        ("WorkbenchDrawerItems", "List<ItemSave>"), ("SceneRatCatchCooldownEndHour", "int"),
        ("PurchaseSafetyState", "PurchaseSafetyState"), ("ExploreVisitedList", "List<ExploreVisitedEntry>"),
        ("ConsumedWeightTrimmed", "long"), ("NeighborNeglectAnchorSeconds", "int"),
        ("NeighborLastSendDay", "int"), ("NeighborConsecutiveSendDays", "int"),
        ("NeighborWishIndex", "int"), ("NeighborStruggleState", "int"),
        ("NeighborStruggleDeadlineSeconds", "int"), ("NeighborStruggleCount", "int"),
        ("NeighborDeathDayBonus", "int"), ("FoodPollutionCellMap", "Dictionary<long,List<int>>"),
        ("FoodPollutionLastSpreadHour", "int"), ("PendingDeathChoice", "bool"),
        ("PendingDeath_Day", "int"), ("PendingDeath_Hour", "int"), ("PendingDeath_CauseJson", "string"),
        ("SeenNewSlotNames", "List<string>"), ("FoodPollutionLastShrinkHour", "int"),
        ("FoodPollutionCrisisStartDay", "int"), ("FoodPollutionLastSeedDay", "int"),
        ("FoodPollutionMinorCabinetId", "long"), ("LoanSharkAppViewed", "bool"),
        ("NeighborSurvivalTier", "int"), ("NeighborTierAnchorSeconds", "int"),
        ("NeighborWishPendingReveal", "bool"), ("LoanSharkRevengeTier", "int"),
        ("LoanSharkRevengeDay", "int"), ("LoanSharkRevengeCount", "int"),
        ("LoanSharkStalkTier", "int"), ("LoanSharkStalkDay", "int"), ("LoanSharkStalkCount", "int"),
        ("CompanionNeglectAnchorSeconds", "int"), ("CompanionSurvivalTier", "int"),
        ("CompanionTierAnchorSeconds", "int"), ("CompanionWishPendingReveal", "bool"),
        ("CompanionStruggleState", "int"), ("CompanionStruggleDeadlineSeconds", "int"),
        ("CompanionStruggleCount", "int"), ("CompanionLastSendDay", "int"),
        ("CompanionConsecutiveSendDays", "int"), ("CompanionWishIndex", "int"),
        ("LoanSharkGnawRemainDamage", "int"), ("LoanSharkGnawRemainTicks", "int"),
        ("LoanSharkGnawNextSeconds", "int"), ("LoanSharkGnawEventId", "int"),
        ("PreDisasterFurniturePurchaseRecords", "Dictionary<int,int>"), ("PhoneMuted", "bool"),
        ("RainedToday", "bool"),
    ),
    "ItemSave": (
        ("ItemConfigId", "int"), ("ItemCount", "int"), ("BagPos", "int[]"),
        ("StartTime", "int"), ("TimeLeft", "int"), ("UseTimes", "int"), ("TimeScale", "float"),
        ("OriginalTimeLeft", "int"), ("InstanceVD", "float[]"), ("InstanceEffectEnd", "float[]"),
        ("MaxUseTimes", "int"), ("InstanceBurnValue", "int"), ("Polluted", "bool"),
        ("IsMapPreset", "bool"), ("NoPackage", "bool"), ("InstanceWeight", "int"),
    ),
    "AgentSave": (
        ("NewInstanceId", "long"), ("SaveInstanceId", "long"), ("InstanceIdType", "int"),
        ("AgentConfigId", "int"), ("AttrDict", "Dictionary<int,int>"), ("BuffArgsList", "List<BuffSave>"),
        ("FurnitureDurability", "int"), ("ShopConfigId", "int"), ("ShopCache", "Dictionary<int,int>"),
        ("ShopItemCache", "List<ShopItemSave>"), ("FurnitureFuncCDDict", "Dictionary<int,int>"),
        ("FurnitureFuncDailyUsageDict", "Dictionary<int,int>"), ("HandMadeState", "int"),
        ("HandMadeMakingTime", "float"), ("HandMadeMakingDuration", "float"),
        ("HandMadeCachedItemIds", "List<long>"), ("CookingFuelSlots", "List<CookingFuelSlotSave>"),
        ("GeneratorFuelSlots", "List<GeneratorFuelSlotSave>"), ("CookingIsCooking", "bool"),
        ("CookingStartTotalSeconds", "float"), ("CookingDuration", "float"), ("CookingType", "int"),
        ("CookingMatchedRecipeId", "int"), ("CookingMatchedRecipeIds", "List<int>"),
        ("CookingState", "int"), ("CookingPauseStartTotalSeconds", "float"),
        ("CookingHasPendingProduct", "bool"), ("CookingPendingProductName", "string"),
        ("CookingPendingProductItemId", "int"), ("CookingConsumedFuelCapacity", "float"),
        ("CookingLevel", "int"), ("CookingExp", "int"), ("UnlockedCookingRecipeIds", "List<int>"),
        ("HandMadeRecordList", "List<string>"), ("ItemList", "List<ItemSave>"),
        ("BirthPos", "float[]"), ("Position", "float[]"), ("Rotation", "float[]"), ("Name", "string"),
        ("Money", "int"), ("MapConfigId", "int"), ("MapConfigIdHome", "int"), ("GuidanceNpcId", "int"),
        ("IsShow", "bool"), ("ChapterId", "int"), ("FuncOpen", "bool"),
        ("PoorAppetiteHistory", "List<PoorAppetiteHistorySave>"), ("PoorAppetiteList", "List<PoorAppetiteCacheSave>"),
        ("SurvivalPlanningActiveIds", "List<int>"), ("ProductionExp", "int"), ("ProductionLevel", "int"),
        ("BuildShopConfigId", "int"), ("BuildShopStockDict", "Dictionary<int,int>"),
        ("BuildPurchaseSourceMap", "Dictionary<long,long>"), ("SlotPosType", "int"), ("SlotPosPoint", "string"),
        ("IsBagFurniture", "bool"), ("BagFurnitureConfigId", "int"), ("IsDoorBox", "bool"),
        ("BuildPackagePointMap", "Dictionary<long,string>"), ("PlantFurnitureConfigId", "int"),
        ("PlantState", "int"), ("PlantConfigId", "int"), ("PlantSeedCount", "int"),
        ("PlantFertItemConfigId", "int"), ("PlantGrowthProgress", "float"), ("PlantStartTotalSeconds", "int"),
        ("PlantAnomalyFlags", "int"), ("PlantDecayStartTotalSeconds", "int"),
        ("PlantAnomalyStallStartTotalSeconds", "int"), ("PlantMatureStartTotalSeconds", "int"),
        ("IsGuidanceFurniture", "bool"), ("DemolishedGuidanceFurnitureIds", "List<int>"),
        ("PlantNextAnomalyCheckTotalSeconds", "int"), ("DoorBoxIndex", "int"), ("IsBagLocked", "bool"),
        ("CraftUnlockedCookingRecipeIds", "List<int>"), ("PlantGrowthTotalSeconds", "float"),
        ("DroneTrip", "DroneTripSave"), ("VaseState", "int"), ("VaseFlowerItemConfigId", "int"),
        ("VaseInsertTotalSeconds", "int"), ("TowerAttackTimerSeconds", "float"),
        ("RatCageMice", "List<RatCageMouseSave>"), ("RatCageFoodCp", "float"), ("RatVisitMark", "bool"),
        ("HotPotTotalSatiety", "float"), ("HotPotRemainSatiety", "float"), ("MusicCurrentTrackId", "int"),
        ("BrewState", "int"), ("BrewStartHour", "int"), ("BrewTotalHours", "int"),
        ("BrewResultItemId", "int"), ("BrewResultCount", "int"), ("HotPotTasteScore", "float"),
        ("BuildPurchasePaidMap", "Dictionary<long,int>"), ("CookingLockedPortions", "int"),
        ("HasSearched", "bool"), ("PlantYieldBonus", "float"), ("PlantGrowthTimeExtend", "float"),
        ("GeneratorAutoStart", "bool"), ("GeneratorAutoStartThreshold", "float"), ("FurnitureTagId", "int"),
        ("ShredderTrayItems", "List<ItemSave>"), ("ShredderState", "int"),
        ("ShredderStartTotalSeconds", "int"), ("ShredderTotalSeconds", "int"),
        ("ShredderPauseStartTotalSeconds", "int"), ("ShredderHeadConfigId", "int"),
        ("ShredderHeadBagPosX", "int"), ("ShredderHeadBagPosY", "int"), ("PlantExpBonus", "float"),
        ("CookingPendingIsNewUnlock", "bool"), ("CookingPendingQualityTier", "int"),
        ("FurnitureModelState", "string"), ("CompressorTrayItems", "List<ItemSave>"),
        ("CompressorState", "int"), ("CompressorStartTotalSeconds", "int"),
        ("CompressorTotalSeconds", "int"), ("CompressorPauseStartTotalSeconds", "int"),
        ("CompressorEmittedGroups", "int"), ("CompressorOut", "List<float>"),
        ("CompressorBlocks", "int"), ("CompressorCrumbs", "int"),
        ("CompressorFlavorBlocks", "List<int>"), ("CompressorSeasonG", "float"),
        ("CompressorTotalWeight", "int"), ("CompressorPolluted", "bool"),
    ),
    "VitalityChangeRecord": (("Timestamp", "int"), ("ChangeValue", "float"), ("ValueBefore", "float"), ("ValueAfter", "float"), ("SourceType", "int"), ("ConfigId", "int")),
    "ItemUsageRecord": tuple((f"field{index}", "int") for index in range(6)),
    "ActionRecord": (("ActionConfigId", "int"), ("GameTime", "int")),
    "BuffChangeRecord": (("Timestamp", "int"), ("ChangeType", "int"), ("BuffConfigId", "int")),
    "EventLogRecord": (("ID", "int"), ("IsUnique", "bool"), ("Timestamp", "int")),
    "WishData": (("Type", "int"), ("TargetValue", "int"), ("TargetValues", "List<int>"), ("TimeStamp", "int"), ("IsCompleted", "bool"), ("IsExpired", "bool")),
    "DynamicEventSave": (("CDMap", "Dictionary<int,int>"), ("CurrentArgsList", "List<DynamicEventArgsSave>"), ("CacheArgs", "List<DynamicEventArgsSave>"), ("HasTriggeredFirstDayEvent", "bool"), ("SettlementBeliefPoint", "int"), ("RunningEventIds", "List<int>")),
    "TagSave": (("CacheTagMap", "Dictionary<string,int>"), ("IgnoreTagMap", "Dictionary<string,int>")),
    "PermissionsSave": (("IsDynamicEventOpen", "bool"), ("IsThinkingOpen", "bool"), ("FuncMapData", "Dictionary<int,bool>")),
    "PowerSave": (("CurPowerValue", "int"), ("MaxPowerValue", "int"), ("CurrentStoredPower", "float"), ("GeneratorStates", "Dictionary<long,bool>"), ("ConsumerStates", "Dictionary<long,bool>"), ("IsSelfSupplyPowerOff", "bool")),
    "PromptTriggerSave": (("ActiveStoryIds", "List<int>"), ("CompletedStoryIds", "List<int>")),
    "PreDisasterStatistics": (("VisitedLocations", "Dictionary<int,int>"), ("ShoppingCount", "int"), ("TotalMoneySpent", "int"), ("TotalItemsWeight", "int")),
    "CompletedWishRecord": (("Day", "int"), ("Type", "int"), ("TargetValue", "int"), ("CompletedTime", "int")),
    "ToolTableData": (("FurnitureId", "long"), ("State", "int"), ("CachedItemIds", "List<long>"), ("MakingTime", "float"), ("MakingDuration", "float")),
    "PaperAirplaneSaveData": (("RelativePosition", "float[]"), ("RelativeRotation", "float[]")),
    "DropItemSaveData": (("Position", "float[]"), ("ItemList", "List<ItemSave>"), ("ModeList", "List<int>"), ("RotationY", "Nullable<float>"), ("MapConfigId", "Nullable<int>"), ("IsWaveLoot", "Nullable<bool>")),
    "PlacedTrapSave": (("TrapConfigId", "int"), ("SlotNodeName", "string"), ("ItemInstanceId", "long"), ("CurrentDurability", "int"), ("MaxDurability", "int"), ("BaitItemConfigId", "int"), ("HasPrey", "bool"), ("PreyItemConfigId", "int"), ("CaptureStartTotalSeconds", "int")),
    "ProficiencyDiscoverySave": (("DiscoveryRecord", "Dictionary<string,bool>"), ("DailyResearchUsed", "Dictionary<int,bool>")),
    "BasketScheduledReturn": (("FurnitureInstanceId", "long"), ("ReturnAtTotalSeconds", "int"), ("SentItemConfigIds", "List<int>"), ("SentItemCounts", "List<int>")),
    "PhoneSMSConvSave": (("ContactId", "int"), ("Messages", "List<PhoneSMSMsgSave>"), ("Unread", "int"), ("HasEvent", "bool"), ("LastMsgUtcMs", "long"), ("IsContactDead", "bool"), ("CanReply", "bool"), ("NormalUnread", "int"), ("EventUnread", "int"), ("TradeUnread", "int"), ("ReplySourceSmsId", "int"), ("QueueCursor", "int"), ("QueueWaitingReply", "bool"), ("IsMuted", "bool"), ("LastAffinitySnapshot", "int"), ("AffinitySnapshotInited", "bool")),
    "NpcCommonState": (("NpcConfigId", "int"), ("Vitality", "int"), ("Morale", "int"), ("Material", "int"), ("Affinity", "int"), ("IsDead", "bool"), ("LastMonologueDay", "int"), ("LastTradeRequestDay", "int")),
    "PhoneSMSNpcReplyTask": (("ContactId", "int"), ("ReplySmsId", "int"), ("ReplyAtUtcMs", "long"), ("MoraleAdd", "float")),
    "PhoneSMSQueuePlanEntry": (("ContactId", "int"), ("Hour", "int")),
    "TowerDefenseSaveData": (("WaveState", "int"), ("LegacyCrisisId", "int"), ("RemainingBudget", "int"), ("FieldCount", "int"), ("TotalBudget", "int"), ("SpawnIntervalSeconds", "float"), ("FinalChargeBudgetRatio", "float"), ("PeakFieldCap", "int"), ("MutedSlotTypes", "List<int>"), ("SpawnTypeList", "List<int>"), ("SpawnRemainCountList", "List<int>"), ("AliveZombies", "List<TowerZombieSaveData>"), ("WaveIndex", "int"), ("WaveKillCount", "int"), ("WaveDeviceDamage", "int"), ("WaveStructureDamage", "int"), ("WaveEventId", "int"), ("MaxTotalHpBudget", "int"), ("FinalChargePortentSeconds", "float"), ("SpawnGroups", "List<TowerWaveGroupSaveData>"), ("AttackMultiplier", "int"), ("AttackSpeedMultiplier", "float"), ("DurationHours", "float"), ("WaveOpenTotalSeconds", "int"), ("HpMultiplier", "int"), ("OwnerCrisisId", "int"), ("AliveCapTypeList", "List<int>"), ("AliveCapValueList", "List<int>"), ("CrisisStageIndex", "int"), ("AliveCapAnchorList", "List<string>"), ("LastRewardedKillCount", "int"), ("HpMultiplierFine", "float")),
    "TowerZombieSaveData": (("ZombieTypeId", "int"), ("CurrentHP", "int"), ("PosX", "float"), ("PosY", "float"), ("PosZ", "float"), ("TargetSlotTypes", "List<int>"), ("SpawnAnchor", "string")),
    "TowerWaveGroupSaveData": (("SpawnAnchor", "string"), ("SpawnTypes", "List<int>"), ("SpawnRemainCounts", "List<int>"), ("SpawnBlocked", "bool"), ("TargetSlotTypes", "List<int>"), ("SpawnTotalCount", "int"), ("ChargeTriggered", "bool")),
    "GroundLootEntrySave": (("ItemConfigId", "int"), ("PosX", "float"), ("PosY", "float"), ("PosZ", "float"), ("RotationY", "float"), ("Floor", "int"), ("StartTime", "int"), ("TimeLeft", "int"), ("Collected", "bool")),
    "PurchaseSafetyState": (("HasFiredMoney40", "bool"), ("HasFiredMoney20", "bool"), ("HasFiredTime4h", "bool"), ("DisasterInitialMoney", "int"), ("FiredCouplingHintKeys", "List<string>")),
    "ExploreVisitedEntry": (("SceneName", "string"), ("Cells", "List<int>")),
    "BuffSave": (("BuffConfigId", "int"), ("BuffCount", "int"), ("During", "int"), ("ReleaserId", "long")),
    "ShopItemSave": (("ItemConfigId", "int"), ("ItemCount", "int"), ("FreshDecay", "float")),
    "CookingFuelSlotSave": (("ConfigId", "int"), ("Count", "int"), ("BurnValue", "int"), ("BurnProgress", "float"), ("Item", "ItemSave")),
    "GeneratorFuelSlotSave": (("ConfigId", "int"), ("Count", "int"), ("BurnValue", "int"), ("BurnProgress", "float"), ("Item", "ItemSave")),
    "PoorAppetiteHistorySave": (("ItemConfigId", "int"), ("TimeStamp", "int"), ("RemainingTime", "int"), ("Count", "int")),
    "PoorAppetiteCacheSave": (("ItemConfigId", "int"), ("TimeStamp", "int"), ("RemainingTime", "int")),
    "DroneTripSave": (("DepartSec", "int"), ("ReturnSec", "int"), ("CargoJson", "string"), ("OwnerId", "long"), ("TripType", "int"), ("IsCharity", "bool"), ("EncounterDone", "bool"), ("LastDealDay", "int"), ("DealCountToday", "int"), ("LastForagingDay", "int"), ("ForagingCountToday", "int")),
    "RatCageMouseSave": (("ConfigId", "int"), ("RemainLifeSeconds", "float"), ("Item", "ItemSave")),
    "ItemRewardSave": (("ItemConfigId", "int"), ("ItemCount", "int")),
    "DynamicEventArgsSave": (("TriggerHour", "int"), ("EventType", "int"), ("EventId", "int"), ("TaskCount", "int"), ("TaskFinishTime", "int"), ("ActionProgress", "Dictionary<int,int>"), ("ItemProgress", "Dictionary<int,int>"), ("CachedNextEventId", "Nullable<int>"), ("IsChose", "bool"), ("WaitingFurnitureId", "int"), ("DayProgress", "Dictionary<int,int>"), ("CurrentFsmStateId", "byte")),
    "PhoneSMSMsgSave": (("Side", "string"), ("ContentKey", "string"), ("ContentRaw", "string"), ("TimeText", "string"), ("SpeakerTag", "string"), ("IsEvent", "bool"), ("EventState", "string"), ("EventId", "int"), ("ExpireRealMs", "long"), ("TimeScale", "int"), ("TaskDeadlineGameSec", "long"), ("SMSId", "int"), ("IsTrade", "bool"), ("QuotedText", "string"), ("QuotedImagePath", "string"), ("ShelfSnapshotJson", "string"), ("AffinityDelta", "int"), ("FloatPlayed", "bool")),
}


_SAVE_CHILD_V181_EXTRA_FIELDS = tuple(
    (f"LegacyExtraInt{index}", "int") for index in range(5)
)


_SAVE_PRIMITIVE_SIZES = {
    "bool": 1,
    "byte": 1,
    "int": 4,
    "long": 8,
    "float": 4,
}
_SAVE_CAPTURE_FIELDS = {
    "GameSaveData": frozenset({
        "Name", "FileName", "HistoryMaxDay", "TurnIndex", "isFinished", "FinishResult",
        "PlayerSelectId", "DifficultyPresetId", "DifficultyLevels", "EndlessActive",
        "IsPureEndless", "EndlessStartDay", "EndlessOriginEnding", "CurSave",
    }),
    "SaveChildData": frozenset({
        "LeadingRole", "ChapterAgentMap", "VehicleTrunkItems", "DoorBoxItems",
        "DoorBoxItems2", "WorkbenchDrawerItems",
    }),
    "AgentSave": frozenset({
        "NewInstanceId", "SaveInstanceId", "AgentConfigId", "ItemList",
        "IsBagFurniture", "BagFurnitureConfigId", "IsDoorBox", "DoorBoxIndex",
        "MapConfigId", "MapConfigIdHome", "ChapterId", "SlotPosPoint",
    }),
    "ItemSave": frozenset({"ItemConfigId", "ItemCount"}),
}


def _split_generic_arguments(value: str) -> tuple[str, ...]:
    depth = 0
    start = 0
    parts: list[str] = []
    for index, char in enumerate(value):
        if char == "<":
            depth += 1
        elif char == ">":
            depth -= 1
        elif char == "," and depth == 0:
            parts.append(value[start:index].strip())
            start = index + 1
    parts.append(value[start:].strip())
    return tuple(parts)


def _save_type_kind(type_name: str) -> tuple[str, tuple[str, ...]]:
    if type_name in _SAVE_PRIMITIVE_SIZES or type_name == "string" or type_name.startswith("Nullable<"):
        return type_name, ()
    if type_name.endswith("[]"):
        return "array", (type_name[:-2],)
    if type_name.startswith("List<") and type_name.endswith(">"):
        return "list", _split_generic_arguments(type_name[5:-1])
    if type_name.startswith("Dictionary<") and type_name.endswith(">"):
        return "dictionary", _split_generic_arguments(type_name[11:-1])
    return "object", (type_name,)


def _save_unmanaged_size(type_name: str) -> int | None:
    if type_name in _SAVE_PRIMITIVE_SIZES:
        return _SAVE_PRIMITIVE_SIZES[type_name]
    if type_name.startswith("Nullable<") and type_name.endswith(">"):
        inner = type_name[9:-1]
        if inner not in _SAVE_PRIMITIVE_SIZES:
            return None
        return 2 if inner == "bool" else 8
    return None


def _save_dictionary_pair_size(key_type: str, value_type: str) -> int | None:
    key_size = _save_unmanaged_size(key_type)
    value_size = _save_unmanaged_size(value_type)
    if key_size is None or value_size is None:
        return None
    alignment = max(1, min(8, key_size), min(8, value_size))
    value_offset = (key_size + alignment - 1) // alignment * alignment
    total = value_offset + value_size
    return (total + alignment - 1) // alignment * alignment


class _SaveWireReader:
    """Schema-driven MemoryPack reader for the current GameSaveData graph."""

    def __init__(self, data: bytes, *, schemas: Mapping[str, tuple[tuple[str, str], ...]] | None = None):
        self.reader = _Reader(data)
        self.schemas = schemas or _SAVE_SCHEMAS

    @property
    def pos(self) -> int:
        return self.reader.pos

    def _error(self, message: str, *, field: str) -> SaveParseError:
        return SaveParseError(
            f"存档字段 {field} 解析失败：{message} at offset={self.pos}",
            code="game_save_schema_error",
            stage="game_save_wire",
            offset=self.pos,
        )

    def _primitive(self, type_name: str, field: str) -> int | float | bool:
        if type_name == "bool":
            return self.reader.boolean(field)
        if type_name == "byte":
            return self.reader.u8(field)
        if type_name == "int":
            return self.reader.i32(field)
        if type_name == "long":
            return self.reader.i64(field)
        if type_name == "float":
            return self.reader.f32(field)
        raise self._error(f"未知基础类型：{type_name}", field=field)

    def _object_header(self, schema_name: str, field: str) -> bool:
        marker = self.reader.u8(f"{field}.member_count")
        if marker == 0xFF:
            return False
        expected = len(self.schemas.get(schema_name, ()))
        if schema_name not in self.schemas:
            raise self._error(f"未知对象 schema：{schema_name}", field=field)
        if marker != expected:
            raise SaveParseError(
                f"存档字段 {field} 的成员数量变化：actual={marker}, expected={expected}, offset={self.pos - 1}",
                code="game_save_schema_mismatch",
                stage="game_save_wire",
                offset=self.pos - 1,
            )
        return True

    def _collection_count(self, field: str) -> int | None:
        return self.reader.collection_count(field)

    def _read_unmanaged_sequence(self, type_name: str, count: int, field: str) -> list[object]:
        size = _save_unmanaged_size(type_name)
        if size is None:
            raise self._error(f"集合元素不是可直接读取的基础类型：{type_name}", field=field)
        raw = self.reader.raw(count * size, field)
        if type_name == "bool":
            if any(value not in (0, 1) for value in raw):
                raise self._error("布尔集合包含非法值", field=field)
            return [bool(value) for value in raw]
        if type_name == "byte":
            return list(raw)
        fmt = "<" + {"int": "i", "long": "q", "float": "f"}[type_name] * count
        return list(struct.unpack(fmt, raw)) if count else []

    def _read_value(self, type_name: str, field: str, *, capture: bool = False) -> object:
        kind, args = _save_type_kind(type_name)
        if kind in _SAVE_PRIMITIVE_SIZES:
            return self._primitive(type_name, field)
        if kind == "string":
            return self.reader.memorypack_string(field)
        if kind == "object":
            return self.read_object(args[0], field, capture=capture)
        if kind == "array" or kind == "list":
            count = self._collection_count(field)
            if count is None:
                return None
            item_type = args[0]
            if _save_unmanaged_size(item_type) is not None:
                return self._read_unmanaged_sequence(item_type, count, field)
            return [self._read_value(item_type, f"{field}[{index}]", capture=capture) for index in range(count)]
        if kind == "dictionary":
            count = self._collection_count(field)
            if count is None:
                return {}
            key_type, value_type = args
            result: dict[object, object] = {}
            for index in range(count):
                item_field = f"{field}[{index}]"
                key = self._read_value(key_type, f"{item_field}.key")
                value = self._read_value(value_type, f"{item_field}.value", capture=capture)
                if key in result:
                    raise SaveParseError(f"存档字段 {field} 出现重复键：{key}")
                result[key] = value
            return result
        if kind.startswith("Nullable<"):
            size = _save_unmanaged_size(type_name)
            if size is None:
                raise self._error(f"Nullable 类型无法按当前 schema 读取：{type_name}", field=field)
            return self.reader.raw(size, field)
        raise self._error(f"未知字段类型：{type_name}", field=field)

    def skip_value(self, type_name: str, field: str) -> None:
        kind, args = _save_type_kind(type_name)
        if kind in _SAVE_PRIMITIVE_SIZES:
            self._primitive(type_name, field)
            return
        if kind == "string":
            self.reader.memorypack_string(field)
            return
        if kind == "object":
            self.skip_object(args[0], field)
            return
        if kind == "Nullable<int>" or kind == "Nullable<float>" or kind == "Nullable<bool>":
            size = _save_unmanaged_size(type_name)
            assert size is not None
            self.reader.raw(size, field)
            return
        if kind == "array" or kind == "list":
            count = self._collection_count(field)
            if count is None:
                return
            item_type = args[0]
            item_size = _save_unmanaged_size(item_type)
            if item_size is not None:
                raw = self.reader.raw(count * item_size, field)
                if item_type == "bool" and any(value not in (0, 1) for value in raw):
                    raise self._error("布尔集合包含非法值", field=field)
                return
            for index in range(count):
                self.skip_value(item_type, f"{field}[{index}]")
            return
        if kind == "dictionary":
            count = self._collection_count(field)
            if count is None:
                return
            key_type, value_type = args
            pair_size = _save_dictionary_pair_size(key_type, value_type)
            if pair_size is not None:
                raw = self.reader.raw(count * pair_size, field)
                if key_type == "bool" or value_type == "bool":
                    # Padding bytes are implementation details; the bool byte is
                    # validated by the object readers where it is semantically used.
                    del raw
                return
            for index in range(count):
                item_field = f"{field}[{index}]"
                self.skip_value(key_type, f"{item_field}.key")
                self.skip_value(value_type, f"{item_field}.value")
            return
        raise self._error(f"未知字段类型：{type_name}", field=field)

    def read_object(self, schema_name: str, field: str, *, capture: bool = False) -> dict[str, object] | None:
        if not self._object_header(schema_name, field):
            return None
        selected = _SAVE_CAPTURE_FIELDS.get(schema_name, frozenset()) if capture else frozenset()
        result: dict[str, object] = {}
        for name, type_name in self.schemas[schema_name]:
            member_field = f"{field}.{name}"
            if name in selected:
                result[name] = self._read_value(type_name, member_field, capture=True)
            else:
                self.skip_value(type_name, member_field)
        return result

    def skip_object(self, schema_name: str, field: str) -> None:
        if not self._object_header(schema_name, field):
            return
        for name, type_name in self.schemas[schema_name]:
            self.skip_value(type_name, f"{field}.{name}")


def _save_file_info(path: Path, data: bytes, *, used_backup: bool = False) -> SaveFileInfo:
    try:
        stat = path.stat()
    except OSError:
        stat = None
    return SaveFileInfo(
        path=path,
        sha256=hashlib.sha256(data).hexdigest(),
        size=len(data),
        mtime_ns=stat.st_mtime_ns if stat is not None else 0,
        read_at=datetime.now().astimezone().isoformat(timespec="seconds"),
        used_backup=used_backup,
    )


def _read_game_save_wire_with_schemas(
    data: bytes,
    schemas: Mapping[str, tuple[tuple[str, str], ...]],
) -> dict[str, object]:
    wire = _SaveWireReader(data, schemas=schemas)
    root = wire.read_object("GameSaveData", "GameSaveData", capture=True)
    if root is None:
        raise SaveParseError(
            "GameSaveData 不能为 null",
            code="game_save_null_root",
            stage="game_save_wire",
            offset=0,
        )
    if wire.pos != len(data):
        raise SaveParseError(
            f"GameSaveData 未读取到文件末尾：offset={wire.pos}, total={len(data)}",
            code="game_save_trailing_bytes",
            stage="game_save_eof",
            offset=wire.pos,
        )
    return root


def _read_game_save_wire(data: bytes) -> dict[str, object]:
    current_schema = _SAVE_SCHEMAS["GameSaveData"]
    if not data:
        raise SaveParseError("GameSaveData 文件为空", code="game_save_empty", stage="game_save_wire")
    if data[0] == len(current_schema):
        schemas: Mapping[str, tuple[tuple[str, str], ...]] = _SAVE_SCHEMAS
    elif data[0] == len(current_schema) - 1:
        schemas = dict(_SAVE_SCHEMAS)
        schemas["GameSaveData"] = current_schema[:-1]
    else:
        raise SaveParseError(
            f"GameSaveData 的成员数量变化：actual={data[0]}, expected={len(current_schema)} 或 {len(current_schema) - 1}",
            code="game_save_schema_mismatch",
            stage="game_save_wire",
            offset=0,
        )
    try:
        return _read_game_save_wire_with_schemas(data, schemas)
    except SaveParseError as first_error:
        message = str(first_error)
        if "GameSaveData.History[" not in message or "actual=181" not in message:
            raise
        compatible_schemas = dict(schemas)
        compatible_schemas["SaveChildData"] = (
            _SAVE_SCHEMAS["SaveChildData"] + _SAVE_CHILD_V181_EXTRA_FIELDS
        )
        return _read_game_save_wire_with_schemas(data, compatible_schemas)


def _item_dicts(value: object) -> list[dict[str, object]]:
    if value is None:
        return []
    if not isinstance(value, list):
        raise SaveParseError(f"存档库存字段不是列表：{value!r}", code="game_save_inventory_shape", stage="inventory")
    return [item for item in value if isinstance(item, dict)]


def _append_inventory_items(
    destination: list[InventoryItem],
    value: object,
    *,
    source: str,
    container: str,
    diagnostics: list[str],
) -> int:
    count = 0
    for index, item in enumerate(_item_dicts(value)):
        item_id = item.get("ItemConfigId")
        item_count = item.get("ItemCount")
        if not isinstance(item_id, int) or item_id <= 0:
            diagnostics.append(f"{source}第 {index + 1} 项包含未知物品 ID：{item_id!r}")
            continue
        if not isinstance(item_count, int) or item_count <= 0:
            diagnostics.append(f"{source}中的物品 ID {item_id} 数量非法：{item_count!r}")
            continue
        destination.append(InventoryItem(item_id, item_count, source, container))
        count += 1
    return count


def _normalize_storage_furniture(storage_furniture: Mapping[int, str]) -> dict[int, str]:
    return {
        int(config_id): str(name).strip() or f"ID:{int(config_id)}"
        for config_id, name in storage_furniture.items()
        if isinstance(config_id, int)
        and not isinstance(config_id, bool)
        and config_id > 0
    }


def _optional_positive_int(value: object) -> int | None:
    if isinstance(value, int) and not isinstance(value, bool) and value > 0:
        return value
    return None


def _resolve_player_select_id(
    root: Mapping[str, object],
    leading_role: Mapping[str, object] | None,
    fallback_player_select_id: int | None,
) -> int | None:
    """Resolve the active character without inferring it from a slot name."""

    save_player_select_id = _optional_positive_int(root.get("PlayerSelectId"))
    if save_player_select_id is not None:
        return save_player_select_id

    explicit_player_select_id = _optional_positive_int(fallback_player_select_id)
    if explicit_player_select_id is not None:
        return explicit_player_select_id

    if leading_role is not None:
        leading_role_config_id = _optional_positive_int(leading_role.get("AgentConfigId"))
        return PLAYER_SELECT_ID_BY_AGENT_CONFIG_ID.get(leading_role_config_id)
    return None


def _home_storage_slot_prefixes(player_select_id: int | None) -> tuple[str, ...]:
    if player_select_id is None:
        # Older hand-built fixtures predate PlayerSelectId.  Keep their
        # historical role-1 behavior while real saves use an explicit role.
        return HOME_STORAGE_SLOT_PREFIXES
    return PLAYER_HOME_STORAGE_SLOT_PREFIXES.get(player_select_id, ())


def _known_player_select_id(player_select_id: int | None) -> bool:
    return player_select_id is None or player_select_id in PLAYER_HOME_STORAGE_SLOT_PREFIXES


def _effective_agent_config_id(
    agent: Mapping[str, object],
    storage_config_ids: Collection[int],
) -> int | None:
    bag_config_id = _optional_positive_int(agent.get("BagFurnitureConfigId"))
    agent_config_id = _optional_positive_int(agent.get("AgentConfigId"))
    if bag_config_id is not None and (
        bag_config_id in storage_config_ids
        or agent_config_id is None
        or agent.get("IsDoorBox") is True
    ):
        return bag_config_id
    return agent_config_id or bag_config_id


def _agent_instance_id(agent: Mapping[str, object]) -> int | None:
    for field_name in ("SaveInstanceId", "NewInstanceId"):
        instance_id = _optional_positive_int(agent.get(field_name))
        if instance_id is not None:
            return instance_id
    return None


def _storage_location(
    agent: Mapping[str, object],
    *,
    chapter_map_key: int | None,
    home_map_config_id: int | None,
    player_select_id: int | None,
) -> tuple[str, bool | None]:
    map_config_id = _optional_positive_int(agent.get("MapConfigId"))
    slot_pos_point = str(agent.get("SlotPosPoint") or "").strip().casefold()

    if (
        chapter_map_key is not None
        and home_map_config_id is not None
        and chapter_map_key != home_map_config_id
    ):
        return STORAGE_LOCATION_OTHER, False

    if (
        map_config_id is not None
        and home_map_config_id is not None
        and map_config_id != home_map_config_id
    ):
        return STORAGE_LOCATION_OTHER, False

    home_prefixes = _home_storage_slot_prefixes(player_select_id)
    if slot_pos_point.startswith(home_prefixes):
        if (
            home_map_config_id is None
            or map_config_id is None
            or map_config_id == home_map_config_id
        ):
            return STORAGE_LOCATION_HOME, True
        return STORAGE_LOCATION_OTHER, False

    if slot_pos_point.startswith(tuple(KNOWN_HOME_STORAGE_SLOT_PREFIXES)):
        return STORAGE_LOCATION_OTHER, False

    if (
        _known_player_select_id(player_select_id)
        and not slot_pos_point
        and map_config_id is not None
        and home_map_config_id is not None
        and map_config_id == home_map_config_id
    ):
        return STORAGE_LOCATION_HOME, True

    return STORAGE_LOCATION_UNKNOWN, None


def _storage_container_key(config_id: int | None) -> str:
    if config_id == 15000:
        return "fridge_15000"
    if config_id == 15001:
        return "freezer_15001"
    if config_id is None:
        return "storage_unknown"
    return f"storage_{config_id}"


def _storage_container_name(
    config_id: int | None,
    storage_furniture: Mapping[int, str],
) -> str:
    if config_id is None:
        return "未知储物容器"
    return str(storage_furniture.get(config_id) or f"ID:{config_id}").strip()


def _storage_container_from_agent(
    agent: Mapping[str, object],
    *,
    config_id: int | None,
    name: str,
    chapter_map_key: int | None,
    home_map_config_id: int | None,
    player_select_id: int | None,
    item_stack_count: int,
) -> StorageContainer:
    location, is_home = _storage_location(
        agent,
        chapter_map_key=chapter_map_key,
        home_map_config_id=home_map_config_id,
        player_select_id=player_select_id,
    )
    return StorageContainer(
        config_id=config_id,
        name=name,
        instance_id=_agent_instance_id(agent),
        map_config_id=_optional_positive_int(agent.get("MapConfigId")),
        home_map_config_id=home_map_config_id,
        chapter_map_key=_optional_positive_int(chapter_map_key),
        chapter_id=agent.get("ChapterId") if isinstance(agent.get("ChapterId"), int) else None,
        slot_pos_point=str(agent.get("SlotPosPoint") or "").strip(),
        location=location,
        is_home=is_home,
        item_stack_count=item_stack_count,
    )


def _inventory_from_game_save(
    root: dict[str, object],
    file_info: SaveFileInfo,
    *,
    cookable_item_ids: Collection[int] | None = None,
    storage_furniture: Mapping[int, str] | None = None,
    player_select_id: int | None = None,
) -> SaveInventoryState:
    child = root.get("CurSave")
    if not isinstance(child, dict):
        raise SaveParseError(
            "GameSaveData.CurSave 缺失或为 null",
            code="game_save_missing_cur_save",
            stage="inventory",
        )
    diagnostics: list[str] = []
    raw_items: list[InventoryItem] = []
    container_counts: dict[str, int] = {}
    leading_role = child.get("LeadingRole")
    home_map_config_id: int | None = None
    if isinstance(leading_role, dict):
        container_counts["主控背包"] = _append_inventory_items(
            raw_items,
            leading_role.get("ItemList"),
            source="主控背包",
            container="leading_role",
            diagnostics=diagnostics,
        )
        home_map_config_id = _optional_positive_int(leading_role.get("MapConfigIdHome"))
    else:
        diagnostics.append("CurSave.LeadingRole 缺失或为 null")

    legacy_storage = {15000: "双开门冰箱", 15001: "冰柜"}
    resolved_player_select_id = _resolve_player_select_id(
        root,
        leading_role if isinstance(leading_role, dict) else None,
        player_select_id,
    )
    storage_names = _normalize_storage_furniture(
        legacy_storage if storage_furniture is None else storage_furniture
    )
    container_keys = {
        config_id: _storage_container_key(config_id)
        for config_id in storage_names
    }
    for container_key in container_keys.values():
        container_counts[container_key] = 0

    storage_agents: list[tuple[int | None, int | None, dict[str, object]]] = []
    actual_storage_config_ids: set[int] = set()
    chapter_agents = child.get("ChapterAgentMap")
    if isinstance(chapter_agents, dict):
        for chapter_map_key, agents in chapter_agents.items():
            for agent in _item_dicts(agents):
                config_id = _effective_agent_config_id(agent, storage_names)
                if config_id not in storage_names and agent.get("IsDoorBox") is not True:
                    continue
                chapter_key = (
                    chapter_map_key
                    if isinstance(chapter_map_key, int) and not isinstance(chapter_map_key, bool)
                    else None
                )
                storage_agents.append((config_id, chapter_key, agent))
                if config_id in {15000, 15001}:
                    actual_storage_config_ids.add(config_id)
    else:
        diagnostics.append("CurSave.ChapterAgentMap 缺失或为 null")

    storage_agents.sort(
        key=lambda value: (
            int(value[0]) if value[0] is not None else 2_147_483_647,
            int(_agent_instance_id(value[2]) or 0),
            int(value[1]) if value[1] is not None else 0,
            str(value[2].get("SlotPosPoint") or ""),
        )
    )
    storage_containers: list[StorageContainer] = []
    for config_id, chapter_map_key, agent in storage_agents:
        item_values = agent.get("ItemList")
        item_stack_count = len(_item_dicts(item_values))
        name = _storage_container_name(config_id, storage_names)
        container = _storage_container_from_agent(
            agent,
            config_id=config_id,
            name=name,
            chapter_map_key=chapter_map_key,
            home_map_config_id=home_map_config_id,
            player_select_id=resolved_player_select_id,
            item_stack_count=item_stack_count,
        )
        storage_containers.append(container)
        if container.is_home is True:
            container_key = _storage_container_key(config_id)
            container_counts[container_key] = container_counts.get(container_key, 0) + _append_inventory_items(
                raw_items,
                item_values,
                source=name,
                container=container_key,
                diagnostics=diagnostics,
            )
        elif container.is_home is None:
            instance_label = (
                f"实例 ID {container.instance_id}"
                if container.instance_id is not None
                else "无实例 ID"
            )
            diagnostics.append(
                f"储物容器 {name}（{instance_label}）的位置无法确认，已跳过其库存"
            )

    fallback_fields = {15000: "DoorBoxItems", 15001: "DoorBoxItems2"}
    for config_id in sorted(storage_names):
        source_name = _storage_container_name(config_id, storage_names)
        container_key = container_keys[config_id]
        fallback_field = fallback_fields.get(config_id)
        direct_items = child.get(fallback_field) if fallback_field else None
        direct_count = len(_item_dicts(direct_items))
        if config_id in actual_storage_config_ids:
            if direct_count and fallback_field:
                diagnostics.append(
                    f"{source_name}同时存在标记家具和兼容字段 {fallback_field}；已保留标记家具结果"
                )
        elif fallback_field and direct_items is not None:
            container = StorageContainer(
                config_id=config_id,
                name=source_name,
                instance_id=None,
                map_config_id=home_map_config_id,
                home_map_config_id=home_map_config_id,
                chapter_map_key=None,
                chapter_id=None,
                slot_pos_point="",
                location=STORAGE_LOCATION_HOME,
                is_home=True,
                item_stack_count=direct_count,
            )
            storage_containers.append(container)
            container_counts[container_key] = _append_inventory_items(
                raw_items,
                direct_items,
                source=f"{source_name}（兼容字段）",
                container=container_key,
                diagnostics=diagnostics,
            )

    if "WorkbenchDrawerItems" in child:
        direct_items = child.get("WorkbenchDrawerItems")
        direct_count = len(_item_dicts(direct_items))
        storage_containers.append(
            StorageContainer(
                config_id=None,
                name="工作台抽屉",
                instance_id=None,
                map_config_id=home_map_config_id,
                home_map_config_id=home_map_config_id,
                chapter_map_key=None,
                chapter_id=None,
                slot_pos_point="",
                location=STORAGE_LOCATION_HOME,
                is_home=True,
                item_stack_count=direct_count,
            )
        )
        container_counts["workbench_drawer"] = _append_inventory_items(
            raw_items,
            direct_items,
            source="工作台抽屉",
            container="workbench_drawer",
            diagnostics=diagnostics,
        )

    if cookable_item_ids is not None:
        allowed = frozenset(int(item_id) for item_id in cookable_item_ids)
        raw_items = [item for item in raw_items if item.item_config_id in allowed]
    return SaveInventoryState(
        file_info=file_info,
        items=tuple(raw_items),
        diagnostics=tuple(diagnostics),
        container_counts=container_counts,
        storage_containers=tuple(storage_containers),
    )


def read_game_save_inventory_bytes(
    data: bytes,
    *,
    source_path: Path | None = None,
    file_info: SaveFileInfo | None = None,
    cookable_item_ids: Collection[int] | None = None,
    storage_furniture: Mapping[int, str] | None = None,
    player_select_id: int | None = None,
) -> SaveInventoryState:
    """Read only the current save's player inventory from GameSaveData bytes."""

    info = file_info or _save_file_info(source_path or Path("<memory>"), data)
    root = _read_game_save_wire(data)
    return _inventory_from_game_save(
        root,
        info,
        cookable_item_ids=cookable_item_ids,
        storage_furniture=storage_furniture,
        player_select_id=player_select_id,
    )


def _read_stable_game_save_file(
    path: Path,
    *,
    used_backup: bool,
    cookable_item_ids: Collection[int] | None,
    storage_furniture: Mapping[int, str] | None,
    player_select_id: int | None,
) -> SaveInventoryState:
    try:
        before = path.stat()
        if not path.is_file():
            raise OSError("路径不是文件")
        data = path.read_bytes()
        after = path.stat()
    except OSError as exc:
        raise SaveParseError(f"读取子存档失败 {path}：{exc}", code="game_save_file_error", stage="file_open") from exc
    if before.st_size != after.st_size or before.st_mtime_ns != after.st_mtime_ns:
        raise SaveParseError(f"子存档正在写入，读取期间文件发生变化：{path}", code="game_save_changed", stage="file_open")
    info = _save_file_info(path, data, used_backup=used_backup)
    return read_game_save_inventory_bytes(
        data,
        file_info=info,
        cookable_item_ids=cookable_item_ids,
        storage_furniture=storage_furniture,
        player_select_id=player_select_id,
    )


def read_game_save_inventory(
    save_file: Path,
    *,
    allow_backup: bool = True,
    cookable_item_ids: Collection[int] | None = None,
    storage_furniture: Mapping[int, str] | None = None,
    player_select_id: int | None = None,
) -> SaveInventoryState:
    """Read a child save, preferring its active bytes and then its .bak copy."""

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
            return _read_stable_game_save_file(
                candidate,
                used_backup=used_backup,
                cookable_item_ids=cookable_item_ids,
                storage_furniture=storage_furniture,
                player_select_id=player_select_id,
            )
        except SaveParseError as exc:
            errors.append(str(exc))
            last_error = exc
    raise SaveParseError(
        "无法读取有效的子存档：" + "；".join(errors),
        code=last_error.code if last_error else "game_save_file_unavailable",
        stage=last_error.stage if last_error else "file_open",
        offset=last_error.offset if last_error else None,
        details={"attempts": errors},
    )


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

    try:
        return _parse_history_data_strict(
            data,
            source_path=source_path,
            file_info=file_info,
        )
    except SaveParseError as strict_error:
        # Older fixtures used by the codex scanner predate the full HistoryData
        # schema. Keep their structural scanner available, but never use it for
        # the recipe inventory path.
        prefix_error: SaveParseError | None = strict_error

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
        history_records=(),
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


def _read_stable_history_file(path: Path, *, used_backup: bool) -> CodexSaveState:
    try:
        before = path.stat()
        if not path.is_file():
            raise OSError("路径不是文件")
        data = path.read_bytes()
        after = path.stat()
    except OSError as exc:
        raise SaveParseError(f"读取 HistorySave 失败 {path}：{exc}", code="history_file_error", stage="file_open") from exc
    if before.st_size != after.st_size or before.st_mtime_ns != after.st_mtime_ns:
        raise SaveParseError(f"HistorySave 正在写入，读取期间文件发生变化：{path}", code="history_changed", stage="file_open")
    info = _save_file_info(path, data, used_backup=used_backup)
    return _parse_history_data_strict(data, file_info=info)


def read_history_save(save_file: Path, *, allow_backup: bool = True) -> CodexSaveState:
    """Read the current HistoryData schema without structural map scanning."""

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
            return _read_stable_history_file(candidate, used_backup=used_backup)
        except SaveParseError as exc:
            errors.append(str(exc))
            last_error = exc
    raise SaveParseError(
        "无法读取严格 HistorySave：" + "；".join(errors),
        code=last_error.code if last_error else "history_file_unavailable",
        stage=last_error.stage if last_error else "file_open",
        offset=last_error.offset if last_error else None,
        details={"attempts": errors},
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
    "ALLOWED_STORAGE_FURNITURE_NAMES",
    "CODEX_CATEGORY_IDS",
    "CODEX_CATEGORY_SOURCE_TABLES",
    "CodexMapCandidate",
    "CodexSaveState",
    "InventoryItem",
    "SaveFileInfo",
    "SaveHistoryRecord",
    "SaveInventoryState",
    "SaveParseError",
    "StorageContainer",
    "build_save_diagnostic",
    "default_save_file",
    "parse_codex_save_bytes",
    "read_codex_save",
    "read_game_save_inventory",
    "read_game_save_inventory_bytes",
    "read_history_save",
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
