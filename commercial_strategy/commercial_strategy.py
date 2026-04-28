#!/usr/bin/env python3
"""commercial_strategy.py — 竞品商业变现策略分析"""
import os, json, sys, urllib.request, ssl
from datetime import datetime, timedelta
from pathlib import Path
from collections import Counter

import requests
from requests.adapters import HTTPAdapter
import ssl as _ssl

_SCRIPT_DIR = Path(__file__).resolve().parent
_PROJECT_ROOT = _SCRIPT_DIR.parent
DATA_DIR = _PROJECT_ROOT / "data"
HISTORY_PATH = DATA_DIR / "commercial_history.json"
sys.path.insert(0, str(_PROJECT_ROOT))

from competitors import get_market_rank_competitors
from regions import get_region_codes
from shared.ai_client import run_task

COMPETITORS = get_market_rank_competitors()
REGIONS = get_region_codes()
BETTING_KEYWORDS = ["betting", "odds", "tips", "prediction", "fantasy", "bet", "wager"]

CLAUDE_API_KEY = os.environ.get("CLAUDE_API_KEY", "")  # 兼容旧入口检查（run_headless 启动时校验）


# ── SSL Session ───────────────────────────────────────────────

class _SSLAdapter(HTTPAdapter):
    def init_poolmanager(self, *args, **kwargs):
        ctx = _ssl.create_default_context()
        ctx.minimum_version = _ssl.TLSVersion.TLSv1_2
        ctx.maximum_version = _ssl.TLSVersion.TLSv1_2
        kwargs["ssl_context"] = ctx
        return super().init_poolmanager(*args, **kwargs)


def _session():
    s = requests.Session()
    s.mount("https://", _SSLAdapter())
    s.headers.update({"User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36"})
    return s


# ── History ───────────────────────────────────────────────────

def load_history():
    if not HISTORY_PATH.exists():
        return {}
    return json.loads(HISTORY_PATH.read_text(encoding="utf-8"))


def save_history(h):
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    HISTORY_PATH.write_text(json.dumps(h, ensure_ascii=False, indent=2), encoding="utf-8")


# ── IAP Scraping ──────────────────────────────────────────────

def scrape_iap(app_id: str, country: str) -> list[dict]:
    """从 App Store 网页抓取 IAP 列表"""
    url = f"https://apps.apple.com/{country}/app/id{app_id}"
    try:
        resp = _session().get(url, timeout=15)
        resp.raise_for_status()
        html = resp.text

        # 尝试从 JSON-LD 提取
        ld_matches = re.findall(r'<script[^>]+type="application/ld\+json"[^>]*>(.*?)</script>', html, re.DOTALL)
        for raw in ld_matches:
            try:
                obj = json.loads(raw)
                offers = obj.get("offers", [])
                if isinstance(offers, list) and offers:
                    items = []
                    for o in offers:
                        name = o.get("name", "")
                        price_str = str(o.get("price", ""))
                        currency = o.get("priceCurrency", "")
                        if name and price_str:
                            try:
                                price = float(price_str)
                            except ValueError:
                                price = None
                            items.append({"name": name, "price": price, "currency": currency})
                    if items:
                        return items
            except Exception:
                continue

        # 备用：从页面文本提取内购价格模式
        items = []
        # 匹配 "App Name $X.XX" 或类似模式
        price_pattern = re.findall(r'"name"\s*:\s*"([^"]{3,60})"\s*,\s*"price"\s*:\s*"?(\d+\.?\d*)"?', html)
        for name, price_str in price_pattern[:10]:
            try:
                items.append({"name": name, "price": float(price_str), "currency": "USD"})
            except ValueError:
                pass
        return items
    except Exception as e:
        print(f"    [IAP] 爬取失败 {country}: {e}")
        return []


# ── Metadata ──────────────────────────────────────────────────

def fetch_metadata(app_name: str, app_id: str) -> dict:
    """从 iTunes API 获取元数据"""
    try:
        s = _session()
        resp = s.get(
            "https://itunes.apple.com/lookup",
            params={"id": app_id, "entity": "software"},
            timeout=15,
        )
        data = resp.json()
        if data.get("resultCount", 0) == 0:
            return {}
        app = data["results"][0]
        desc = app.get("description", "").lower()
        betting_signals = any(kw in desc for kw in BETTING_KEYWORDS)
        keywords_found = [kw for kw in BETTING_KEYWORDS if kw in desc]
        return {
            "version": app.get("version", ""),
            "release_notes": app.get("releaseNotes", ""),
            "seller_url": app.get("sellerUrl", ""),
            "genres": app.get("genres", []),
            "betting_signals": betting_signals,
            "description_keywords": keywords_found,
        }
    except Exception as e:
        print(f"    [Meta] 获取失败: {e}")
        return {}


# ── IAP Classification ────────────────────────────────────────

