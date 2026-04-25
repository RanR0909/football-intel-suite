#!/usr/bin/env python3
"""
competitor_detail.py — 单竞品深度分析脚本
抓取指定竞品在 Apple App Store + Google Play 近一周评论，
按地区汇总分析产品反馈，输出结构化 JSON 供看板使用。

用法:
  python3 competitor_detail.py SofaScore
  python3 competitor_detail.py SofaScore --days 7
"""

import os, json, re, sys, urllib.request, ssl
from datetime import datetime, timezone, timedelta
from pathlib import Path
from collections import Counter

# ── 路径 ──────────────────────────────────────────────────────
_SCRIPT_DIR = Path(__file__).resolve().parent
_PROJECT_ROOT = _SCRIPT_DIR.parent
DATA_DIR = _PROJECT_ROOT / "data"
sys.path.insert(0, str(_PROJECT_ROOT))

from competitors import get_comment_competitors
from regions import load_regions
from prompts.comment_prompts import build_label_prompt, build_competitor_detail_prompt

# ── 竞品配置 ──────────────────────────────────────────────────
# 格式: { "竞品名": { "gp": "包名", "ios": AppStore ID } }
COMPETITORS = get_comment_competitors()

# 地区配置: 标签 -> (地区代码, 语言)
REGIONS = load_regions()

FETCH_COUNT = 200  # 每个平台×地区抓取条数
DEFAULT_DAYS = 7   # 默认回溯天数

# Claude API 配置
CLAUDE_API_KEY = os.environ.get("CLAUDE_API_KEY", "")
CLAUDE_API_URL = "https://ai.flashapi.top/v1/messages"
CLAUDE_MODEL = "claude-opus-4-6"  # 主模型


def call_claude(prompt, max_tokens=8192):
    """调用 Anthropic Native 格式的 Claude API"""
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
    with urllib.request.urlopen(req, timeout=120, context=ctx) as resp:
        result = json.loads(resp.read())
    return result["content"][0]["text"]


# ═══════════════════════════════════════════════════════════════
# 数据抓取
# ═══════════════════════════════════════════════════════════════

def fetch_gp(pkg, country, cutoff_dt):
    """抓取 Google Play 评论"""
    from google_play_scraper import reviews, Sort
    lang = REGIONS.get(country, {}).get("lang", "en")
    try:
        result, _ = reviews(pkg, lang=lang, country=country, sort=Sort.NEWEST, count=FETCH_COUNT)
    except Exception as e:
        print(f"    [GP] 抓取失败: {e}")
        return []
    rows = []
    for r in result:
        at = r["at"].replace(tzinfo=timezone.utc) if r["at"].tzinfo is None else r["at"]
        if at >= cutoff_dt:
            rows.append({
                "platform": "Google Play",
                "score": r["score"],
                "version": r.get("appVersion", "") or "",
                "content": r["content"],
            })
    return rows


def fetch_ios(app_id, country, cutoff_dt):
    """抓取 Apple App Store 评论"""
    rows = []
    for page in range(1, 11):
        if len(rows) >= FETCH_COUNT:
            break
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
            content = e.get("content", {}).get("label", "")
            score = int(e.get("im:rating", {}).get("label", 5))
            rows.append({
                "platform": "App Store",
                "score": score,
                "version": e.get("im:version", {}).get("label", ""),
                "content": content,
            })
    return rows


# ═══════════════════════════════════════════════════════════════
# AI 分析
# ═══════════════════════════════════════════════════════════════

CATEGORIES = "[问题抱怨]、[高价值功能请求]、[竞品对比]、[流失信号]、[正向反馈]、[其他]"


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


def label_reviews(rows):
    """使用 Claude 对评论打标"""
    if not rows:
        return rows
    id_map = {str(i): r["content"] for i, r in enumerate(rows)}
    try:
        resp_text = call_claude(
            build_label_prompt(id_map, CATEGORIES),
            max_tokens=4096
        )
        raw = resp_text.strip()
        if "```" in raw:
            raw = re.sub(r'^```(?:json)?\s*|\s*```$', '', raw, flags=re.DOTALL).strip()
        mapping = json.loads(raw)
        for i, r in enumerate(rows):
            r["label"] = mapping.get(str(i), "[其他]")
    except Exception as e:
        print(f"    [AI] 打标失败: {e}")
        for r in rows:
            r["label"] = "[其他]"
    return rows


