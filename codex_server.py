#!/usr/bin/env python3
"""Serve the offline Survival Log codex through a standard-library web app."""

from __future__ import annotations

import argparse
import json
import re
import sqlite3
import sys
import threading
import time
import urllib.parse
import webbrowser
from collections import Counter
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any

from codex_database import (
    CATEGORY_LABELS,
    CATEGORY_ORDER,
    CompletionSyncResult,
    get_category_summaries,
    get_entry,
    get_entry_relations,
    get_metadata,
    get_overall_summary,
    open_database,
    query_entries,
    resolve_default_database_path,
    sync_game_completion,
)
from codex_save import SaveParseError, default_save_file
from codex_parser import FIELD_LABELS, format_scalar
from codex_recipe import RecipeConfigError, build_recipe_error, build_recipe_plan


POLL_INTERVAL_SECONDS = 5
PAGE_CLOSE_GRACE_SECONDS = 30
CATEGORY_EMOJI = {
    "food": "🍞",
    "dish": "🍳",
    "plant": "🌱",
    "prey": "🐾",
    "craft": "🔧",
    "furniture": "🛋️",
    "recipes": "🍲",
}
DETAIL_RELATION_PREFIXES = {
    "food": ("关联植物", "目标家具"),
    "prey": ("关联植物", "目标家具"),
    "dish": ("具体食材", "食材分类"),
    "craft": ("制造材料",),
    "furniture": ("制造材料", "制造要求等级"),
}
STATIC_FILES = {
    "/": ("index.html", "text/html; charset=utf-8"),
    "/index.html": ("index.html", "text/html; charset=utf-8"),
    "/app.js": ("app.js", "text/javascript; charset=utf-8"),
    "/styles.css": ("styles.css", "text/css; charset=utf-8"),
}


def default_database_path() -> Path:
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent / "SurvivalLogDataViewer.sqlite3"
    return resolve_default_database_path()


def static_root() -> Path:
    candidates = [Path(__file__).resolve().parent / "web"]
    candidates.append(Path(sys.executable).resolve().parent / "web")
    bundle_root = getattr(sys, "_MEIPASS", None)
    if bundle_root:
        candidates.append(Path(bundle_root) / "web")
    for candidate in candidates:
        if candidate.is_dir():
            return candidate
    raise FileNotFoundError("找不到本地网页资源目录：web")


def _first_query_value(values: dict[str, list[str]], name: str, default: str = "") -> str:
    return values.get(name, [default])[0]


def _client_id(value: str) -> str | None:
    if re.fullmatch(r"[A-Za-z0-9_-]{1,128}", value):
        return value
    return None


def _json_safe_entry(entry: dict[str, Any]) -> dict[str, Any]:
    return {key: value for key, value in entry.items() if key != "raw_json"}


def _relation_matches(relation_type: str, prefixes: tuple[str, ...]) -> bool:
    return any(relation_type == prefix or relation_type.startswith(f"{prefix}（") for prefix in prefixes)


def _format_relation_values(
    relations: list[dict[str, Any]],
    *,
    include_group: bool = False,
    include_id: bool = True,
) -> str:
    grouped: dict[str, list[dict[str, Any]]] = {}
    for relation in relations:
        grouped.setdefault(relation["relation_type"], []).append(relation)
    parts: list[str] = []
    for relation_type, values in grouped.items():
        counts = Counter((value["target_id"], value["target_name"]) for value in values)
        items = []
        for (target_id, target_name), count in counts.items():
            quantity = f" × {count}" if count > 1 else ""
            identity = f"（ID {target_id}）" if include_id else ""
            display_name = str(target_name)
            if not include_id and re.fullmatch(r"ID\s*:?\s*\d+", display_name):
                display_name = "未知关联"
            items.append(f"{display_name}{quantity}{identity}")
        text = "、".join(items) or "无"
        display_relation_type = relation_type
        if not include_id:
            display_relation_type = re.sub(r"\s*ID\s*:?\s*\d+", "", display_relation_type)
            display_relation_type = display_relation_type.replace("（）", "")
        parts.append(
            f"{display_relation_type}：{text}" if include_group else text
        )
    return "；".join(parts) or "无"


