#!/usr/bin/env python3
"""Offline codex extractor for Survival Log.

The game uses YooAsset bundles encrypted by GameCore.Scripts.BundleCrypto and
stores codex configuration tables as MemoryPack TextAssets.  This tool reads those
files directly; it never starts the game and never changes the installation.
"""

from __future__ import annotations

import argparse
import hashlib
import os
import struct
import sys
from collections import defaultdict
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Iterable


if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")
if hasattr(sys.stderr, "reconfigure"):
    sys.stderr.reconfigure(encoding="utf-8")


SALT = b"SL_BundleCrypto_v1_9f3d7a1c"
_PROJECT_DIR = Path(__file__).resolve().parent
DEFAULT_SNAPSHOT_DIR = _PROJECT_DIR / "snapshots"
_VENDOR_CANDIDATES = (_PROJECT_DIR / "_vendor_unitypy",)
_configured_vendor = os.environ.get("SURVIVALLOG_UNITYPY_DIR")
VENDOR_DIR = (
    Path(_configured_vendor)
    if _configured_vendor
    else next((path for path in _VENDOR_CANDIDATES if path.is_dir()), _VENDOR_CANDIDATES[0])
)
_BUNDLE_ENV_CACHE: dict[Path, Any] = {}


def load_unitypy() -> Any:
    """Load the bundled UnityPy dependency, with a useful error if absent."""

    if VENDOR_DIR.is_dir() and str(VENDOR_DIR) not in sys.path:
        sys.path.insert(0, str(VENDOR_DIR))
    try:
        import UnityPy  # type: ignore
    except ImportError as exc:  # pragma: no cover - only used on a new machine
        raise RuntimeError(
            f"缺少 UnityPy。请先运行：python -m pip install --target "
            f"\"{VENDOR_DIR}\" UnityPy，或设置 SURVIVALLOG_UNITYPY_DIR；"
            f"导入错误：{exc}"
        ) from exc
    return UnityPy


class Reader:
    """Small little-endian reader for the MemoryPack wire format."""

    def __init__(self, data: bytes):
        self.data = data
        self.pos = 0

    def _need(self, size: int) -> None:
        if self.pos + size > len(self.data):
            raise ValueError(
                f"数据提前结束：offset={self.pos}, need={size}, total={len(self.data)}"
            )

    def u8(self) -> int:
        self._need(1)
        value = self.data[self.pos]
        self.pos += 1
        return value

    def u16(self) -> int:
        self._need(2)
        value = struct.unpack_from("<H", self.data, self.pos)[0]
        self.pos += 2
        return value

    def i32(self) -> int:
        self._need(4)
        value = struct.unpack_from("<i", self.data, self.pos)[0]
        self.pos += 4
        return value

    def u32(self) -> int:
        self._need(4)
        value = struct.unpack_from("<I", self.data, self.pos)[0]
        self.pos += 4
        return value

    def i64(self) -> int:
        self._need(8)
        value = struct.unpack_from("<q", self.data, self.pos)[0]
        self.pos += 8
        return value

    def f32(self) -> float:
        self._need(4)
        value = struct.unpack_from("<f", self.data, self.pos)[0]
        self.pos += 4
        return value

    def boolean(self) -> bool:
        return bool(self.u8())

    def catalog_string(self) -> str:
        size = self.u16()
        self._need(size)
        value = self.data[self.pos : self.pos + size].decode("utf-8")
        self.pos += size
        return value

    def memorypack_string(self) -> str | None:
        """Read MemoryPack's UTF-8/UTF-16 string forms."""

        marker = self.i32()
        if marker == -1:
            return None
        if marker == 0:
            return ""
        if marker <= -2:
            utf8_size = ~marker
            _utf16_length = self.i32()
            self._need(utf8_size)
            value = self.data[self.pos : self.pos + utf8_size].decode("utf-8")
            self.pos += utf8_size
            return value
        utf16_size = marker * 2
        self._need(utf16_size)
        value = self.data[self.pos : self.pos + utf16_size].decode("utf-16-le")
        self.pos += utf16_size
        return value

    def int_list(self) -> list[int] | None:
        count = self.i32()
        if count == -1:
            return None
        if count < -1 or count > 1_000_000:
            raise ValueError(f"非法列表长度 {count} at offset {self.pos - 4}")
        return [self.i32() for _ in range(count)]

    def string_list(self) -> list[str | None] | None:
        count = self.i32()
        if count == -1:
            return None
        if count < -1 or count > 1_000_000:
            raise ValueError(f"非法字符串列表长度 {count} at offset {self.pos - 4}")
        return [self.memorypack_string() for _ in range(count)]


@dataclass(frozen=True)
class BundleRecord:
    name: str
    file_hash: str
    file_size: int
    encrypted: bool


SchemaField = tuple[str, str]


@dataclass(frozen=True)
class ConfigRow:
    """One MemoryPack configuration object, kept as named raw fields."""

    table: str
    values: dict[str, Any]

    @property
    def row_id(self) -> int:
        value = self.values.get("ID", self.values.get("Lv"))
        if not isinstance(value, int):
            raise ValueError(f"{self.table} row has no integer ID/Lv: {value!r}")
        return value


@dataclass
class ExtractionContext:
    game_root: Path
    package_version: str
    bundle_name: str
    bundle_path: Path
    tables: dict[str, list[ConfigRow]]

    @property
    def items(self) -> dict[int, ConfigRow]:
        return {row.row_id: row for row in self.tables["Config_Item"]}

    @property
    def item_names(self) -> dict[int, str]:
        return {
            row.row_id: str(row.values.get("ItemName_Local") or row.values.get("ItemName") or "")
            for row in self.tables["Config_Item"]
        }

    @property
    def subcategory_names(self) -> dict[int, str]:
        return {
            row.row_id: str(row.values.get("Name_Local") or row.values.get("Name") or "")
            for row in self.tables["Config_ItemSubCategory"]
        }

    @property
    def food_type_names(self) -> dict[int, str]:
        return {
            row.row_id: str(row.values.get("Name_Local") or row.values.get("Name") or "")
            for row in self.tables["Config_FoodType"]
        }

    @property
    def dish_names(self) -> dict[int, str]:
        return {
            row.row_id: str(
                row.values.get("RecipeName_Local")
                or row.values.get("RecipeName")
                or f"ID:{row.row_id}"
            )
            for row in self.tables["Config_CookingRecipe"]
        }

    @property
    def furniture_func_names(self) -> dict[int, str]:
        return {
            row.row_id: str(row.values.get("BtnName_Local") or row.values.get("BtnName") or "")
            for row in self.tables.get("Config_FurnitureFunc", [])
        }


