#!/usr/bin/env python3
"""comment_label.py — 读 raw 评论 → Claude 翻译/打标 → 写 competitor_comments.json

P0 拆分的 AI 部分。设计：
- 输入：data/raw/comments_raw.json（comment_fetch.py 产物）
- 输出：data/competitor_comments.json（与原 auto_report.py 完全兼容）
- **Checkpoint**：每个竞品打完标后立刻写盘 → 中途挂掉重跑只补缺失竞品
- 同日重跑默认跳过已完成竞品（--force 强制重跑）

输出 shape（与历史保持兼容，aggregator 直接消费）：
{
  "generated_at": "...",
  "date": "YYYY-MM-DD",
  "competitors": {
    "<name>": {
      "regions": {
        "<region>": {
          "count": int, "negative_count": int,
          "labels": {label: count}, "summary": "",
          "reviews": [{score, version, label, content}, ...]
        }
      }
    }
  }
}
"""

from __future__ import annotations

import argparse
import json
import os
import re
import ssl
import sys
import time
import urllib.request
from collections import Counter
from datetime import datetime
from pathlib import Path

_SCRIPT_DIR = Path(__file__).resolve().parent
_PROJECT_ROOT = _SCRIPT_DIR.parent
DATA_DIR = _PROJECT_ROOT / "data"
RAW_IN = DATA_DIR / "raw" / "comments_raw.json"
OUT_PATH = DATA_DIR / "competitor_comments.json"

if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

from regions import load_regions  # type: ignore
from prompts.comment_prompts import build_label_prompt  # type: ignore

CATEGORIES = "[问题抱怨]、[高价值功能请求]、[竞品对比]、[流失信号]、[正向反馈]、[其他]"
CLAUDE_API_KEY = os.environ.get("CLAUDE_API_KEY", "")
CLAUDE_API_URL = "https://ai.flashapi.top/v1/messages"
CLAUDE_MODEL = "claude-haiku-4-5-20251001"

_VALID_LABELS = {"[问题抱怨]", "[高价值功能请求]", "[竞品对比]", "[流失信号]", "[正向反馈]", "[其他]"}


def call_claude(prompt: str, max_tokens: int = 4096, timeout: int = 60, retries: int = 3) -> str:
    """Anthropic native 接口（沿用 auto_report.py）。"""
    last_error: Exception | None = None
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
    raise last_error  # type: ignore


def _normalize_label(raw_label: str) -> str:
    if not raw_label:
        return "[其他]"
    s = str(raw_label).strip().strip("'\"")
    if not s.startswith("["):
        s = "[" + s
    if not s.endswith("]"):
        s = s + "]"
    return s if s in _VALID_LABELS else "[其他]"


def _strip_codefence(raw: str) -> str:
    return re.sub(r'^```(?:json)?\s*|\s*```$', '', raw, flags=re.DOTALL).strip()


def translate_to_english(rows: list[dict]) -> list[dict]:
    """非英语区评论批量译为英文（一次 Claude 调用），失败忽略原样返回。"""
    if not rows:
        return rows
    id_map = {str(i): r["content"] for i, r in enumerate(rows) if r.get("content")}
    if not id_map:
        return rows
    prompt = (
        "Translate the following app reviews to English. "
        "Return a JSON object mapping each ID to its English translation. "
        "If already English, keep as-is. Output only JSON.\n\n"
        + json.dumps(id_map, ensure_ascii=False)
    )
    try:
        raw = _strip_codefence(call_claude(prompt))
        translations = json.loads(raw)
        for i, r in enumerate(rows):
            if str(i) in translations:
                r["content"] = translations[str(i)]
    except Exception as exc:
        print(f"  [AI] 翻译失败，保留原文: {exc}", file=sys.stderr)
    return rows


def label_rows(rows: list[dict]) -> list[dict]:
    """对评论批量打标（一次 Claude 调用）。失败时全部 [其他]。"""
    if not rows:
        return rows
    id_map = {str(i): r["content"] for i, r in enumerate(rows)}
    try:
        raw = _strip_codefence(call_claude(build_label_prompt(id_map, CATEGORIES)))
        mapping = json.loads(raw)
        for i, r in enumerate(rows):
            r["label"] = _normalize_label(mapping.get(str(i), "[其他]"))
    except Exception as exc:
        print(f"  [AI] 打标失败，降级 [其他]: {exc}", file=sys.stderr)
        for r in rows:
            r["label"] = "[其他]"
    return rows


