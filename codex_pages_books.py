#!/usr/bin/env python3
"""Extract the public book list (Config_Item Category 3) as a versioned JSON.

书籍不进入六类主图鉴，但玩家需要一本可查阅的读书手册；此处导出名称、
图标、效果说明与价格等配置字段，供在线站点单独成页。
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

from codex_parser import load_config_table


def extract_books(game_root: Path) -> dict[str, Any]:
    items, _, version, _ = load_config_table(game_root, "Config_Item")
    books = []
    for row in sorted(items, key=lambda row: row.row_id):
        raw = dict(row.values)
        if raw.get("Category") != 3:
            continue
        books.append({
            "id": row.row_id,
            "name": str(raw.get("ItemName_Local") or raw.get("ItemName") or f"ID:{row.row_id}"),
            "icon": next((raw[field] for field in ("Icon", "ICON", "WebIcon") if raw.get(field)), ""),
            "description": str(raw.get("ItemDes2_Local") or raw.get("ItemDes2") or ""),
            "flavor": str(raw.get("ItemDes1_Local") or raw.get("ItemDes1") or ""),
            "price": raw.get("price"), "weight": raw.get("weight"), "stack": raw.get("StackLimit"),
            "story": raw.get("Story"), "raw": raw,
        })
    if not books:
        raise ValueError("Config_Item 中没有书籍分类条目")
    return {"format_version": 1, "game_version": version, "books": books}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--game-root", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    try:
        root = args.game_root.expanduser().resolve()
        target = args.output.expanduser().resolve()
        if target.is_relative_to(root) or args.output.is_symlink():
            raise ValueError("书籍输出不能位于游戏目录或写入符号链接")
        data = extract_books(root)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        print(f"书籍列表已导出：{data['game_version']}（{len(data['books'])} 本）")
        return 0
    except (ValueError, KeyError, OSError, RuntimeError) as exc:
        print(f"书籍导出失败：{exc}")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