def _raw_field(raw: dict[str, Any], field: str, label: str | None = None) -> dict[str, str] | None:
    if field not in raw:
        return None
    return {
        "field": field,
        "label": label or FIELD_LABELS.get(field, field),
        "value": format_scalar(raw[field]),
    }


def _build_detail_fields(
    category: str,
    raw: dict[str, Any],
    relations: list[dict[str, Any]],
) -> tuple[list[dict[str, str]], list[dict[str, str]], list[str]]:
    highlights: list[dict[str, str]] = []
    highlighted_fields: set[str] = set()
    highlighted_relation_prefixes = DETAIL_RELATION_PREFIXES.get(category, ())

    if category in {"food", "prey"}:
        acquisition_parts: list[str] = []
        acquisition_text = raw.get("ItemDes1_Local") or raw.get("ItemDes1")
        if acquisition_text:
            acquisition_parts.append(str(acquisition_text))
            highlighted_fields.add("ItemDes1_Local")
            highlighted_fields.add("ItemDes1")
        for prefix in highlighted_relation_prefixes:
            matching = [
                relation
                for relation in relations
                if relation["relation_type"] == prefix
            ]
            if matching:
                acquisition_parts.append(
                    f"{prefix}：{_format_relation_values(matching, include_id=False)}"
                )
        highlights.append(
            {
                "field": "acquisition",
                "label": "获取方法",
                "value": "；".join(acquisition_parts) or "当前配置未提供专门的获取方法",
            }
        )
        if category == "food":
            price = _raw_field(raw, "price", "购买价格")
            if price:
                highlights.append(price)
                highlighted_fields.add("price")

    elif category == "dish":
        ingredients = [
            relation
            for relation in relations
            if relation["relation_type"] in {"具体食材", "食材分类"}
        ]
        highlights.append(
            {
                "field": "ingredients",
                "label": "制作所需食材",
                "value": _format_relation_values(ingredients, include_id=False),
            }
        )
        highlighted_fields.update({"SpecificItems", "TagCombo"})
        level = _raw_field(raw, "MinLevel", "要求等级")
        if level:
            level["value"] = f"{level['value']}级"
            highlights.append(level)
            highlighted_fields.add("MinLevel")

    elif category == "plant":
        for field in ("Size", "LightNeed", "ColdResistance"):
            item = _raw_field(raw, field)
            if item:
                highlights.append(item)
                highlighted_fields.add(field)

    elif category == "craft":
        materials = [
            relation
            for relation in relations
            if relation["relation_type"].startswith("制造材料")
        ]
        highlights.append(
            {
                "field": "materials",
                "label": "制作所需材料",
                "value": _format_relation_values(materials, include_id=False),
            }
        )
        highlighted_fields.add("MaterialList")
        level = _raw_field(raw, "Level", "要求等级")
        if level:
            level["value"] = f"{level['value']}级"
            highlights.append(level)
            highlighted_fields.add("Level")

    elif category == "furniture":
        price = _raw_field(raw, "FurniturePrice", "家具价格")
        if price:
            highlights.append(price)
            highlighted_fields.add("FurniturePrice")
        materials = [
            relation
            for relation in relations
            if relation["relation_type"].startswith("制造材料")
        ]
        highlights.append(
            {
                "field": "materials",
                "label": "制作所需材料",
                "value": _format_relation_values(materials, include_id=False),
            }
        )
        levels = [
            relation
            for relation in relations
            if relation["relation_type"].startswith("制造要求等级")
        ]
        highlights.append(
            {
                "field": "level",
                "label": "要求等级",
                "value": _format_relation_values(levels, include_id=False),
            }
        )

    fields = []
    for field, value in raw.items():
        if field in highlighted_fields:
            continue
        fields.append(
            {
                "field": field,
                "label": FIELD_LABELS.get(field, field),
                "value": format_scalar(value),
            }
        )
    return highlights, fields, list(highlighted_relation_prefixes)