def analyze_features(rows, app_name, days):
    """
    使用 Claude 深度分析评论中的产品信号。
    输出结构化分析报告。
    """
    if not rows:
        return {"summary": "暂无数据", "feature_requests": [], "localization_issues": [], "key_insights": []}

    feature_rows = rows

    # 标签分布
    label_dist = dict(Counter(r.get("label", "[其他]") for r in rows))
    platform_dist = dict(Counter(r.get("platform", "unknown") for r in rows))
    region_dist = dict(Counter(r.get("region_label", "") for r in rows))

    region_names = [f"{cfg.get('label', code)}({code})" for code, cfg in REGIONS.items()]
    prompt = build_competitor_detail_prompt(app_name, days, feature_rows, region_names, list(COMPETITORS.keys()))

    try:
        summary = call_claude(prompt, max_tokens=8192)
    except Exception as e:
        summary = f"AI 分析失败: {e}"

    # 提取功能需求关键词
    feature_keywords = Counter()
    for r in feature_rows:
        content = r.get("content", "").lower()
        # 提取可能的功能关键词
        words = re.findall(r'\b[a-z]{4,}\b', content)
        stop_words = {"this", "that", "with", "from", "have", "been", "was", "were",
                      "what", "when", "where", "there", "their", "about", "would",
                      "could", "should", "after", "still", "more", "some", "than",
                      "also", "other", "into", "only", "over", "such", "very",
                      "just", "because", "example", "but", "not", "they", "them",
                      "its", "has", "had", "can", "will", "may", "all", "are",
                      "for", "you", "your", "our", "the", "and", "app", "apps",
                      "does", "dont", "cant", "wont", "get", "got", "use", "used",
                      "using", "make", "made", "like", "time", "one", "even",
                      "much", "really", "please", "need", "needs", "want", "wants"}
        for w in words:
            if w not in stop_words and len(w) > 3:
                feature_keywords[w] += 1

    return {
        "summary": summary,
        "total_reviews": len(rows),
        "label_distribution": label_dist,
        "platform_distribution": platform_dist,
        "region_distribution": region_dist,
        "feature_keywords": dict(feature_keywords.most_common(20)),
        "feature_review_count": len(feature_rows),
    }


# ═══════════════════════════════════════════════════════════════
# 主流程
# ═══════════════════════════════════════════════════════════════

def analyze_competitor(comp_name, days=DEFAULT_DAYS):
    """分析单个竞品，返回结构化结果"""
    if comp_name not in COMPETITORS:
        print(f"错误: 未知竞品 '{comp_name}'，可选: {list(COMPETITORS.keys())}")
        return None

    if not CLAUDE_API_KEY:
        print("错误: 未设置 CLAUDE_API_KEY 环境变量")
        return None

    comp = COMPETITORS[comp_name]
    cutoff_dt = datetime.now(timezone.utc) - timedelta(days=days)
    print(f"\n{'='*60}")
    print(f"分析竞品: {comp_name}")
    print(f"回溯天数: {days} 天 (截止 {cutoff_dt.strftime('%Y-%m-%d')})")
    print(f"{'='*60}")

    all_reviews = []
    regions_data = {}

    for region_code, region_cfg in REGIONS.items():
        region_label = region_cfg["label"]
        print(f"\n--- {region_label} ({region_code}) ---")

        # Google Play
        print(f"  [GP] 抓取中...")
        gp_rows = fetch_gp(comp["gp"], region_code, cutoff_dt)
        for r in gp_rows:
            r["region"] = region_code
            r["region_label"] = region_label
        print(f"    Google Play: {len(gp_rows)} 条评论")

        # App Store
        print(f"  [iOS] 抓取中...")
        ios_rows = fetch_ios(comp["ios"], region_code, cutoff_dt)
        for r in ios_rows:
            r["region"] = region_code
            r["region_label"] = region_label
        print(f"    App Store: {len(ios_rows)} 条评论")

        region_rows = gp_rows + ios_rows
        all_reviews.extend(region_rows)

        # AI 打标
        if region_rows:
            if REGIONS.get(region_code, {}).get("lang", "en") != "en":
                print(f"  [翻译] 翻译为英文...")
                region_rows = translate_to_english(region_rows)
            print(f"  [AI] 打标中...")
            region_rows = label_reviews(region_rows)
            label_dist = dict(Counter(r.get("label", "[其他]") for r in region_rows))
            print(f"    标签分布: {label_dist}")
        else:
            label_dist = {}

        regions_data[region_code] = {
            "label": region_label,
            "gp_count": len(gp_rows),
            "ios_count": len(ios_rows),
            "total": len(region_rows),
            "labels": label_dist,
            "reviews": [
                {
                    "platform": r["platform"],
                    "score": r["score"],
                    "version": r.get("version", ""),
                    "label": r.get("label", ""),
                    "content": r["content"],
                }
                for r in region_rows
            ],
        }

    print(f"\n{'='*60}")
    print(f"总评论数: {len(all_reviews)} 条")
    print(f"正在生成深度功能分析报告...")

    # 全局 AI 分析
    feature_analysis = analyze_features(all_reviews, comp_name, days)

    # 构建输出
    result = {
        "competitor": comp_name,
        "generated_at": datetime.now().isoformat(),
        "days_analyzed": days,
        "total_reviews": len(all_reviews),
        "regions": regions_data,
        "feature_analysis": feature_analysis,
    }

    return result


def export_result(result):
    """导出分析结果到 JSON 文件"""
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    comp_name = result["competitor"]
    out_path = DATA_DIR / f"competitor_detail_{comp_name}.json"
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(result, f, ensure_ascii=False, indent=2)
    print(f"\n分析结果已导出: {out_path}")
    return out_path


def main():
    if len(sys.argv) < 2:
        print("用法: python3 competitor_detail.py <竞品名> [--days N]")
        print(f"可选竞品: {list(COMPETITORS.keys())}")
        sys.exit(1)

    comp_name = sys.argv[1]
    days = DEFAULT_DAYS
    if "--days" in sys.argv:
        idx = sys.argv.index("--days")
        if idx + 1 < len(sys.argv):
            days = int(sys.argv[idx + 1])

    result = analyze_competitor(comp_name, days)
    if result:
        export_result(result)
        print(f"\n数据已保存，刷新看板即可查看「{comp_name}」详情页")


if __name__ == "__main__":
    main()
