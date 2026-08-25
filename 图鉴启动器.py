#!/usr/bin/env python3
"""Launch the bundled Survival Log local web frontend."""

from __future__ import annotations

import argparse
import ctypes
import os
import shutil
import sys
from pathlib import Path

from 图鉴前端 import run_local_server


APP_NAME = "SurvivalLogDataViewer"
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
        help="指定运行数据库路径；不指定时使用用户数据目录中的数据库",
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


def user_data_directory() -> Path:
    local_app_data = Path.home() / "AppData" / "Local"
    if sys.platform == "win32":
        local_app_data = Path(os.environ.get("LOCALAPPDATA", local_app_data))
    return local_app_data / APP_NAME


def prepare_database(requested_path: Path | None) -> Path:
    if requested_path is not None:
        return requested_path.expanduser().resolve()

    seed_path = application_directory() / DATABASE_NAME
    runtime_path = user_data_directory() / DATABASE_NAME
    if runtime_path.exists():
        return runtime_path
    if not seed_path.exists():
        raise FileNotFoundError(f"分发包中找不到数据库：{seed_path}")

    runtime_path.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(seed_path, runtime_path)
    return runtime_path


def show_error(message: str) -> None:
    print(message, file=sys.stderr)
    if sys.platform == "win32":
        try:
            ctypes.windll.user32.MessageBoxW(0, message, "Survival Log 生存图鉴", 0x10)
        except Exception:
            pass


def run_frontend(args: argparse.Namespace) -> None:
    database_path = prepare_database(args.database)
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
