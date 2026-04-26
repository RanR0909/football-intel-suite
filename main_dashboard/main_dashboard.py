#!/usr/bin/env python3
"""
INTEL-OPS 竞品情报总控面板
集成 [产品动态]、[排名变化]、[用户评论] 三大模块的统一数据看板。
"""

import json
import os
import subprocess
import sys
import concurrent.futures
from datetime import datetime
from pathlib import Path
from collections import Counter

import streamlit as st
import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
import urllib.request

# ---------------------------------------------------------------------------
# 路径自动定位
# ---------------------------------------------------------------------------

_SCRIPT_DIR = Path(__file__).resolve().parent
_PROJECT_ROOT = _SCRIPT_DIR.parent          # Football_Intel_Suite/
DATA_DIR = _PROJECT_ROOT / "data"           # 统一数据输出目录

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

SCRIPTS = {
    "competitor_comment": {
        "path": str(_PROJECT_ROOT / "competitor_comment" / "auto_report.py"),
        "cwd": str(_PROJECT_ROOT / "competitor_comment"),
        "output": DATA_DIR / "competitor_comments.json",
    },
    "strategy_monitor": {
        "path": str(_PROJECT_ROOT / "strategy_monitor" / "run_headless.py"),
        "cwd": str(_PROJECT_ROOT / "strategy_monitor"),
        "output": DATA_DIR / "strategy_monitor.json",
    },
    "market_rank": {
        "path": str(_PROJECT_ROOT / "market_rank" / "run_headless.py"),
        "cwd": str(_PROJECT_ROOT / "market_rank"),
        "output": DATA_DIR / "market_rank.json",
    },
}

# ---------------------------------------------------------------------------
# Page Config & Custom CSS — INTEL-OPS Dark Theme
# ---------------------------------------------------------------------------

st.set_page_config(
    page_title="INTEL-OPS 竞品情报总控",
    layout="wide",
    initial_sidebar_state="expanded",
)

