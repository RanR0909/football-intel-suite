#!/usr/bin/env python3
"""
weekly_review.py — 竞品评论周报生成器
收集各主要竞品过去7天的评论，汇总关键点（尤其产品功能方面），
按地区分析相关问题，生成结构化 JSON 供看板使用。

用法:
  export CLAUDE_API_KEY="your_key"
  python3 competitor_comment/weekly_review.py
"""

import os, json, re, sys, urllib.request, ssl, time
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
from prompts.comment_prompts import (
    build_label_prompt,
    build_weekly_report_prompt,
    build_localization_prompt,
)

# ── 竞品配置 ──────────────────────────────────────────────────
COMPETITORS = get_comment_competitors()
REGIONS = load_regions()

FETCH_COUNT = 200
DEFAULT_DAYS = 7

# Claude API 配置
CLAUDE_API_KEY = os.environ.get("CLAUDE_API_KEY", "")
CLAUDE_API_URL = "https://ai.flashapi.top/v1/messages"
CLAUDE_MODEL = "claude-opus-4-6"  # 主模型


def call_claude(prompt, max_tokens=8192, timeout=120, retries=3):
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
            updated = e.get("updated", {}).get("label", "")
            try:
                updated_at = datetime.fromisoformat(updated.replace("Z", "+00:00"))
            except Exception:
                updated_at = None
            if updated_at and updated_at < cutoff_dt:
                continue
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


def generate_weekly_report(all_data, days):
    """
    使用 Claude 生成周报摘要。
    汇总所有竞品过去N天的评论，按竞品、地区、功能维度分析。
    """
    if not all_data:
        return {"summary": "暂无数据", "per_competitor": {}, "localization_insights": {}}

    per_comp_summaries = {}
    all_reviews_flat = []

    for comp_name, comp_info in all_data.items():
        comp_reviews = []
        for region_code, region_info in comp_info.get("regions", {}).items():
            for r in region_info.get("reviews", []):
                r_copy = dict(r)
                r_copy["region"] = region_code
                r_copy["region_label"] = REGIONS.get(region_code, {}).get("label", region_code)
                comp_reviews.append(r_copy)
                all_reviews_flat.append(r_copy)

        per_comp_summaries[comp_name] = {
            "total": len(comp_reviews),
            "regions": {code: {"count": info.get("total", 0), "labels": info.get("labels", {})}
                       for code, info in comp_info.get("regions", {}).items()},
        }

    if not all_reviews_flat:
        return {"summary": f"过去{days}天无评论数据", "per_competitor": per_comp_summaries, "localization_insights": {}}

    # ── 生成全局周报摘要 ──
    # 按竞品组织样本
    comp_samples = {}
    for r in all_reviews_flat:
        cn = r.get("competitor", "unknown")
        if cn not in comp_samples:
            comp_samples[cn] = []
        comp_samples[cn].append(r)

    # 统计
    total_reviews = len(all_reviews_flat)
    label_dist = dict(Counter(r.get("label", "[其他]") for r in all_reviews_flat))
    platform_dist = dict(Counter(r.get("platform", "unknown") for r in all_reviews_flat))
    region_dist = dict(Counter(r.get("region_label", "") for r in all_reviews_flat))

    competitor_lines = []
    for comp_name, comp_summary in per_comp_summaries.items():
        region_parts = []
        for region_code, region_info in comp_summary.get("regions", {}).items():
            region_label = REGIONS.get(region_code, {}).get("label", region_code)
            labels_text = "、".join(
                f"{label}:{count}"
                for label, count in region_info.get("labels", {}).items()
            ) or "无标签"
            region_parts.append(
                f"{region_label}({region_code}) {region_info.get('count', 0)}条 [{labels_text}]"
            )
        competitor_lines.append(
            f"{comp_name}: 总计{comp_summary.get('total', 0)}条；"
            + "；".join(region_parts)
        )

    region_lines = []
    for region_code, region_cfg in REGIONS.items():
        region_label = region_cfg.get("label", region_code)
        comp_parts = []
        for comp_name, comp_info in all_data.items():
            region_info = comp_info.get("regions", {}).get(region_code, {})
            labels_text = "、".join(
                f"{label}:{count}"
                for label, count in region_info.get("labels", {}).items()
            ) or "无标签"
            comp_parts.append(
                f"{comp_name} {region_info.get('total', 0)}条 [{labels_text}]"
            )
        region_lines.append(f"{region_label}({region_code}): " + "；".join(comp_parts))

    competitor_names = list(per_comp_summaries.keys())
    region_names = [f"{cfg.get('label', code)}({code})" for code, cfg in REGIONS.items()]

    # 本地化相关评论
    localization_reviews = [r for r in all_reviews_flat if r.get("label") in ("[高价值功能请求]", "[问题抱怨]", "[竞品对比]")]
    localization_by_region = {}
    for r in localization_reviews:
        reg = r.get("region_label", "unknown")
        if reg not in localization_by_region:
            localization_by_region[reg] = []
        localization_by_region[reg].append(r["content"][:120])

    prompt = build_weekly_report_prompt(
        days=days,
        competitor_names=competitor_names,
        region_names=region_names,
        total_reviews=total_reviews,
        label_dist=label_dist,
        platform_dist=platform_dist,
        region_dist=region_dist,
        competitor_lines=competitor_lines,
        region_lines=region_lines,
        comp_samples=comp_samples,
        competitor_names_for_signal=competitor_names,
    )

    try:
        summary = call_claude(prompt, max_tokens=8192)
    except Exception as e:
        summary = f"AI 分析失败: {e}"

    # ── 本地化专题摘要 ──
    loc_prompt = build_localization_prompt(region_names, localization_reviews, competitor_names)

    try:
        localization_insight = call_claude(loc_prompt, max_tokens=4096)
    except Exception as e:
        localization_insight = f"本地化分析失败: {e}"

    # ── 提取功能关键词 ──
    feature_keywords = Counter()
    for r in all_reviews_flat:
        content = r.get("content", "").lower()
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
        "localization_insight": localization_insight,
        "per_competitor": per_comp_summaries,
        "total_reviews": total_reviews,
        "label_distribution": label_dist,
        "platform_distribution": platform_dist,
        "region_distribution": region_dist,
        "feature_keywords": dict(feature_keywords.most_common(30)),
        "localization_review_count": len(localization_reviews),
        "localization_by_region": {k: len(v) for k, v in localization_by_region.items()},
        "generated_at": datetime.now().isoformat(),
    }