# These are the serialized backing-field schemas from the current HotUpdate.dll
# interop metadata. Computed MainKey properties are intentionally not serialized.
CONFIG_SCHEMAS: dict[str, tuple[SchemaField, ...]] = {
    "Config_Item": (
        ("ID", "i32"), ("ItemName", "str"), ("ItemName_Local", "str"),
        ("ItemDes1", "str"), ("ItemDes1_Local", "str"), ("ItemDes2", "str"),
        ("ItemDes2_Local", "str"), ("ValueDisplay1", "f32"), ("ValueDisplay2", "f32"),
        ("ValueDisplay3", "f32"), ("ValueDisplay4", "f32"), ("ValueDisplay5", "f32"),
        ("StackLimit", "i32"), ("Category", "i32"), ("SubCategory", "i32"),
        ("CanCook", "bool"), ("FoodTag1", "i32"), ("FoodTag2", "i32"),
        ("FoodTag3", "i32"), ("Size", "list_i32"), ("price", "i32"),
        ("weight", "i32"), ("Life", "i32"), ("IT_Rot_Threshold", "f32"),
        ("It_Rot_Product_Id", "list_i32"), ("UseTimes", "i32"), ("CantUse", "bool"),
        ("CanUsePeace", "bool"), ("OverdueDebuff", "list_i32"), ("DebuffPow", "list_i32"),
        ("Taste", "i32"), ("WishPower", "i32"), ("Story", "i32"), ("DailyMax", "i32"),
        ("Plant", "i32"), ("Plant_Fast", "f32"), ("Burnable", "bool"),
        ("BurnValue", "i32"), ("Trap", "i32"), ("TargetFurnitureID", "i32"),
        ("Prey_Rarity", "i32"), ("IT_Discovery_Exp", "i32"), ("CaptureExp", "i32"),
        ("ItemFmodPath", "str"), ("Icon", "str"), ("WebIcon", "str"), ("Model", "str"),
        ("ConditionSetId", "i32"), ("IsHighDemand", "bool"), ("TradeValue", "i32"),
        ("RecommendType", "i32"), ("RecommendWeight", "i32"), ("InCodex", "bool"),
        ("DemoTwoMode", "i32"), ("VaseLife", "i32"), ("VaseMoraleRate", "f32"),
        ("VaseModel", "str"), ("CanBrew", "bool"), ("CutProductId", "i32"),
        ("UseAction", "i32"),
    ),
    "Config_ItemSubCategory": (
        ("ID", "i32"), ("Name", "str"), ("Name_Local", "str"),
    ),
    "Config_FoodType": (
        ("ID", "i32"), ("Name", "str"), ("Name_Local", "str"), ("IT_Icon", "str"),
    ),
    "Config_CookingRecipe": (
        ("ID", "i32"), ("RecipeName", "str"), ("RecipeName_Local", "str"),
        ("TagCombo", "list_i32"), ("SpecificItems", "list_i32"),
        ("PerfectItemID", "i32"), ("GoodItemID", "i32"),
        ("NormalItemID", "i32"), ("FailItemID", "i32"), ("Tier", "i32"),
        ("QualityMap", "list_i32"), ("MinLevel", "i32"), ("CookTime", "i32"),
        ("SatietyStandard", "i32"), ("CookExp", "i32"), ("ShowLevel", "i32"),
        ("CraftLevel", "i32"), ("DiscoveryExp", "i32"),
    ),
    "Config_Plant": (
        ("ID", "i32"), ("Name", "str"), ("Name_Local", "str"), ("Des", "str"),
        ("Des_Local", "str"), ("Modle1", "str"), ("Modle2", "str"), ("Modle3", "str"),
        ("Modle4", "str"), ("Modle5", "str"), ("Size", "i32"), ("GrowthTime", "i32"),
        ("LightNeed", "i32"), ("ColdResistance", "i32"), ("Pest", "f32"), ("Weed", "f32"),
        ("Dry", "f32"), ("Gain", "list_i32"), ("HarvestExp", "i32"),
        ("Perfect_Gain", "list_i32"), ("Perfect_Rate", "f32"), ("Gain_Seed", "list_i32"),
        ("Seed_Rate", "f32"), ("WitheredGain", "list_i32"), ("DecayTime", "i32"),
        ("HarvestTime", "i32"), ("Discovery_Exp", "i32"), ("InCodex", "bool"),
    ),
    "Config_PlantLv": (
        ("Lv", "i32"), ("EXP", "i32"), ("Info", "str"), ("Info_Local", "str"),
        ("required_condition", "list_i32"), ("growth_speed_bonus", "f32"),
        ("pest_rate_reduction", "f32"), ("perfect_grow_rate", "f32"),
        ("research_exp", "i32"), ("research_action_id", "i32"),
    ),
    "Config_ProductionList": (
        ("ID", "i32"), ("ShopName", "str"), ("ShopName_Local", "str"),
        ("DemoTwoMode", "i32"), ("IsUseable", "bool"), ("MaterialList", "list_i32"),
        ("ProductID", "list_i32"), ("FailedID", "list_i32"), ("Level", "i32"),
        ("DiscountRate", "f32"), ("LifeMin", "i32"), ("show_level", "i32"),
        ("craft_level", "i32"), ("perfect_item_id", "list_i32"), ("perfect_rate", "f32"),
        ("discovery_exp", "i32"), ("InCodex", "bool"), ("NoteCategory", "i32"),
        ("defense_exp", "i32"),
    ),
    "Config_ProductionLv": (
        ("Lv", "i32"), ("EXP", "i32"), ("Info", "str"), ("Info_Local", "str"),
        ("required_condition", "list_i32"), ("stamina_reduction", "f32"),
        ("perfect_craft_rate", "f32"),
    ),
    "Config_Furniture": (
        ("ID", "i32"), ("Name", "str"), ("Name_Local", "str"), ("FsmName", "str"),
        ("Story", "i32"), ("ResName", "str"), ("BagResName", "str"), ("ICON", "str"),
        ("FurniturePrice", "i32"), ("PawnPrice", "i32"), ("PurchaseRewardSetId", "i32"),
        ("InstallTime", "i32"), ("Des", "str"), ("Des_Local", "str"),
        ("FurnitureType", "i32"), ("ShopPage", "i32"), ("DemoTwoMode", "i32"),
        ("SlotType", "i32"), ("isAutoSilence", "bool"), ("isShowName", "bool"),
        ("ShowStorage", "i32"), ("isShowHP", "bool"), ("FurnitureHP", "i32"),
        ("FurnitureHPMax", "i32"), ("FurnitureLowHP", "str"), ("FurnitureLowHP_Local", "str"),
        ("isFurnitureDead", "bool"), ("FurnitureDeadText", "str"),
        ("FurnitureDeadText_Local", "str"), ("FurnitureFunc", "list_i32"),
        ("RemoveFunc", "list_i32"), ("MoveFunc", "list_i32"), ("RemoveGet", "list_i32"),
        ("ActionId", "i32"), ("ActionPos", "str"), ("PlantFurnitureID", "i32"),
        ("CookFurnitureID", "i32"), ("VaseCapacity", "i32"), ("BagId", "i32"),
        ("IsElectrical", "bool"), ("ElectricalType", "i32"), ("ColdRate", "f32"),
        ("PowerCost", "i32"), ("PowerMode", "i32"), ("HeatOutput", "i32"),
        ("ElectricalFurnitureID", "i32"), ("RestoreCoeff", "f32"), ("DefReduceCoeff", "f32"),
        ("InCodex", "bool"), ("LootRandomGroupId", "i32"), ("LootRandomGroupId_P1", "i32"),
        ("LootRandomGroupId_P2", "i32"), ("LootRandomGroupId_P3", "i32"),
        ("LootRandomGroupId_P4", "i32"), ("LootRandomCount", "i32"),
        ("RotProductOverride", "list_i32"), ("RotSourceSubCategory", "list_i32"),
    ),
    "Config_FurnitureFunc": (
        ("ID", "i32"), ("BtnName", "str"), ("BtnName_Local", "str"), ("BtnTips", "str"),
        ("BtnTips_Local", "str"), ("ConfirmInfo", "str"), ("ConfirmInfo_Local", "str"),
        ("VisibilityConditionSetId", "i32"), ("DemoTwoMode", "i32"), ("ConditionSetId", "i32"),
        ("BtnIcon", "str"), ("Chapter", "i32"), ("FunCD", "i32"), ("DailyMax", "i32"),
        ("RewardSetId", "i32"), ("FuncType", "i32"), ("ActionIds", "list_i32"),
        ("JumpMapId", "i32"), ("RecommendWeight", "i32"), ("PreviewAttrDelta", "str"),
        ("GroupKey", "str"), ("GroupOrder", "i32"),
    ),
    "Config_FurnitureCook": (
        ("ID", "i32"), ("CookType", "i32"), ("CookMode", "i32"), ("HotPotCookTime", "i32"),
        ("MaxFoodCount", "i32"), ("MaxSeasoningCount", "i32"), ("FuelSlotCount", "i32"),
        ("FuelRate", "f32"), ("SpeedRate", "f32"), ("QualityBonus", "i32"),
        ("AllowedRecipes", "list_i32"), ("InitialFuel", "list_i32"),
    ),
    "Config_FurniturePlant": (
        ("ID", "i32"), ("Capacity", "i32"), ("AddLight", "i32"), ("AddHeat", "i32"),
        ("NeedPower", "bool"), ("ElectricLight", "i32"), ("ElectricHeat", "i32"),
        ("GrowthFaster", "f32"), ("PestControl", "f32"), ("WeedControl", "f32"),
        ("DryControl", "f32"),
    ),
    "Config_FurnitureElectrical": (
        ("ID", "i32"), ("ElectricalType", "i32"), ("BasePower", "f32"),
        ("FuelCost", "f32"), ("FuelSlotCount", "i32"), ("FuelRate", "f32"),
        ("InjectPower", "f32"), ("Capacity", "f32"), ("AllowedRooms", "list_i32"),
    ),
    "Config_FurnitureState": (
        ("ID", "i32"), ("FurnitureBagRate", "list_i32"), ("FurnitureShowState", "list_str"),
    ),
    "Config_FurnitureTag": (
        ("ID", "i32"), ("TagName", "str"), ("TagName_Local", "str"),
        ("IconKey", "str"), ("Color", "str"),
    ),
    "Config_FurniturePartner": (
        ("ID", "i32"), ("TriggerFurnitureId", "i32"), ("PartnerType", "i32"),
        ("PartnerConfigIds", "list_i32"), ("MissingHintKey", "str"), ("PriorityWeight", "i32"),
    ),
}


