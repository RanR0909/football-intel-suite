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
import ssl
import sys
import time
import urllib.request
from datetime import datetime, timezone, timedelta
from pathlib import Path

_SCRIPT_DIR = Path(__file__).resolve().parent
_PROJECT_ROOT = _SCRIPT_DIR.parent
DATA_DIR = _PROJECT_ROOT / "data"

CLAUDE_API_KEY = os.environ.get("CLAUDE_API_KEY", "")
CLAUDE_API_URL = "https://ai.flashapi.top/v1/messages"
CLAUDE_MODEL = "claude-haiku-4-5-20251001"


def call_claude(prompt: str, max_tokens: int = 4096, timeout: int = 60, retries: int = 3) -> str:
    last_error = None
    for attempt in range(1, retries + 1):
        try:
            data = json.dumps({
                "model": CLAUDE_MODEL,
                "max_tokens": max_tokens,
                "messages": [{"role": "user", "content": prompt}],
            }).encode("utf-8")
            req = urllib.request.Request(
                CLAUDE_API_URL,
                data=data,
                headers={
                    "Content-Type": "application/json",
                    "x-api-key": CLAUDE_API_KEY,
                    "anthropic-version": "2023-06-01",
                },
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


def _build_prompt(competitor: str, reviews: list[dict], days: int) -> str:
    samples = []
    for i, r in enumerate(reviews[:80]):
        snippet = (r.get("content") or "").replace("\n", " ")[:240]
        samples.append(f"[{i+1}] ({r.get('region')} · {r.get('rating')}星) {snippet}")
    sample_block = "\n".join(samples) if samples else "（无评论样本）"
    return f"""你是资深竞品分析师。下面是 **{competitor}** 应用近 {days} 天的用户评论样本（共 {len(reviews)} 条），请生成结构化 JSON 报告。

要求：
1. 200-400 字中文摘要，聚焦本期内"用户在抱怨什么 / 在表扬什么 / 是否有突发问题"
2. 抽出 Top 3-5 个用户痛点（每个：topic 短语、count 出现次数、severity 1-5、sample_quote 用户原话不超 60 字）
3. 抽出 Top 3-5 条代表原话（直接引用用户的句子，正面或负面均可，每条 ≤ 80 字）
4. 抽出本期高频话题标签 3-8 个（分词，例：登录 / 推送 / 直播 / UI / 数据准确性）

只输出严格的 JSON（无 markdown 代码框），格式：
{{
  "summary": "...",
  "top_pains": [
    {{"topic":"...", "count": N, "severity": 1-5, "sample_quote":"..."}}
  ],
  "top_quotes": ["...", "..."],
  "tagged_topics": ["...", "..."]
}}

评论样本：
{sample_block}
"""


def _strip_json(text: str) -> str:
    s = text.strip()
    if s.startswith("```"):
        s = s.split("```", 2)[1]
        if s.lower().startswith("json"):
            s = s[4:]
        s = s.rsplit("```", 1)[0]
    return s.strip()


def run(competitor: str, days: int = 3) -> dict:
    if not CLAUDE_API_KEY:
        raise RuntimeError("CLAUDE_API_KEY 未配置（环境变量）")
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
        prompt = _build_prompt(competitor, reviews, days)
        raw = call_claude(prompt)
        try:
            ai_payload = json.loads(_strip_json(raw))
        except json.JSONDecodeError:
            ai_payload = {
                "summary": raw[:1200],
                "top_pains": [],
                "top_quotes": [],
                "tagged_topics": [],
                "_parse_error": True,
            }
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
