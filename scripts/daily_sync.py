#!/usr/bin/env python3
"""daily_sync.py — 每日 02:00 自动跑（launchd 触发）。

3 阶段流水线：
  Phase 1（并行）：所有抓取源（HTTP + Playwright），目标 ~3 min
  Phase 2（串行）：comment_label + commercial_strategy（AI 重活），目标 ~15 min
  Phase 3：generate_dashboard 聚合 → 重新生成静态 HTML

设计：
- 每个子任务独立 timeout（不让一个慢任务拖死全部）
- 每个子任务跑完写 sync_state.json + sync_log.json（与 dashboard 现有 telemetry 兼容）
- Playwright 源 exit=2 → 标 cookie_status=expired + 触发 macOS 通知
- 失败不阻塞下一个；orchestrator 最后汇总成功/失败计数
- --max-age-hours 检查避免重复跑（默认 20h，给 launchd 误差留弹性）
- --force 强制重跑

CLI:
  python3 scripts/daily_sync.py            # 正常跑（带新鲜度跳过）
  python3 scripts/daily_sync.py --force    # 全部重跑
  python3 scripts/daily_sync.py --dry-run  # 只打印计划，不执行
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime
from pathlib import Path
from typing import Optional

_PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

# 兜底加载 .env.local
try:
    from shared.env_loader import load_env_file
    load_env_file()
except Exception:
    pass

from shared import sync_state  # noqa: E402

PYTHON = sys.executable
SYNC_LOG_PATH = _PROJECT_ROOT / "data" / "sync_log.json"
SYNC_LOG_MAX_ENTRIES = 50

# ---- 任务定义 -------------------------------------------------------------

# Phase 1：纯抓取（并行）。每条：(name, label, args, timeout_s, kind)
#   kind: "http"（HTTP API/scrape）/ "playwright"（需 cookie）
PHASE_1_FETCHERS = [
    # HTTP - async_crawler 单源调用
    ("appstore_rank", "App Store 排名",
        ["-m", "async_crawler", "--sources", "appstore_rank"], 120, "http"),
    ("androidrank", "Androidrank 历史",
        ["-m", "async_crawler", "--sources", "androidrank"], 180, "http"),
    ("reddit", "Reddit 舆情",
        ["-m", "async_crawler", "--sources", "reddit"], 240, "http"),
    ("twitter", "X (Twitter)",
        ["-m", "async_crawler", "--sources", "twitter"], 120, "http"),
    ("google_news", "Google 商业新闻",
        ["-m", "async_crawler", "--sources", "google_news"], 180, "http"),
    # 评论原始抓取（拆出来的快路径）
    ("comment_fetch", "评论抓取（GP+iOS）",
        ["-m", "competitor_comment.comment_fetch"], 300, "http"),
    # 产品动态（含轻量 AI 解读 diff，沿用现状）
    ("strategy_monitor", "产品动态监测",
        [str(_PROJECT_ROOT / "strategy_monitor" / "run_headless.py")], 180, "http"),
    # Playwright - 三个手动登录源
    ("appmagic", "AppMagic 排名",
        [str(_PROJECT_ROOT / "market_rank" / "run_headless.py")], 240, "playwright"),
    ("fb_adlib", "Meta 广告库",
        ["-m", "market_rank.scrape_fb_adlib", "scrape"], 600, "playwright"),
    ("sensor_tower", "Sensor Tower",
        ["-m", "market_rank.scrape_sensor_tower", "scrape"], 300, "playwright"),
]

# Phase 2：AI 重活（串行；失败不阻塞下一个）
PHASE_2_AI = [
    ("comment_label", "评论 AI 标签",
        ["-m", "competitor_comment.comment_label"], 1500),
    ("commercial_strategy", "商业策略分析",
        [str(_PROJECT_ROOT / "commercial_strategy" / "run_headless.py")], 600),
]

# Phase 3：聚合
PHASE_3_AGG = [
    ("generate_dashboard", "看板生成（聚合）",
        [str(_PROJECT_ROOT / "main_dashboard" / "generate_dashboard.py")], 120),
]

DAILY_MAX_AGE_HOURS = 20.0  # 各源新鲜度阈值（launchd 02:00 ± 抖动）


# ---- 子任务运行 -----------------------------------------------------------

def _run_one(name: str, label: str, args: list[str], timeout: int) -> dict:
    """跑一个子进程，返回结果 dict（含 success/exit_code/duration/output_tail）。"""
    cmd = [PYTHON] + args
    started_at = datetime.now().isoformat(timespec="seconds")
    sync_state.mark_attempt(name)
    t0 = time.monotonic()
    try:
        result = subprocess.run(
            cmd,
            cwd=str(_PROJECT_ROOT),
            capture_output=True,
            text=True,
            timeout=timeout,
            env=os.environ.copy(),
        )
        success = (result.returncode == 0)
        return {
            "name": name, "label": label, "started_at": started_at,
            "duration_sec": round(time.monotonic() - t0, 1),
            "exit_code": result.returncode, "success": success,
            "stdout_tail": (result.stdout or "")[-1500:],
            "stderr_tail": (result.stderr or "")[-1500:],
            "kind": None,
            "cmd": " ".join(cmd),
        }
    except subprocess.TimeoutExpired as e:
        return {
            "name": name, "label": label, "started_at": started_at,
            "duration_sec": round(time.monotonic() - t0, 1),
            "exit_code": -1, "success": False,
            "stdout_tail": (e.stdout or "")[-1500:] if isinstance(e.stdout, str) else "",
            "stderr_tail": f"执行超时（{timeout}s）",
            "kind": "timeout",
            "cmd": " ".join(cmd),
        }
    except Exception as exc:
        return {
            "name": name, "label": label, "started_at": started_at,
            "duration_sec": round(time.monotonic() - t0, 1),
            "exit_code": -2, "success": False,
            "stdout_tail": "", "stderr_tail": f"{type(exc).__name__}: {exc}",
            "kind": "exception",
            "cmd": " ".join(cmd),
        }


def _post_process(result: dict, source_kind: str) -> None:
    """跑完一个任务后写 sync_state + sync_log + 检测 LoginRequired。"""
    name = result["name"]
    success = result["success"]

    # LoginRequired 检测（exit=2 + stderr 含 LoginRequired，约定见 scrape_*.py）
    is_login_required = (
        source_kind == "playwright"
        and result["exit_code"] == 2
        and ("LoginRequired" in (result.get("stderr_tail") or "")
             or "登录态" in (result.get("stderr_tail") or ""))
    )
    if is_login_required:
        sync_state.mark_cookie_expired(name)
        result["kind"] = "login_required"
    elif success:
        sync_state.mark_success(name)
        if source_kind == "playwright":
            sync_state.mark_cookie_ok(name)
    else:
        kind = result.get("kind") or ("error" if result["exit_code"] != 0 else "unknown")
        sync_state.mark_failure(name, kind, result.get("stderr_tail", ""))

    _append_sync_log({
        "script": name,
        "label": result["label"],
        "competitor": None,
        "started_at": result["started_at"],
        "finished_at": datetime.now().isoformat(timespec="seconds"),
        "duration_sec": result["duration_sec"],
        "success": success,
        "error_kind": result.get("kind"),
        "stdout_tail": result.get("stdout_tail", ""),
        "stderr_tail": result.get("stderr_tail", ""),
        "cmd": result.get("cmd", ""),
    })


def _append_sync_log(entry: dict) -> None:
    try:
        entries = []
        if SYNC_LOG_PATH.exists():
            try:
                entries = json.loads(SYNC_LOG_PATH.read_text(encoding="utf-8")) or []
                if not isinstance(entries, list):
                    entries = []
            except Exception:
                entries = []
        entries.append(entry)
        entries = entries[-SYNC_LOG_MAX_ENTRIES:]
        SYNC_LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
        SYNC_LOG_PATH.write_text(json.dumps(entries, ensure_ascii=False, indent=2), encoding="utf-8")
    except Exception as exc:
        print(f"[sync_log] 写入失败: {exc}", file=sys.stderr)


# ---- 通知 ----------------------------------------------------------------

def _notify(title: str, msg: str) -> None:
    """macOS osascript 弹通知；非 mac 平台直接 print。"""
    if sys.platform == "darwin":
        try:
            safe_title = title.replace('"', '\\"')
            safe_msg = msg.replace('"', '\\"')
            subprocess.run([
                "osascript", "-e",
                f'display notification "{safe_msg}" with title "{safe_title}"',
            ], timeout=5, check=False)
            return
        except Exception:
            pass
    print(f"[NOTIFY] {title}: {msg}")


# ---- Phase runners --------------------------------------------------------

def _should_skip(name: str, force: bool, max_age_hours: float) -> bool:
    if force:
        return False
    return sync_state.is_fresh(name, max_age_hours)


def run_phase_1(force: bool, max_age_hours: float, dry_run: bool) -> tuple[int, int, list[str]]:
    """并行跑所有抓取源；返回 (ok, fail, expired_cookies)。"""
    print("\n" + "=" * 70)
    print(f"Phase 1/3 — 抓取源（{len(PHASE_1_FETCHERS)} 个并行）")
    print("=" * 70)
    expired: list[str] = []
    skipped: list[str] = []
    pending = []
    for name, label, args, to, kind in PHASE_1_FETCHERS:
        if _should_skip(name, force, max_age_hours):
            print(f"[skip] {name} 上次成功 < {max_age_hours}h，跳过")
            skipped.append(name)
            continue
        pending.append((name, label, args, to, kind))

    if dry_run:
        for name, label, args, to, kind in pending:
            print(f"[dry-run] {name} ({label}) timeout={to}s kind={kind}")
        return (len(pending), 0, [])

    ok = fail = 0
    futures = {}
    with ThreadPoolExecutor(max_workers=min(len(pending), 6) or 1) as ex:
        for name, label, args, to, kind in pending:
            futures[ex.submit(_run_one, name, label, args, to)] = (name, kind)
            print(f"[start] {name} ({label})")
        for fut in as_completed(futures):
            name, kind = futures[fut]
            result = fut.result()
            _post_process(result, kind)
            tag = "✓" if result["success"] else "✗"
            ekind = result.get("kind") or ""
            print(f"  [{tag}] {name}  {result['duration_sec']}s  exit={result['exit_code']}  {ekind}")
            if result["success"]:
                ok += 1
            else:
                fail += 1
                if result.get("kind") == "login_required":
                    expired.append(name)
    if skipped:
        print(f"[phase1] {len(skipped)} 个跳过：{skipped}")
    print(f"[phase1] 完成：ok={ok} fail={fail}")
    return (ok, fail, expired)


def run_phase_2(force: bool, max_age_hours: float, dry_run: bool) -> tuple[int, int]:
    """串行跑 AI 重活；失败不阻塞后续。"""
    print("\n" + "=" * 70)
    print(f"Phase 2/3 — AI 分析（{len(PHASE_2_AI)} 个串行）")
    print("=" * 70)
    ok = fail = 0
    for name, label, args, to in PHASE_2_AI:
        if _should_skip(name, force, max_age_hours):
            print(f"[skip] {name}")
            continue
        if dry_run:
            print(f"[dry-run] {name} ({label}) timeout={to}s")
            continue
        print(f"[start] {name} ({label})")
        result = _run_one(name, label, args, to)
        _post_process(result, "ai")
        tag = "✓" if result["success"] else "✗"
        print(f"  [{tag}] {name}  {result['duration_sec']}s  exit={result['exit_code']}")
        if result["success"]:
            ok += 1
        else:
            fail += 1
    print(f"[phase2] 完成：ok={ok} fail={fail}")
    return (ok, fail)


def run_phase_3(dry_run: bool) -> bool:
    print("\n" + "=" * 70)
    print("Phase 3/3 — 聚合 + 生成看板")
    print("=" * 70)
    for name, label, args, to in PHASE_3_AGG:
        if dry_run:
            print(f"[dry-run] {name} timeout={to}s")
            return True
        print(f"[start] {name} ({label})")
        result = _run_one(name, label, args, to)
        _post_process(result, "aggregate")
        tag = "✓" if result["success"] else "✗"
        print(f"  [{tag}] {name}  {result['duration_sec']}s  exit={result['exit_code']}")
        if not result["success"]:
            return False
    return True


# ---- main -----------------------------------------------------------------

def main(argv: Optional[list[str]] = None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--force", action="store_true", help="忽略新鲜度，全部重跑")
    ap.add_argument("--max-age-hours", type=float, default=DAILY_MAX_AGE_HOURS)
    ap.add_argument("--dry-run", action="store_true", help="只打印计划不执行")
    args = ap.parse_args(argv)

    t0 = time.monotonic()
    print(f"=== daily_sync 开始 {datetime.now().isoformat(timespec='seconds')} ===")
    print(f"force={args.force}  max-age={args.max_age_hours}h  dry-run={args.dry_run}")

    p1_ok, p1_fail, expired = run_phase_1(args.force, args.max_age_hours, args.dry_run)
    p2_ok, p2_fail = run_phase_2(args.force, args.max_age_hours, args.dry_run)
    p3_ok = run_phase_3(args.dry_run)

    total = time.monotonic() - t0
    total_fail = p1_fail + p2_fail + (0 if p3_ok else 1)
    print("\n" + "=" * 70)
    print(f"=== daily_sync 完成 — 总耗时 {total/60:.1f} min ===")
    print(f"  Phase 1: ok={p1_ok} fail={p1_fail}")
    print(f"  Phase 2: ok={p2_ok} fail={p2_fail}")
    print(f"  Phase 3: {'ok' if p3_ok else 'fail'}")
    print("=" * 70)

    # 通知
    if expired:
        _notify("INTEL-OPS · Cookie 失效", f"{', '.join(expired)} 需要重新登录")
    if total_fail >= 3:
        _notify("INTEL-OPS · 同步告警", f"今日同步 {total_fail} 个任务失败，详情见 sync_log")
    elif total / 60 > 30:
        _notify("INTEL-OPS · 同步耗时告警", f"今日同步耗时 {total/60:.0f} 分钟（>30 min）")

    return 0 if total_fail == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