CUSTOM_CSS = """
<style>
    /* Base dark theme */
    .stApp {
        background-color: #0e1117;
    }
    .main > div {
        background-color: #0e1117;
    }
    /* Sidebar */
    section[data-testid="stSidebar"] {
        background-color: #161a22;
        border-right: 1px solid #2a2f3a;
    }
    section[data-testid="stSidebar"] .stMarkdown h1,
    section[data-testid="stSidebar"] .stMarkdown h2,
    section[data-testid="stSidebar"] .stMarkdown h3 {
        color: #e0e0e0;
    }
    /* Cards */
    div[data-testid="stMetric"] {
        background-color: #1e2330;
        border: 1px solid #2a2f3a;
        border-radius: 8px;
        padding: 16px;
        box-shadow: 0 2px 8px rgba(0,0,0,0.3);
    }
    div[data-testid="stMetric"] label {
        color: #8892a4 !important;
        font-size: 13px !important;
        font-weight: 500 !important;
        text-transform: uppercase;
        letter-spacing: 0.5px;
    }
    div[data-testid="stMetric"] div[data-testid="stMetricValue"] {
        color: #f0f0f0 !important;
        font-size: 28px !important;
        font-weight: 700 !important;
    }
    div[data-testid="stMetric"] div[data-testid="stMetricDelta"] {
        font-size: 14px !important;
    }
    /* Containers */
    .stContainer {
        background-color: #1e2330;
        border: 1px solid #2a2f3a;
        border-radius: 8px;
        padding: 20px;
        margin-bottom: 16px;
    }
    div[data-testid="stVerticalBlock"] > div[data-testid="stVerticalBlock"] > div[data-testid="element-container"] > div.stContainer {
        background-color: #1e2330;
        border: 1px solid #2a2f3a;
        border-radius: 8px;
        padding: 20px;
    }
    /* Headers */
    h1, h2, h3, h4, h5, h6 {
        color: #e8eaed !important;
    }
    h1 {
        font-weight: 700;
        letter-spacing: 1px;
    }
    h2 {
        font-weight: 600;
        border-bottom: 1px solid #2a2f3a;
        padding-bottom: 8px;
        margin-bottom: 16px;
    }
    h3 {
        font-weight: 500;
        color: #b0b8c8 !important;
    }
    /* Text */
    p, li, .stMarkdown {
        color: #c8ccd4;
    }
    /* Dataframe */
    .stDataFrame {
        background-color: #1e2330;
    }
    .stDataFrame table {
        background-color: #1e2330;
    }
    .stDataFrame th {
        background-color: #252b3a !important;
        color: #8892a4 !important;
        font-weight: 500 !important;
    }
    .stDataFrame td {
        color: #c8ccd4 !important;
    }
    /* Tabs */
    .stTabs [data-baseweb="tab-list"] {
        background-color: #161a22;
        border-bottom: 1px solid #2a2f3a;
    }
    .stTabs [data-baseweb="tab"] {
        color: #8892a4;
    }
    .stTabs [aria-selected="true"] {
        color: #f0f0f0 !important;
        border-bottom-color: #4a9eff !important;
    }
    /* Feed items */
    .feed-item {
        background-color: #1e2330;
        border-left: 3px solid #4a9eff;
        border-radius: 4px;
        padding: 12px 16px;
        margin-bottom: 8px;
    }
    .feed-item .feed-tag {
        display: inline-block;
        background-color: #2a3a5c;
        color: #7ab7ff;
        font-size: 11px;
        padding: 2px 8px;
        border-radius: 3px;
        margin-right: 8px;
        font-weight: 600;
    }
    .feed-item .feed-time {
        color: #6b7280;
        font-size: 12px;
    }
    .feed-item .feed-title {
        color: #e0e0e0;
        font-weight: 600;
        margin: 4px 0;
    }
    .feed-item .feed-desc {
        color: #9ca3af;
        font-size: 13px;
    }
    /* Warning / Info boxes */
    .stAlert {
        background-color: #1e2330 !important;
        border: 1px solid #2a2f3a !important;
        color: #c8ccd4 !important;
    }
    /* Sidebar nav */
    .sidebar-nav {
        padding: 8px 0;
    }
    .sidebar-nav-item {
        padding: 10px 16px;
        margin: 2px 0;
        border-radius: 6px;
        cursor: pointer;
        color: #8892a4;
        font-size: 14px;
        font-weight: 500;
        transition: all 0.2s;
    }
    .sidebar-nav-item:hover {
        background-color: #252b3a;
        color: #e0e0e0;
    }
    .sidebar-nav-item.active {
        background-color: #2a3a5c;
        color: #7ab7ff;
        border-left: 3px solid #4a9eff;
    }
    /* Divider */
    hr {
        border-color: #2a2f3a !important;
    }
    /* Expander */
    .streamlit-expanderHeader {
        color: #b0b8c8 !important;
        background-color: #1e2330 !important;
    }
    .streamlit-expanderContent {
        background-color: #1e2330 !important;
    }
    /* Button */
    .stButton button {
        background-color: #2a3a5c !important;
        color: #e0e0e0 !important;
        border: 1px solid #3a4a6c !important;
        border-radius: 6px !important;
    }
    .stButton button:hover {
        background-color: #3a4a6c !important;
    }
    /* Selectbox */
    div[data-baseweb="select"] {
        background-color: #1e2330 !important;
    }
    div[data-baseweb="select"] div {
        background-color: #1e2330 !important;
        color: #c8ccd4 !important;
    }
</style>
"""

st.markdown(CUSTOM_CSS, unsafe_allow_html=True)

# ---------------------------------------------------------------------------
# Sidebar Navigation
# ---------------------------------------------------------------------------

