"""Extract the public planting environment presets from read-only game configs."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

from codex_parser import config_row_name, load_config_table
from codex_recipe import read_global_settings


def extract_environment(game_root: Path) -> dict[str, Any]:
    tables = {}
    versions = set()
    for name in ("Config_Weather", "Config_EnvArea", "Config_EnvAreaWeather", "Config_MapRoom", "Config_Furniture"):
        rows, _, version, _ = load_config_table(game_root, name)
        tables[name] = {row.row_id: row for row in rows}
        versions.add(version)
    if len(versions) != 1:
        raise ValueError("种植环境配置来自不同游戏版本")
    weather = tables["Config_Weather"]
    scenarios = []
    # These are distinct native weather rows, including the cold-rain light penalty.
    for kind, ids in (("sunny", (1, 7, 8, 9)), ("cloudy", (2, 4, 5, 6)), ("rainy", (3, 15, 16, 17))):
        for severity, row_id in enumerate(ids):
            row = weather[row_id]
            if row.values["ColdValue"] != severity:
                raise ValueError(f"Config_Weather:{row_id} 寒潮预设与本地配置不一致")
            scenarios.append({"weather": kind, "cold_wave": severity, "id": row_id,
                              "name": config_row_name(row), "light": row.values["LightValue"],
                              "cold": row.values["ColdValue"]})
    locations = []
    for key, room_id, area_id in (("basement", 2, 5), ("first", 1, 1), ("second", 3, 2), ("terrace", 4, 3)):
        room = tables["Config_MapRoom"][room_id]
        area = tables["Config_EnvArea"][area_id]
        params = [row.values for row in tables["Config_EnvAreaWeather"].values()
                  if row.values["AreaID"] == area_id]
        default = next((row for row in params if row["WeatherID"] == 0), None)
        if default is None or (room.values["Light"], room.values["Heat"]) != (default["LightMul"], default["TempAdd"]):
            raise ValueError(f"Config_MapRoom:{room_id} 与环境区域基础参数不一致")
        locations.append({"key": key, "name": config_row_name(room), "room_id": room_id, "area_id": area_id,
                          "device_heat": area.values["DeviceHeat"],
                          "parameters": [{"weather_id": row["WeatherID"], "light_multiplier": row["LightMul"],
                                          "heat": row["TempAdd"]} for row in params]})
    heaters = []
    for key, row_id in (("ac", 21007), ("stove", 65001)):
        row = tables["Config_Furniture"][row_id]
        if not row.values["InCodex"] or row.values["HeatOutput"] <= 0:
            raise ValueError(f"Config_Furniture:{row_id} 供暖设备配置变化")
        heaters.append({"key": key, "id": row_id, "name": config_row_name(row), "heat": row.values["HeatOutput"]})
    return {"format_version": 1, "game_version": versions.pop(), "scenarios": scenarios,
            "locations": locations, "heaters": heaters,
            "heat_cap": read_global_settings(game_root)["RoomTemp_Max"][0]}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--game-root", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    try:
        root = args.game_root.expanduser().resolve()
        target = args.output.expanduser().resolve()
        if target.is_relative_to(root) or args.output.is_symlink():
            raise ValueError("种植环境输出不能位于游戏目录或写入符号链接")
        data = extract_environment(root)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        print(f"种植环境已导出：{data['game_version']}")
        return 0
    except (ValueError, KeyError, OSError, RuntimeError) as exc:
        print(f"种植环境导出失败：{exc}")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
