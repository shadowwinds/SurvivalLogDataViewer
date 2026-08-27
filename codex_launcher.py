#!/usr/bin/env python3
"""Launch the bundled Survival Log local web frontend."""

from __future__ import annotations

import argparse
import ctypes
import json
import os
import sys
from datetime import datetime
from pathlib import Path
from ctypes import wintypes

DATABASE_NAME = "SurvivalLogDataViewer.sqlite3"
LOG_NAME = "SurvivalLogDataViewer.log"


def application_directory() -> Path:
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parent


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="启动 Survival Log 生存图鉴本地网页")
    parser.add_argument(
        "--port",
        type=int,
        default=8501,
        help="本地服务端口；默认端口被占用时自动选择空闲端口",
    )
    parser.add_argument(
        "--database",
        type=Path,
        help="指定运行数据库路径；不指定时使用 exe 同目录中的数据库",
    )
    parser.add_argument(
        "--save-file",
        type=Path,
        default=None,
        help="HistorySave.bytes 存档路径",
    )
    parser.add_argument(
        "--game-root",
        type=Path,
        default=None,
        help="指定游戏安装目录；不指定时自动查找 Steam 库",
    )
    parser.add_argument(
        "--headless",
        action="store_true",
        help="启动服务但不自动打开浏览器",
    )
    return parser.parse_args()


def default_database_path() -> Path:
    directory = application_directory()
    return directory / DATABASE_NAME


def resolve_database(requested_path: Path | None) -> Path:
    if requested_path is not None:
        return requested_path.expanduser().resolve()

    database_path = default_database_path()
    if not database_path.exists():
        raise FileNotFoundError(f"程序目录中找不到数据库：{database_path}")
    return database_path


def _select_save_file(initial_dir: Path) -> Path | None:
    if sys.platform != "win32":
        return None

    class OpenFileName(ctypes.Structure):
        _fields_ = [
            ("lStructSize", wintypes.DWORD),
            ("hwndOwner", wintypes.HWND),
            ("hInstance", wintypes.HINSTANCE),
            ("lpstrFilter", wintypes.LPCWSTR),
            ("lpstrCustomFilter", wintypes.LPWSTR),
            ("nMaxCustFilter", wintypes.DWORD),
            ("nFilterIndex", wintypes.DWORD),
            ("lpstrFile", wintypes.LPWSTR),
            ("nMaxFile", wintypes.DWORD),
            ("lpstrFileTitle", wintypes.LPWSTR),
            ("nMaxFileTitle", wintypes.DWORD),
            ("lpstrInitialDir", wintypes.LPCWSTR),
            ("lpstrTitle", wintypes.LPCWSTR),
            ("Flags", wintypes.DWORD),
            ("nFileOffset", wintypes.WORD),
            ("nFileExtension", wintypes.WORD),
            ("lpstrDefExt", wintypes.LPCWSTR),
            ("lCustData", wintypes.LPARAM),
            ("lpfnHook", wintypes.LPVOID),
            ("lpTemplateName", wintypes.LPCWSTR),
        ]

    buffer = ctypes.create_unicode_buffer(32768)
    dialog = OpenFileName()
    dialog.lStructSize = ctypes.sizeof(OpenFileName)
    dialog.lpstrFilter = "HistorySave.bytes\0HistorySave.bytes\0所有文件\0*.*\0\0"
    dialog.nFilterIndex = 1
    dialog.lpstrFile = ctypes.cast(buffer, wintypes.LPWSTR)
    dialog.nMaxFile = len(buffer)
    dialog.lpstrInitialDir = str(initial_dir) if initial_dir.is_dir() else None
    dialog.lpstrTitle = "选择 Survival Log 存档文件"
    dialog.Flags = 0x00001000 | 0x00000800 | 0x00000008
    if not ctypes.windll.comdlg32.GetOpenFileNameW(ctypes.byref(dialog)):
        return None
    return Path(buffer.value)


def resolve_save_file(requested_path: Path | None) -> Path:
    from codex_save import default_save_file

    if requested_path is not None:
        return requested_path.expanduser().resolve()
    default_path = default_save_file().expanduser().resolve()
    if default_path.is_file() or Path(f"{default_path}.bak").is_file():
        return default_path
    selected = _select_save_file(default_path.parent)
    return (selected or default_path).expanduser().resolve()


def show_error(message: str) -> None:
    safe_message = _redact_user_path(message)
    if getattr(sys, "frozen", False):
        _write_startup_error(safe_message)
    if sys.stderr is not None:
        try:
            print(safe_message, file=sys.stderr)
        except (AttributeError, OSError, ValueError):
            pass
    if sys.platform == "win32":
        try:
            ctypes.windll.user32.MessageBoxW(0, safe_message, "Survival Log 生存图鉴", 0x10)
        except Exception:
            pass


def _redact_user_path(message: str) -> str:
    home = str(Path.home().expanduser().resolve())
    if message.casefold().startswith(home.casefold()):
        return "%USERPROFILE%" + message[len(home) :]
    return message.replace(home, "%USERPROFILE%")


def _startup_log_paths() -> tuple[Path, ...]:
    paths = [application_directory() / LOG_NAME]
    local_app_data = os.environ.get("LOCALAPPDATA")
    fallback_root = (
        Path(local_app_data)
        if local_app_data
        else Path.home() / "AppData" / "Local"
    )
    paths.append(fallback_root / "SurvivalLogDataViewer" / LOG_NAME)
    result: list[Path] = []
    seen: set[str] = set()
    for path in paths:
        key = os.path.normcase(str(path))
        if key not in seen:
            seen.add(key)
            result.append(path)
    return tuple(result)


def _write_startup_error(message: str) -> None:
    payload = json.dumps(
        {
            "event": "startup_error",
            "timestamp": datetime.now().astimezone().isoformat(timespec="seconds"),
            "message": message,
        },
        ensure_ascii=False,
        separators=(",", ":"),
    )
    for path in _startup_log_paths():
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            with path.open("a", encoding="utf-8", newline="\n") as handle:
                handle.write(payload)
                handle.write("\n")
            return
        except OSError:
            continue


def run_frontend(args: argparse.Namespace) -> None:
    from codex_server import run_local_server
    from codex_update import update_database_if_needed, validate_game_root

    database_path = resolve_database(args.database)
    save_file = resolve_save_file(args.save_file)
    try:
        game = validate_game_root(args.game_root) if args.game_root else None
        result = update_database_if_needed(database_path, game, single_file=True)
        print(result.message)
    except Exception as exc:
        show_error(f"自动更新图鉴失败，将继续使用现有数据库：{exc}")
    log_path = application_directory() / LOG_NAME if getattr(sys, "frozen", False) else None
    run_local_server(
        database_path,
        save_file,
        args.port,
        args.headless,
        runtime_database_path=None,
        log_path=log_path,
    )


def main() -> int:
    try:
        args = parse_args()
        if not 1 <= args.port <= 65535:
            raise ValueError(f"端口必须在 1 到 65535 之间：{args.port}")
        run_frontend(args)
    except KeyboardInterrupt:
        return 0
    except Exception as exc:
        show_error(f"图鉴本地网页启动失败：{exc}")
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
