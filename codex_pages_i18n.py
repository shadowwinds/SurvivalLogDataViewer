"""Export only the official English strings used by the public website."""

from __future__ import annotations

import argparse
import json
import sqlite3
import sys
from pathlib import Path
from typing import Any

from codex_parser import Reader, load_text_asset


def read_localization(data: bytes, name: str) -> dict[str, str]:
    reader = Reader(data)
    count = reader.i32()
    if count < 0 or count > len(data) // 8:
        raise ValueError(f"{name}: 无效本地化条目数量 {count}")
    result = {}
    for index in range(count):
        try:
            key, value = reader.memorypack_string(), reader.memorypack_string()
            if not key or key in result or value is None:
                raise ValueError("空键、重复键或空值")
            result[key] = value
        except (ValueError, UnicodeError) as exc:
            raise ValueError(f"{name}: 第 {index + 1} 行，offset {reader.pos}: {exc}") from exc
    if reader.pos != len(data):
        raise ValueError(f"{name}: offset {reader.pos}，末尾还有 {len(data) - reader.pos} 字节")
    return result


def public_strings(value: Any) -> set[str]:
    if isinstance(value, str):
        return {value}
    if isinstance(value, dict):
        return set().union(*(public_strings(item) for item in value.values()))
    if isinstance(value, list):
        return set().union(*(public_strings(item) for item in value))
    return set()


def trade_model_strings(source_dir: Path, game_version: str | None) -> set[str]:
    """Collect display strings from the trade model when its version matches."""

    try:
        model = json.loads((source_dir / "trade-model.json").read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return set()
    if not isinstance(model, dict) or model.get("format_version") != 2 \
            or (game_version is not None and model.get("game_version") != game_version):
        return set()
    from codex_pages_seo import clean_text

    strings: set[str] = set()
    strings.update(value for value in model.get("categories", {}).values() if isinstance(value, str))
    for point in model.get("points", []):
        if isinstance(point.get("name"), str):
            strings.add(point["name"])
        for item in point.get("items", []):
            if isinstance(item.get("name"), str):
                strings.add(item["name"])
    for entry in model.get("shared", []) + model.get("items", []) + model.get("crafts", []):
        if isinstance(entry.get("name"), str):
            strings.add(entry["name"])
    return {clean_text(text) for text in strings}


def export_game_translations(game_root: Path, database: Path, output_dir: Path) -> Path:
    from codex_pages import export_data
    from codex_pages_seo import clean_text

    game_root, output_dir = game_root.resolve(), output_dir.resolve()
    if output_dir == game_root or output_dir.is_relative_to(game_root):
        raise ValueError("本地化输出目录不能位于游戏目录")
    used = {clean_text(text) for text in public_strings(export_data(database))}
    game_version = None
    try:
        connection = sqlite3.connect(f"{database.expanduser().resolve().as_uri()}?mode=ro", uri=True)
        try:
            row = connection.execute(
                "SELECT value FROM metadata WHERE key='game_version'").fetchone()
            game_version = row[0] if row else None
        finally:
            connection.close()
    except sqlite3.Error:
        game_version = None
    used |= trade_model_strings(Path(__file__).resolve().parent / "pages", game_version)
    tables = {}
    for language in ("Main", "English"):
        raw, *_ = load_text_asset(game_root, f"Assets/RuntimeAssets/Config/MemoryPack/LocalTxt/{language}.bytes")
        tables[language] = read_localization(raw, language)
    candidates: dict[str, set[str]] = {}
    for key, chinese in tables["Main"].items():
        chinese, english = clean_text(chinese), clean_text(tables["English"].get(key, ""))
        if chinese in used and chinese and english:
            candidates.setdefault(chinese, set()).add(english)
    # Ambiguous text stays in Chinese rather than borrowing a different entry's name.
    selected = {text: next(iter(values)) for text, values in sorted(candidates.items()) if len(values) == 1}
    output_dir.mkdir(parents=True, exist_ok=True)
    target = output_dir / "game-en.json"
    if target.is_symlink():
        raise ValueError("本地化输出文件不能是符号链接")
    target.write_text(json.dumps(selected, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return target


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--game-root", type=Path, required=True)
    parser.add_argument("--database", type=Path, default=Path(__file__).with_name("survival_log_codex.sqlite3"))
    parser.add_argument("--output-dir", type=Path, required=True)
    args = parser.parse_args()
    try:
        print(export_game_translations(args.game_root, args.database, args.output_dir))
    except (OSError, ValueError, RuntimeError) as exc:
        print(f"英文文本提取失败：{exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