st.sidebar.markdown(
    """
    <div style="padding: 16px 0; border-bottom: 1px solid #2a2f3a; margin-bottom: 16px;">
        <h1 style="font-size: 22px; font-weight: 700; letter-spacing: 2px; color: #e0e0e0; margin: 0;">
            INTEL-OPS
        </h1>
        <p style="font-size: 11px; color: #6b7280; margin: 4px 0 0 0; letter-spacing: 1px;">
            COMPETITIVE INTELLIGENCE PLATFORM
        </p>
    </div>
    """,
    unsafe_allow_html=True,
)

# Link to new HTML dashboard
st.sidebar.markdown(
    f"""
    <div style="margin-bottom: 16px; padding: 0 4px;">
        <a href="dashboard.html" target="_blank" style="display: flex; align-items: center; gap: 8px; padding: 8px 12px; background-color: #1e2330; border: 1px solid #2a2f3a; border-radius: 8px; text-decoration: none; color: #7ab7ff; font-size: 13px; font-weight: 500; transition: all 0.2s;">
            <span style="font-size: 16px;">️</span>
            <span>打开新版 HTML 看板</span>
            <span style="margin-left: auto; font-size: 11px; color: #6b7280;">↗</span>
        </a>
    </div>
    """,
    unsafe_allow_html=True,
)


nav_options = ["[总览看板]", "[产品动态]", "[排名变化]", "[用户评论]"]
nav_icons = ["01", "02", "03", "04"]

# Use radio for navigation
nav_choice = st.sidebar.radio(
    "导航模块",
    nav_options,
    label_visibility="collapsed",
    index=0,
)

st.sidebar.markdown(
    f"""
    <div style="margin-top: 32px; padding: 12px; background-color: #1e2330; border-radius: 6px; border: 1px solid #2a2f3a;">
        <p style="font-size: 11px; color: #6b7280; margin: 0; letter-spacing: 0.5px;">
            数据更新时间
        </p>
        <p style="font-size: 13px; color: #9ca3af; margin: 4px 0 0 0;">
            {datetime.now().strftime('%Y-%m-%d %H:%M')}
        </p>
    </div>
    """,
    unsafe_allow_html=True,
)

# Claude API Key input in sidebar (password field, no hardcoded default)
st.sidebar.markdown("<br>", unsafe_allow_html=True)
claude_api_key = st.sidebar.text_input(
    "Claude API Key",
    type="password",
    help="从 https://ai.flashapi.top 获取 Claude API 密钥",
    key="claude_api_key_global",
)

# Sync button in sidebar
sync_clicked = st.sidebar.button("同步所有数据", type="primary", use_container_width=True)

# ---------------------------------------------------------------------------
# Data Sync Functions
# ---------------------------------------------------------------------------


def _run_single_script(module_name: str, config: dict) -> tuple:
    """Run a single script and return (module_name, status_dict)."""
    script_path = config["path"]
    cwd = config.get("cwd", os.path.dirname(script_path))
    try:
        result = subprocess.run(
            [sys.executable, script_path],
            capture_output=True,
            text=True,
            timeout=300,
            cwd=cwd,
        )
        if result.returncode == 0:
            return (module_name, {
                "success": True,
                "stdout": result.stdout[-300:] if result.stdout else "",
            })
        else:
            return (module_name, {
                "success": False,
                "stderr": result.stderr[-300:] if result.stderr else "未知错误",
            })
    except subprocess.TimeoutExpired:
        return (module_name, {"success": False, "stderr": "执行超时"})
    except Exception as e:
        return (module_name, {"success": False, "stderr": str(e)})


def sync_all_data() -> dict:
    """Run all three sub-scripts in parallel via subprocess and return status."""
    status = {}
    status_placeholder = st.empty()
    status_placeholder.info("正在并行同步数据...")

    with concurrent.futures.ThreadPoolExecutor(max_workers=3) as executor:
        futures = {
            executor.submit(_run_single_script, name, config): name
            for name, config in SCRIPTS.items()
        }
        completed = 0
        progress_bar = st.progress(0, text="正在同步数据...")

        for future in concurrent.futures.as_completed(futures):
            module_name, result = future.result()
            status[module_name] = result
            completed += 1
            progress_bar.progress(completed / len(SCRIPTS))

            if result["success"]:
                status_placeholder.success(f"[{module_name}] 执行成功")
            else:
                err_msg = result.get("stderr", "未知错误")[:200]
                status_placeholder.error(f"[{module_name}] 执行失败: {err_msg}")

    progress_bar.empty()
    status_placeholder.empty()
    return status


