#!/usr/bin/env python3
"""Extract only the icons referenced by the public codex, without changing game files."""

from __future__ import annotations

import argparse
import json
import sqlite3
from collections import defaultdict
from contextlib import closing
from pathlib import Path

from codex_pages import PRODUCT_FIELDS, icon_filename
from codex_parser import decrypt_bundle, find_catalog, load_unitypy, parse_catalog


def extract_icons(database: Path, game_root: Path, output_dir: Path) -> None:
    database, game_root, output_dir = (path.resolve() for path in (database, game_root, output_dir))
    if output_dir == game_root or output_dir.is_relative_to(game_root) or database.is_relative_to(output_dir):
        raise ValueError("图标输出目录不能位于游戏目录或包含源数据库")
    requested: set[str] = set()
    with closing(sqlite3.connect(f"{database.as_uri()}?mode=ro", uri=True)) as connection:
        recipes = []
        for table, raw_json in connection.execute("SELECT source_table, raw_json FROM codex_entries WHERE is_current=1"):
            raw = json.loads(raw_json)
            if raw.get("Icon"):
                requested.add(raw["Icon"])
            if table == "Config_CookingRecipe":
                recipes.extend(raw.get(field, 0) for field, _quality in PRODUCT_FIELDS)
        product_ids = set(recipes) - {0}
        for item_id, raw_json in connection.execute("SELECT item_id, raw_json FROM recipe_items"):
            if item_id in product_ids:
                raw = json.loads(raw_json)
                if raw.get("Icon"):
                    requested.add(raw["Icon"])
    catalog = find_catalog(game_root)
    assets, bundles, version = parse_catalog(catalog)
    asset_lookup = {path.removesuffix(".png").lower(): path for path in assets}
    grouped: dict[int, list[tuple[str, str]]] = defaultdict(list)
    missing = []
    for requested_path in sorted(requested):
        actual = asset_lookup.get(requested_path.replace("\\", "/").removesuffix(".png").lower())
        if actual:
            grouped[assets[actual]].append((actual, icon_filename(requested_path)))
        else:
            missing.append(icon_filename(requested_path))
    UnityPy = load_unitypy()
    output_dir.mkdir(parents=True, exist_ok=True)
    if output_dir.is_symlink():
        raise ValueError("图标输出目录不能是符号链接")
    exported = []
    for bundle_id, paths in grouped.items():
        bundle = bundles[bundle_id]
        bundle_path = catalog.parent / f"{bundle.file_hash}.bundle"
        contents = decrypt_bundle(bundle_path, bundle.name) if bundle.encrypted else bundle_path.read_bytes()
        environment = UnityPy.load(contents)
        lookup = {path.replace("\\", "/").lower(): obj for path, obj in environment.container.items()}
        for asset_path, filename in paths:
            obj = lookup.get(asset_path.lower())
            if not obj:
                missing.append(filename)
                continue
            asset = obj.read()
            if obj.type.name not in {"Sprite", "Texture2D"}:
                raise ValueError(f"图标不是 Sprite 或 Texture2D：{asset_path}")
            target = output_dir / filename
            if target.is_symlink():
                raise ValueError(f"图标输出文件不能是符号链接：{filename}")
            image = asset.image
            image.thumbnail((192, 192))
            image.save(target, format="PNG", optimize=True)
            exported.append(filename)
        print(f"已提取 {len(exported)} 个图标", flush=True)
    manifest = output_dir / "manifest.json"
    if manifest.is_symlink():
        raise ValueError("图标清单不能是符号链接")
    manifest.write_text(json.dumps({"source": "Survival Log / item icons", "game_version": version,
                                    "icons": sorted(exported), "missing": sorted(missing)}, indent=2) + "\n", encoding="utf-8")
    print(f"完成：{len(exported)} 个图标，{len(missing)} 个未找到；游戏文件保持只读。")


def main() -> int:
    parser = argparse.ArgumentParser(description="只读提取在线图鉴需要的游戏物品图标")
    parser.add_argument("--game-root", type=Path, required=True)
    parser.add_argument("--database", type=Path, default=Path(__file__).with_name("survival_log_codex.sqlite3"))
    parser.add_argument("--output-dir", type=Path, required=True)
    args = parser.parse_args()
    try:
        extract_icons(args.database, args.game_root, args.output_dir)
        return 0
    except (OSError, ValueError, KeyError, RuntimeError) as error:
        print(f"图标提取失败：{error}")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