# ═══════════════════════════════════════════════════════════════
# 主流程
# ═══════════════════════════════════════════════════════════════

def run_weekly_review(days=DEFAULT_DAYS):
    """运行周报分析"""
    if not CLAUDE_API_KEY:
        print("错误: 未设置 CLAUDE_API_KEY 环境变量")
        return None

    cutoff_dt = datetime.now(timezone.utc) - timedelta(days=days)
    print(f"\n{'='*60}")
    print(f"竞品评论周报生成器")
    print(f"回溯天数: {days} 天 (截止 {cutoff_dt.strftime('%Y-%m-%d')})")
    print(f"{'='*60}")

    all_data = {}

    for comp_name, comp in COMPETITORS.items():
        print(f"\n--- {comp_name} ---")
        comp_reviews = []
        regions_data = {}

        for region_code, region_cfg in REGIONS.items():
            region_label = region_cfg["label"]
            print(f"  [{region_label}] 抓取中...")

            gp_rows = fetch_gp(comp["gp"], region_code, cutoff_dt)
            for r in gp_rows:
                r["region"] = region_code
                r["region_label"] = region_label
                r["competitor"] = comp_name

            ios_rows = fetch_ios(comp["ios"], region_code, cutoff_dt)
            for r in ios_rows:
                r["region"] = region_code
                r["region_label"] = region_label
                r["competitor"] = comp_name

            region_rows = gp_rows + ios_rows
            if region_rows:
                if REGIONS.get(region_code, {}).get("lang", "en") != "en":
                    print(f"    翻译为英文...")
                    region_rows = translate_to_english(region_rows)
                region_rows = label_reviews(region_rows)
                label_dist = dict(Counter(r.get("label", "[其他]") for r in region_rows))
            else:
                label_dist = {}

            comp_reviews.extend(region_rows)

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

            print(f"    GP:{len(gp_rows)} iOS:{len(ios_rows)} 总计:{len(region_rows)}")

        all_data[comp_name] = {
            "total": len(comp_reviews),
            "regions": regions_data,
        }

    print(f"\n{'='*60}")
    print(f"总评论数: {sum(d['total'] for d in all_data.values())} 条")
    print(f"正在生成周报...")

    report = generate_weekly_report(all_data, days)
    report["competitors"] = all_data
    report["days_analyzed"] = days

    return report


def export_report(report):
    """导出周报到 JSON 文件"""
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    out_path = DATA_DIR / "weekly_review.json"
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(report, f, ensure_ascii=False, indent=2)
    print(f"\n周报已导出: {out_path}")
    return out_path


def main():
    days = DEFAULT_DAYS
    if "--days" in sys.argv:
        idx = sys.argv.index("--days")
        if idx + 1 < len(sys.argv):
            days = int(sys.argv[idx + 1])

    report = run_weekly_review(days)
    if report:
        export_report(report)
        print(f"\n周报数据已保存，刷新看板即可查看")


if __name__ == "__main__":
    main()
