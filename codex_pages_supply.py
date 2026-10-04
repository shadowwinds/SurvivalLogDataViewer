"""Export allowlisted planting action times and morale settlement parameters."""

from __future__ import annotations

import argparse
import json
import math
from pathlib import Path

from codex_parser import load_config_table
from codex_recipe import read_global_settings


def extract_supply_model(game_root: Path) -> dict:
    rows, _, version, _ = load_config_table(game_root, "Config_Action")
    actions = {row.row_id: row.values for row in rows}
    durations = {}
    for key, row_id in (("sow", 1611), ("harvest", 1617), ("pest", 1613), ("weed", 1614), ("water", 1615)):
        value = actions[row_id]["During"]
        if not math.isfinite(value) or value <= 0:
            raise ValueError(f"Config_Action:{row_id} 的基础动作时间非法")
        durations[key] = {"id": row_id, "seconds": value}
    settings = read_global_settings(game_root)
    base, per_point = (settings[key][0] for key in ("MoraleBase", "MoraleToPoint"))
    if base < 0 or per_point <= 0:
        raise ValueError("心态结算参数非法")
    special_plants = set()
    for key in ("Greenhouse_DailyFertPlants", "Greenhouse_RegrowPlants"):
        for pair in (settings[key][2] or "").split(","):
            if pair.strip():
                special_plants.add(int(pair.split(":", 1)[0]))
    return {"format_version": 1, "game_version": version, "actions": durations,
            "anomaly_interval_seconds": 86400,
            "special_plants": sorted(special_plants),
            "morale_base": base, "morale_per_point": per_point}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--game-root", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    try:
        root, target = args.game_root.resolve(), args.output.resolve()
        if target.is_relative_to(root) or args.output.is_symlink():
            raise ValueError("补给参数输出不能位于游戏目录或写入符号链接")
        data = extract_supply_model(root)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        print(f"补给参数已导出：{data['game_version']}")
        return 0
    except (ValueError, KeyError, OSError, RuntimeError) as exc:
        print(f"补给参数导出失败：{exc}")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