def find_catalog(game_root: Path) -> Path:
    main = game_root / "SurvivalLog_Data" / "StreamingAssets" / "PackageManifest" / "MainPackage"
    candidates = sorted(main.glob("RuntimeAssets_MainPackage_*.bytes"))
    if not candidates:
        raise FileNotFoundError(f"找不到 YooAsset RuntimeAssets catalog：{main}")
    return candidates[-1]


def parse_catalog(catalog_path: Path) -> tuple[dict[str, int], list[BundleRecord], str]:
    data = catalog_path.read_bytes()
    if data[:4] != b"OOY\x00":
        raise ValueError(f"不是预期的 YooAsset catalog：{catalog_path}")
    reader = Reader(data[4:])

    file_version = reader.catalog_string()
    # PackageManifest fields: three bools, two int32 values, then four strings.
    _enable_addressable = reader.u8()
    _location_to_lower = reader.u8()
    _include_asset_guid = reader.u8()
    _output_name_style = reader.i32()
    _build_bundle_type = reader.i32()
    _build_pipeline = reader.catalog_string()
    _package_name = reader.catalog_string()
    package_version = reader.catalog_string()
    _package_note = reader.catalog_string()

    asset_count = reader.i32()
    if asset_count < 0 or asset_count > 1_000_000:
        raise ValueError(f"catalog asset count is invalid: {asset_count}")

    asset_to_bundle: dict[str, int] = {}
    for _ in range(asset_count):
        _address = reader.catalog_string()
        asset_path = reader.catalog_string()
        _asset_guid = reader.catalog_string()
        tag_count = reader.u16()
        for _ in range(tag_count):
            reader.catalog_string()
        bundle_id = reader.i32()
        dependency_count = reader.u16()
        for _ in range(dependency_count):
            reader.u32()
        asset_to_bundle[asset_path] = bundle_id

    bundle_count = reader.u32()
    bundles: list[BundleRecord] = []
    for _ in range(bundle_count):
        bundle_name = reader.catalog_string()
        _unity_crc = reader.u32()
        file_hash = reader.catalog_string()
        _file_crc = reader.catalog_string()
        file_size = reader.i64()
        encrypted = bool(reader.u8())
        tag_count = reader.u16()
        for _ in range(tag_count):
            reader.catalog_string()
        dependency_count = reader.u16()
        for _ in range(dependency_count):
            reader.u32()
        bundles.append(BundleRecord(bundle_name, file_hash, file_size, encrypted))

    if reader.pos != len(reader.data):
        raise ValueError(
            f"catalog 解析未到末尾：offset={reader.pos}, total={len(reader.data)}"
        )
    return asset_to_bundle, bundles, f"{package_version} / catalog {file_version}"


def locate_bundle(game_root: Path, catalog_path: Path, asset_path: str) -> tuple[Path, BundleRecord, str]:
    asset_to_bundle, bundles, version = parse_catalog(catalog_path)
    if asset_path not in asset_to_bundle:
        raise KeyError(f"catalog 中找不到资源：{asset_path}")
    bundle_id = asset_to_bundle[asset_path]
    try:
        bundle = bundles[bundle_id]
    except IndexError as exc:
        raise ValueError(f"资源的 bundle ID 越界：{bundle_id}") from exc

    main = catalog_path.parent
    expected = main / f"{bundle.file_hash}.bundle"
    if expected.exists():
        return expected, bundle, version
    # Fallback for a future filename style or a moved package directory.
    matches = list(main.rglob(f"{bundle.file_hash}*.bundle"))
    if matches:
        return matches[0], bundle, version
    raise FileNotFoundError(
        f"找不到 bundle 文件：{bundle.file_hash}.bundle（目录：{main}）"
    )


def decrypt_bundle(bundle_path: Path, bundle_name: str) -> bytes:
    data = bytearray(bundle_path.read_bytes())
    key = hashlib.md5(SALT + bundle_name.encode("utf-8")).digest()
    key += hashlib.md5(bundle_name.encode("utf-8") + SALT).digest()
    for index in range(len(data)):
        data[index] ^= key[index % 32]
    if data[:7] != b"UnityFS":
        raise ValueError(f"bundle 解密失败，magic={bytes(data[:16])!r}")
    return bytes(data)