def load_json_data(filename: str) -> dict:
    """Load a JSON file from root /data/."""
    filepath = DATA_DIR / filename
    if not filepath.exists():
        return {}
    try:
        with open(filepath, "r", encoding="utf-8") as f:
            return json.load(f)
    except (json.JSONDecodeError, Exception):
        return {}


# ---------------------------------------------------------------------------
# Data Loading
# ---------------------------------------------------------------------------

if sync_clicked:
    # 检查 API Key 是否已配置
    if not claude_api_key:
        st.sidebar.error("请先配置 API Key。提示：您可以从 https://ai.flashapi.top 获取 Claude API 密钥。")
    else:
        # 将 API Key 注入环境变量，供子进程使用
        os.environ["CLAUDE_API_KEY"] = claude_api_key
        sync_status = sync_all_data()
        if all(s.get("success") for s in sync_status.values()):
            st.sidebar.success("所有数据同步完成")
        else:
            st.sidebar.warning("部分数据同步失败，请检查日志")

# Load all data
strategy_data = load_json_data("strategy_monitor.json")
market_data = load_json_data("market_rank.json")
comment_data = load_json_data("competitor_comments.json")

# ---------------------------------------------------------------------------
# Helper: Compute summary metrics
# ---------------------------------------------------------------------------


def compute_metrics():
    """Compute top-level KPI metrics from loaded data."""
    # [产品动态] changes count
    strategy_changes = strategy_data.get("changes_detected", 0) if strategy_data else 0

    # [排名变化] max rank improvement
    max_rank_delta = 0
    if market_data:
        perf = market_data.get("competitor_performance", {})
        for comp_name, info in perf.items():
            delta = info.get("delta")
            if delta is not None and delta > max_rank_delta:
                max_rank_delta = delta

    # [用户评论] total low-star reviews
    total_negative = 0
    if comment_data:
        for comp_name, comp_info in comment_data.get("competitors", {}).items():
            for region, region_data in comp_info.get("regions", {}).items():
                total_negative += region_data.get("negative_count", region_data.get("count", 0))

    return {
        "strategy_changes": strategy_changes,
        "max_rank_delta": max_rank_delta,
        "total_negative": total_negative,
    }


metrics = compute_metrics()

# ===========================================================================
# PAGE: [总览看板]
# ===========================================================================

