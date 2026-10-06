#!/usr/bin/env python3
"""Extract the public stranger-trade model (contact map trade points and shelves).

联络地图交易据点的静态数据链路为 Config_MapPoint（PointCategory=3，ID 1100-1109）
→ Config_Shop（货架，ID 911-920）→ Config_Item（名称、交易价值、价格、分类）。
两张表的 MemoryPack 线序与 IL2CPP 声明顺序不一致，且 Config_Shop 存在
DemoTwoMode 按四字节写入、随机货架（RandomID=1）在物品列表后携带未解码随机池
数据的线格式差异，因此这里使用专用严格解码：验证对象数量、成员数量与数据 EOF，
只发布语义已核实的字段；随机货架按字节跳过并在诊断中计数。
导出的估值基准是 Config_Item.TradeValue；实际成交比率由游戏运行时需求状态决定，
模型不包含也不推断动态汇率。
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

from codex_parser import Reader, load_config_table, load_text_asset

MAPPOINT_ASSET = "Assets/RuntimeAssets/Config/MemoryPack/Default/Config_MapPoint.bytes"
SHOP_ASSET = "Assets/RuntimeAssets/Config/MemoryPack/Default/Config_Shop.bytes"
# 联络地图交易据点：PointCategory=3 的行，货架引用 Config_Shop 911-920。
TRADE_POINT_CATEGORY = 3
TRADE_SHOP_ID_RANGE = (900, 1000)
# 联络地图据点行的线序前 15 个字段（与 IL2CPP 声明顺序不同，已按当前本地版本核对）。
MAPPOINT_PREFIX = (("ID", "i32"), ("Name", "str"), ("Name_Local", "str"), ("PointCategory", "i32"),
                   ("ChapterID", "i32"), ("Type", "i32"), ("IsUnlock", "u8"), ("Dec", "str"),
                   ("Dec_Local", "str"), ("Icon", "str"), ("WebIcon", "str"), ("Time", "i32"),
                   ("PositionName", "str"), ("ExitPos", "str"), ("EntryNodeName", "str"))
ITEM_ICON_FIELDS = ("Icon", "ICON", "WebIcon", "WebSmallIcon")
# 货架分类标签键（Config_ConstantText），缺失的分类回退为 "分类 N"。
CATEGORY_TEXT_PREFIX = "SR_Web_TradeUI_Cat_"


def read_prefix(reader: Reader) -> dict[str, Any]:
    values: dict[str, Any] = {}
    for name, kind in MAPPOINT_PREFIX:
        if kind == "i32":
            values[name] = reader.i32()
        elif kind == "u8":
            values[name] = reader.u8()
        else:
            values[name] = reader.memorypack_string()
    return values


def decode_mappoint_trade_rows(raw: bytes) -> list[dict[str, Any]]:
    """Decode Config_MapPoint, keeping semantic fields of trade-point rows.

    行内字符串自描述、其余字段按四字节推进；行边界由“下一行成员数量 48 + 合理
    行 ID + 字符串标记”锚定，最后一行读到数据末尾。全部行验证成员数量、行数与
    数据 EOF。交易行中 ShelfShopId 以取值范围识别（911-920），解锁键与提示按
    已知文本前缀识别；空字符串与 0 共用同一编码，未核实语义的字段不发布。
    """

    reader = Reader(raw)
    count = reader.i32()
    points: list[dict[str, Any]] = []
    for index in range(count):
        start = reader.pos
        if reader.u8() != 48:
            raise ValueError(f"Config_MapPoint 行 {index} 成员数量变化 at {start}")
        prefix = read_prefix(reader)
        row_end = len(raw)
        if index + 1 < count:
            for candidate in range(reader.pos, len(raw) - 6):
                if raw[candidate] != 48:
                    continue
                next_id = int.from_bytes(raw[candidate + 1:candidate + 5], "little", signed=True)
                if not 0 < next_id < 100000:
                    continue
                marker = int.from_bytes(raw[candidate + 5:candidate + 9], "little", signed=True)
                if marker <= -2 and 4 <= ~marker <= 64:
                    row_end = candidate
                    break
        strings: list[str] = []
        ints: list[int] = []
        window = Reader(raw)
        window.pos = reader.pos
        while window.pos < row_end:
            marker = window.i32()
            if marker <= -2 and 1 <= ~marker <= 8192:
                window.pos -= 4
                text = window.memorypack_string()
                if text is not None and all(ch.isprintable() or ch == "\u200b" for ch in text):
                    strings.append(text)
                    continue
                window.pos += 4
                ints.append(marker)
            else:
                ints.append(marker)
        reader.pos = row_end
        if reader.pos > len(raw):
            raise ValueError(f"Config_MapPoint 行 {index} 越出数据末尾：{reader.pos} / {len(raw)}")
        if prefix["PointCategory"] != TRADE_POINT_CATEGORY:
            continue
        shop_id = next((value for value in ints
                        if TRADE_SHOP_ID_RANGE[0] <= value <= TRADE_SHOP_ID_RANGE[1]), None)
        unlock_key = next((text for text in strings
                           if text.startswith(("TradePointUnlock_", "CrossTradePointUnlock"))), None)
        hint = next((text for text in strings
                     if len(text) > 12 and not text.startswith(("MapPoint_", "TradePoint", "Cross"))
                     and "\u4e00" <= text[0] <= "\u9fff"), None)
        points.append({"id": prefix["ID"], "name": str(prefix["Name_Local"] or prefix["Name"] or ""),
                       "chapter": prefix["ChapterID"], "shop_id": shop_id,
                       "unlock_key": unlock_key, "hint": hint})
    return points


def decode_shop_rows(raw: bytes) -> tuple[list[dict[str, Any]], list[int]]:
    """Decode Config_Shop rows with the fixed 12-field layout.

    RandomID=1 的随机货架行（当前版本 ID 8/11）在物品列表之后携带随机池数据，
    线格式未核实：其物品列表之后的字节整体跳过，并向前重同步到下一行
    （下一行必须同样能完整解码，避免把数据误认成行首）。返回 (常规行, 跳过的行 ID)。
    """

    def try_row(position: int) -> dict[str, Any] | None:
        probe = Reader(raw)
        probe.pos = position
        try:
            if probe.u8() != 12:
                return None
            shop_id = probe.i32()
            if not 0 < shop_id < 100000:
                return None
            name = probe.memorypack_string()
            name_local = probe.memorypack_string()
            demo = probe.u32()
            random_id = probe.i32()
            random_amount = probe.i32()
            ids = probe.int_list()
            counts = probe.int_list()
            if ids is None or counts is None:
                return None
            probe.pos += 12  # DiscountRate / LifeMin / LifeMax
            weights = probe.int_list()
            if weights is None:
                return None
            if probe.pos > len(raw):
                return None
            return {"ID": shop_id, "name": name, "name_local": name_local, "demo": demo,
                    "random_id": random_id, "random_amount": random_amount,
                    "ids": ids, "counts": counts, "end": probe.pos}
        except Exception:
            return None

    reader = Reader(raw)
    count = reader.i32()
    rows: list[dict[str, Any]] = []
    skipped: list[int] = []
    position = reader.pos
    while len(rows) + len(skipped) < count and position < len(raw):
        row = try_row(position)
        if row is not None and row["random_id"] != 1:
            position = row.pop("end")
            rows.append(row)
            continue
        # 随机货架行（RandomID=1）也会按 12 字段布局“成功”读出但字节偏短，
        # 必须连同无法解析的行一起，从当前位置重同步到下一条常规行。
        failed_id = row["ID"] if row is not None else \
            int.from_bytes(raw[position + 1:position + 5], "little", signed=True)
        found = None
        for candidate in range(position + 1, len(raw) - 20):
            probe = try_row(candidate)
            if probe is not None and probe["random_id"] != 1 and \
                    (try_row(probe["end"]) is not None or probe["end"] >= len(raw) - 4):
                found = probe
                break
        if found is None:
            raise ValueError(f"Config_Shop 在 {position} 之后无法重同步到下一行")
        if 0 < failed_id < 100000:
            skipped.append(failed_id)
        position = found.pop("end")
        rows.append(found)
    if position != len(raw):
        raise ValueError(f"Config_Shop 解析未到末尾：{position} / {len(raw)}")
    return rows, skipped


def item_icon(raw: dict[str, Any]) -> str:
    return next((raw[field] for field in ITEM_ICON_FIELDS if raw.get(field)), "")


def extract_trade_model(game_root: Path) -> dict[str, Any]:
    items, _, version, _ = load_config_table(game_root, "Config_Item")
    item_map = {row.row_id: dict(row.values) for row in items}
    texts, _, text_version, _ = load_config_table(game_root, "Config_ConstantText")
    if text_version != version:
        raise ValueError("Config_ConstantText 与 Config_Item 版本不一致")
    category_labels = {}
    for row in texts:
        key = str(row.values["ID"])
        if key.startswith(CATEGORY_TEXT_PREFIX) and key[len(CATEGORY_TEXT_PREFIX):].isdigit():
            category_labels[int(key[len(CATEGORY_TEXT_PREFIX):])] = str(row.values["Text_Local"] or row.values["Text"])
    # 游戏分类 chips 没有书籍条目；货架含书籍时回退到图鉴的分类名。
    category_labels.setdefault(3, "书籍")

    map_raw, _, _, _ = load_text_asset(game_root, MAPPOINT_ASSET)
    points = decode_mappoint_trade_rows(map_raw)
    shop_raw, _, _, _ = load_text_asset(game_root, SHOP_ASSET)
    shops, skipped = decode_shop_rows(shop_raw)
    shop_map = {row["ID"]: row for row in shops}

    def item_entry(item_id: int, count: int | None) -> dict[str, Any] | None:
        raw = item_map.get(item_id)
        if raw is None:
            return None
        category = raw.get("Category")
        in_codex = raw.get("InCodex") is True
        if in_codex and (raw.get("Prey_Rarity") or 0) > 0:
            codex = "prey"
        elif in_codex and category == 1:
            codex = "food"
        elif category == 3:
            codex = "books"
        else:
            codex = None
        return {"id": item_id, "name": str(raw.get("ItemName_Local") or raw.get("ItemName") or f"ID:{item_id}"),
                "cat": category, "icon": item_icon(raw), "count": count,
                "trade_value": raw.get("TradeValue"), "price": raw.get("price"),
                "use_times": raw.get("UseTimes"), "codex": codex}

    trade_points = []
    shelf_items: dict[int, list[dict[str, Any]]] = {}
    for point in points:
        shop = shop_map.get(point["shop_id"]) if point["shop_id"] is not None else None
        if shop is None:
            raise ValueError(f"交易据点 {point['id']} 引用的货架 {point['shop_id']} 缺失或无法解码")
        entries = []
        listed_ids = shop["ids"] or []
        listed_counts = shop["counts"] or []
        if len(listed_counts) not in (0, len(listed_ids)):
            raise ValueError(f"货架 {shop['ID']} 物品与数量列表长度不一致")
        for position, item_id in enumerate(listed_ids):
            entry = item_entry(item_id, listed_counts[position] if listed_counts else None)
            if entry is None:
                raise ValueError(f"货架 {shop['ID']} 引用的物品 {item_id} 不在 Config_Item 中")
            entries.append(entry)
            shelf_items.setdefault(item_id, []).append(point["id"])
        categories = sorted({entry["cat"] for entry in entries if entry["cat"] is not None})
        trade_points.append({**point, "offer_cats": categories, "items": entries})

    shared = []
    for item_id, owners in sorted(shelf_items.items()):
        if len(owners) < 2:
            continue
        entry = item_entry(item_id, None)
        assert entry is not None
        shared.append({**entry, "points": owners})

    return {"format_version": 1, "game_version": version,
            "categories": {str(key): category_labels.get(key, f"分类 {key}") for key in sorted(category_labels)},
            "skipped_random_shops": skipped,
            "points": trade_points, "shared": shared}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--game-root", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    try:
        root = args.game_root.expanduser().resolve()
        target = args.output.expanduser().resolve()
        if target.is_relative_to(root) or args.output.is_symlink():
            raise ValueError("交易数据输出不能位于游戏目录或写入符号链接")
        data = extract_trade_model(root)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(json.dumps(data, ensure_ascii=False, separators=(",", ":")) + "\n", encoding="utf-8")
        skipped = f"，跳过随机货架 {data['skipped_random_shops']}" if data["skipped_random_shops"] else ""
        print(f"交易数据已导出：{data['game_version']}"
              f"（{len(data['points'])} 据点 / {sum(len(p['items']) for p in data['points'])} 货架项{skipped}）")
        return 0
    except (ValueError, KeyError, OSError, RuntimeError) as exc:
        print(f"交易数据导出失败：{exc}")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