def load_text_asset(game_root: Path, asset_path: str) -> tuple[bytes, str, str, Path]:
    UnityPy = load_unitypy()
    catalog_path = find_catalog(game_root)
    bundle_path, bundle, version = locate_bundle(game_root, catalog_path, asset_path)
    environment = _BUNDLE_ENV_CACHE.get(bundle_path)
    if environment is None:
        decrypted = decrypt_bundle(bundle_path, bundle.name)
        environment = UnityPy.load(decrypted)
        _BUNDLE_ENV_CACHE[bundle_path] = environment
    try:
        asset = environment.container[asset_path]
    except KeyError:
        # UnityPy can normalize path separators in unusual bundle versions.
        asset = next(
            (value for key, value in environment.container.items() if key.replace("\\", "/") == asset_path),
            None,
        )
    if asset is None:
        raise KeyError(f"解密后的 bundle 中找不到 TextAsset：{asset_path}")
    text_asset = asset.read()
    script = getattr(text_asset, "m_Script", None)
    if not isinstance(script, str):
        raise TypeError(f"资源不是预期的 TextAsset：{asset_path}")
    # UnityPy preserves invalid bytes via surrogateescape when reading TextAsset.
    return script.encode("utf-8", "surrogateescape"), bundle.name, version, bundle_path


def read_schema_value(reader: Reader, kind: str) -> Any:
    if kind == "i32":
        return reader.i32()
    if kind == "f32":
        return reader.f32()
    if kind == "bool":
        return reader.boolean()
    if kind == "str":
        return reader.memorypack_string()
    if kind == "list_i32":
        return reader.int_list()
    if kind == "list_str":
        return reader.string_list()
    raise ValueError(f"未知 MemoryPack 字段类型：{kind}")


def parse_config_table(raw: bytes, table_name: str) -> list[ConfigRow]:
    schema = CONFIG_SCHEMAS.get(table_name)
    if schema is None:
        raise KeyError(f"没有配置表 schema：{table_name}")
    reader = Reader(raw)
    count = reader.i32()
    if count < 0 or count > 2_000_000:
        raise ValueError(f"{table_name} 行数非法：{count}")
    rows: list[ConfigRow] = []
    expected_members = len(schema)
    for index in range(count):
        member_count = reader.u8()
        if member_count != expected_members:
            raise ValueError(
                f"{table_name} schema changed at row {index}: "
                f"member count={member_count}, expected={expected_members}"
            )
        values = {name: read_schema_value(reader, kind) for name, kind in schema}
        rows.append(ConfigRow(table_name, values))
    if reader.pos != len(raw):
        raise ValueError(
            f"{table_name} 解析未到末尾：offset={reader.pos}, total={len(raw)}"
        )
    return rows


def load_config_table(game_root: Path, table_name: str) -> tuple[list[ConfigRow], str, str, Path]:
    asset_path = f"Assets/RuntimeAssets/Config/MemoryPack/Default/{table_name}.bytes"
    raw, bundle_name, package_version, bundle_path = load_text_asset(game_root, asset_path)
    return parse_config_table(raw, table_name), bundle_name, package_version, bundle_path


def build_extraction_context(game_root: Path) -> ExtractionContext:
    primary_tables = [
        "Config_Item",
        "Config_ItemSubCategory",
        "Config_FoodType",
        "Config_CookingRecipe",
        "Config_Plant",
        "Config_PlantLv",
        "Config_ProductionList",
        "Config_ProductionLv",
        "Config_Furniture",
        "Config_FurnitureFunc",
        "Config_FurnitureCook",
        "Config_FurniturePlant",
        "Config_FurnitureElectrical",
        "Config_FurnitureState",
        "Config_FurnitureTag",
        "Config_FurniturePartner",
    ]
    tables: dict[str, list[ConfigRow]] = {}
    bundle_names: set[str] = set()
    package_versions: set[str] = set()
    bundle_paths: set[Path] = set()
    for table_name in primary_tables:
        rows, bundle_name, package_version, bundle_path = load_config_table(game_root, table_name)
        tables[table_name] = rows
        bundle_names.add(bundle_name)
        package_versions.add(package_version)
        bundle_paths.add(bundle_path)

    if len(bundle_names) != 1 or len(package_versions) != 1 or len(bundle_paths) != 1:
        raise ValueError("图鉴配置不在同一个资源包/版本中，当前游戏资源结构发生变化。")

    return ExtractionContext(
        game_root=game_root,
        package_version=next(iter(package_versions)),
        bundle_name=next(iter(bundle_names)),
        bundle_path=next(iter(bundle_paths)),
        tables=tables,
    )


def classify_codex_items(context: ExtractionContext) -> tuple[list[ConfigRow], list[ConfigRow]]:
    """Select the food and prey rows used by the current export policy.

    The game has no standalone Config_Prey table. Prey are Config_Item rows
    with a prey rarity; food requires both the codex marker and Category == 1.
    An item can therefore occur in both tabs.  The prey selector intentionally
    keeps every positive-rarity row, while the raw InCodex value is preserved.
    """

    items = context.tables["Config_Item"]
    food: list[ConfigRow] = []
    prey: list[ConfigRow] = []
    for row in items:
        values = row.values
        if int(values.get("Prey_Rarity") or 0) > 0:
            prey.append(row)
        if values.get("InCodex") and int(values.get("Category") or 0) == 1:
            food.append(row)
    return food, prey


def select_category_rows(context: ExtractionContext) -> dict[str, list[ConfigRow]]:
    """Return one shared row selection for all primary codex categories."""

    food, prey = classify_codex_items(context)
    return {
        "food": food,
        "dish": list(context.tables["Config_CookingRecipe"]),
        "plant": list(context.tables["Config_Plant"]),
        "prey": prey,
        "craft": list(context.tables["Config_ProductionList"]),
        "furniture": list(context.tables["Config_Furniture"]),
    }


def scan_item_names(raw: bytes) -> dict[int, str]:
    """Extract ItemName_Local after each Item_ItemName_<id> string.

    Config_Item has many fields, but the two adjacent strings needed here are
    stable and this avoids hard-coding the full 60-field item schema.
    """

    names: dict[int, str] = {}
    prefix = b"Item_ItemName_"
    position = 0
    while True:
        start = raw.find(prefix, position)
        if start < 0:
            break
        number_start = start + len(prefix)
        number_end = number_start
        while number_end < len(raw) and 48 <= raw[number_end] <= 57:
            number_end += 1
        if number_end == number_start:
            position = start + 1
            continue
        item_id = int(raw[number_start:number_end])
        reader = Reader(raw)
        reader.pos = number_end
        local_name = reader.memorypack_string()
        names[item_id] = local_name or ""
        position = number_end
    return names


def parse_subcategories(raw: bytes) -> dict[int, str]:
    reader = Reader(raw)
    count = reader.i32()
    result: dict[int, str] = {}
    for _ in range(count):
        member_count = reader.u8()
        if member_count != 3:
            raise ValueError(f"Config_ItemSubCategory member count changed: {member_count}")
        category_id = reader.i32()
        reader.memorypack_string()  # localization key
        result[category_id] = reader.memorypack_string() or ""
    return result


def display_item(item_id: int, item_names: dict[int, str]) -> str:
    return item_names.get(item_id) or f"ID:{item_id}"


def display_ingredients(
    dish: ConfigRow,
    item_names: dict[int, str],
    subcategories: dict[int, str],
) -> tuple[str, str]:
    values = dish.values
    specific_items = values.get("SpecificItems")
    tag_combo = values.get("TagCombo")
    if specific_items:
        names = [display_item(item_id, item_names) for item_id in specific_items]
        return "、".join(names), ", ".join(str(item_id) for item_id in specific_items)
    if tag_combo:
        names = [subcategories.get(tag_id) or f"ID:{tag_id}" for tag_id in tag_combo]
        return "、".join(names), ", ".join(str(tag_id) for tag_id in tag_combo)
    return "无", ""