if nav_choice == "[总览看板]":

    st.markdown(
        """
        <h1 style="font-size: 28px; margin-bottom: 4px;">INTEL-OPS 竞品情报总控</h1>
        <p style="color: #6b7280; font-size: 13px; margin-bottom: 24px;">
            集成 [产品动态] [排名变化] [用户评论] 三大模块的统一情报看板
        </p>
        """,
        unsafe_allow_html=True,
    )

    # -- Top KPI Cards --
    col1, col2, col3, col4 = st.columns(4)

    with col1:
        st.metric(
            label="最近检测变动数",
            value=metrics["strategy_changes"],
            delta=None,
        )

    with col2:
        st.metric(
            label="最大排名升幅",
            value=f"+{metrics['max_rank_delta']}" if metrics['max_rank_delta'] > 0 else "0",
            delta=None,
        )

    with col3:
        st.metric(
            label="低星评论汇总",
            value=metrics["total_negative"],
            delta=None,
        )

    with col4:
        monitored_count = strategy_data.get("total_monitored", 0) if strategy_data else 0
        st.metric(
            label="监控竞品总数",
            value=monitored_count,
            delta=None,
        )

    st.markdown("<br>", unsafe_allow_html=True)

    # -- Two-column layout for main content --
    left_col, right_col = st.columns([3, 2])

    with left_col:
        st.markdown("### [最新动态] Feed 流")

        # Collect feed items from strategy_monitor
        feed_items = []
        if strategy_data:
            for comp_name, comp_info in strategy_data.get("competitors", {}).items():
                if "error" in comp_info:
                    continue
                if comp_info.get("has_changed"):
                    for change in comp_info.get("changes", []):
                        feed_items.append({
                            "competitor": comp_name,
                            "change": change,
                            "version": comp_info.get("version", ""),
                            "has_analysis": "analysis" in comp_info,
                        })
                elif comp_info.get("is_first_record"):
                    feed_items.append({
                        "competitor": comp_name,
                        "change": f"[首次记录] 版本 {comp_info.get('version', '未知')}",
                        "version": comp_info.get("version", ""),
                        "has_analysis": False,
                    })

        # Also add market rank alerts as feed items (unified ranking changes)
        if market_data:
            for contender in market_data.get("new_contenders", []):
                delta = contender.get("delta", 0)
                feed_items.append({
                    "competitor": contender.get("name", "Unknown"),
                    "change": f"[排名上升] 7天内上升 {delta} 位至 #{contender.get('rank', '?')}",
                    "version": "",
                    "has_analysis": False,
                })
            for mover in market_data.get("fast_movers", []):
                feed_items.append({
                    "competitor": mover.get("name", "Unknown"),
                    "change": f"[排名上升] 24h内上升 {mover.get('delta', 0)} 位至 #{mover.get('rank', '?')}",
                    "version": "",
                    "has_analysis": False,
                })

        if feed_items:
            for item in feed_items:
                change_text = item["change"]
                tag = "[产品迭代]"
                if "商业化" in change_text:
                    tag = "[商业化更新]"
                elif "首次记录" in change_text:
                    tag = "[首次记录]"
                elif "排名上升" in change_text:
                    tag = "[排名上升]"

                st.markdown(
                    f"""
                    <div class="feed-item">
                        <span class="feed-tag">{tag}</span>
                        <span class="feed-time">{item['competitor']}</span>
                        <div class="feed-title">{change_text}</div>
                        <div class="feed-desc">版本 {item['version'] if item['version'] else 'N/A'}</div>
                    </div>
                    """,
                    unsafe_allow_html=True,
                )
        else:
            st.info("[提示] 暂无最新动态，请点击侧边栏 [同步所有数据] 按钮获取最新情报。")

    with right_col:
        st.markdown("### [用户情感评分]")

        # Build sentiment comparison chart from comment data
        sentiment_data = []
        if comment_data:
            for comp_name, comp_info in comment_data.get("competitors", {}).items():
                total_reviews = 0
                label_counts = Counter()
                for region, region_data in comp_info.get("regions", {}).items():
                    total_reviews += region_data.get("count", 0)
                    for label, count in region_data.get("labels", {}).items():
                        label_counts[label] += count

                if total_reviews > 0:
                    for label, count in label_counts.items():
                        sentiment_data.append({
                            "竞品": comp_name,
                            "类别": label,
                            "数量": count,
                        })

        if sentiment_data:
            df_sentiment = pd.DataFrame(sentiment_data)
            fig = px.bar(
                df_sentiment,
                x="竞品",
                y="数量",
                color="类别",
                barmode="group",
                color_discrete_sequence=px.colors.qualitative.Set2,
                height=300,
            )
            fig.update_layout(
                plot_bgcolor="#1e2330",
                paper_bgcolor="#1e2330",
                font_color="#c8ccd4",
                legend=dict(
                    orientation="h",
                    yanchor="bottom",
                    y=1.02,
                    xanchor="right",
                    x=1,
                    font=dict(size=10),
                ),
                margin=dict(l=10, r=10, t=10, b=10),
            )
            fig.update_xaxes(gridcolor="#2a2f3a", tickfont=dict(size=10))
            fig.update_yaxes(gridcolor="#2a2f3a", tickfont=dict(size=10))
            st.plotly_chart(fig, use_container_width=True, key="sentiment_chart")
        else:
            st.info("[提示] 暂无评论数据，请同步后查看。")

        st.markdown("<br>", unsafe_allow_html=True)
        st.markdown("### [高频需求词云]")

        # Extract high-frequency keywords from negative reviews
        keyword_data = Counter()
        if comment_data:
            for comp_name, comp_info in comment_data.get("competitors", {}).items():
                for region, region_data in comp_info.get("regions", {}).items():
                    for review in region_data.get("reviews", []):
                        content = review.get("content", "")
                        label = review.get("label", "")
                        # Focus on signal-heavy reviews
                        if "[高价值功能请求]" in label or "[问题抱怨]" in label:
                            # Simple keyword extraction: look for common patterns
                            keywords = [
                                "score", "data", "update", "live", "match",
                                "feature", "bug", "crash", "slow", "ads",
                                "notification", "league", "player", "team",
                                "bracket", "playoff", "series", "error",
                                "loading", "version", "missing", "remove",
                                "broken", "fix", "issue", "problem",
                            ]
                            content_lower = content.lower()
                            for kw in keywords:
                                if kw in content_lower:
                                    keyword_data[kw] += 1

        if keyword_data:
            # Create a simple horizontal bar chart for top keywords
            top_keywords = keyword_data.most_common(15)
            df_kw = pd.DataFrame(top_keywords, columns=["关键词", "频次"])

            fig_kw = go.Figure(go.Bar(
                x=df_kw["频次"],
                y=df_kw["关键词"],
                orientation="h",
                marker=dict(
                    color=df_kw["频次"],
                    colorscale="Blues",
                    reversescale=False,
                ),
            ))
            fig_kw.update_layout(
                plot_bgcolor="#1e2330",
                paper_bgcolor="#1e2330",
                font_color="#c8ccd4",
                height=350,
                margin=dict(l=10, r=10, t=10, b=10),
                xaxis=dict(gridcolor="#2a2f3a", tickfont=dict(size=10)),
                yaxis=dict(tickfont=dict(size=11)),
            )
            st.plotly_chart(fig_kw, use_container_width=True, key="keyword_chart")
        else:
            st.info("[提示] 暂无功能缺陷关键词数据，请同步后查看。")