def _highlight_items(
    category: str,
    raw: dict[str, Any],
    relations: list[dict[str, Any]],
) -> list[dict[str, str]]:
    highlights, _fields, _prefixes = _build_detail_fields(category, raw, relations)
    return [
        {
            "label": str(field["label"]),
            "value": str(field["value"]),
        }
        for field in highlights
        if str(field["value"])
    ]


def _highlight_summary(items: list[dict[str, str]]) -> str:
    return "；".join(f"{item['label']}：{item['value']}" for item in items)


class CodexService:
    """Serialize database access and avoid parsing the save when its signature is unchanged."""

    def __init__(
        self,
        database_path: Path,
        save_file: Path,
        *,
        log_path: Path | None = None,
    ):
        self.database_path = database_path.expanduser().resolve()
        self.save_file = save_file.expanduser().resolve()
        self.log_path = log_path.expanduser().resolve() if log_path is not None else None
        self.connection = open_database(self.database_path, check_same_thread=False)
        self._lock = threading.RLock()
        self._last_success_signature: tuple[Any, ...] | None = None
        self._last_sync: CompletionSyncResult | None = None
        self._last_recipe_signature: tuple[Any, ...] | None = None
        self._last_recipe_plan: dict[str, Any] | None = None

    @staticmethod
    def _file_signature(path: Path) -> tuple[Any, ...]:
        try:
            stat = path.stat()
        except OSError:
            return (str(path), False, 0, 0)
        if not path.is_file():
            return (str(path), False, 0, 0)
        return (str(path), True, stat.st_size, stat.st_mtime_ns)

    def _save_signature(self) -> tuple[Any, ...]:
        return (
            self._file_signature(self.save_file),
            self._file_signature(Path(f"{self.save_file}.bak")),
        )

    def _recipe_signature(self) -> tuple[Any, ...]:
        children = []
        for path in sorted(self.save_file.parent.glob("Save_*.bytes"), key=lambda value: value.name):
            if not re.fullmatch(r"Save_[A-Za-z0-9_-]+\.bytes", path.name):
                continue
            children.append(self._file_signature(path))
            children.append(self._file_signature(Path(f"{path}.bak")))
        return self._save_signature() + tuple(children)

    def _ensure_sync(self) -> CompletionSyncResult:
        signature = self._save_signature()
        with self._lock:
            if (
                self._last_sync is not None
                and self._last_success_signature == signature
                and self._last_sync.status in {"ok", "fallback"}
            ):
                return CompletionSyncResult(
                    status=self._last_sync.status,
                    changed=False,
                    save_path=self._last_sync.save_path,
                    category_counts=self._last_sync.category_counts,
                    unknown_ids=self._last_sync.unknown_ids,
                    updated_entries=0,
                    used_backup=self._last_sync.used_backup,
                    message="存档未变化，完成状态无需更新",
                    schema_profile=self._last_sync.schema_profile,
                    codex_offset=self._last_sync.codex_offset,
                    codex_end_offset=self._last_sync.codex_end_offset,
                    candidate_count=self._last_sync.candidate_count,
                    candidate_score=self._last_sync.candidate_score,
                )

            result = sync_game_completion(
                self.connection,
                self.save_file,
                log_path=self.log_path,
            )
            self._last_sync = result
            if result.status in {"ok", "fallback"}:
                self._last_success_signature = signature
            else:
                self._last_success_signature = None
            return result

    def _revision(self, metadata: dict[str, str], result: CompletionSyncResult) -> str:
        return json.dumps(
            {
                "path": metadata.get("save_path", str(result.save_path)),
                "sha256": metadata.get("save_sha256", ""),
                "mtime_ns": metadata.get("save_mtime_ns", ""),
                "status": metadata.get("save_sync_status", result.status),
                "error": metadata.get("save_sync_error", ""),
            },
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        )

    def state(self) -> dict[str, Any]:
        with self._lock:
            result = self._ensure_sync()
            metadata = get_metadata(self.connection)
            summaries = get_category_summaries(self.connection)
            summary_by_category = {row["category"]: row for row in summaries}
            categories = [
                {
                    "category": category,
                    "label": CATEGORY_LABELS[category],
                    "emoji": CATEGORY_EMOJI[category],
                    "total": int(summary_by_category.get(category, {}).get("total", 0)),
                    "completed": int(summary_by_category.get(category, {}).get("completed", 0)),
                }
                for category in CATEGORY_ORDER
            ]
            categories.append(
                {
                    "category": "recipes",
                    "label": "可烹饪菜谱",
                    "emoji": CATEGORY_EMOJI["recipes"],
                    "total": None,
                    "completed": None,
                }
            )
            sync = {
                "status": result.status,
                "changed": result.changed,
                "message": result.message,
                "revision": self._revision(metadata, result),
                "save_path": str(result.save_path),
                "used_backup": result.used_backup,
                "updated_entries": result.updated_entries,
                "category_counts": result.category_counts,
                "schema_profile": result.schema_profile,
                "codex_offset": result.codex_offset,
                "codex_end_offset": result.codex_end_offset,
                "candidate_count": result.candidate_count,
                "candidate_score": list(result.candidate_score),
                "unknown_ids": {
                    category: list(values) for category, values in result.unknown_ids.items()
                },
            }
            return {
                "categories": categories,
                "overall": get_overall_summary(self.connection),
                "metadata": metadata,
                "sync": sync,
                "poll_interval_seconds": POLL_INTERVAL_SECONDS,
                "disconnect_grace_seconds": PAGE_CLOSE_GRACE_SECONDS,
            }

    def recipe_plans(self) -> dict[str, Any]:
        with self._lock:
            self._ensure_sync()
            signature = self._recipe_signature()
            if self._last_recipe_plan is not None and self._last_recipe_signature == signature:
                return self._last_recipe_plan
            try:
                payload = build_recipe_plan(self.connection, self.save_file)
            except (OSError, RecipeConfigError, SaveParseError, sqlite3.Error) as exc:
                payload = build_recipe_error(str(exc))
            payload["revision"] = json.dumps(
                {
                    "save_signature": signature,
                    "history_source": payload.get("history_source"),
                    "status": payload.get("status"),
                },
                ensure_ascii=False,
                sort_keys=True,
                separators=(",", ":"),
                default=str,
            )
            self._last_recipe_signature = signature
            self._last_recipe_plan = payload
            return payload

    def entries(
        self,
        category: str,
        name_search: str,
        material_search: str,
        completion_filter: str,
    ) -> dict[str, Any]:
        if category not in CATEGORY_ORDER:
            raise ValueError(f"未知图鉴分类：{category}")
        if completion_filter not in {"all", "completed", "pending"}:
            raise ValueError(f"未知完成状态筛选：{completion_filter}")
        with self._lock:
            self._ensure_sync()
            rows = query_entries(
                self.connection,
                category,
                name_search,
                completion_filter,
                limit=None,
                material_search=material_search,
            )
            for row in rows:
                raw = json.loads(row["raw_json"])
                relations = get_entry_relations(self.connection, row["entry_key"])
                highlight_items = _highlight_items(category, raw, relations)
                row["highlight_items"] = highlight_items
                row["highlight_summary"] = _highlight_summary(highlight_items)
            return {
                "category": category,
                "label": CATEGORY_LABELS[category],
                "total": len(rows),
                "name_search": name_search,
                "material_search": material_search,
                "entries": [_json_safe_entry(row) for row in rows],
            }

    def entry(self, category: str, entry_key: str) -> dict[str, Any] | None:
        if category not in CATEGORY_ORDER:
            raise ValueError(f"未知图鉴分类：{category}")
        if not entry_key:
            raise ValueError("缺少条目键")
        with self._lock:
            self._ensure_sync()
            row = get_entry(self.connection, entry_key, category)
            if row is None:
                return None
            payload = json.loads(row["raw_json"])
            relations = get_entry_relations(self.connection, entry_key)
            highlights, fields, highlight_relation_prefixes = _build_detail_fields(
                category,
                payload,
                relations,
            )
            return {
                "entry": _json_safe_entry(row),
                "relations": relations,
                "highlight_relation_prefixes": highlight_relation_prefixes,
                "highlights": highlights,
                "fields": fields,
            }

    def close(self) -> None:
        with self._lock:
            self.connection.close()