def output_name(item_id: int, item_names: dict[int, str]) -> str:
    return display_item(item_id, item_names) if item_id else "无"


def md_escape(value: str) -> str:
    return value.replace("|", "\\|").replace("\r", " ").replace("\n", " ")


FIELD_LABELS = {
    "ID": "ID", "ItemName": "名称键", "ItemName_Local": "名称", "ItemDes1": "描述键1",
    "RecipeName": "菜肴名称键", "RecipeName_Local": "菜肴名称",
    "TagCombo": "食材分类", "SpecificItems": "具体食材",
    "PerfectItemID": "完美产物 ID", "GoodItemID": "良好产物 ID",
    "NormalItemID": "普通产物 ID", "FailItemID": "失败产物 ID",
    "QualityMap": "品质映射", "MinLevel": "最低等级", "CookTime": "烹饪时间",
    "SatietyStandard": "饱腹标准", "CookExp": "烹饪经验", "ShowLevel": "显示等级",
    "CraftLevel": "制作等级", "DiscoveryExp": "发现经验",
    "ItemDes1_Local": "描述1", "ItemDes2": "描述键2", "ItemDes2_Local": "描述2",
    "ValueDisplay1": "属性1", "ValueDisplay2": "属性2", "ValueDisplay3": "属性3",
    "ValueDisplay4": "属性4", "ValueDisplay5": "属性5", "StackLimit": "堆叠上限",
    "Category": "物品大类 ID", "SubCategory": "物品子类", "CanCook": "可烹饪",
    "FoodTag1": "食品标签1", "FoodTag2": "食品标签2", "FoodTag3": "食品标签3",
    "Size": "尺寸", "price": "价格", "weight": "重量", "Life": "保质时间",
    "IT_Rot_Threshold": "腐烂阈值", "It_Rot_Product_Id": "腐烂产物",
    "UseTimes": "使用次数", "CantUse": "不可使用", "CanUsePeace": "和平模式可用",
    "OverdueDebuff": "过期负面效果", "DebuffPow": "负面效果强度", "Taste": "口味",
    "WishPower": "愿望力量", "Story": "故事 ID", "DailyMax": "每日上限",
    "Plant": "植物 ID", "Plant_Fast": "快速生长系数", "Burnable": "可燃烧",
    "BurnValue": "燃烧值", "Trap": "陷阱 ID", "TargetFurnitureID": "目标家具 ID",
    "Prey_Rarity": "猎物稀有度", "IT_Discovery_Exp": "发现经验", "CaptureExp": "捕获经验",
    "ItemFmodPath": "FMOD 路径", "Icon": "图标", "WebIcon": "网页图标", "Model": "模型",
    "ConditionSetId": "条件组 ID", "IsHighDemand": "高需求", "TradeValue": "交易价值",
    "RecommendType": "推荐类型", "RecommendWeight": "推荐权重", "InCodex": "进入图鉴",
    "DemoTwoMode": "Demo 模式", "VaseLife": "花瓶寿命", "VaseMoraleRate": "花瓶士气系数",
    "VaseModel": "花瓶模型", "CanBrew": "可酿造", "CutProductId": "切割产物", "UseAction": "使用动作",
    "Name": "名称键", "Name_Local": "名称", "Des": "描述键", "Des_Local": "描述",
    "GrowthTime": "生长时间", "LightNeed": "光照需求", "ColdResistance": "耐寒",
    "Pest": "虫害", "Weed": "杂草", "Dry": "干旱", "Gain": "收获产物",
    "HarvestExp": "收获经验", "Perfect_Gain": "完美收获产物", "Perfect_Rate": "完美率",
    "Gain_Seed": "种子产物", "Seed_Rate": "种子率", "WitheredGain": "枯萎产物",
    "DecayTime": "腐烂时间", "HarvestTime": "收获时间", "Discovery_Exp": "发现经验",
    "Lv": "等级", "EXP": "经验", "Info": "说明键", "Info_Local": "说明",
    "required_condition": "前置条件", "growth_speed_bonus": "生长速度加成",
    "pest_rate_reduction": "虫害降低", "perfect_grow_rate": "完美生长率",
    "research_exp": "研究经验", "research_action_id": "研究动作 ID",
    "ShopName": "制造名称键", "ShopName_Local": "制造名称", "IsUseable": "可使用",
    "MaterialList": "材料", "ProductID": "产物", "FailedID": "失败产物", "Level": "要求等级",
    "DiscountRate": "折扣率", "LifeMin": "最短时间", "show_level": "显示等级",
    "craft_level": "制作等级", "perfect_item_id": "完美产物", "perfect_rate": "完美率",
    "discovery_exp": "发现经验", "NoteCategory": "笔记分类", "defense_exp": "防御经验",
    "stamina_reduction": "体力消耗降低", "perfect_craft_rate": "完美制作率",
    "FsmName": "状态机名称", "Story": "故事 ID", "ResName": "资源名称",
    "BagResName": "包裹资源名称", "ICON": "图标", "FurniturePrice": "家具价格",
    "PawnPrice": "典当价格", "PurchaseRewardSetId": "购买奖励组", "InstallTime": "安装时间",
    "FurnitureType": "家具类型", "ShopPage": "商店页", "SlotType": "家具槽位类型",
    "isAutoSilence": "自动静音", "isShowName": "显示名称", "ShowStorage": "显示储物",
    "isShowHP": "显示耐久", "FurnitureHP": "家具耐久", "FurnitureHPMax": "家具最大耐久",
    "FurnitureLowHP": "低耐久提示键", "FurnitureLowHP_Local": "低耐久提示",
    "isFurnitureDead": "可损坏", "FurnitureDeadText": "损坏提示键", "FurnitureDeadText_Local": "损坏提示",
    "FurnitureFunc": "家具功能", "RemoveFunc": "移除功能", "MoveFunc": "移动功能",
    "RemoveGet": "移除获得", "ActionId": "动作 ID", "ActionPos": "动作位置",
    "PlantFurnitureID": "种植配置 ID", "CookFurnitureID": "烹饪配置 ID", "VaseCapacity": "花瓶容量",
    "BagId": "包裹 ID", "IsElectrical": "通电家具", "ElectricalType": "电力类型",
    "ColdRate": "制冷系数", "PowerCost": "耗电", "PowerMode": "供电模式",
    "HeatOutput": "热量输出", "ElectricalFurnitureID": "电力配置 ID", "RestoreCoeff": "恢复系数",
    "DefReduceCoeff": "防御减伤系数", "LootRandomGroupId": "随机掉落组", "LootRandomGroupId_P1": "掉落组 P1",
    "LootRandomGroupId_P2": "掉落组 P2", "LootRandomGroupId_P3": "掉落组 P3", "LootRandomGroupId_P4": "掉落组 P4",
    "LootRandomCount": "掉落数量", "RotProductOverride": "腐烂产物覆盖", "RotSourceSubCategory": "腐烂来源子类",
    "BtnName": "功能名称键", "BtnName_Local": "功能名称", "BtnTips": "功能提示键", "BtnTips_Local": "功能提示",
    "ConfirmInfo": "确认信息键", "ConfirmInfo_Local": "确认信息", "VisibilityConditionSetId": "显示条件组",
    "ConditionSetId": "条件组", "BtnIcon": "功能图标", "Chapter": "章节", "FunCD": "冷却时间",
    "DailyMax": "每日上限", "RewardSetId": "奖励组", "FuncType": "功能类型", "ActionIds": "动作 ID 列表",
    "JumpMapId": "跳转地图", "RecommendWeight": "推荐权重", "PreviewAttrDelta": "预览属性变化",
    "GroupKey": "功能组键", "GroupOrder": "功能组顺序", "CookType": "烹饪类型", "CookMode": "烹饪模式",
    "HotPotCookTime": "火锅时间", "MaxFoodCount": "最大食材数", "MaxSeasoningCount": "最大调味品数",
    "FuelSlotCount": "燃料槽数", "FuelRate": "燃料消耗率", "SpeedRate": "速度系数",
    "QualityBonus": "品质加成", "AllowedRecipes": "允许菜肴", "InitialFuel": "初始燃料",
    "Capacity": "容量", "AddLight": "增加光照", "AddHeat": "增加热量", "NeedPower": "需要电力",
    "ElectricLight": "电力光照", "ElectricHeat": "电力热量", "GrowthFaster": "生长加速",
    "PestControl": "虫害控制", "WeedControl": "杂草控制", "DryControl": "干旱控制",
    "BasePower": "基础功率", "FuelCost": "燃料消耗", "InjectPower": "注入功率", "AllowedRooms": "允许房间",
    "FurnitureBagRate": "家具包裹率", "FurnitureShowState": "家具显示状态", "TagName": "标签键",
    "TagName_Local": "标签名称", "IconKey": "图标键", "Color": "颜色", "TriggerFurnitureId": "触发家具",
    "PartnerType": "伙伴类型", "PartnerConfigIds": "伙伴配置", "MissingHintKey": "缺失提示键",
    "PriorityWeight": "优先级权重",
}