_IAP_RULES = {
    "去广告":    ["no ads", "ad-free", "remove ads", "ad free", "去广告"],
    "高级数据包": ["pro", "premium", "stats", "data", "advanced", "plus", "elite"],
    "AI预测":    ["ai", "predict", "tip", "forecast", "insight"],
    "球队主题":  ["theme", "club", "team", "badge", "kit"],
    "订阅":      ["monthly", "yearly", "annual", "subscription", "week"],
}

def classify_iap(name: str) -> str:
    n = name.lower()
    for category, keywords in _IAP_RULES.items():
        if any(kw in n for kw in keywords):
            return category
    return "其他"


# ── RPD Index ─────────────────────────────────────────────────

def compute_rpd(rank, iap_items: list[dict]) -> float:
    """RPD = (100 - rank) / 100 × max_subscription_price"""
    if not iap_items or rank is None:
        return 0.0
    prices = [i["price"] for i in iap_items if i.get("price") and i["price"] > 0]
    if not prices:
        return 0.0
    max_price = max(prices)
    rank_weight = max(0, (100 - rank) / 100)
    return round(rank_weight * max_price, 2)


# ── AI Analysis ───────────────────────────────────────────────

def ai_tag_monetization(comp_name: str, iap_items: list, keywords: list, api_key: str = "") -> list[str]:
    if not (api_key or os.environ.get("CLAUDE_API_KEY") or os.environ.get("ANTHROPIC_API_KEY")):
        return []
    iap_summary = ", ".join(f"{i['name']}({i.get('price',0)} {i.get('currency','')})" for i in iap_items[:10]) or "无内购项"
    try:
        result = run_task("commercial_monetize_tag", context={
            "comp_name": comp_name,
            "iap_summary": iap_summary,
            "keywords": ", ".join(keywords) or "无",
        })
        # output_format=json → returns list / dict / 解析失败 dict
        if isinstance(result, list):
            return result
        return []
    except Exception:
        return []


def ai_intent_analysis(comp_name: str, iap_changes: list, release_notes: str, api_key: str = "") -> str:
    if not (api_key or os.environ.get("CLAUDE_API_KEY") or os.environ.get("ANTHROPIC_API_KEY")):
        return ""
    if not iap_changes and not release_notes:
        return ""
    try:
        return run_task("commercial_intent", context={
            "comp_name": comp_name,
            "changes_str": "、".join(iap_changes) if iap_changes else "无变动",
            "release_notes": (release_notes[:300] if release_notes else "无"),
        }).strip()
    except Exception:
        return ""


# ── Price Delta Detection ─────────────────────────────────────

def detect_price_alerts(comp_name: str, current_iap: list, history: dict) -> list[dict]:
    alerts = []
    prev_date = sorted(history.keys())[-1] if history else None
    if not prev_date:
        return alerts
    prev_items = {i["name"]: i for i in history[prev_date].get(comp_name, {}).get("iap_us", [])}
    for item in current_iap:
        name = item["name"]
        curr_price = item.get("price")
        if name in prev_items and curr_price is not None:
            prev_price = prev_items[name].get("price")
            if prev_price is not None and curr_price != prev_price:
                direction = "涨价" if curr_price > prev_price else "降价"
                alerts.append({
                    "name": name,
                    "direction": direction,
                    "prev": prev_price,
                    "curr": curr_price,
                    "delta": round(curr_price - prev_price, 2),
                })
    return alerts


def detect_iap_changes(comp_name: str, current_iap: list, history: dict) -> list[dict]:
    changes = []
    prev_date = sorted(history.keys())[-1] if history else None
    if not prev_date:
        return changes
    prev_names = {i["name"] for i in history[prev_date].get(comp_name, {}).get("iap_us", [])}
    curr_names = {i["name"] for i in current_iap}
    for name in curr_names - prev_names:
        changes.append({"name": name, "type": "新增"})
    for name in prev_names - curr_names:
        changes.append({"name": name, "type": "移除"})
    return changes


# ── Main Flow ─────────────────────────────────────────────────