def _load_existing_checkpoint(today: str) -> dict | None:
    """如果 OUT_PATH 已经存在且日期 == today，返回旧数据用于增量 / 跳过。"""
    if not OUT_PATH.exists():
        return None
    try:
        existing = json.loads(OUT_PATH.read_text(encoding="utf-8"))
    except Exception:
        return None
    if not isinstance(existing, dict):
        return None
    if existing.get("date") != today:
        return None
    return existing


def _process_competitor(app_name: str, app_raw: dict, region_info: dict) -> dict:
    """处理单个竞品：(region → rows) → (region → 含 label 的结构)。"""
    out_regions: dict[str, dict] = {}
    for region, region_data in (app_raw.get("regions") or {}).items():
        rows = list(region_data.get("rows") or [])
        if not rows:
            out_regions[region] = {
                "count": 0, "negative_count": 0, "labels": {}, "summary": "", "reviews": [],
            }
            continue
        # 翻译（仅非英语区）
        if region_info.get(region, {}).get("lang", "en") != "en":
            rows = translate_to_english(rows)
        rows = label_rows(rows)
        label_dist = dict(Counter(r["label"] for r in rows))
        negative_count = sum(1 for r in rows if r.get("score", 5) <= 3)
        out_regions[region] = {
            "count": len(rows),
            "negative_count": negative_count,
            "labels": label_dist,
            "summary": "",
            "reviews": [
                {"score": r["score"], "version": r.get("version", ""),
                 "label": r["label"], "content": r["content"]}
                for r in rows
            ],
        }
    return {"regions": out_regions}


def main(force: bool = False) -> Path:
    if not CLAUDE_API_KEY:
        print("错误: 未设置 CLAUDE_API_KEY 环境变量", file=sys.stderr)
        sys.exit(2)
    if not RAW_IN.exists():
        print(f"错误: 找不到 {RAW_IN}，请先跑 comment_fetch.py", file=sys.stderr)
        sys.exit(2)

    raw = json.loads(RAW_IN.read_text(encoding="utf-8"))
    today = datetime.now().strftime("%Y-%m-%d")
    region_info = load_regions()

    # Checkpoint：同日已完成竞品跳过
    existing = None if force else _load_existing_checkpoint(today)
    done_set: set[str] = set()
    if existing and existing.get("competitors"):
        out = existing
        out["generated_at"] = datetime.now().isoformat()  # 刷新时间戳
        for name, app_out in (out.get("competitors") or {}).items():
            # 视为完成：每个 region 都有 reviews（即使 0 条）
            regions = (app_out.get("regions") or {})
            if regions and all(("reviews" in r) for r in regions.values()):
                done_set.add(name)
        if done_set:
            print(f"[checkpoint] {len(done_set)} 竞品今日已完成，跳过：{sorted(done_set)}")
    else:
        out = {
            "generated_at": datetime.now().isoformat(),
            "date": today,
            "competitors": {},
        }

    competitors = raw.get("competitors") or {}
    pending = [name for name in competitors if name not in done_set]
    print(f"[label] 待处理 {len(pending)} 竞品 / 共 {len(competitors)} 竞品")

    DATA_DIR.mkdir(parents=True, exist_ok=True)
    for i, app_name in enumerate(pending, 1):
        t0 = time.monotonic()
        app_raw = competitors[app_name]
        print(f"[{i}/{len(pending)}] {app_name} 打标中...")
        out["competitors"][app_name] = _process_competitor(app_name, app_raw, region_info)
        # 每个竞品完成立即落盘 — 中途挂掉重跑能跳过
        OUT_PATH.write_text(json.dumps(out, ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"  -> 已写盘（{time.monotonic() - t0:.1f}s）")

    print(f"\n[OK] 评论标签已保存 -> {OUT_PATH}（{len(out['competitors'])} 竞品）")
    return OUT_PATH


def cli() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--force", action="store_true", help="忽略当日 checkpoint，全部重跑")
    args = ap.parse_args()
    main(force=args.force)


if __name__ == "__main__":
    cli()