class CodexHTTPServer(ThreadingHTTPServer):
    allow_reuse_address = True

    def __init__(
        self,
        address: tuple[str, int],
        service: CodexService,
        assets: Path,
        *,
        auto_exit: bool,
    ):
        super().__init__(address, CodexRequestHandler)
        self.service = service
        self.assets = assets
        self.auto_exit = auto_exit
        self._lifecycle_lock = threading.Lock()
        self._active_client_ids: set[str] = set()
        self._closed_client_ids: set[str] = set()
        self._page_close_requested_at: float | None = None
        self._stopping = threading.Event()
        if self.auto_exit:
            monitor = threading.Thread(
                target=self._monitor_client,
                name="codex-client-monitor",
                daemon=True,
            )
            monitor.start()

    def note_client_activity(self, client_id: str | None = None) -> None:
        with self._lifecycle_lock:
            if client_id:
                if client_id in self._closed_client_ids:
                    return
                self._active_client_ids.add(client_id)
            self._page_close_requested_at = None

    def note_client_closed(self, client_id: str | None = None) -> None:
        with self._lifecycle_lock:
            if client_id:
                self._closed_client_ids.add(client_id)
                self._active_client_ids.discard(client_id)
                if self._active_client_ids:
                    self._page_close_requested_at = None
                    return
            self._page_close_requested_at = time.monotonic()

    def _monitor_client(self) -> None:
        while not self._stopping.wait(POLL_INTERVAL_SECONDS):
            with self._lifecycle_lock:
                close_requested_at = self._page_close_requested_at
            if (
                close_requested_at is not None
                and time.monotonic() - close_requested_at >= PAGE_CLOSE_GRACE_SECONDS
            ):
                self.shutdown()
                return

    def server_close(self) -> None:
        self._stopping.set()
        super().server_close()


