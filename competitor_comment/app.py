import os
import json
import urllib.request
import ssl
import streamlit as st
import pandas as pd
import sys
from pathlib import Path
from collections import Counter

PROJECT_ROOT = Path(__file__).resolve().parent.parent
DATA_FILE = PROJECT_ROOT / "data" / "competitor_comments.json"
sys.path.insert(0, str(PROJECT_ROOT))

from competitors import get_comment_competitors
from regions import load_regions

COMPETITORS = dict(get_comment_competitors())
REGION_CONFIG = load_regions()
REGIONS = {info["label"]: code for code, info in REGION_CONFIG.items()}

st.set_page_config(page_title="竞品用户评论检查", layout="wide")
st.title("竞品用户评论检查")


def call_claude(prompt, api_key, max_tokens=4096):
    data = json.dumps({
        "model": "claude-haiku-4-5-20251001",
        "max_tokens": max_tokens,
        "messages": [{"role": "user", "content": prompt}]
    }).encode("utf-8")
    req = urllib.request.Request(
        "https://ai.flashapi.top/v1/messages",
        data=data,
        headers={
            "Content-Type": "application/json",
            "x-api-key": api_key,
            "anthropic-version": "2023-06-01",
        }
    )
    ctx = ssl.create_default_context()
    ctx.check_hostname = False
    ctx.verify_mode = ssl.CERT_NONE
    with urllib.request.urlopen(req, timeout=60, context=ctx) as resp:
        result = json.loads(resp.read())
    return result["content"][0]["text"]


def generate_report(reviews, app_name, region, api_key):
    from prompts.comment_prompts import build_daily_summary_prompt
    competitors = list(COMPETITORS.keys())
    prompt = build_daily_summary_prompt(app_name, region, 3, reviews, competitors)
    return call_claude(prompt, api_key)


# ── 侧边栏 ────────────────────────────────────────────────────
with st.sidebar:
    st.header("配置")
    api_key = st.text_input("Claude API Key", type="password",
                            help="从 https://ai.flashapi.top 获取 Claude API 密钥")
    st.divider()
    st.subheader("同步评论数据")
    st.caption("抓取过去 3 天全量评论并打标，写入 data/competitor_comments.json")
    sync_btn = st.button("同步数据", type="primary")

if sync_btn:
    if not api_key:
        st.sidebar.error("请先填写 Claude API Key")
    else:
        os.environ["CLAUDE_API_KEY"] = api_key
        import auto_report
        with st.sidebar.status("同步中...", expanded=True) as status:
            try:
                auto_report.main()
                status.update(label="同步完成", state="complete")
            except Exception as e:
                status.update(label=f"同步失败: {e}", state="error")

# ── 主面板：读取已同步数据，按需生成报告 ──────────────────────
if not DATA_FILE.exists():
    st.info("尚无数据，请先点击侧边栏「同步数据」。")
    st.stop()

with open(DATA_FILE, encoding="utf-8") as f:
    data = json.load(f)

generated_at = data.get("generated_at", "")
st.caption(f"数据更新时间：{generated_at}")

comp_names = list(data.get("competitors", {}).keys())
region_codes = list(REGION_CONFIG.keys())
region_labels = {code: REGION_CONFIG[code]["label"] for code in region_codes}

col1, col2 = st.columns(2)
with col1:
    selected_comp = st.selectbox("竞品", comp_names)
with col2:
    selected_region_label = st.selectbox("地区", list(REGIONS.keys()))

selected_region = REGIONS[selected_region_label]
region_data = data["competitors"].get(selected_comp, {}).get("regions", {}).get(selected_region)

if not region_data or region_data["count"] == 0:
    st.warning(f"过去 3 天「{selected_comp}」在「{selected_region_label}」无评论数据。")
    st.stop()

reviews = region_data["reviews"]
labels = region_data["labels"]
negative_count = region_data["negative_count"]

st.subheader("痛点分布")
dist_df = pd.DataFrame(list(labels.items()), columns=["类别", "数量"]).set_index("类别")
st.bar_chart(dist_df)

st.metric("评论总数", region_data["count"], delta=f"-{negative_count} 负面" if negative_count else None, delta_color="inverse")

# 已有缓存摘要则直接展示，否则按需生成
summary = region_data.get("summary", "")

if summary:
    st.subheader("AI 分析报告")
    st.markdown(summary)
else:
    if st.button("生成 AI 报告", type="primary"):
        if not api_key:
            st.error("请先填写 Claude API Key")
        else:
            with st.spinner("AI 分析中..."):
                try:
                    summary = generate_report(reviews, selected_comp, selected_region, api_key)
                    # 写回缓存
                    data["competitors"][selected_comp]["regions"][selected_region]["summary"] = summary
                    with open(DATA_FILE, "w", encoding="utf-8") as f:
                        json.dump(data, f, ensure_ascii=False, indent=2)
                    st.subheader("AI 分析报告")
                    st.markdown(summary)
                except Exception as e:
                    st.error(f"生成失败：{e}")

with st.expander("原始评论数据"):
    df = pd.DataFrame(reviews)
    st.dataframe(df)
