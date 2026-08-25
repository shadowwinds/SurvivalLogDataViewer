#!/usr/bin/env python3
"""Streamlit frontend for the offline Survival Log codex database."""

from __future__ import annotations

import argparse
import json
import sys
from html import escape
from pathlib import Path
from typing import Any

import streamlit as st

from 图鉴数据库 import (
    CATEGORY_LABELS,
    CATEGORY_ORDER,
    get_category_summaries,
    get_entry,
    get_entry_relations,
    get_metadata,
    open_database,
    query_entries,
    sync_game_completion,
)
from 图鉴存档解析 import default_save_file
from 图鉴解析工具 import FIELD_LABELS, format_scalar


CATEGORY_EMOJI = {
    "food": "🍞",
    "dish": "🍳",
    "plant": "🌱",
    "prey": "🐾",
    "craft": "🔧",
    "furniture": "🛋️",
}


APP_CSS = """
<style>
:root {
    --codex-ink: #1f2933;
    --codex-muted: #6b7785;
    --codex-border: #dfe6eb;
    --codex-surface: #ffffff;
    --codex-background: #f5f7f9;
    --codex-accent: #1f7a6d;
    --codex-accent-soft: #e8f5f1;
    --codex-success: #397b50;
    --codex-success-soft: #e8f4eb;
    --codex-pending: #b7791f;
    --codex-pending-soft: #fff6df;
}

[data-testid="stAppViewContainer"] {
    background: var(--codex-background);
}

[data-testid="stHeader"] {
    background: transparent;
}

[data-testid="stSidebar"] {
    background: #edf2f4;
    border-right: 1px solid var(--codex-border);
}

[data-testid="stSidebar"] > div:first-child {
    padding-top: 1.25rem;
}

.block-container {
    max-width: 1480px;
    padding-top: 1.5rem;
    padding-bottom: 2rem;
}

[data-testid="stVerticalBlockBorderWrapper"] {
    border-color: var(--codex-border);
    border-radius: 10px;
    background: var(--codex-surface);
}

[data-testid="stVerticalBlockBorderWrapper"]:has(.entry-row-marker) {
    transition: border-color 120ms ease, box-shadow 120ms ease;
}

[data-testid="stVerticalBlockBorderWrapper"]:has(.entry-row-marker):hover {
    border-color: #b7d8d1;
    box-shadow: 0 3px 12px rgba(31, 122, 109, 0.08);
}

.entry-row-marker {
    width: 8px;
    height: 8px;
    margin: 0.35rem auto 0;
    border-radius: 50%;
    background: var(--codex-pending);
}

.entry-row-marker.completed {
    background: var(--codex-success);
}

.entry-name {
    color: var(--codex-ink);
    font-size: 1rem;
    font-weight: 650;
    line-height: 1.35;
}

.entry-meta {
    color: var(--codex-muted);
    font-size: 0.78rem;
    line-height: 1.35;
    margin-top: 0.18rem;
}

.status-pill {
    display: inline-block;
    border-radius: 999px;
    font-size: 0.76rem;
    font-weight: 600;
    line-height: 1.4;
    padding: 0.22rem 0.55rem;
    white-space: nowrap;
}

.status-pill.completed {
    background: var(--codex-success-soft);
    color: var(--codex-success);
}

.status-pill.pending {
    background: var(--codex-pending-soft);
    color: var(--codex-pending);
}

.section-summary {
    color: var(--codex-muted);
    font-size: 0.82rem;
    margin-top: 0.25rem;
}

.data-source-label {
    color: var(--codex-muted);
    font-size: 0.78rem;
    line-height: 1.5;
}

.stButton > button {
    border: 1px solid var(--codex-border);
    border-radius: 8px;
    color: var(--codex-ink);
    min-height: 2.25rem;
    transition: border-color 120ms ease, background-color 120ms ease, color 120ms ease;
}

.stButton > button:hover {
    border-color: var(--codex-accent);
    color: var(--codex-accent);
    background: var(--codex-accent-soft);
}

[data-testid="stProgressBarTrack"] {
    background: var(--codex-border);
}

[data-testid="stProgressBarTrack"] > div {
    background: var(--codex-accent);
}

[data-testid="stTextInput"] input:focus {
    border-color: var(--codex-accent);
    box-shadow: 0 0 0 1px var(--codex-accent);
}

[data-testid="stExpander"] {
    border-color: var(--codex-border);
    background: var(--codex-surface);
}
</style>
"""