ITEM_ID_LIST_FIELDS = {
    "It_Rot_Product_Id", "Gain", "Perfect_Gain",
    "Gain_Seed", "WitheredGain", "MaterialList", "ProductID", "FailedID", "perfect_item_id",
    "InitialFuel", "RemoveGet", "RotProductOverride",
}
DISH_ID_LIST_FIELDS = {"AllowedRecipes"}
FURNITURE_FUNC_LIST_FIELDS = {"FurnitureFunc", "RemoveFunc", "MoveFunc"}
SUBCATEGORY_LIST_FIELDS = {"RotSourceSubCategory"}
UNKNOWN_ID_LIST_FIELDS = {"OverdueDebuff", "required_condition", "ActionIds", "AllowedRooms"}
UNKNOWN_ID_SCALAR_FIELDS = {
    "Story", "Trap", "ConditionSetId", "UseAction", "research_action_id",
    "PurchaseRewardSetId", "ActionId", "VisibilityConditionSetId", "RewardSetId",
    "JumpMapId", "LootRandomGroupId", "LootRandomGroupId_P1", "LootRandomGroupId_P2",
    "LootRandomGroupId_P3", "LootRandomGroupId_P4",
}

TABLE_HEADING_LABELS = {
    "Config_FurnitureCook": "家具烹饪配置",
    "Config_FurniturePlant": "家具种植配置",
    "Config_FurnitureElectrical": "家具电力配置",
    "Config_FurnitureState": "家具状态配置",
    "Config_FurniturePartner": "家具伙伴配置",
}


def format_scalar(value: Any) -> str:
    if value is None:
        return "无"
    if isinstance(value, bool):
        return "是" if value else "否"
    if isinstance(value, float):
        return f"{value:.6g}"
    if isinstance(value, list):
        if not value:
            return "[]"
        return "[" + ", ".join(format_scalar(item) for item in value) + "]"
    return str(value)


def resolve_ids(values: list[int] | None, names: dict[int, str]) -> str:
    if not values:
        return "无"
    return "、".join(f"{names.get(value) or f'ID:{value}'}（ID {value}）" for value in values)


def resolve_id(value: int | None, names: dict[int, str]) -> str:
    if not value:
        return "无"
    return f"{names.get(value) or f'ID:{value}'}（ID {value}）"


def unresolved_ids(values: list[int] | None) -> str:
    if not values:
        return "无"
    return "、".join("无" if not value else f"ID:{value}" for value in values)


def resolve_furniture_config_id(
    value: int | None,
    context: ExtractionContext,
    furniture_names: dict[int, str],
    table_name: str,
    label: str,
    link_field: str,
) -> str:
    """Resolve a furniture's secondary-config ID and show its owning furniture."""

    if not value:
        return "无"
    config_ids = {row.row_id for row in context.tables.get(table_name, [])}
    if value not in config_ids:
        return f"ID:{value}"
    related = [
        f"{furniture_names.get(row.row_id) or f'ID:{row.row_id}'}（ID {row.row_id}）"
        for row in context.tables.get("Config_Furniture", [])
        if row.values.get(link_field) == value
    ]
    result = f"{label}（ID {value}）"
    if related:
        result += f"；关联家具：{'、'.join(related)}"
    return result


def config_row_name(row: ConfigRow) -> str:
    values = row.values
    for field in (
        "ItemName_Local", "RecipeName_Local", "Name_Local", "ShopName_Local",
        "BtnName_Local", "TagName_Local", "Info_Local",
    ):
        value = values.get(field)
        if value:
            return str(value)
    for field in (
        "ItemName", "RecipeName", "Name", "ShopName", "BtnName", "TagName", "Info",
    ):
        value = values.get(field)
        if value:
            return str(value)
    return f"ID:{row.row_id}"


