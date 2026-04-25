import os
import json
import urllib.request
import ssl
import streamlit as st
import pandas as pd
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from competitors import get_comment_competitors
from regions import load_regions

COMPETITORS = dict(get_comment_competitors())
COMPETITORS["自定义"] = {"gp": "", "ios": 0}
REGION_CONFIG = load_regions()
REGIONS = {info["label"]: code for code, info in REGION_CONFIG.items()}

st.set_page_config(page_title="竞品用户评论检查", layout="wide")
st.title("竞品用户评论检查")

with st.sidebar:
    st.header("配置")
    platform = st.radio("平台", ["Google Play", "App Store"], horizontal=True)
    competitor = st.selectbox("竞品", list(COMPETITORS.keys()))
    region_label = st.selectbox("地区", list(REGIONS.keys()))

    if competitor == "自定义":
        pkg    = st.text_input("包名", value="com.example.app") if platform == "Google Play" else None
        app_id = st.number_input("App ID", value=0, step=1) if platform == "App Store" else None
    else:
        pkg    = COMPETITORS[competitor]["gp"]
        app_id = COMPETITORS[competitor]["ios"]
        st.caption(f"`{pkg}`" if platform == "Google Play" else f"App ID: `{app_id}`")

    count   = st.slider("抓取条数", 20, 500, 100, 10)
    # Claude API Key — 用户手动输入
    api_key = st.text_input("Claude API Key", type="password",
                            help="从 https://ai.flashapi.top 获取 Claude API 密钥")
    run     = st.button("开始分析", type="primary")


def call_claude(prompt, api_key, max_tokens=4096):
    """调用 Anthropic Native 格式的 Claude API"""
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


def fetch_gp(pkg, country, count):
    from google_play_scraper import reviews, Sort
    result, _ = reviews(pkg, lang="en", country=country, sort=Sort.NEWEST, count=count)
    if not result:
        return pd.DataFrame(columns=["userName", "score", "at", "appVersion", "content"])
    df = pd.DataFrame(result)[["userName", "score", "at", "appVersion", "content"]]
    return df.reset_index(drop=True)


def fetch_ios(app_id, country, count):
    rows, page = [], 1
    while len(rows) < count and page <= 10:
        url = f"https://itunes.apple.com/{country}/rss/customerreviews/page={page}/id={app_id}/sortby=mostrecent/json"
        try:
            with urllib.request.urlopen(url, timeout=10) as r:
                data = json.loads(r.read())
        except Exception:
            break
        entries = data.get("feed", {}).get("entry", [])
        if not entries:
            break
        for e in entries[1:]:
            rows.append({
                "userName":   e.get("author", {}).get("name", {}).get("label", ""),
                "score":      int(e.get("im:rating", {}).get("label", 5)),
                "at":         e.get("updated", {}).get("label", ""),
                "appVersion": e.get("im:version", {}).get("label", ""),
                "content":    e.get("content", {}).get("label", ""),
            })
        page += 1
    if not rows:
        return pd.DataFrame(columns=["userName", "score", "at", "appVersion", "content"])
    df = pd.DataFrame(rows)
    return df.reset_index(drop=True)


def label_reviews(df, api_key):
    """使用 Claude 对评论进行打标分类"""
    id_content = {str(i): row["content"] for i, row in df.iterrows()}
    prompt = (
        "你是一名产品分析师。请对以下 JSON 中每条评论按以下类别归类：\n"
        "[问题抱怨]、[高价值功能请求]、[竞品对比]、[流失信号]、[正向反馈]、[其他]\n"
        "仅返回一个 JSON 对象，key 为 id，value 为类别字符串，不要输出其他内容。\n\n"
        f"{json.dumps(id_content, ensure_ascii=False)}"
    )
    resp_text = call_claude(prompt, api_key)
    raw = resp_text.strip()
    if "```" in raw:
        import re
        raw = re.sub(r'^```(?:json)?\s*|\s*```$', '', raw, flags=re.DOTALL).strip()
    mapping = json.loads(raw)
    df = df.copy()
    df["分类标签"] = df.index.map(lambda i: mapping.get(str(i), "[其他]"))
    return df


def analyze_reviews(df, api_key, competitor_name, platform):
    """使用 Claude 生成分析报告"""
    dist_str = "、".join(f"{k}：{v}条" for k, v in df["分类标签"].value_counts().items())
    sample = df[["score", "appVersion", "分类标签", "content"]].to_string(index=False, max_rows=80)
    prompt = (
        f"你是一名资深体育 App 产品经理，正在分析竞品「{competitor_name}」（{platform}）的用户评论。\n"
        "请生成《用户评论分析报告》，要求：\n"
        "1. 分类识别：准确区分 [问题抱怨]、[高价值功能请求]、[竞品对比]、[流失信号] 四类高价值信号。\n"
        "2. 标签格式：使用纯文本方括号，如 [高价值功能请求]。禁止使用任何 emoji。\n"
        "3. 结构化输出：用户抱怨最多的3个问题、用户主动要求的3个功能、竞品对比场景、忠实用户流失信号。\n"
        f"4. 标签分布（请与此保持一致）：{dist_str}\n\n"
        f"评论数据：\n{sample}"
    )
    return call_claude(prompt, api_key)


if run:
    # 检查 API Key
    if not api_key:
        st.error("请先配置 API Key。提示：您可以从 https://ai.flashapi.top 获取 Claude API 密钥。")
        st.stop()

    country = REGIONS[region_label]

    with st.status("正在抓取评论...", expanded=True) as status:
        try:
            df = fetch_gp(pkg, country, int(count)) if platform == "Google Play" else fetch_ios(int(app_id), country, int(count))
            st.write(f"抓取完成，共 {len(df)} 条评论")
            if df.empty:
                st.warning("未找到评论，请尝试更换地区或增加抓取条数。")
                st.stop()
        except Exception as e:
            st.error(f"抓取失败：{e}")
            st.stop()

        status.update(label="正在 AI 打标分类...")
        try:
            df = label_reviews(df, api_key)
            st.write(f"打标完成：{df['分类标签'].value_counts().to_dict()}")
        except Exception as e:
            st.error(f"打标失败：{e}")
            st.stop()

        status.update(label="正在生成分析报告...")
        try:
            report = analyze_reviews(df, api_key, competitor, platform)
            status.update(label="分析完成", state="complete")
        except Exception as e:
            st.error(f"分析失败：{e}")
            st.stop()

    st.subheader("痛点分布")
    dist_df = df["分类标签"].value_counts().rename_axis("类别").reset_index(name="数量")
    st.bar_chart(dist_df.set_index("类别"))

    st.subheader("用户评论分析报告")
    st.markdown(report)

    with st.expander("原始评论数据（含分类标签）"):
        st.dataframe(df)
