#!/usr/bin/env python3
"""Discover the local Survival Log installation and refresh stale codex data."""

from __future__ import annotations

import os
import re
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterator

from codex_parser import find_catalog, parse_catalog


GAME_RELATIVE_PATH = Path("SurvivalLog_Data") / "StreamingAssets" / "PackageManifest"
GAME_NAME = "Survival Log"
_VERSION_PARTS = re.compile(r"\d+")


@dataclass(frozen=True)
class GameInstallation:
    root: Path
    catalog_path: Path
    package_version: str


@dataclass(frozen=True)
class UpdateResult:
    status: str
    game_root: Path | None
    old_version: str
    new_version: str
    message: str


def _dedupe_paths(paths: Iterator[Path]) -> list[Path]:
    seen: set[str] = set()
    result: list[Path] = []
    for path in paths:
        try:
            resolved = path.expanduser().resolve()
        except OSError:
            continue
        key = os.path.normcase(str(resolved))
        if key not in seen:
            seen.add(key)
            result.append(resolved)
    return result


def _vdf_tokens(text: str) -> list[str]:
    tokens: list[str] = []
    index = 0
    while index < len(text):
        while index < len(text) and text[index].isspace():
            index += 1
        if index >= len(text):
            break
        if text.startswith("//", index):
            end = text.find("\n", index + 2)
            index = len(text) if end < 0 else end + 1
            continue
        if text[index] in "{}":
            tokens.append(text[index])
            index += 1
            continue
        if text[index] == '"':
            index += 1
            chars: list[str] = []
            while index < len(text):
                char = text[index]
                index += 1
                if char == '"':
                    break
                if char == "\\" and index < len(text):
                    escaped = text[index]
                    index += 1
                    chars.append({"n": "\n", "r": "\r", "t": "\t"}.get(escaped, escaped))
                else:
                    chars.append(char)
            else:
                raise ValueError("Steam VDF 包含未闭合的字符串")
            tokens.append("".join(chars))
            continue
        end = index
        while end < len(text) and not text[end].isspace() and text[end] not in "{}":
            end += 1
        tokens.append(text[index:end])
        index = end
    return tokens


def _parse_vdf_object(tokens: list[str], index: int = 0) -> tuple[dict[str, Any], int]:
    values: dict[str, Any] = {}
    while index < len(tokens):
        if tokens[index] == "}":
            return values, index + 1
        key = tokens[index]
        index += 1
        if index >= len(tokens):
            raise ValueError(f"Steam VDF 键缺少值：{key}")
        if tokens[index] == "{":
            value, index = _parse_vdf_object(tokens, index + 1)
        else:
            value = tokens[index]
            index += 1
        if key in values:
            previous = values[key]
            values[key] = previous + [value] if isinstance(previous, list) else [previous, value]
        else:
            values[key] = value
    return values, index


def parse_vdf(text: str) -> dict[str, Any]:
    tokens = _vdf_tokens(text)
    if not tokens:
        return {}
    if len(tokens) >= 2 and tokens[1] == "{":
        value, index = _parse_vdf_object(tokens, 2)
        if index != len(tokens):
            raise ValueError("Steam VDF 在根对象后仍有未解析内容")
        return {tokens[0]: value}
    value, index = _parse_vdf_object(tokens)
    if index != len(tokens):
        raise ValueError("Steam VDF 格式不完整")
    return value


def _walk_vdf(value: Any) -> Iterator[tuple[str, Any]]:
    if isinstance(value, dict):
        for key, child in value.items():
            yield key, child
            yield from _walk_vdf(child)
    elif isinstance(value, list):
        for child in value:
            yield from _walk_vdf(child)


def _registry_steam_roots() -> list[Path]:
    if sys.platform != "win32":
        return []
    try:
        import winreg
    except ImportError:
        return []

    locations = (
        (winreg.HKEY_CURRENT_USER, r"Software\Valve\Steam"),
        (winreg.HKEY_LOCAL_MACHINE, r"SOFTWARE\WOW6432Node\Valve\Steam"),
        (winreg.HKEY_LOCAL_MACHINE, r"SOFTWARE\Valve\Steam"),
    )
    roots: list[Path] = []
    for hive, key_name in locations:
        try:
            with winreg.OpenKey(hive, key_name) as key:
                for value_name in ("SteamPath", "InstallPath"):
                    try:
                        value, _value_type = winreg.QueryValueEx(key, value_name)
                    except OSError:
                        continue
                    if value:
                        roots.append(Path(str(value)))
        except OSError:
            continue
    return roots