def render_config_value(
    table_name: str,
    field: str,
    value: Any,
    context: ExtractionContext,
    furniture_names: dict[int, str],
    plant_names: dict[int, str],
) -> str:
    if field == "SpecificItems" and isinstance(value, list):
        return f"`{format_scalar(value)}`；解析：{md_escape(resolve_ids(value, context.item_names))}"
    if field == "TagCombo" and isinstance(value, list):
        return f"`{format_scalar(value)}`；解析：{md_escape(resolve_ids(value, context.subcategory_names))}"
    if field in {"PerfectItemID", "GoodItemID", "NormalItemID", "FailItemID"} and isinstance(value, int):
        return md_escape(resolve_id(value, context.item_names))
    if field == "CookTime" and isinstance(value, int):
        return f"{value} 秒（{value / 60:.1f} 分钟）"
    if field in ITEM_ID_LIST_FIELDS and isinstance(value, list):
        return f"`{format_scalar(value)}`；解析：{md_escape(resolve_ids(value, context.item_names))}"
    if field in DISH_ID_LIST_FIELDS and isinstance(value, list):
        return f"`{format_scalar(value)}`；解析：{md_escape(resolve_ids(value, context.dish_names))}"
    if field in FURNITURE_FUNC_LIST_FIELDS and isinstance(value, list):
        return f"`{format_scalar(value)}`；解析：{md_escape(resolve_ids(value, context.furniture_func_names))}"
    if field == "PartnerConfigIds" and isinstance(value, list):
        return f"`{format_scalar(value)}`；解析：{md_escape(resolve_ids(value, furniture_names))}"
    if field in SUBCATEGORY_LIST_FIELDS and isinstance(value, list):
        return f"`{format_scalar(value)}`；解析：{md_escape(resolve_ids(value, context.subcategory_names))}"
    if field in {"SubCategory", "RotSourceSubCategory"} and isinstance(value, int):
        if not value:
            return "无"
        return f"{value}；{md_escape(context.subcategory_names.get(value) or f'ID:{value}') }"
    if field in {"FoodTag1", "FoodTag2", "FoodTag3"} and isinstance(value, int):
        if not value:
            return "无"
        return f"{value}；{md_escape(context.food_type_names.get(value) or f'ID:{value}') }"
    if field in {"Plant", "Gain", "Perfect_Gain", "Gain_Seed", "WitheredGain"} and isinstance(value, int):
        return resolve_id(value, plant_names)
    if field in {"TargetFurnitureID", "TriggerFurnitureId"} and isinstance(value, int):
        return resolve_id(value, furniture_names)
    if field == "CutProductId" and isinstance(value, int):
        return resolve_id(value, context.item_names)
    if field == "BagId" and isinstance(value, int):
        return resolve_id(value, context.item_names)
    if field == "PlantFurnitureID" and isinstance(value, int):
        return resolve_furniture_config_id(
            value, context, furniture_names, "Config_FurniturePlant", "种植配置", "PlantFurnitureID"
        )
    if field == "CookFurnitureID" and isinstance(value, int):
        return resolve_furniture_config_id(
            value, context, furniture_names, "Config_FurnitureCook", "烹饪配置", "CookFurnitureID"
        )
    if field == "ElectricalFurnitureID" and isinstance(value, int):
        return resolve_furniture_config_id(
            value, context, furniture_names, "Config_FurnitureElectrical", "电力配置", "ElectricalFurnitureID"
        )
    if field in UNKNOWN_ID_LIST_FIELDS and isinstance(value, list):
        return f"`{format_scalar(value)}`；解析：{md_escape(unresolved_ids(value))}"
    if field in UNKNOWN_ID_SCALAR_FIELDS and isinstance(value, int):
        return "无" if not value else f"ID:{value}"
    return md_escape(format_scalar(value))


def render_config_rows(
    lines: list[str],
    rows: Iterable[ConfigRow],
    table_name: str,
    context: ExtractionContext,
    furniture_names: dict[int, str] | None = None,
    plant_names: dict[int, str] | None = None,
) -> None:
    furniture_names = furniture_names or {}
    plant_names = plant_names or {}
    schema = CONFIG_SCHEMAS[table_name]
    for row in sorted(rows, key=lambda item: item.row_id):
        name = config_row_name(row)
        if name.startswith("ID:"):
            name = f"{TABLE_HEADING_LABELS.get(table_name, table_name)} {row.row_id}"
        name = md_escape(name)
        lines.extend([f"### {name}（ID {row.row_id}）", ""])
        for field, _kind in schema:
            label = FIELD_LABELS.get(field, field)
            value = render_config_value(table_name, field, row.values.get(field), context, furniture_names, plant_names)
            lines.append(f"- {label}：{value}")
        lines.append("")


def markdown_header(title: str, count: int, context: ExtractionContext, source_tables: Iterable[str], note: str) -> list[str]:
    return [
        f"# Survival Log {title}（离线解析）",
        "",
        f"- 生成时间：{datetime.now().astimezone().isoformat(timespec='seconds')}",
        f"- 游戏资源版本：{md_escape(context.package_version)}",
        f"- 数据包：`{context.bundle_name}`",
        f"- 实际读取文件：`{context.bundle_path}`",
        f"- 条目数量：{count}",
        f"- 配置表：`{'`、`'.join(source_tables)}`",
        "- 解析方式：直接读取本地 YooAsset 加密资源包和 MemoryPack 配置，不启动游戏。",
        f"- 说明：{note}",
        "",
    ]


def render_item_category_markdown(
    context: ExtractionContext,
    rows: list[ConfigRow],
    title: str,
    category_note: str,
) -> str:
    furniture_names = {row.row_id: config_row_name(row) for row in context.tables["Config_Furniture"]}
    plant_names = {row.row_id: config_row_name(row) for row in context.tables["Config_Plant"]}
    lines = markdown_header(title, len(rows), context, ("Config_Item", "Config_ItemSubCategory", "Config_FoodType"), category_note)
    lines.extend(["## 条目", ""])
    render_config_rows(lines, rows, "Config_Item", context, furniture_names, plant_names)
    return "\n".join(lines).rstrip() + "\n"


def render_plant_markdown(context: ExtractionContext, rows: list[ConfigRow]) -> str:
    furniture_names = {row.row_id: config_row_name(row) for row in context.tables["Config_Furniture"]}
    plant_names = {row.row_id: config_row_name(row) for row in context.tables["Config_Plant"]}
    lines = markdown_header("植物", len(rows), context, ("Config_Plant", "Config_PlantLv", "Config_Item"), "记录 Config_Plant 全部配置，并将收获物、种子和枯萎产物 ID 解析为物品名称；解锁状态不读取存档。")
    lines.extend(["## 植物", ""])
    render_config_rows(lines, rows, "Config_Plant", context, furniture_names, plant_names)
    return "\n".join(lines).rstrip() + "\n"


def render_production_markdown(context: ExtractionContext, rows: list[ConfigRow]) -> str:
    furniture_names = {row.row_id: config_row_name(row) for row in context.tables["Config_Furniture"]}
    plant_names = {row.row_id: config_row_name(row) for row in context.tables["Config_Plant"]}
    lines = markdown_header("制造", len(rows), context, ("Config_ProductionList", "Config_ProductionLv", "Config_Item"), "记录 Config_ProductionList 全部配置，包含制造材料、产物、失败产物、完美产物、等级、概率和经验等字段；解锁状态不读取存档。")
    lines.extend(["## 制造配方", ""])
    render_config_rows(lines, rows, "Config_ProductionList", context, furniture_names, plant_names)
    return "\n".join(lines).rstrip() + "\n"


def render_furniture_markdown(context: ExtractionContext, rows: list[ConfigRow]) -> str:
    furniture_names = {row.row_id: config_row_name(row) for row in context.tables["Config_Furniture"]}
    plant_names = {row.row_id: config_row_name(row) for row in context.tables["Config_Plant"]}
    source_tables = ("Config_Furniture", "Config_FurnitureFunc", "Config_FurnitureCook", "Config_FurniturePlant", "Config_FurnitureElectrical", "Config_FurnitureState", "Config_FurnitureTag", "Config_FurniturePartner")
    lines = markdown_header("家具", len(rows), context, source_tables, "记录 Config_Furniture 全部配置，并按语义解析家具功能、种植、烹饪和电力关联；解锁状态不读取存档。")
    lines.extend(["## 家具", ""])
    render_config_rows(lines, rows, "Config_Furniture", context, furniture_names, plant_names)
    return "\n".join(lines).rstrip() + "\n"