# ===========================================================================
# PAGE: [产品动态]
# ===========================================================================

elif nav_choice == "[产品动态]":

    st.markdown(
        """
        <h1 style="font-size: 24px; margin-bottom: 4px;">[产品动态]</h1>
        <p style="color: #6b7280; font-size: 13px; margin-bottom: 24px;">
            竞品版本迭代与商业化变动监控
        </p>
        """,
        unsafe_allow_html=True,
    )

    if not strategy_data:
        st.info("[提示] 暂无策略监控数据，请点击侧边栏 [同步所有数据] 按钮获取最新情报。")
    else:
        competitors = strategy_data.get("competitors", {})

        # Summary cards
        total = strategy_data.get("total_monitored", 0)
        changed = strategy_data.get("changes_detected", 0)
        col1, col2, col3 = st.columns(3)
        with col1:
            st.metric("监控竞品数", total)
        with col2:
            st.metric("检测到变动", changed)
        with col3:
            stable = total - changed
            st.metric("状态稳定", stable)

        st.markdown("<br>", unsafe_allow_html=True)

        # Detail cards for each competitor
        for comp_name, comp_info in competitors.items():
            if "error" in comp_info:
                with st.container():
                    st.markdown(
                        f"""
                        <div style="background-color: #1e2330; border: 1px solid #2a2f3a; border-radius: 8px; padding: 16px; margin-bottom: 12px;">
                            <h3 style="margin: 0 0 8px 0;">{comp_name}</h3>
                            <p style="color: #ef4444; font-size: 13px;">抓取失败: {comp_info['error']}</p>
                        </div>
                        """,
                        unsafe_allow_html=True,
                    )
                continue

            has_changed = comp_info.get("has_changed", False)
            is_first = comp_info.get("is_first_record", False)
            version = comp_info.get("version", "N/A")
            changes = comp_info.get("changes", [])
            release_notes = comp_info.get("release_notes", "")
            analysis = comp_info.get("analysis", "")

            border_color = "#4a9eff" if has_changed else "#2a2f3a"
            status_icon = "[变动]" if has_changed else "[稳定]"

            with st.container():
                st.markdown(
                    f"""
                    <div style="background-color: #1e2330; border: 1px solid {border_color}; border-radius: 8px; padding: 16px; margin-bottom: 12px;">
                        <div style="display: flex; justify-content: space-between; align-items: center;">
                            <h3 style="margin: 0;">{comp_name}</h3>
                            <span style="font-size: 12px; color: {'#7ab7ff' if has_changed else '#6b7280'}; background-color: #252b3a; padding: 2px 10px; border-radius: 4px;">
                                {status_icon} v{version}
                            </span>
                        </div>
                    </div>
                    """,
                    unsafe_allow_html=True,
                )

                if changes:
                    for change in changes:
                        st.markdown(f"- {change}")

                if release_notes:
                    with st.expander("更新日志"):
                        st.markdown(release_notes[:500] + ("..." if len(release_notes) > 500 else ""))

                if analysis:
                    with st.expander("AI 策略分析"):
                        st.markdown(analysis)