def parse_script_args() -> argparse.Namespace:
    raw_args = sys.argv[1:]
    if "--" in raw_args:
        raw_args = raw_args[raw_args.index("--") + 1 :]
    parser = argparse.ArgumentParser(add_help=False)
    parser.add_argument(
        "--database",
        type=Path,
        default=Path(__file__).resolve().parent / "SurvivalLog图鉴.sqlite3",
    )
    parser.add_argument(
        "--save-file",
        type=Path,
        default=default_save_file(),
    )
    return parser.parse_args(raw_args)


def format_ratio(completed: int, total: int) -> str:
    if not total:
        return "0%"
    return f"{completed * 100 / total:.0f}%"


def get_selected_key() -> str | None:
    value = st.session_state.get("selected_entry_key")
    return str(value) if value else None


def inject_styles() -> None:
    st.markdown(APP_CSS, unsafe_allow_html=True)


def render_sidebar(
    summaries: list[dict[str, Any]],
    selected_category: str,
    metadata: dict[str, str],
    save_file: Path,
    sync_status: str,
) -> tuple[str, str, str]:
    summary_by_category = {row["category"]: row for row in summaries}
    overall_total = sum(int(row["total"]) for row in summaries)
    overall_completed = sum(int(row["completed"]) for row in summaries)
    st.sidebar.title("生存图鉴")
    st.sidebar.metric(
        "总体进度",
        f"{overall_completed}/{overall_total}",
    )
    st.sidebar.progress(
        min(1.0, overall_completed / overall_total) if overall_total else 0.0
    )
    st.sidebar.caption(f"完成率 {format_ratio(overall_completed, overall_total)}")
    st.sidebar.divider()

    labels = []
    for category in CATEGORY_ORDER:
        row = summary_by_category.get(category, {"completed": 0, "total": 0})
        labels.append(
            f"{CATEGORY_EMOJI[category]}  {CATEGORY_LABELS[category]}  "
            f"{row['completed']}/{row['total']}"
        )
    selected_label = st.sidebar.radio(
        "分类",
        labels,
        index=CATEGORY_ORDER.index(selected_category),
        label_visibility="collapsed",
    )
    selected_category = CATEGORY_ORDER[labels.index(selected_label)]

    st.sidebar.divider()
    st.sidebar.subheader("筛选")
    search = st.sidebar.text_input(
        "搜索条目",
        placeholder="名称、名称键或 ID",
        key="codex_search",
    )
    filter_label = st.sidebar.radio(
        "完成状态",
        ["全部", "已完成", "未完成"],
        horizontal=True,
        key="codex_completion_filter",
    )
    filter_value = {"全部": "all", "已完成": "completed", "未完成": "pending"}[filter_label]

    st.sidebar.divider()
    st.sidebar.caption(sync_status)
    with st.sidebar.expander("数据源", expanded=False):
        resource_version = metadata.get("game_version", "未知")
        source_path = metadata.get("save_path", str(save_file))
        st.markdown(
            f'<div class="data-source-label">游戏版本 {escape(resource_version)}</div>',
            unsafe_allow_html=True,
        )
        st.code(source_path, language="text")

    return selected_category, search, filter_value


def render_entry_row(entry: dict[str, Any]) -> None:
    entry_key = entry["entry_key"]
    completed = bool(entry["completed"])
    selected = entry_key == get_selected_key()
    status_class = "completed" if completed else "pending"
    status_label = "已解锁" if completed else "未解锁"
    source_label = f"{entry['source_table']} · ID {entry['source_id']}"
    with st.container(border=True):
        marker_column, content_column, status_column, action_column = st.columns(
            [0.18, 3.8, 1.05, 1.05],
            gap="small",
        )
        with marker_column:
            st.markdown(
                f'<div class="entry-row-marker {status_class}"></div>',
                unsafe_allow_html=True,
            )
        with content_column:
            st.markdown(
                f'<div class="entry-name">{escape(str(entry["name"]))}</div>'
                f'<div class="entry-meta">{escape(source_label)}</div>',
                unsafe_allow_html=True,
            )
        with status_column:
            st.markdown(
                f'<span class="status-pill {status_class}">{status_label}</span>',
                unsafe_allow_html=True,
            )
            if selected:
                st.caption("当前查看")
        with action_column:
            if st.button(
                "详情",
                key=f"detail:{entry_key}",
                use_container_width=True,
            ):
                st.session_state.selected_entry_key = entry_key
                st.rerun()


def render_entry_list(
    entries: list[dict[str, Any]],
) -> None:
    if not entries:
        st.info("没有符合条件的条目")
        return
    with st.container(height=680, border=False):
        for entry in entries:
            render_entry_row(entry)