def render_dish_markdown(context: ExtractionContext, rows: list[ConfigRow]) -> str:
    rows = sorted(rows, key=lambda row: row.row_id)
    groups: dict[int, list[ConfigRow]] = defaultdict(list)
    for dish in rows:
        groups[(dish.row_id // 1000) * 1000].append(dish)

    lines = markdown_header(
        "菜肴",
        len(rows),
        context,
        ("Config_CookingRecipe", "Config_Item", "Config_ItemSubCategory"),
        "记录 Config_CookingRecipe 全部字段；食材、产物和烹饪时间同时保留原始值并提供可读解析。",
    )
    lines.extend(
        [
            "## 字段说明",
            "",
            "菜肴条目按 ID 分段，正文通过统一 schema 输出全部原始字段。具体食材使用 `SpecificItems`，无具体食材时仍保留 `TagCombo`；产物 ID 和食材 ID 尽量解析为配置名称。",
            "",
        ]
    )
    furniture_names = {row.row_id: config_row_name(row) for row in context.tables["Config_Furniture"]}
    plant_names = {row.row_id: config_row_name(row) for row in context.tables["Config_Plant"]}

    for group_id, group_rows in sorted(groups.items()):
        lines.extend([f"## ID {group_id} 段", ""])
        render_config_rows(
            lines,
            group_rows,
            "Config_CookingRecipe",
            context,
            furniture_names,
            plant_names,
        )
    return "\n".join(lines).rstrip() + "\n"


OUTPUT_FILENAMES = {
    "food": "survival_log_food.md",
    "dish": "survival_log_dish.md",
    "plant": "survival_log_plant.md",
    "prey": "survival_log_prey.md",
    "craft": "survival_log_craft.md",
    "furniture": "survival_log_furniture.md",
    "auxiliary": "survival_log_auxiliary.md",
}


AUXILIARY_TABLES = (
    ("Config_ItemSubCategory", "物品子分类"),
    ("Config_FoodType", "食品标签"),
    ("Config_PlantLv", "植物等级配置"),
    ("Config_ProductionLv", "制造等级配置"),
    ("Config_FurnitureFunc", "家具功能配置"),
    ("Config_FurnitureCook", "家具烹饪配置"),
    ("Config_FurniturePlant", "家具种植配置"),
    ("Config_FurnitureElectrical", "家具电力配置"),
    ("Config_FurnitureState", "家具状态配置"),
    ("Config_FurnitureTag", "家具标签配置"),
    ("Config_FurniturePartner", "家具伙伴配置"),
)


def render_auxiliary_markdown(context: ExtractionContext) -> str:
    source_tables = tuple(table_name for table_name, _title in AUXILIARY_TABLES)
    count = sum(len(context.tables[table_name]) for table_name in source_tables)
    furniture_names = {row.row_id: config_row_name(row) for row in context.tables["Config_Furniture"]}
    plant_names = {row.row_id: config_row_name(row) for row in context.tables["Config_Plant"]}
    lines = markdown_header(
        "图鉴辅助配置",
        count,
        context,
        source_tables,
        "保存主图鉴条目引用的分类、等级和家具辅助配置；这些行不参与六类图鉴完成进度。",
    )
    for table_name, title in AUXILIARY_TABLES:
        lines.extend([f"## {title}", ""])
        render_config_rows(
            lines,
            context.tables[table_name],
            table_name,
            context,
            furniture_names,
            plant_names,
        )
    return "\n".join(lines).rstrip() + "\n"


def write_output(path: Path, content: str) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")
    return path


def ensure_output_outside_game_root(game_root: Path, output_path: Path) -> None:
    resolved_game_root = game_root.resolve()
    resolved_output = output_path.resolve()
    try:
        resolved_output.relative_to(resolved_game_root)
    except ValueError:
        return
    raise ValueError(f"拒绝将输出写入游戏安装目录：{resolved_output}")


def export_food(context: ExtractionContext) -> tuple[int, str]:
    rows = select_category_rows(context)["food"]
    return len(rows), render_item_category_markdown(
        context,
        rows,
        "食品",
        "按游戏 Codex 的食品规则导出：进入图鉴且物品大类为食品；猎物物品可以同时出现在食品分类。",
    )


def export_dish(context: ExtractionContext) -> tuple[int, str]:
    rows = select_category_rows(context)["dish"]
    return len(rows), render_dish_markdown(context, rows)


def export_plant(context: ExtractionContext) -> tuple[int, str]:
    rows = select_category_rows(context)["plant"]
    return len(rows), render_plant_markdown(context, rows)


def export_prey(context: ExtractionContext) -> tuple[int, str]:
    rows = select_category_rows(context)["prey"]
    return len(rows), render_item_category_markdown(
        context,
        rows,
        "猎物",
        "按物品配置中的猎物稀有度导出：Prey_Rarity 大于 0；保留原始 InCodex 值，不以该值过滤猎物。",
    )


def export_craft(context: ExtractionContext) -> tuple[int, str]:
    rows = select_category_rows(context)["craft"]
    return len(rows), render_production_markdown(context, rows)


def export_furniture(context: ExtractionContext) -> tuple[int, str]:
    rows = select_category_rows(context)["furniture"]
    return len(rows), render_furniture_markdown(context, rows)


def export_auxiliary(context: ExtractionContext) -> tuple[int, str]:
    count = sum(len(context.tables[table_name]) for table_name, _title in AUXILIARY_TABLES)
    return count, render_auxiliary_markdown(context)


CATEGORY_EXPORTERS = {
    "food": export_food,
    "dish": export_dish,
    "plant": export_plant,
    "prey": export_prey,
    "craft": export_craft,
    "furniture": export_furniture,
    "auxiliary": export_auxiliary,
}


def extract_category(context: ExtractionContext, category: str, output_path: Path) -> tuple[int, Path]:
    try:
        exporter = CATEGORY_EXPORTERS[category]
    except KeyError as exc:
        raise ValueError(f"未知图鉴分类：{category}") from exc
    count, content = exporter(context)
    ensure_output_outside_game_root(context.game_root, output_path)
    return count, write_output(output_path, content)


def extract_all(
    game_root: Path,
    output_dir: Path,
) -> dict[str, tuple[int, Path]]:
    context = build_extraction_context(game_root)
    output_paths = {category: output_dir / filename for category, filename in OUTPUT_FILENAMES.items()}
    results: dict[str, tuple[int, Path]] = {}
    for category in OUTPUT_FILENAMES:
        results[category] = extract_category(context, category, output_paths[category])
    return results


def main() -> int:
    parser = argparse.ArgumentParser(description="离线解析 Survival Log 图鉴并导出 Markdown")
    parser.add_argument(
        "--game-root",
        type=Path,
        default=Path(r"G:\SteamLibrary\steamapps\common\Survival Log"),
        help="游戏安装目录",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=None,
        help="显式单分类时的输出文件路径；all 模式请使用 --output-dir",
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=DEFAULT_SNAPSHOT_DIR,
        help="图鉴 Markdown 的输出目录（默认：snapshots）",
    )
    parser.add_argument(
        "--category",
        choices=["all", "food", "dish", "plant", "prey", "craft", "furniture", "auxiliary"],
        default="all",
        help="导出全部分类，或只导出一个分类；默认全部",
    )
    args = parser.parse_args()
    try:
        if args.category == "all":
            if args.output is not None:
                raise ValueError("--output 只适用于显式单分类；all 模式请使用 --output-dir")
            results = extract_all(args.game_root, args.output_dir)
            for category, (count, path) in results.items():
                print(f"{category}: {count} 条 -> {path}")
        else:
            output_path = args.output or args.output_dir / OUTPUT_FILENAMES[args.category]
            context = build_extraction_context(args.game_root)
            count, path = extract_category(context, args.category, output_path)
            print(f"{args.category}: {count} 条 -> {path}")
    except Exception as exc:  # command-line tool: show a concise actionable error
        print(f"解析失败：{exc}", file=sys.stderr)
        return 1
    print("解析完成")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