# ===========================================================================
# PAGE: [排名变化]
# ===========================================================================

elif nav_choice == "[排名变化]":

    st.markdown(
        """
        <h1 style="font-size: 24px; margin-bottom: 4px;">[排名变化]</h1>
        <p style="color: #6b7280; font-size: 13px; margin-bottom: 24px;">
            App Store 体育分类 Top 100 排名追踪
        </p>
        """,
        unsafe_allow_html=True,
    )

    if not market_data:
        st.info("[提示] 暂无排名数据，请点击侧边栏 [同步所有数据] 按钮获取最新情报。")
    else:
        # Competitor performance metrics
        perf = market_data.get("competitor_performance", {})
        if perf:
            st.markdown("### 核心竞品排名")
            cols = st.columns(len(perf))
            for idx, (comp_name, info) in enumerate(perf.items()):
                with cols[idx]:
                    rank = info.get("rank")
                    delta = info.get("delta")
                    delta_str = None
                    if delta is not None:
                        if delta > 0:
                            delta_str = f"+{delta}"
                        elif delta < 0:
                            delta_str = str(delta)
                        else:
                            delta_str = "0"

                    st.metric(
                        label=comp_name,
                        value=f"#{rank}" if rank else "N/A",
                        delta=delta_str,
                    )

        st.markdown("<br>", unsafe_allow_html=True)

        # New contenders
        contenders = market_data.get("new_contenders", [])
        if contenders:
            st.markdown("### [新晋竞争者]")
            contender_df = pd.DataFrame(contenders)
            st.dataframe(contender_df, hide_index=True, use_container_width=True)

        # Fast movers
        movers = market_data.get("fast_movers", [])
        if movers:
            st.markdown("### [快速上升应用]")
            mover_df = pd.DataFrame(movers)
            st.dataframe(mover_df, hide_index=True, use_container_width=True)

        # AI Brief
        ai_brief = market_data.get("ai_brief")
        if ai_brief:
            st.markdown("### AI 市场简报")
            st.markdown(
                f"""
                <div style="background-color: #1e2330; border: 1px solid #2a2f3a; border-left: 3px solid #4a9eff; border-radius: 8px; padding: 16px; margin-bottom: 16px;">
                    <p style="color: #c8ccd4; font-size: 14px; line-height: 1.6; white-space: pre-wrap;">{ai_brief}</p>
                </div>
                """,
                unsafe_allow_html=True,
            )

        # Full leaderboard
        leaderboard = market_data.get("leaderboard", [])
        if leaderboard:
            st.markdown("### 完整排行榜")
            lb_df = pd.DataFrame(leaderboard)
            # Rename columns for display
            lb_display = lb_df.rename(columns={
                "rank": "排名",
                "name": "应用名称",
                "delta": "排名变化",
                "is_known": "已知竞品",
            })
            lb_display["排名变化"] = lb_display["排名变化"].apply(
                lambda x: f"+{x}" if x and x > 0 else (str(x) if x and x < 0 else "0" if x == 0 else "N/A")
            )
            lb_display["已知竞品"] = lb_display["已知竞品"].apply(
                lambda x: "是" if x else ""
            )
            st.dataframe(
                lb_display[["排名", "应用名称", "排名变化", "已知竞品"]],
                hide_index=True,
                use_container_width=True,
            )

