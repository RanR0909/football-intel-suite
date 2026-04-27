#!/usr/bin/env python3
"""auto_report.py — 多竞品 × 多地区 滚动评论监测 (Claude API)"""
import os, json, re, urllib.request, ssl, sys, time
from datetime import datetime, timezone, timedelta
from pathlib import Path
from collections import Counter
from google_play_scraper import reviews, Sort

# ── 路径自动定位 ──────────────────────────────────────────────
_SCRIPT_DIR = Path(__file__).resolve().parent
_PROJECT_ROOT = _SCRIPT_DIR.parent          # Football_Intel_Suite/
DATA_DIR = _PROJECT_ROOT / "data"           # 统一数据输出目录
REPORTS_DIR = _SCRIPT_DIR / "reports"       # 报告仍保留在模块内
sys.path.insert(0, str(_PROJECT_ROOT))

from competitors import get_comment_competitors
from regions import get_region_codes, load_regions
from prompts.comment_prompts import build_label_prompt, build_daily_summary_prompt

COMPETITORS = get_comment_competitors()
REGIONS     = get_region_codes()
REGION_INFO = load_regions()
FETCH_COUNT = 200
CUTOFF_DAYS = 3
CATEGORIES  = "[问题抱怨]、[高价值功能请求]、[竞品对比]、[流失信号]、[正向反馈]、[其他]"

# Claude API 配置
CLAUDE_API_KEY = os.environ.get("CLAUDE_API_KEY", "")
CLAUDE_API_URL = "https://ai.flashapi.top/v1/messages"
CLAUDE_MODEL = "claude-haiku-4-5-20251001"  # 快速模型


def call_claude(prompt, max_tokens=4096, timeout=60, retries=3):
    """调用 Anthropic Native 格式的 Claude API"""
    last_error = None
    for attempt in range(1, retries + 1):
        try:
            data = json.dumps({
                "model": CLAUDE_MODEL,
                "max_tokens": max_tokens,
                "messages": [{"role": "user", "content": prompt}]
            }).encode("utf-8")
            req = urllib.request.Request(
                CLAUDE_API_URL,
                data=data,
                headers={
                    "Content-Type": "application/json",
                    "x-api-key": CLAUDE_API_KEY,
                    "anthropic-version": "2023-06-01",
                }
            )
            ctx = ssl.create_default_context()
            ctx.check_hostname = False
            ctx.verify_mode = ssl.CERT_NONE
            with urllib.request.urlopen(req, timeout=timeout, context=ctx) as resp:
                result = json.loads(resp.read())
            return result["content"][0]["text"]
        except Exception as exc:
            last_error = exc
            if attempt < retries:
                time.sleep(min(attempt * 2, 6))
    raise last_error


def translate_to_english(rows):
    """批量翻译非英文评论为英文"""
    non_en = [(i, r) for i, r in enumerate(rows) if r.get("content")]
    if not non_en:
        return rows
    id_map = {str(i): r["content"] for i, r in non_en}
    prompt = (
        "Translate the following app reviews to English. "
        "Return a JSON object mapping each ID to its English translation. "
        "If already English, keep as-is. Output only JSON.\n\n"
        + json.dumps(id_map, ensure_ascii=False)
    )
    try:
        raw = call_claude(prompt).strip()
        raw = re.sub(r'^```(?:json)?\s*|\s*```$', '', raw, flags=re.DOTALL).strip()
        translations = json.loads(raw)
        for i, r in non_en:
            if str(i) in translations:
                r["content"] = translations[str(i)]
    except Exception:
        pass
    return rows


def fetch(pkg, country):
    cutoff = datetime.now(timezone.utc) - timedelta(days=CUTOFF_DAYS)
    lang = REGION_INFO.get(country, {}).get("lang", "en")
    try:
        result, _ = reviews(pkg, lang=lang, country=country, sort=Sort.NEWEST, count=FETCH_COUNT)
    except Exception as e:
        print(f"    [GP][{pkg}/{country}] 抓取失败（包名错？）: {type(e).__name__}: {e}", file=sys.stderr)
        return []
    if not result:
        print(
            f"    [GP][{pkg}/{country}] 警告：返回 0 条 — 通常是包名 {pkg!r} "
            f"在 Google Play 不存在（'幽灵 ID'）。",
            file=sys.stderr,
        )
    rows = []
    for r in result:
        at = r["at"].replace(tzinfo=timezone.utc) if r["at"].tzinfo is None else r["at"]
        if at >= cutoff:
            rows.append({"score": r["score"], "version": r.get("appVersion", ""), "content": r["content"]})
    return rows


