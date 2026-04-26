import os
import json
import re
import ssl
import urllib.request
from datetime import datetime
from pathlib import Path
import requests
from requests.adapters import HTTPAdapter
from urllib3.poolmanager import PoolManager
import streamlit as st
import sys


class SSLAdapter(HTTPAdapter):
    """Adapter that forces TLS 1.2 to avoid SSL EOF errors on macOS."""
    def init_poolmanager(self, *args, **kwargs):
        ctx = ssl.create_default_context()
        ctx.minimum_version = ssl.TLSVersion.TLSv1_2
        ctx.maximum_version = ssl.TLSVersion.TLSv1_2
        kwargs['ssl_context'] = ctx
        return super().init_poolmanager(*args, **kwargs)

# ── 路径自动定位 ──────────────────────────────────────────────
_SCRIPT_DIR = Path(__file__).resolve().parent
_PROJECT_ROOT = _SCRIPT_DIR.parent          # Football_Intel_Suite/
DATA_DIR = _PROJECT_ROOT / "data"           # 统一数据输出目录
sys.path.insert(0, str(_PROJECT_ROOT))

from competitors import load_competitors, save_competitors, get_strategy_monitor_apps

# ============================================================
# 竞品数据管理
# ============================================================

STATE_FILE = DATA_DIR / "strategy_state.json"


def load_extra_competitors() -> dict:
    """返回非默认核心竞品的 App Store ID 映射。数据源统一来自 competitors.json。"""
    default_names = {"SofaScore", "FlashScore", "OneFootball", "365Scores", "Fotmob", "LiveScore"}
    return {
        name: int(entry["ios"])
        for name, entry in load_competitors().items()
        if name not in default_names and entry.get("ios")
    }


def save_extra_competitors(apps: dict) -> None:
    """保存额外竞品到统一竞品配置 competitors.json。"""
    registry = load_competitors()
    for name, app_id in apps.items():
        existing = registry.get(name, {})
        registry[name] = {
            "name": name,
            "ios": int(app_id),
            "app_id": str(app_id),
            "gp": existing.get("gp", ""),
            "bundle_id": existing.get("bundle_id", ""),
        }
    save_competitors(registry)


def load_custom_apps() -> dict:
    """兼容旧命名，保留给历史调用方。"""
    return load_extra_competitors()


def save_custom_apps(apps: dict) -> None:
    """兼容旧命名，保留给历史调用方。"""
    save_extra_competitors(apps)


def get_all_apps() -> dict:
    """返回 competitors.json 中所有参与策略监控的竞品。"""
    return get_strategy_monitor_apps()


# ============================================================
# Diff Engine — 状态管理
# ============================================================

