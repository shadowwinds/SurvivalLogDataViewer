"""Export the verified cooking formula coefficients from read-only game data."""

from __future__ import annotations

import argparse
import json
import math
from pathlib import Path

from codex_parser import find_catalog, parse_catalog
from codex_recipe import read_global_settings


def extract_cooking_model(game_root: Path) -> dict:
    _, _, version = parse_catalog(find_catalog(game_root))
    settings = read_global_settings(game_root)
    def value(key: str) -> float:
        result = settings[key][1]
        if not math.isfinite(result) or result <= 0:
            raise ValueError(f"烹饪计算参数非法：{key}")
        return result
    return {"format_version": 1, "game_version": version,
            "tier_coefficients": {str(tier): value("CookingVD_TierCoeff_" + name)
                                  for tier, name in ((1, "High"), (2, "Mid"), (3, "Low"))},
            "quality_coefficients": {name: value("CookingVD_QualityCoeff_" + key)
                                     for name, key in (("失败", "Fail"), ("普通", "Normal"), ("良好", "Good"), ("完美", "Perfect"))},
            "base_satiety_per_ingredient": value("CookingVD_BaseSatietyPerIngredient"),
            "split_threshold": value("CookingSatiety_SplitThreshold")}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--game-root", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    try:
        root = args.game_root.expanduser().resolve()
        target = args.output.expanduser().resolve()
        if target.is_relative_to(root) or args.output.is_symlink():
            raise ValueError("烹饪参数输出不能位于游戏目录或写入符号链接")
        data = extract_cooking_model(root)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        print(f"烹饪参数已导出：{data['game_version']}")
        return 0
    except (ValueError, KeyError, OSError, RuntimeError) as exc:
        print(f"烹饪参数导出失败：{exc}")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