# ===========================================================================
# PAGE: [用户评论]
# ===========================================================================

elif nav_choice == "[用户评论]":

    st.markdown(
        """
        <h1 style="font-size: 24px; margin-bottom: 4px;">[用户评论]</h1>
        <p style="color: #6b7280; font-size: 13px; margin-bottom: 24px;">
            竞品用户评论分析与情感追踪
        </p>
        """,
        unsafe_allow_html=True,
    )

    if not comment_data:
        st.info("[提示] 暂无评论数据，请点击侧边栏 [同步所有数据] 按钮获取最新情报。")
    else:
        competitors = comment_data.get("competitors", {})

        # Summary
        total_all = sum(
            region_data.get("count", 0)
            for comp_info in competitors.values()
            for region_data in comp_info.get("regions", {}).values()
        )
        st.metric("总评论数", total_all)

        st.markdown("<br>", unsafe_allow_html=True)

        # Per-competitor breakdown
        for comp_name, comp_info in competitors.items():
            regions = comp_info.get("regions", {})
            has_data = any(r.get("count", 0) > 0 for r in regions.values())

            with st.container():
                st.markdown(
                    f"""
                    <div style="background-color: #1e2330; border: 1px solid #2a2f3a; border-radius: 8px; padding: 16px; margin-bottom: 12px;">
                        <h3 style="margin: 0 0 12px 0;">{comp_name}</h3>
                    </div>
                    """,
                    unsafe_allow_html=True,
                )

                if not has_data:
                    st.caption("当前无评论数据。")
                    continue

                # Region tabs
                region_tabs = st.tabs([r.upper() for r in regions.keys() if regions[r].get("count", 0) > 0])

                tab_idx = 0
                for region_code, region_data in regions.items():
                    if region_data.get("count", 0) == 0:
                        continue

                    with region_tabs[tab_idx]:
                        count = region_data.get("count", 0)
                        labels = region_data.get("labels", {})
                        summary = region_data.get("summary", "")

                        st.caption(f"评论数: {count}")

                        # Label distribution bar chart
                        if labels:
                            df_labels = pd.DataFrame(
                                list(labels.items()),
                                columns=["类别", "数量"],
                            )
                            fig = px.bar(
                                df_labels,
                                x="类别",
                                y="数量",
                                color="类别",
                                color_discrete_sequence=px.colors.qualitative.Set2,
                                height=200,
                            )
                            fig.update_layout(
                                plot_bgcolor="#1e2330",
                                paper_bgcolor="#1e2330",
                                font_color="#c8ccd4",
                                showlegend=False,
                                margin=dict(l=10, r=10, t=10, b=10),
                            )
                            fig.update_xaxes(gridcolor="#2a2f3a")
                            fig.update_yaxes(gridcolor="#2a2f3a")
                            st.plotly_chart(fig, use_container_width=True, key=f"label_chart_{comp_name}_{region_code}")

                        # Summary text
                        if summary:
                            with st.expander("分析报告"):
                                st.markdown(summary)

                        # Raw reviews
                        reviews = region_data.get("reviews", [])
                        if reviews:
                            with st.expander(f"原始评论 ({len(reviews)} 条)"):
                                review_df = pd.DataFrame(reviews)
                                st.dataframe(review_df, hide_index=True, use_container_width=True)

                    tab_idx += 1