def render_details(connection: Any, entry_key: str | None, category: str) -> None:
    st.subheader("条目详情")
    if not entry_key:
        st.info("选择一个条目查看详情")
        return
    entry = get_entry(connection, entry_key, category)
    if entry is None:
        st.warning("条目已不存在或尚未完成数据库刷新")
        return
    payload = json.loads(entry["raw_json"])
    st.markdown(f"### {entry['name']}")
    st.caption(f"{entry['source_table']} · ID {entry['source_id']}")
    if entry["description"]:
        st.write(entry["description"])
    status = "已完成" if entry["completed"] else "未完成"
    st.write(f"状态：**{status}**")

    relations = get_entry_relations(connection, entry_key)
    if relations:
        grouped: dict[str, list[str]] = {}
        for relation in relations:
            grouped.setdefault(relation["relation_type"], []).append(
                f"{relation['target_name']}（ID {relation['target_id']}）"
            )
        with st.expander("关联数据", expanded=True):
            for relation_type, values in grouped.items():
                st.markdown(f"**{relation_type}**：{'、'.join(values)}")

    with st.expander("配置字段", expanded=False):
        rows = []
        for field, value in payload.items():
            rows.append(
                {
                    "字段": FIELD_LABELS.get(field, field),
                    "原始字段": field,
                    "值": format_scalar(value),
                }
            )
        st.dataframe(rows, use_container_width=True, hide_index=True)


def render_page(database_path: Path, save_file: Path) -> None:
    try:
        connection = open_database(database_path)
    except Exception as exc:
        st.error(f"无法打开图鉴数据库：{exc}")
        st.code(
            f'python "图鉴数据库.py" --database "{database_path}"',
            language="powershell",
        )
        st.stop()

    try:
        try:
            sync_result = sync_game_completion(connection, save_file)
        except Exception as exc:
            sync_result = None
            st.error(f"图鉴存档同步失败：{exc}")

        metadata = get_metadata(connection)
        if sync_result is not None and sync_result.status == "error":
            st.warning(f"未能读取游戏图鉴存档：{sync_result.message}")
            sync_status = "存档同步未完成，请查看页面提示"
        elif sync_result is not None and sync_result.status == "fallback":
            st.warning(f"当前使用存档备份同步：{sync_result.message}")
            sync_status = "已使用存档备份"
        elif sync_result is None:
            sync_status = "存档同步失败，请查看页面提示"
        else:
            last_read = metadata.get("save_read_at", "未知")
            sync_status = f"存档已同步 · 最近读取 {last_read}"

        summaries = get_category_summaries(connection)
        selected_category = st.session_state.get("selected_category", "furniture")
        selected_category, search, filter_value = render_sidebar(
            summaries,
            selected_category,
            metadata,
            save_file,
            sync_status,
        )
        st.session_state.selected_category = selected_category

        summary_by_category = {row["category"]: row for row in summaries}
        current = summary_by_category[selected_category]
        query_signature = (selected_category, search.strip(), filter_value)
        if st.session_state.get("entry_query_signature") != query_signature:
            st.session_state.entry_query_signature = query_signature
            st.session_state.selected_entry_key = None
        entries = query_entries(
            connection,
            selected_category,
            search,
            filter_value,
            limit=None,
        )
        entry_keys = {entry["entry_key"] for entry in entries}
        if entries and get_selected_key() not in entry_keys:
            st.session_state.selected_entry_key = entries[0]["entry_key"]
        elif not entries:
            st.session_state.selected_entry_key = None

        grid_column, detail_column = st.columns([3, 2], gap="large")
        with grid_column:
            heading_column, summary_column = st.columns([3, 2], gap="small")
            with heading_column:
                st.subheader(f"{CATEGORY_EMOJI[selected_category]} {CATEGORY_LABELS[selected_category]}")
            with summary_column:
                st.markdown(
                    f'<div class="section-summary">已完成 {current["completed"]}/{current["total"]} · '
                    f'当前显示 {len(entries)} 条</div>',
                    unsafe_allow_html=True,
                )
            render_entry_list(entries)
        with detail_column:
            render_details(connection, get_selected_key(), selected_category)
    finally:
        connection.close()


def main() -> None:
    st.set_page_config(page_title="Survival Log 生存图鉴", layout="wide")
    inject_styles()
    args = parse_script_args()
    if hasattr(st, "fragment"):
        @st.fragment(run_every="5s")
        def render_live_page() -> None:
            render_page(args.database, args.save_file)

        render_live_page()
    else:
        render_page(args.database, args.save_file)


if __name__ == "__main__":
    main()
