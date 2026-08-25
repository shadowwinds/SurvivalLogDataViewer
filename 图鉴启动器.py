#!/usr/bin/env python3
"""Launch the bundled Survival Log local web frontend."""

from __future__ import annotations

import argparse
import ctypes
import sys
from pathlib import Path

from 图鉴前端 import run_local_server


DATABASE_NAME = "SurvivalLog图鉴.sqlite3"


def application_directory() -> Path:
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parent


def default_save_file() -> Path:
    return (
        Path.home()
        / "AppData"
        / "LocalLow"
        / "LLS"
        / "SLGame"
        / "Saves"
        / "HistorySave.bytes"
    )


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="启动 Survival Log 生存图鉴本地网页")
    parser.add_argument("--port", type=int, default=8501, help="本地服务端口")
    parser.add_argument(
        "--database",
        type=Path,
        help="指定运行数据库路径；不指定时使用 exe 同目录中的数据库",
    )
    parser.add_argument(
        "--save-file",
        type=Path,
        default=default_save_file(),
        help="HistorySave.bytes 存档路径",
    )
    parser.add_argument(
        "--headless",
        action="store_true",
        help="启动服务但不自动打开浏览器",
    )
    return parser.parse_args()


def default_database_path() -> Path:
    return application_directory() / DATABASE_NAME


def resolve_database(requested_path: Path | None) -> Path:
    if requested_path is not None:
        return requested_path.expanduser().resolve()

    database_path = default_database_path()
    if not database_path.exists():
        raise FileNotFoundError(f"程序目录中找不到数据库：{database_path}")
    return database_path


def show_error(message: str) -> None:
    print(message, file=sys.stderr)
    if sys.platform == "win32":
        try:
            ctypes.windll.user32.MessageBoxW(0, message, "Survival Log 生存图鉴", 0x10)
        except Exception:
            pass


def run_frontend(args: argparse.Namespace) -> None:
    database_path = resolve_database(args.database)
    run_local_server(
        database_path,
        args.save_file.expanduser().resolve(),
        args.port,
        args.headless,
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
