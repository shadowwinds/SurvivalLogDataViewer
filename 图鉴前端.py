#!/usr/bin/env python3
"""Streamlit frontend for the offline Survival Log codex database."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

import streamlit as st

from 图鉴数据库 import (
    CATEGORY_LABELS,
    CATEGORY_ORDER,
    count_entries,
    get_category_summaries,
    get_entry,
    get_entry_relations,
    get_metadata,
    get_overall_summary,
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


def render_sidebar(
    summaries: list[dict[str, Any]],
    selected_category: str,
) -> str:
    summary_by_category = {row["category"]: row for row in summaries}
    overall_total = sum(int(row["total"]) for row in summaries)
    overall_completed = sum(int(row["completed"]) for row in summaries)
    st.sidebar.title("生存图鉴")
    st.sidebar.metric(
        "总体进度",
        f"{overall_completed}/{overall_total}",
        format_ratio(overall_completed, overall_total),
    )
    st.sidebar.progress(
        min(1.0, overall_completed / overall_total) if overall_total else 0.0
    )
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
    return CATEGORY_ORDER[labels.index(selected_label)]


def render_entry_card(entry: dict[str, Any], column: Any) -> None:
    entry_key = entry["entry_key"]
    with column.container(border=True):
        st.markdown(f"**{entry['name']}**")
        st.caption(f"ID {entry['source_id']}")
        st.checkbox(
            "已解锁",
            value=bool(entry["completed"]),
            key=f"game-completion:{entry_key}:{int(bool(entry['completed']))}",
            disabled=True,
            label_visibility="collapsed",
        )
        st.caption("游戏存档：已解锁" if entry["completed"] else "游戏存档：未解锁")
        if st.button("查看详情", key=f"detail:{entry_key}", use_container_width=True):
            st.session_state.selected_entry_key = entry_key
            st.rerun()


def render_grid(
    entries: list[dict[str, Any]],
    category: str,
    page: int,
    page_count: int,
) -> None:
    st.subheader(f"{CATEGORY_EMOJI[category]} {CATEGORY_LABELS[category]}")
    if not entries:
        st.info("没有符合条件的条目")
        return
    columns = st.columns(4, gap="small")
    for index, entry in enumerate(entries):
        render_entry_card(entry, columns[index % len(columns)])
    if page_count > 1:
        new_page = st.number_input(
            "页码",
            min_value=1,
            max_value=page_count,
            value=page,
            step=1,
            key=f"page:{category}",
        )
        if int(new_page) != page:
            st.session_state[f"page_value:{category}"] = int(new_page)
            st.rerun()
        st.caption(f"第 {page} / {page_count} 页")


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
    st.markdown(f"## {entry['name']}")
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
        elif sync_result is not None and sync_result.status == "fallback":
            st.warning(f"当前使用存档备份同步：{sync_result.message}")
        else:
            source_path = metadata.get("save_path", str(save_file))
            last_read = metadata.get("save_read_at", "未知")
            st.caption(f"游戏存档已同步：`{source_path}` · 最近读取 {last_read}")

        summaries = get_category_summaries(connection)
        overall = get_overall_summary(connection)
        selected_category = st.session_state.get("selected_category", "furniture")
        selected_category = render_sidebar(summaries, selected_category)
        st.session_state.selected_category = selected_category

        summary_by_category = {row["category"]: row for row in summaries}
        current = summary_by_category[selected_category]
        st.title("生存图鉴")
        st.caption(
            f"游戏版本 {metadata.get('game_version', '未知')} · "
            f"当前完成 {current['completed']}/{current['total']} · "
            f"总体 {overall['completed']}/{overall['total']}"
        )

        toolbar_left, toolbar_right = st.columns([3, 2])
        with toolbar_left:
            search = st.text_input("搜索条目", placeholder="名称、名称键或 ID")
        with toolbar_right:
            filter_label = st.radio(
                "完成状态",
                ["全部", "已完成", "未完成"],
                horizontal=True,
                label_visibility="collapsed",
            )
        filter_value = {"全部": "all", "已完成": "completed", "未完成": "pending"}[filter_label]
        page_size = st.select_slider("每页条目", options=[12, 24, 48], value=24)
        if st.session_state.get("detail_category") != selected_category:
            st.session_state.selected_entry_key = None
            st.session_state.detail_category = selected_category
        total = count_entries(connection, selected_category, search, filter_value)
        page_count = max(1, (total + page_size - 1) // page_size)
        page_key = f"page_value:{selected_category}"
        page = min(int(st.session_state.get(page_key, 1)), page_count)
        st.session_state[page_key] = page
        entries = query_entries(
            connection,
            selected_category,
            search,
            filter_value,
            limit=page_size,
            offset=(page - 1) * page_size,
        )
        if entries and not get_selected_key():
            st.session_state.selected_entry_key = entries[0]["entry_key"]

        grid_column, detail_column = st.columns([3, 2], gap="large")
        with grid_column:
            render_grid(entries, selected_category, page, page_count)
        with detail_column:
            render_details(connection, get_selected_key(), selected_category)
    finally:
        connection.close()


def main() -> None:
    st.set_page_config(page_title="Survival Log 生存图鉴", layout="wide")
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
