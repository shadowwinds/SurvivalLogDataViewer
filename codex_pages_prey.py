#!/usr/bin/env python3
"""Extract the public trap-hunting model (traps, baits, rooms, mouse cages).

The prey page presents capture information instead of food statistics, so the
trapping tables are exported as a versioned JSON document, mirroring the
planting environment preset. All display names are resolved from the current
local game resources; icon fields keep raw asset paths and are mapped to
public icon files during the pages build. Shared effect strings and icon
paths are deduplicated into lookup tables to keep the 2200+ bait entries
compact; the client resolves names from the model itself.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

from codex_parser import load_config_table


TRAP_TABLES = ("Config_Trap", "Config_TrapBait", "Config_TrapLv", "Config_TrapRoomBias", "Config_TrapSlot")
SUPPORT_TABLES = ("Config_Item", "Config_ProductionList", "Config_Furniture", "Config_FurnitureElectrical", "Config_Bag")
CAGE_FURNITURE_IDS = (42009, 42010, 42011, 42012)
TOP_BAITS_PER_PREY = 8
TOP_PREY_PER_BAIT = 6
# 排行榜中排除的开发/系统物品（无法正常获取，避免污染推荐诱饵）。
DEV_BAIT_MARKERS = ("开发者", "测试", "通用读条")


def is_dev_item(name: str) -> bool:
    return any(marker in name for marker in DEV_BAIT_MARKERS)


def item_icon(raw: dict[str, Any]) -> str:
    return next((raw[field] for field in ("Icon", "ICON", "WebIcon", "WebSmallIcon") if raw.get(field)), "")


def item_name(items: dict[int, dict[str, Any]], item_id: int) -> str:
    raw = items.get(item_id)
    if raw is None:
        return f"ID:{item_id}"
    return str(raw.get("ItemName_Local") or raw.get("ItemName") or f"ID:{item_id}")


def round_float(value: float) -> float:
    return round(value, 4)


def craft_key_for_product(productions: dict[int, dict[str, Any]], item_id: int, name: str) -> str | None:
    """Pick the codex craft recipe producing this item, preferring a name match."""

    candidates = [raw for raw in productions.values() if item_id in (raw.get("ProductID") or [])]
    if not candidates:
        return None
    named = [raw for raw in candidates if raw.get("ShopName_Local") == name]
    chosen = (named or candidates)[0]
    return f"Config_ProductionList:{chosen['ID']}"


def extract_prey_model(game_root: Path) -> dict[str, Any]:
    tables: dict[str, dict[int, dict[str, Any]]] = {}
    versions: set[str] = set()
    for name in (*TRAP_TABLES, *SUPPORT_TABLES):
        rows, _, version, _ = load_config_table(game_root, name)
        tables[name] = {row.row_id: dict(row.values) for row in rows}
        versions.add(version)
    if len(versions) != 1:
        raise ValueError("陷阱狩猎配置来自不同游戏版本")
    items = tables["Config_Item"]
    productions = tables["Config_ProductionList"]

    prey_rows = {row_id: raw for row_id, raw in items.items()
                 if (raw.get("Prey_Rarity") or 0) > 0 and raw.get("InCodex") is True}
    prey_ids = sorted(prey_rows)
    prey_names = {row_id: item_name(items, row_id) for row_id in prey_ids}

    traps = []
    for trap_id in sorted(tables["Config_Trap"]):
        raw = tables["Config_Trap"][trap_id]
        prey_list = raw.get("Prey_Id") or []
        rates = raw.get("Base_Rate") or []
        exps = raw.get("Discovery_Exp") or []
        if not (len(prey_list) == len(rates) == len(exps)):
            raise ValueError(f"Config_Trap:{trap_id} 猎物与概率、经验列表长度不一致")
        room_names = [str(tables["Config_TrapRoomBias"][room_id]["Des1"])
                      if room_id in tables["Config_TrapRoomBias"] else f"ID:{room_id}"
                      for room_id in (raw.get("Capture_Room") or [])]
        item_candidates = [row_id for row_id, item in items.items() if item.get("Trap") == trap_id]
        item_id = item_candidates[0] if item_candidates else None
        # 陷阱的 WebIcon 指向 WebUI 资源，部分文件缺失；物品的 Icon 是 bundle 纹理，优先使用。
        icon = item_icon(items.get(item_id, {})) if item_id else ""
        traps.append({
            "id": trap_id, "item_id": item_id,
            "name": str(raw.get("Name_Local") or raw.get("Name") or f"ID:{trap_id}"),
            "description": str(raw.get("Description_Local") or ""),
            "durability": raw.get("Durability_Max"), "capture_cost": raw.get("Capture_Cost"),
            "interval_hours": round_float(raw["Capture_Interval"] / 3600) if raw.get("Capture_Interval") else None,
            "rooms": room_names, "empty_weight": round_float(raw.get("Empty_Weight") or 0.0),
            "bait_capacity": raw.get("Bait_Capacity"), "prey_capacity": raw.get("Prey_Capacity"),
            "trap_get": [item_name(items, value) for value in (raw.get("Trap_Get") or [])],
            "icon": icon or str(raw.get("WebIcon") or ""),
            "craft_key": craft_key_for_product(productions, item_id, item_name(items, item_id)) if item_id else None,
            "prey": [{"id": prey_id, "name": prey_names.get(prey_id, f"ID:{prey_id}"),
                      "base_rate": round_float(rates[index]), "discovery_exp": exps[index]}
                     for index, prey_id in enumerate(prey_list)],
        })

    # 每个猎物的可捕获陷阱、推荐诱饵与房间倾向，供详情页直接渲染；
    # 诱饵/猎物名以 ID 引用，由客户端从模型主列表解析。
    # TrapBait 的 ID 是物品 ID，但表里有少量非物品的特殊行（通用诱饵档位配置），
    # 只保留各陷阱 Bait_id 并集内、可实际放置的诱饵。
    placeable = {bait_id for trap in tables["Config_Trap"].values()
                 for bait_id in (trap.get("Bait_id") or [])}
    bait_rows = tables["Config_TrapBait"]
    bait_effects: dict[str, int] = {}
    bait_icons: dict[str, int] = {}
    top_baits: dict[int, list[list[Any]]] = {prey_id: [] for prey_id in prey_ids}
    baits = []
    for bait_id in sorted(bait_rows):
        if bait_id not in placeable:
            continue
        raw = bait_rows[bait_id]
        prey_list = raw.get("Prey_Id") or []
        coefficients = raw.get("Bait_coefficient") or []
        if len(prey_list) != len(coefficients):
            raise ValueError(f"Config_TrapBait:{bait_id} 猎物与系数列表长度不一致")
        effect = str(raw.get("Effect_Des_Local") or "")
        effect_index = bait_effects.setdefault(effect, len(bait_effects))
        icon = item_icon(items.get(bait_id, {}))
        icon_index = bait_icons.setdefault(icon, len(bait_icons)) if icon else -1
        rated = sorted(((prey_id, coefficients[index]) for index, prey_id in enumerate(prey_list)
                        if prey_id in prey_names and coefficients[index] > 0),
                       key=lambda pair: (-pair[1], prey_names[pair[0]], pair[0]))
        dev = is_dev_item(item_name(items, bait_id))
        if not dev:
            for prey_id, coefficient in rated:
                top_baits[prey_id].append([bait_id, round_float(coefficient)])
        baits.append({
            "id": bait_id, "name": item_name(items, bait_id), "icon": icon_index,
            "effect": effect_index,
            "uniform": len({round_float(value) for value in coefficients}) <= 1,
            "dev": dev,
            "top": [[prey_id, round_float(value)] for prey_id, value in rated[:TOP_PREY_PER_BAIT]],
        })
    for prey_id in top_baits:
        top_baits[prey_id] = sorted(top_baits[prey_id],
                                    key=lambda bait: (-bait[1], bait[0]))[:TOP_BAITS_PER_PREY]

    rooms = []
    room_coefs: dict[int, list[dict[str, Any]]] = {prey_id: [] for prey_id in prey_ids}
    for room_id in sorted(tables["Config_TrapRoomBias"]):
        raw = tables["Config_TrapRoomBias"][room_id]
        prey_list = raw.get("Prey_Id") or []
        coefficients = raw.get("Room_coefficient") or []
        if len(prey_list) != len(coefficients):
            raise ValueError(f"Config_TrapRoomBias:{room_id} 猎物与系数列表长度不一致")
        name = str(raw.get("Des1") or f"ID:{room_id}")
        for index, prey_id in enumerate(prey_list):
            if prey_id in prey_names:
                room_coefs[prey_id].append({"id": room_id, "coefficient": round_float(coefficients[index])})
        rated = sorted(((prey_id, coefficients[index]) for index, prey_id in enumerate(prey_list)
                        if prey_id in prey_names and coefficients[index] > 0),
                       key=lambda pair: (-pair[1], prey_names[pair[0]], pair[0]))
        rooms.append({
            "id": room_id, "name": name,
            "description": str(raw.get("Effect_Des_Local") or ""),
            "top": [[prey_id, round_float(value)] for prey_id, value in rated[:TOP_PREY_PER_BAIT]],
        })
    for prey_id in room_coefs:
        room_coefs[prey_id].sort(key=lambda room: (-room["coefficient"], room["id"]))

    slot_counts: dict[int, int] = {}
    for raw in tables["Config_TrapSlot"].values():
        slot_counts[raw.get("Room_Id")] = slot_counts.get(raw.get("Room_Id"), 0) + 1
    slots = [{"room_id": room_id, "name": str(tables["Config_TrapRoomBias"][room_id]["Des1"])
              if room_id in tables["Config_TrapRoomBias"] else f"ID:{room_id}", "count": count}
             for room_id, count in sorted(slot_counts.items())]

    trap_levels = []
    for lv in sorted(tables["Config_TrapLv"]):
        raw = tables["Config_TrapLv"][lv]
        trap_levels.append({"lv": raw.get("Lv"), "exp": raw.get("EXP"),
                            "info": str(raw.get("Info_Local") or ""),
                            "empty_weight_reduction": round_float(raw.get("empty_weight_reduction") or 0.0),
                            "rare_prey_bonus": round_float(raw.get("rare_prey_bonus") or 0.0),
                            "capture_cost_reduction": raw.get("capture_cost_reduction") or 0})

    cages = []
    for cage_id in CAGE_FURNITURE_IDS:
        raw = tables["Config_Furniture"].get(cage_id)
        if raw is None:
            raise ValueError(f"Config_Furniture:{cage_id} 老鼠笼配置缺失")
        electrical = tables["Config_FurnitureElectrical"].get(raw.get("ElectricalFurnitureID"))
        bag = tables["Config_Bag"].get(raw.get("BagId"))
        package = next((item_id for item_id, item in items.items()
                        if item.get("TargetFurnitureID") == cage_id), None)
        cages.append({
            "id": cage_id, "name": str(raw.get("Name_Local") or f"ID:{cage_id}"),
            "description": str(raw.get("Des_Local") or ""),
            "price": raw.get("FurniturePrice"), "install_time": raw.get("InstallTime"),
            "hp": raw.get("FurnitureHPMax"), "slot_type": raw.get("SlotType"),
            "capacity_mice": electrical.get("Capacity") if electrical else None,
            "power_per_mouse": round_float(electrical.get("BasePower") or 0.0) if electrical else None,
            "fuel_rate": round_float(electrical.get("FuelRate") or 0.0) if electrical else None,
            "bag_size": (bag or {}).get("Size"),
            "bag_slots": (bag["Size"][0] * bag["Size"][1]) if (bag or {}).get("Size") else None,
            "icon": str(raw.get("ICON") or ""), "craft_key": craft_key_for_product(
                productions, package, item_name(items, package)) if package else None,
        })

    prey = []
    for prey_id in prey_ids:
        entry_traps = []
        for trap in traps:
            match = next((entry for entry in trap["prey"] if entry["id"] == prey_id), None)
            if match:
                entry_traps.append({"id": trap["id"], "base_rate": match["base_rate"],
                                    "discovery_exp": match["discovery_exp"]})
        prey.append({"id": prey_id, "name": prey_names[prey_id],
                     "rarity": prey_rows[prey_id].get("Prey_Rarity"),
                     "icon": item_icon(prey_rows[prey_id]),
                     "traps": entry_traps, "top_baits": top_baits[prey_id],
                     "rooms": room_coefs[prey_id]})

    return {"format_version": 1, "game_version": versions.pop(), "prey": prey, "traps": traps,
            "bait_effects": [key for key, _ in sorted(bait_effects.items(), key=lambda pair: pair[1])],
            "bait_icons": [key for key, _ in sorted(bait_icons.items(), key=lambda pair: pair[1])],
            "baits": baits, "rooms": rooms, "slots": slots, "trap_levels": trap_levels, "cages": cages}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--game-root", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    try:
        root = args.game_root.expanduser().resolve()
        target = args.output.expanduser().resolve()
        if target.is_relative_to(root) or args.output.is_symlink():
            raise ValueError("陷阱狩猎输出不能位于游戏目录或写入符号链接")
        data = extract_prey_model(root)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(json.dumps(data, ensure_ascii=False, separators=(",", ":")) + "\n", encoding="utf-8")
        print(f"陷阱狩猎数据已导出：{data['game_version']}（{len(data['traps'])} 陷阱 / {len(data['baits'])} 诱饵）")
        return 0
    except (ValueError, KeyError, OSError, RuntimeError) as exc:
        print(f"陷阱狩猎导出失败：{exc}")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