class CodexRequestHandler(BaseHTTPRequestHandler):
    server: CodexHTTPServer

    def _send_bytes(self, status: int, content_type: str, body: bytes) -> None:
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.end_headers()
        self.wfile.write(body)

    def _send_json(self, status: int, payload: dict[str, Any]) -> None:
        body = json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
        self._send_bytes(status, "application/json; charset=utf-8", body)

    def _send_error_json(self, status: int, message: str) -> None:
        self._send_json(status, {"error": message})

    def _serve_static(self, path: str) -> None:
        asset = STATIC_FILES.get(path)
        if asset is None:
            self._send_error_json(HTTPStatus.NOT_FOUND, "找不到网页资源")
            return
        filename, content_type = asset
        asset_path = self.server.assets / filename
        try:
            body = asset_path.read_bytes()
        except OSError as exc:
            self._send_error_json(HTTPStatus.INTERNAL_SERVER_ERROR, f"读取网页资源失败：{exc}")
            return
        self._send_bytes(HTTPStatus.OK, content_type, body)

    def _handle_api(self, path: str, query: dict[str, list[str]]) -> None:
        service = self.server.service
        if path == "/api/state":
            self._send_json(HTTPStatus.OK, service.state())
            return
        if path == "/api/recipe-plans":
            self._send_json(HTTPStatus.OK, service.recipe_plans())
            return
        if path == "/api/entries":
            category = _first_query_value(query, "category", "furniture")
            name_search = _first_query_value(query, "name_search")
            if not name_search:
                name_search = _first_query_value(query, "search")
            material_search = _first_query_value(query, "material_search")
            completion = _first_query_value(query, "completion", "all")
            self._send_json(
                HTTPStatus.OK,
                service.entries(category, name_search, material_search, completion),
            )
            return
        prefix = "/api/entries/"
        if path.startswith(prefix):
            entry_key = urllib.parse.unquote(path[len(prefix) :])
            category = _first_query_value(query, "category", "furniture")
            result = service.entry(category, entry_key)
            if result is None:
                self._send_error_json(HTTPStatus.NOT_FOUND, "找不到图鉴条目")
            else:
                self._send_json(HTTPStatus.OK, result)
            return
        self._send_error_json(HTTPStatus.NOT_FOUND, "找不到 API 接口")

    def do_GET(self) -> None:  # noqa: N802 - required by BaseHTTPRequestHandler
        parsed = urllib.parse.urlsplit(self.path)
        query = urllib.parse.parse_qs(parsed.query, keep_blank_values=True)
        try:
            if parsed.path.startswith("/api/"):
                self.server.note_client_activity(_client_id(self.headers.get("X-SurvivalLog-Client", "")))
                self._handle_api(parsed.path, query)
            else:
                self._serve_static(parsed.path)
        except ValueError as exc:
            self._send_error_json(HTTPStatus.BAD_REQUEST, str(exc))
        except Exception as exc:  # Keep API failures visible without exposing a traceback in the browser.
            print(f"本地网页请求失败：{exc}", file=sys.stderr)
            self._send_error_json(HTTPStatus.INTERNAL_SERVER_ERROR, f"本地服务处理失败：{exc}")

    def do_POST(self) -> None:  # noqa: N802 - required by BaseHTTPRequestHandler
        parsed = urllib.parse.urlsplit(self.path)
        query = urllib.parse.parse_qs(parsed.query, keep_blank_values=True)
        try:
            if parsed.path == "/api/client/closed":
                self.server.note_client_closed(_client_id(_first_query_value(query, "client_id")))
                self._send_json(HTTPStatus.OK, {"status": "accepted"})
                return
            self._send_error_json(HTTPStatus.NOT_FOUND, "找不到 API 接口")
        except Exception as exc:  # Keep API failures visible without exposing a traceback in the browser.
            print(f"本地网页请求失败：{exc}", file=sys.stderr)
            self._send_error_json(HTTPStatus.INTERNAL_SERVER_ERROR, f"本地服务处理失败：{exc}")

    def log_message(self, format: str, *args: Any) -> None:
        print(f"{self.address_string()} - {format % args}", file=sys.stderr)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="启动 Survival Log 生存图鉴本地网页")
    parser.add_argument("--port", type=int, default=8501, help="本地服务端口")
    parser.add_argument(
        "--database",
        type=Path,
        default=None,
        help="SQLite 数据库路径",
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


def run_local_server(
    database_path: Path,
    save_file: Path,
    port: int = 8501,
    headless: bool = False,
    *,
    log_path: Path | None = None,
) -> None:
    service = CodexService(database_path, save_file, log_path=log_path)
    try:
        server = CodexHTTPServer(
            ("127.0.0.1", port),
            service,
            static_root(),
            auto_exit=not headless,
        )
    except Exception:
        service.close()
        raise

    url = f"http://127.0.0.1:{port}/"
    print(f"图鉴本地网页：{url}")
    print(f"数据库：{service.database_path}")
    print(f"存档：{service.save_file}")
    if not headless:
        browser_timer = threading.Timer(0.25, webbrowser.open, args=(url,))
        browser_timer.daemon = True
        browser_timer.start()
    try:
        server.serve_forever(poll_interval=0.5)
    finally:
        server.server_close()
        service.close()


def main() -> int:
    try:
        args = parse_args()
        if not 1 <= args.port <= 65535:
            raise ValueError(f"端口必须在 1 到 65535 之间：{args.port}")
        args.database = args.database or default_database_path()
        run_local_server(args.database, args.save_file, args.port, args.headless)
    except KeyboardInterrupt:
        return 0
    except Exception as exc:
        print(f"图鉴本地网页启动失败：{exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