def load_state() -> dict:
    """加载历史状态"""
    if os.path.exists(STATE_FILE):
        with open(STATE_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    return {}


def save_state(state: dict) -> None:
    """持久化历史状态"""
    os.makedirs(os.path.dirname(STATE_FILE), exist_ok=True)
    with open(STATE_FILE, "w", encoding="utf-8") as f:
        json.dump(state, f, ensure_ascii=False, indent=2)


def _get_session() -> requests.Session:
    """Create a requests Session with SSL adapter for macOS compatibility."""
    session = requests.Session()
    adapter = SSLAdapter()
    session.mount("https://", adapter)
    session.headers.update({"User-Agent": "StrategyMonitor/1.0"})
    return session


def fetch_app_data(app_name: str) -> dict:
    """
    通过 iTunes Search API 获取竞品数据。
    """
    search_url = "https://itunes.apple.com/search"
    params = {
        "term": app_name,
        "entity": "software",
        "limit": 1,
    }

    session = _get_session()
    resp = session.get(search_url, params=params, timeout=15)
    resp.raise_for_status()
    data = resp.json()

    if data["resultCount"] == 0:
        raise ValueError(f"未在 App Store 中找到 {app_name}")

    app = data["results"][0]

    track_id = app.get("trackId")
    iap_list = []
    if track_id:
        try:
            lookup_url = f"https://itunes.apple.com/lookup?id={track_id}&entity=software"
            lookup_resp = session.get(lookup_url, timeout=10)
            lookup_data = lookup_resp.json()
            if lookup_data["resultCount"] > 0:
                detail = lookup_data["results"][0]
                if detail.get("price", 0) == 0 and detail.get("formattedPrice") == "Free":
                    iap_list = [{"note": "App 免费下载，可能存在内购项目"}]
        except Exception:
            pass

    return {
        "version": app.get("version", ""),
        "release_notes": app.get("releaseNotes", ""),
        "release_date": app.get("currentVersionReleaseDate", ""),
        "in_app_purchases": iap_list,
        "track_name": app.get("trackName", app_name),
        "track_id": track_id,
        "bundle_id": app.get("bundleId", ""),
    }


def compute_diff(app_name: str, current: dict, history: dict) -> dict:
    """
    对比当前数据与历史记录，返回差异结果。
    """
    result = {
        "has_changed": False,
        "is_first_record": False,
        "version_changed": False,
        "iap_changed": False,
        "changes": [],
    }

    prev = history.get(app_name, {})

    if not prev:
        result["is_first_record"] = True
        result["changes"].append(f"[首次记录] 当前版本 {current.get('version', '未知')}")
        return result

    prev_version = prev.get("version", "")
    curr_version = current.get("version", "")
    if prev_version and curr_version and prev_version != curr_version:
        result["has_changed"] = True
        result["version_changed"] = True
        result["changes"].append(f"[产品迭代] {prev_version} -> {curr_version}")

    prev_iap = prev.get("in_app_purchases", [])
    curr_iap = current.get("in_app_purchases", [])

    prev_iap_str = json.dumps(prev_iap, sort_keys=True, ensure_ascii=False)
    curr_iap_str = json.dumps(curr_iap, sort_keys=True, ensure_ascii=False)

    if prev_iap_str != curr_iap_str:
        result["has_changed"] = True
        result["iap_changed"] = True
        result["changes"].append("[商业化更新] 内购项目发生变化")

    return result


# ============================================================
# AI 策略分析 (Claude Haiku via flashapi proxy)
# ============================================================

CLAUDE_API_KEY = os.environ.get("CLAUDE_API_KEY", "")
CLAUDE_API_URL = "https://ai.flashapi.top/v1/messages"
CLAUDE_MODEL = "claude-haiku-4-5-20251001"

ANALYSIS_PROMPT_TEMPLATE = """你是一名资深的体育产品分析师。请对以下竞品情报进行深度分析。

## 竞品名称
{app_name}

## 检测到的变更
{changes}

## 更新日志
{release_notes}

## 当前内购项
{in_app_purchases}

请从以下三个维度进行分析：

### 1. [产品迭代]
分析更新日志是否涉及核心数据维度、AI 功能或重大交互变动。

### 2. [商业策略]
深度拆解内购项变动背后的变现逻辑（如试水订阅制、增加广告位）。

### 3. [本地化信号]
检查是否加强了对德甲、中超等特定联赛的数据覆盖或语言适配。

### 4. [威胁等级]
给出 1-5 星评分（5 星为最高威胁），并简要说明理由。

请用中文回答，保持分析简洁、有洞察力。"""


def analyze_with_ai(app_name: str, changes: list, release_notes: str, in_app_purchases: list, api_key: str = "") -> str:
    """使用 Claude Haiku 对变更进行策略分析"""
    key = api_key or CLAUDE_API_KEY
    if not key:
        return "[AI 分析] 未设置 CLAUDE_API_KEY"
    prompt = ANALYSIS_PROMPT_TEMPLATE.format(
        app_name=app_name,
        changes="\n".join(changes) if changes else "无显著变更",
        release_notes=release_notes if release_notes else "无更新日志",
        in_app_purchases=json.dumps(in_app_purchases, ensure_ascii=False, indent=2) if in_app_purchases else "无内购项",
    )
    data = json.dumps({
        "model": CLAUDE_MODEL,
        "max_tokens": 1024,
        "messages": [{"role": "user", "content": prompt}]
    }).encode("utf-8")
    req = urllib.request.Request(
        CLAUDE_API_URL, data=data,
        headers={"Content-Type": "application/json", "x-api-key": key, "anthropic-version": "2023-06-01"},
    )
    ctx = ssl.create_default_context()
    ctx.check_hostname = False
    ctx.verify_mode = ssl.CERT_NONE
    try:
        with urllib.request.urlopen(req, timeout=60, context=ctx) as resp:
            result = json.loads(resp.read())
        return result["content"][0]["text"]
    except Exception as e:
        return f"[AI 分析] 失败：{str(e)}"


# ============================================================
# JSON 导出 — 供主面板使用
# ============================================================

def export_json(results: list) -> None:
    """Export structured JSON to root /data/ for the main dashboard."""
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    out_path = DATA_DIR / "strategy_monitor.json"

    data = {
        "generated_at": datetime.now().isoformat(),
        "total_monitored": len(results),
        "changes_detected": sum(1 for r in results if "error" not in r and r["diff"]["has_changed"]),
        "competitors": {}
    }

    for r in results:
        name = r["name"]
        if "error" in r:
            data["competitors"][name] = {"error": r["error"]}
            continue

        diff = r["diff"]
        entry = {
            "version": r["current_data"]["version"],
            "release_notes": r["current_data"]["release_notes"],
            "release_date": r["current_data"].get("release_date", ""),
            "in_app_purchases": r["current_data"]["in_app_purchases"],
            "has_changed": diff["has_changed"],
            "is_first_record": diff["is_first_record"],
            "version_changed": diff["version_changed"],
            "iap_changed": diff["iap_changed"],
            "changes": diff["changes"],
        }
        if "analysis" in r:
            entry["analysis"] = r["analysis"]
        data["competitors"][name] = entry

    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    print(f"JSON 数据已导出: {out_path}")


# ============================================================
# Streamlit UI — Dashboard 风格
# ============================================================

st.set_page_config(page_title="竞品商业情报监控", layout="wide")

st.title("竞品商业情报监控")

# ---------- 侧边栏 ----------
with st.sidebar:
    st.header("竞品管理")

    with st.expander("添加竞品到 competitors.json", expanded=False):
        new_name = st.text_input("竞品名称", key="new_app_name")
        new_app_id = st.text_input("App Store ID", key="new_app_id")
        new_gp = st.text_input("Google Play 包名", key="new_gp_package", help="如果要参与评论分析，请填写")
        new_bundle_id = st.text_input("Bundle ID", key="new_bundle_id", help="可选，主要用于排名识别")
        if st.button("确认添加", type="primary"):
            if new_name and new_app_id:
                try:
                    app_id_int = int(new_app_id)
                    registry = load_competitors()
                    registry[new_name] = {
                        "name": new_name,
                        "ios": app_id_int,
                        "app_id": str(app_id_int),
                        "gp": new_gp.strip(),
                        "bundle_id": new_bundle_id.strip(),
                    }
                    save_competitors(registry)
                    st.success("[成功] 已添加竞品：" + new_name)
                    st.rerun()
                except ValueError:
                    st.error("[错误] App Store ID 必须为数字")
            else:
                st.warning("[提示] 请填写竞品名称和 App Store ID")

    st.divider()
    st.header("API 配置")
    claude_api_key_input = st.text_input(
        "Claude API Key",
        type="password",
        help="从 https://ai.flashapi.top 获取 Claude API 密钥",
        key="strategy_claude_key",
    )

# ---------- 监测列表 ----------
all_apps = get_all_apps()
st.subheader("监测列表（共 " + str(len(all_apps)) + " 个竞品）")

cols = st.columns(3)
for idx, (name, app_id) in enumerate(all_apps.items()):
    with cols[idx % 3]:
        with st.container(border=True):
            st.markdown(f"**{name}**")
            st.caption(f"App Store ID: {app_id}")
            if name in load_extra_competitors():
                if st.button("删除", key=f"del_{name}"):
                    registry = load_competitors()
                    registry.pop(name, None)
                    save_competitors(registry)
                    st.rerun()

# ---------- 监测区域 ----------
st.divider()
st.subheader("商业动态监测")

if st.button("开始全量监测", type="primary"):
    if not claude_api_key_input:
        st.error("请先配置 Claude API Key。")
        st.stop()

    state = load_state()
    results = []

    with st.status("正在抓取 App Store 数据...", expanded=True) as status:
        for name in all_apps:
            status.write(f"[抓取中] {name}")
            try:
                current_data = fetch_app_data(name)
                diff = compute_diff(name, current_data, state)
                state[name] = {
                    "version": current_data["version"],
                    "in_app_purchases": current_data["in_app_purchases"],
                }
                results.append({"name": name, "current_data": current_data, "diff": diff})
            except Exception as e:
                results.append({"name": name, "error": str(e), "diff": {"has_changed": False, "changes": []}})

        save_state(state)

        changed_results = [r for r in results if "error" not in r and r["diff"]["has_changed"]]
        if changed_results:
            status.write("[AI 分析] 正在分析变更...")
            for r in changed_results:
                analysis = analyze_with_ai(
                    app_name=r["name"],
                    changes=r["diff"]["changes"],
                    release_notes=r["current_data"]["release_notes"],
                    in_app_purchases=r["current_data"]["in_app_purchases"],
                    api_key=claude_api_key_input,
                )
                r["analysis"] = analysis

        export_json(results)

        status.update(label="监测完成", state="complete")

    for r in results:
        with st.container(border=True):
            if "error" in r:
                st.error(f"**{r['name']}** -- 抓取失败：{r['error']}")
                continue

            diff = r["diff"]
            if diff.get("is_first_record"):
                st.info(f"**{r['name']}** -- [首次记录] 版本 {r['current_data']['version']}，已保存当前状态")
                st.caption(f"更新日志：{r['current_data']['release_notes'][:200]}")
                continue
            if not diff["has_changed"]:
                st.info(f"**{r['name']}** -- [状态稳定] 版本 {r['current_data']['version']}，无变化")
            else:
                if diff["version_changed"]:
                    st.warning(f"**{r['name']}** -- [产品迭代]")
                if diff["iap_changed"]:
                    st.warning(f"**{r['name']}** -- [商业化更新]")

                for change in diff["changes"]:
                    st.markdown(f"- {change}")

                st.caption(f"当前版本：{r['current_data']['version']}")
                iap_count = len(r['current_data']['in_app_purchases'])
                st.caption(f"内购项数量：{iap_count}")

                if "analysis" in r:
                    st.divider()
                    st.markdown("### AI 策略分析")
                    st.markdown(r["analysis"])
else:
    st.info("[提示] 点击上方按钮开始全量监测")
