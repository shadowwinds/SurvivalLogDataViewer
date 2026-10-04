#!/usr/bin/env python3
"""Extract only the icons referenced by the public codex, without changing game files."""

from __future__ import annotations

import argparse
import json
import re
import sqlite3
from collections import defaultdict
from contextlib import closing
from pathlib import Path

from codex_pages import icon_asset, icon_filename, related_icon_items
from codex_parser import decrypt_bundle, find_catalog, load_unitypy, parse_catalog


def web_icon_source(game_root: Path, web_icon: str) -> Path | None:
    match = re.fullmatch(r"\.\./\.\./Res/(Food|Furniture|Structure|Material|Literature|icon|Consumable|Electrical|RobotModule)/([A-Za-z0-9_-]+\.png)", web_icon)
    if not match:
        return None
    resource_dir = (game_root / "SurvivalLog_Data/StreamingAssets/WebUI/Res" / match[1]).resolve()
    if not resource_dir.is_relative_to(game_root.resolve()):
        return None
    source = resource_dir / match[2]
    if source.is_symlink() or not source.resolve().is_relative_to(resource_dir):
        return None
    return source if source.is_file() else None


def extract_icons(database: Path, game_root: Path, output_dir: Path) -> None:
    database, game_root, output_dir = (path.resolve() for path in (database, game_root, output_dir))
    if output_dir == game_root or output_dir.is_relative_to(game_root) or database.is_relative_to(output_dir):
        raise ValueError("图标输出目录不能位于游戏目录或包含源数据库")
    requested: dict[str, str] = {}

    def request(raw: dict) -> None:
        icon = icon_asset(raw)
        if icon:
            requested[icon] = raw.get("WebIcon") or raw.get("ICON") or raw.get("WebSmallIcon") or requested.get(icon, "")

    with closing(sqlite3.connect(f"{database.as_uri()}?mode=ro", uri=True)) as connection:
        referenced_items = set()
        for table, raw_json in connection.execute("SELECT source_table, raw_json FROM codex_entries WHERE is_current=1"):
            raw = json.loads(raw_json)
            request(raw)
            referenced_items.update(related_icon_items(table, raw))
        for item_id, raw_json in connection.execute("SELECT item_id, raw_json FROM recipe_items"):
            if item_id in referenced_items:
                raw = json.loads(raw_json)
                request(raw)
        for (raw_json,) in connection.execute("SELECT raw_json FROM achievements"):
            request(json.loads(raw_json))
    catalog = find_catalog(game_root)
    assets, bundles, version = parse_catalog(catalog)
    asset_lookup = {path.removesuffix(".png").lower(): path for path in assets}
    grouped: dict[int, list[tuple[str, str]]] = defaultdict(list)
    fallback = []
    for requested_path in sorted(requested):
        actual = asset_lookup.get(requested_path.replace("\\", "/").removesuffix(".png").lower())
        if actual:
            grouped[assets[actual]].append((actual, requested_path))
        else:
            fallback.append(requested_path)
    UnityPy = load_unitypy()
    output_dir.mkdir(parents=True, exist_ok=True)
    if output_dir.is_symlink():
        raise ValueError("图标输出目录不能是符号链接")

    def save(image, filename: str) -> None:
        target = output_dir / filename
        if target.is_symlink():
            raise ValueError(f"图标输出文件不能是符号链接：{filename}")
        image = image.convert("RGBA")
        image.thumbnail((192, 192))
        image.save(target, format="PNG", optimize=True)

    exported = []
    for bundle_id, paths in grouped.items():
        bundle = bundles[bundle_id]
        bundle_path = catalog.parent / f"{bundle.file_hash}.bundle"
        contents = decrypt_bundle(bundle_path, bundle.name) if bundle.encrypted else bundle_path.read_bytes()
        environment = UnityPy.load(contents)
        lookup = {path.replace("\\", "/").lower(): obj for path, obj in environment.container.items()}
        for asset_path, requested_path in paths:
            filename = icon_filename(requested_path)
            obj = lookup.get(asset_path.lower())
            if not obj:
                fallback.append(requested_path)
                continue
            asset = obj.read()
            if obj.type.name not in {"Sprite", "Texture2D"}:
                raise ValueError(f"图标不是 Sprite 或 Texture2D：{asset_path}")
            save(asset.image, filename)
            exported.append(filename)
        print(f"已提取 {len(exported)} 个图标", flush=True)
    from PIL import Image
    web_ui_icons, missing = [], []
    for requested_path in sorted(set(fallback)):
        filename = icon_filename(requested_path)
        source = web_icon_source(game_root, requested[requested_path])
        if source is None:
            missing.append(filename)
            continue
        with Image.open(source) as image:
            if image.format != "PNG":
                raise ValueError(f"游戏网页图标不是 PNG：{filename}")
            save(image, filename)
        exported.append(filename)
        web_ui_icons.append(filename)
    manifest = output_dir / "manifest.json"
    if manifest.is_symlink():
        raise ValueError("图标清单不能是符号链接")
    manifest.write_text(json.dumps({"source": "Survival Log / item icons", "game_version": version,
                                    "icons": sorted(exported), "web_ui_icons": sorted(web_ui_icons),
                                    "missing": sorted(missing)}, indent=2) + "\n", encoding="utf-8")
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