def run_all(api_key: str = "") -> dict:
    key = api_key or CLAUDE_API_KEY
    history = load_history()
    today = datetime.now().strftime("%Y-%m-%d")
    today_snapshot = {}

    result = {
        "generated_at": datetime.now().isoformat(),
        "competitors": {}
    }

    for comp_name, comp_info in COMPETITORS.items():
        app_id = comp_info["app_id"]
        print(f"\n[{comp_name}] 分析中...")

        # 元数据
        meta = fetch_metadata(comp_name, app_id)

        # IAP 多地区爬取
        iap_by_region = {}
        for country in REGIONS:
            print(f"  [IAP/{country}] 爬取...")
            items = scrape_iap(app_id, country)
            for item in items:
                item["category"] = classify_iap(item["name"])
            iap_by_region[country] = items

        # 主要用 US 数据做分析
        iap_us = iap_by_region.get("us", [])

        # 价格预警
        price_alerts = detect_price_alerts(comp_name, iap_us, history)

        # IAP 变动检测
        iap_changes = detect_iap_changes(comp_name, iap_us, history)

        # 从 market_rank 获取排名（如果有）
        rank = None
        market_path = DATA_DIR / "market_rank.json"
        if market_path.exists():
            try:
                mdata = json.loads(market_path.read_text(encoding="utf-8"))
                rank = mdata.get("competitor_performance", {}).get(comp_name, {}).get("rank")
            except Exception:
                pass

        rpd = compute_rpd(rank, iap_us)

        # AI 分析
        tags = ai_tag_monetization(comp_name, iap_us, meta.get("description_keywords", []), key)
        intent = ai_intent_analysis(comp_name, [a["name"] for a in price_alerts], meta.get("release_notes", ""), key)

        # 构建多地区价格对比
        price_by_region = {}
        for country, items in iap_by_region.items():
            price_by_region[country] = [
                {"name": i["name"], "price": i.get("price"), "currency": i.get("currency", "")}
                for i in items
            ]

        entry = {
            "monetization_tags": tags,
            "iap_items": [
                {
                    "name": i["name"],
                    "price_usd": i.get("price"),
                    "currency": i.get("currency", "USD"),
                    "category": i.get("category", "其他"),
                    "price_by_region": {
                        c: next((x.get("price") for x in iap_by_region.get(c, []) if x["name"] == i["name"]), None)
                        for c in REGIONS
                    },
                }
                for i in iap_us
            ],
            "price_alerts": price_alerts,
            "iap_changes": iap_changes,
            "rpd_index": rpd,
            "rank": rank,
            "betting_signals": meta.get("betting_signals", False),
            "description_keywords": meta.get("description_keywords", []),
            "seller_url": meta.get("seller_url", ""),
            "ai_intent": intent,
        }

        result["competitors"][comp_name] = entry
        today_snapshot[comp_name] = {"iap_us": iap_us}

    # 保存历史
    history[today] = today_snapshot
    save_history(history)

    return result


def export_json(data: dict) -> Path:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    out = DATA_DIR / "commercial_strategy.json"
    out.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"JSON 已导出: {out}")
    return out


def generate_weekly_report(api_key: str = "") -> dict:
    key = api_key or CLAUDE_API_KEY
    history = load_history()
    current_path = DATA_DIR / "commercial_strategy.json"

    if not history:
        return {"summary": "暂无历史数据，请先运行一次商业策略分析", "generated_at": datetime.now().isoformat(), "period": "7d"}

    sorted_dates = sorted(history.keys(), reverse=True)
    cutoff = (datetime.now() - timedelta(days=7)).strftime("%Y-%m-%d")
    recent_dates = [d for d in sorted_dates if d >= cutoff]
    if not recent_dates:
        recent_dates = sorted_dates[:1]

    current_data = {}
    if current_path.exists():
        try:
            current_data = json.loads(current_path.read_text(encoding="utf-8"))
        except Exception:
            pass

    history_summary = []
    for date in recent_dates:
        snapshot = history[date]
        for comp, info in snapshot.items():
            iap_list = info.get("iap_us", [])
            iap_names = [i.get("name", "") for i in iap_list]
            prices = [f"{i.get('name','')}=${i.get('price','?')}" for i in iap_list if i.get("price")]
            history_summary.append(f"[{date}] {comp}: {', '.join(prices[:5]) or '无IAP'}")

    comp_current = []
    for name, c in current_data.get("competitors", {}).items():
        tags = ", ".join(c.get("monetization_tags", [])) or "无标签"
        alerts = "; ".join(f"{a['name']} {a['direction']} {a['prev']}→{a['curr']}" for a in c.get("price_alerts", []))
        intent = c.get("ai_intent", "")
        comp_current.append(f"{name}: 标签=[{tags}], RPD={c.get('rpd_index',0)}, 预警=[{alerts or '无'}], 意图={intent or '无'}")

    date_from = recent_dates[-1] if recent_dates else datetime.now().strftime("%Y-%m-%d")
    date_to = datetime.now().strftime("%Y-%m-%d")

    summary = ""
    if key or os.environ.get("CLAUDE_API_KEY") or os.environ.get("ANTHROPIC_API_KEY"):
        try:
            summary = run_task("commercial_weekly", context={
                "date_from": date_from,
                "date_to": date_to,
                "history_summary": "\n".join(history_summary[:30]) or "无历史快照",
                "comp_current": "\n".join(comp_current) or "无当前竞品状态",
            })
        except Exception as e:
            summary = f"AI 生成失败: {e}"
    else:
        summary = "未提供 API Key，无法生成 AI 报告"

    return {
        "summary": summary,
        "generated_at": datetime.now().isoformat(),
        "period": "7d",
        "dates_covered": recent_dates,
    }


def export_weekly_json(data: dict) -> Path:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    out = DATA_DIR / "commercial_weekly.json"
    out.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"周报 JSON 已导出: {out}")
    return out