def steam_library_paths() -> list[Path]:
    """Return Steam's own library roots, including the main Steam folder."""

    program_files = [
        os.environ.get("ProgramFiles(x86)"),
        os.environ.get("ProgramFiles"),
    ]
    steam_roots = _dedupe_paths(
        path
        for value in [*program_files, *[str(path) for path in _registry_steam_roots()]]
        if value
        for path in [Path(value) / "Steam", Path(value)]
    )
    library_roots: list[Path] = []
    for steam_root in steam_roots:
        vdf_path = steam_root / "steamapps" / "libraryfolders.vdf"
        if not vdf_path.is_file():
            continue
        library_roots.append(steam_root)
        try:
            document = parse_vdf(vdf_path.read_text(encoding="utf-8-sig"))
        except (OSError, UnicodeError, ValueError):
            continue
        for key, value in _walk_vdf(document):
            if key.lower() != "path" or not isinstance(value, str) or not value:
                continue
            library_roots.append(Path(value))
    return _dedupe_paths(iter(library_roots))


def _logical_drives() -> list[Path]:
    drives: list[Path] = []
    for code in "ABCDEFGHIJKLMNOPQRSTUVWXYZ":
        path = Path(f"{code}:\\")
        if path.is_dir():
            drives.append(path)
    return drives


def _fallback_game_roots() -> Iterator[Path]:
    relative_bases = (
        Path("SteamLibrary"),
        Path("Steam"),
        Path("Program Files (x86)") / "Steam",
        Path("Program Files") / "Steam",
        Path("Games"),
        Path("游戏"),
    )
    for drive in _logical_drives():
        direct_bases = [drive, *(drive / relative for relative in relative_bases)]
        for base in direct_bases:
            yield base / "steamapps" / "common" / GAME_NAME
            yield base / GAME_NAME
            try:
                children = [child for child in base.iterdir() if child.is_dir()]
            except OSError:
                continue
            for child in children[:256]:
                yield child / "steamapps" / "common" / GAME_NAME
                yield child / GAME_NAME


def validate_game_root(game_root: Path) -> GameInstallation:
    root = game_root.expanduser().resolve()
    package_manifest = root / GAME_RELATIVE_PATH
    main_package = package_manifest / "MainPackage"
    if not package_manifest.is_dir() or not main_package.is_dir():
        raise FileNotFoundError(f"不是有效的 Survival Log 游戏目录：{root}")
    catalog_path = find_catalog(root)
    _asset_to_bundle, _bundles, package_version = parse_catalog(catalog_path)
    return GameInstallation(root, catalog_path, package_version)


def discover_game_root() -> GameInstallation | None:
    candidates = [
        library / "steamapps" / "common" / GAME_NAME
        for library in steam_library_paths()
    ]
    candidates.extend(_fallback_game_roots())
    valid: list[GameInstallation] = []
    for candidate in _dedupe_paths(iter(candidates)):
        try:
            valid.append(validate_game_root(candidate))
        except (FileNotFoundError, OSError, ValueError):
            continue
    if not valid:
        return None
    return max(valid, key=lambda item: tuple(int(part) for part in _VERSION_PARTS.findall(item.package_version)))


def _database_version(database_path: Path) -> str:
    if not database_path.is_file():
        return ""
    import sqlite3

    connection = sqlite3.connect(str(database_path))
    try:
        row = connection.execute(
            "SELECT value FROM metadata WHERE key = 'game_version'"
        ).fetchone()
        return str(row[0]) if row else ""
    except sqlite3.DatabaseError:
        return ""
    finally:
        connection.close()


def _database_schema_version(database_path: Path) -> str:
    if not database_path.is_file():
        return ""
    import sqlite3

    connection = sqlite3.connect(str(database_path))
    try:
        row = connection.execute(
            "SELECT value FROM metadata WHERE key = 'database_schema_version'"
        ).fetchone()
        return str(row[0]) if row else ""
    except sqlite3.DatabaseError:
        return ""
    finally:
        connection.close()


def update_database_if_needed(
    database_path: Path,
    game: GameInstallation | None = None,
) -> UpdateResult:
    database_path = database_path.expanduser().resolve()
    game = game or discover_game_root()
    if game is None:
        return UpdateResult("not-found", None, _database_version(database_path), "", "未找到有效的 Survival Log 游戏目录，保留现有图鉴数据库")

    old_version = _database_version(database_path)
    from codex_database import DATABASE_SCHEMA_VERSION, build_database

    if (
        old_version == game.package_version
        and _database_schema_version(database_path) == str(DATABASE_SCHEMA_VERSION)
    ):
        return UpdateResult("unchanged", game.root, old_version, game.package_version, f"图鉴已是游戏版本 {game.package_version}")

    build_database(game.root, database_path, sync_save=False)
    return UpdateResult(
        "updated",
        game.root,
        old_version,
        game.package_version,
        f"已从游戏版本 {old_version or '未知'} 更新图鉴到 {game.package_version}",
    )


__all__ = [
    "GameInstallation",
    "UpdateResult",
    "discover_game_root",
    "parse_vdf",
    "steam_library_paths",
    "update_database_if_needed",
    "validate_game_root",
]
