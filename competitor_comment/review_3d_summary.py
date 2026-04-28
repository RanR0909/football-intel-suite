#!/usr/bin/env python3
"""单竞品 3 日评论 AI 摘要。

用法:
  python3 competitor_comment/review_3d_summary.py SofaScore
  python3 competitor_comment/review_3d_summary.py SofaScore --days 3

产出：data/review_3d_<competitor>.json
{
  "competitor": "SofaScore",
  "generated_at": "ISO 时间",
  "window_days": 3,
  "sample_count": 47,
  "summary": "... 200-400 字摘要 ...",
  "sentiment": {"positive": 0.21, "neutral": 0.43, "negative": 0.36},
  "top_pains": [{"topic": "登录卡顿", "count": 5, "severity": 4, "sample_quote": "..."}, ...],
  "top_quotes": ["...", "..."],
  "tagged_topics": ["登录", "推送", "直播延迟"]
}

数据来源：data/competitor_comments.json 中该竞品 regions[*].reviews 切片，
         按 timestamp ≥ now - days 过滤。

模型：claude-haiku-4-5（快速 + 便宜，单次调用 ≤ 5K token）。
"""

import argparse
import json
import os
import sys
from datetime import datetime, timezone, timedelta
from pathlib import Path

_SCRIPT_DIR = Path(__file__).resolve().parent
_PROJECT_ROOT = _SCRIPT_DIR.parent
DATA_DIR = _PROJECT_ROOT / "data"

if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

from shared.ai_client import run_task  # noqa: E402

CLAUDE_API_KEY = os.environ.get("CLAUDE_API_KEY", "")  # 兼容旧入口检查


def _parse_iso(ts: str | None):
    if not ts:
        return None
    try:
        s = ts.replace("Z", "+00:00")
        return datetime.fromisoformat(s)
    except Exception:
        return None


def _collect_reviews(competitor: str, days: int) -> list[dict]:
    """从 competitor_comments.json 中切出该竞品近 N 天评论。"""
    src = DATA_DIR / "competitor_comments.json"
    if not src.exists():
        print(f"[WARN] {src} 不存在", file=sys.stderr)
        return []
    payload = json.loads(src.read_text(encoding="utf-8"))
    comp_info = (payload.get("competitors") or {}).get(competitor) or {}
    cutoff = datetime.now(timezone.utc) - timedelta(days=days)
    out: list[dict] = []
    for region_code, region_data in (comp_info.get("regions") or {}).items():
        for r in region_data.get("reviews") or []:
            ts = _parse_iso(r.get("date") or r.get("timestamp"))
            if ts and ts < cutoff:
                continue
            out.append({
                "region": region_code,
                "rating": r.get("rating") or r.get("score") or 0,
                "content": (r.get("content") or r.get("text") or "")[:600],
                "label": r.get("label") or "",
                "date": r.get("date") or r.get("timestamp") or "",
            })
    return out


def _quick_sentiment(reviews: list[dict]) -> dict:
    """基于 rating + label 反推情绪分布（label 优先，rating 兜底）。"""
    pos = neu = neg = 0
    for r in reviews:
        lab = (r.get("label") or "").lower()
        if "正面" in lab or "积极" in lab or "positive" in lab:
            pos += 1
        elif "负面" in lab or "问题" in lab or "流失" in lab or "negative" in lab:
            neg += 1
        elif lab:
            neu += 1
        else:
            rating = int(r.get("rating") or 0)
            if rating >= 4:
                pos += 1
            elif rating <= 2:
                neg += 1
            else:
                neu += 1
    total = pos + neu + neg or 1
    return {
        "positive": round(pos / total, 3),
        "neutral":  round(neu / total, 3),
        "negative": round(neg / total, 3),
    }


def _format_samples(reviews: list[dict]) -> str:
    """格式化评论样本为 prompt 内嵌字符串（review_3d 任务 prompt 模板的 {samples} 槽）。"""
    if not reviews:
        return "（无评论样本）"
    lines = []
    for i, r in enumerate(reviews[:80]):
        snippet = (r.get("content") or "").replace("\n", " ")[:240]
        lines.append(f"[{i+1}] ({r.get('region')} · {r.get('rating')}星) {snippet}")
    return "\n".join(lines)


def run(competitor: str, days: int = 3) -> dict:
    if not (os.environ.get("CLAUDE_API_KEY") or os.environ.get("ANTHROPIC_API_KEY")):
        raise RuntimeError("CLAUDE_API_KEY / ANTHROPIC_API_KEY 未配置（环境变量）")
    reviews = _collect_reviews(competitor, days)
    sentiment = _quick_sentiment(reviews)

    if not reviews:
        result = {
            "competitor": competitor,
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "window_days": days,
            "sample_count": 0,
            "summary": f"近 {days} 天 {competitor} 无评论样本，无法生成 AI 摘要。",
            "sentiment": sentiment,
            "top_pains": [],
            "top_quotes": [],
            "tagged_topics": [],
            "skipped": True,
        }
    else:
        # run_task 返回 dict（review_3d output_format=json + json_strip_markdown=true）
        ai_payload = run_task("review_3d", context={
            "competitor": competitor,
            "days": days,
            "count": len(reviews),
            "samples": _format_samples(reviews),
        })
        if not isinstance(ai_payload, dict):
            ai_payload = {"_parse_error": True}
        result = {
            "competitor": competitor,
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "window_days": days,
            "sample_count": len(reviews),
            "sentiment": sentiment,
            "summary":      ai_payload.get("summary") or "",
            "top_pains":    ai_payload.get("top_pains") or [],
            "top_quotes":   ai_payload.get("top_quotes") or [],
            "tagged_topics":ai_payload.get("tagged_topics") or [],
        }
        if ai_payload.get("_parse_error"):
            result["_parse_error"] = True

    out = DATA_DIR / f"review_3d_{competitor}.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"[OK] {competitor} 3 日评论 AI 摘要 → {out}")
    print(f"     样本 {len(reviews)} 条 · 情绪 +{int(sentiment['positive']*100)}% "
          f"/-{int(sentiment['negative']*100)}%")
    return result


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("competitor", help="竞品名（如 SofaScore）")
    ap.add_argument("--days", type=int, default=3, help="时间窗口（默认 3）")
    args = ap.parse_args()
    run(args.competitor, days=args.days)


if __name__ == "__main__":
    main()