def fetch_ios(app_id, country):
    rows, page = [], 1
    while len(rows) < FETCH_COUNT and page <= 10:
        url = f"https://itunes.apple.com/{country}/rss/customerreviews/page={page}/id={app_id}/sortby=mostrecent/json"
        try:
            with urllib.request.urlopen(url, timeout=10) as r:
                data = json.loads(r.read())
        except Exception:
            break
        entries = data.get("feed", {}).get("entry", [])
        if isinstance(entries, dict):
            entries = [entries]
        if not isinstance(entries, list) or not entries:
            break
        start_idx = 1 if entries and isinstance(entries[0], dict) and "im:name" in entries[0] else 0
        for e in entries[start_idx:]:
            score = int(e.get("im:rating", {}).get("label", 5))
            rows.append({
                "score": score,
                "version": e.get("im:version", {}).get("label", ""),
                "content": e.get("content", {}).get("label", ""),
            })
        page += 1
    return rows


def label(rows):
    """使用 Claude 对评论打标"""
    id_map = {str(i): r["content"] for i, r in enumerate(rows)}
    try:
        resp_text = call_claude(build_label_prompt(id_map, CATEGORIES))
        raw = resp_text.strip()
        if "```" in raw:
            raw = re.sub(r'^```(?:json)?\s*|\s*```$', '', raw, flags=re.DOTALL).strip()
        mapping = json.loads(raw)
        for i, r in enumerate(rows):
            r["label"] = mapping.get(str(i), "[其他]")
    except Exception as exc:
        print(f"  [AI] 打标失败，降级为默认标签: {exc}")
        for r in rows:
            r["label"] = "[其他]"
    return rows


def summarize(rows, app_name, region):
    """使用 Claude 生成分析摘要"""
    prompt = build_daily_summary_prompt(app_name, region, CUTOFF_DAYS, rows, list(COMPETITORS.keys()))
    try:
        return call_claude(prompt)
    except Exception as exc:
        print(f"  [AI] 摘要失败，写入降级说明: {exc}")
        return f"AI 分析失败：{exc}"


def export_json(all_data):
    """Export structured JSON to root /data/ for the main dashboard."""
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    out_path = DATA_DIR / "competitor_comments.json"
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(all_data, f, ensure_ascii=False, indent=2)
    print(f"JSON 数据已导出: {out_path}")


def main():
    if not CLAUDE_API_KEY:
        print("错误: 未设置 CLAUDE_API_KEY 环境变量。")
        return

    all_data = {
        "generated_at": datetime.now().isoformat(),
        "date": datetime.now().strftime("%Y-%m-%d"),
        "competitors": {}
    }

    for app_name, comp in COMPETITORS.items():
        app_data = {"regions": {}}
        for region in REGIONS:
            print(f"[{app_name}/{region}] 抓取...")
            gp_rows = fetch(comp["gp"], region)
            ios_rows = fetch_ios(comp["ios"], region)
            rows = gp_rows + ios_rows
            if not rows:
                app_data["regions"][region] = {"count": 0, "negative_count": 0, "labels": {}, "summary": "", "reviews": []}
                continue
            if REGION_INFO.get(region, {}).get("lang", "en") != "en":
                print(f"  翻译为英文...")
                rows = translate_to_english(rows)
            print(f"  {len(rows)} 条，打标...")
            rows = label(rows)
            label_dist = dict(Counter(r["label"] for r in rows))
            negative_count = sum(1 for r in rows if r["score"] <= 3)
            app_data["regions"][region] = {
                "count": len(rows),
                "negative_count": negative_count,
                "labels": label_dist,
                "summary": "",
                "reviews": [
                    {"score": r["score"], "version": r["version"], "label": r["label"], "content": r["content"]}
                    for r in rows
                ]
            }
        all_data["competitors"][app_name] = app_data

    export_json(all_data)


if __name__ == "__main__":
    main()
