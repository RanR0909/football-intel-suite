#!/usr/bin/env python3
"""daily_sync.py — 每日 02:00 自动跑（launchd 触发）。

3 阶段流水线：
  Phase 1（并行）：所有抓取源（HTTP + Playwright），目标 ~3 min
  Phase 2（串行）：comment_label + commercial_strategy（AI 重活），目标 ~15 min
  Phase 3：data_pipeline.aggregator → dashboard_data.json（v2 backend 派生 alerts/news 用）

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
    from shared.env_loader import load_all as _load_env_all
    _load_env_all()  # .env.local + ~/.intelops-secrets fallback
except Exception:
    pass

from shared import sync_state  # noqa: E402
from shared import retry_queue  # noqa: E402
from shared import feishu_notify  # noqa: E402

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
    # google_news 已迁到 weekly_sync（RSS 模式 + 周更，无需 API key）
    # ("google_news", "Google 商业新闻", ...) — 见 weekly_sync.py
    # 评论原始抓取（拆出来的快路径；9 竞品 × 12 区 GP 实际需 5-10 分钟）
    ("comment_fetch", "评论抓取（GP+iOS）",
        ["-m", "competitor_comment.comment_fetch"], 900, "http"),
    # 产品动态：strategy_monitor/run_headless.py 已废（文件不存在）；
    # 版本变化数据由 comment_fetch（带 review.version）+ aggregator 派生 product_updates.items 提供。
    # Playwright - 三个手动登录源
    ("appmagic", "AppMagic 排名",
        ["-m", "market_rank.run_headless"], 240, "playwright"),
    # fb_adlib 拆 per-country：原来全 5 国串行 1200s 仍超时，
    # 现在每国一个独立任务（9 竞品 × 1 国 ≈ 200-300s），并行跑 → wall-time 约 5 min
    ("fb_adlib_us", "Meta 广告 · 美国",
        ["-m", "market_rank.scrape_fb_adlib", "scrape", "--country", "US"], 600, "playwright"),
    ("fb_adlib_gb", "Meta 广告 · 英国",
        ["-m", "market_rank.scrape_fb_adlib", "scrape", "--country", "GB"], 600, "playwright"),
    ("fb_adlib_br", "Meta 广告 · 巴西",
        ["-m", "market_rank.scrape_fb_adlib", "scrape", "--country", "BR"], 600, "playwright"),
    ("fb_adlib_de", "Meta 广告 · 德国",
        ["-m", "market_rank.scrape_fb_adlib", "scrape", "--country", "DE"], 600, "playwright"),
    ("fb_adlib_jp", "Meta 广告 · 日本",
        ["-m", "market_rank.scrape_fb_adlib", "scrape", "--country", "JP"], 600, "playwright"),
    ("sensor_tower", "Sensor Tower",
        ["-m", "market_rank.scrape_sensor_tower", "scrape"], 300, "playwright"),
]

# Phase 2：AI 重活（串行；失败不阻塞下一个）
# 2026-04-30 重构：按 AI_tasks_spec_v1_1.md 砍到 3 个任务（comment_label / entity_extract / alert_title）
# 全部走统一管道 ai_tasks.run_pipeline；旧的 commercial_strategy AI 部分已移除（保留 IAP 抓取在 weekly_sync）
PHASE_2_AI = [
    # 自动发现 peer：appstore_rank top 100 → 未跟踪 app → app_classifier → app_classifications 表
    # 默认仅分类，不自动 promote 到 competitors（要 promote 自己加 --auto-promote 跑一次）
    ("discover_peers", "AI 自动发现新 peer（基于 appstore_rank top 100）",
        ["-m", "ai_tasks.discover_peers", "--limit", "120"], 900),
    # 主 AI 管道：评论 label + entity_extract + 7 类预警
    # limit 1500：comment_fetch 单次抓 ~1200 条新评论，1500 容量保证消化新增 + 部分历史 backlog；
    # 并发 8 路下 1500 条 ~10 min；timeout 60 min 留充足余量
    ("ai_pipeline", "AI 管道（label + 实体抽取 + 7 类预警）",
        ["-m", "ai_tasks.run_pipeline", "--limit", "1500"], 3600),
]

# Phase 3：聚合（写 data/dashboard_data.json，供 v2 backend 读派生 alerts/news 等）
PHASE_3_AGG = [
    ("aggregate", "聚合 dashboard_data.json",
        ["-m", "data_pipeline.aggregator"], 120),
]

DAILY_MAX_AGE_HOURS = 20.0  # 各源新鲜度阈值（launchd 02:00 ± 抖动）


# 全任务速查表 — 给 Phase 0（重试队列）查 (args, timeout, kind, label)
def _build_task_registry() -> dict:
    reg: dict[str, dict] = {}
    for name, label, args, to, kind in PHASE_1_FETCHERS:
        reg[name] = {"label": label, "args": args, "timeout": to, "kind": kind}
    for name, label, args, to in PHASE_2_AI:
        reg[name] = {"label": label, "args": args, "timeout": to, "kind": "ai"}
    for name, label, args, to in PHASE_3_AGG:
        reg[name] = {"label": label, "args": args, "timeout": to, "kind": "aggregate"}
    return reg


TASK_REGISTRY = _build_task_registry()


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
        # 即时飞书告警 — cookie 失效不能等到流水线结束
        _notify_cookie_expired(name, result.get("stderr_tail", ""))
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
    """三路写入：JSON（rolling 50） + MySQL（长期）+ Redis（最近 50 LIST 镜像）。"""
    # 1. JSON
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
        print(f"[sync_log] JSON 写入失败: {exc}", file=sys.stderr)
    # 2 + 3. MySQL + Redis（dao 内部各自降级；MYSQL_DSN/REDIS_URL 未配置就 no-op）
    try:
        from shared.dao import sync_log as _dao_log
        _dao_log.append_sync_log(entry)
    except Exception as exc:
        print(f"[sync_log] dao 写入失败: {exc}", file=sys.stderr)


# ---- 通知 ----------------------------------------------------------------

def _notify(title: str, msg: str) -> None:
    """双通道通知：macOS osascript（本机）+ 飞书机器人（远程）。任一失败不影响另一个。"""
    # 飞书（如配置）
    try:
        feishu_notify.send_text(f"{title}\n{msg}")
    except Exception as e:
        print(f"[feishu] 通知失败: {e}", file=sys.stderr)
    # macOS 本机弹窗
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


def _notify_cookie_expired(source: str, error_tail: str = "") -> None:
    """Cookie 失效专用即时告警（飞书卡片 + macOS 通知）。"""
    title = f"🔒 {source} cookie 失效"
    cmd = f"python3 -m market_rank.scrape_{source} login"
    fields = [
        {"label": "数据源", "value": source},
        {"label": "重新登录命令", "value": f"`{cmd}`"},
    ]
    if error_tail:
        fields.append({"label": "错误信息", "value": error_tail[:200]})
    try:
        feishu_notify.send_card(title, fields=fields, color="red",
                                actions=[{"text": "看同步日志",
                                          "url": feishu_notify.dashboard_url(
                                              "/system/sync-log", source=source)}],
                                footer="登录后下次同步会自动恢复")
    except Exception as e:
        print(f"[feishu] cookie 告警发送失败: {e}", file=sys.stderr)
    # 顺便也走 macOS 通知（与原行为兼容）
    if sys.platform == "darwin":
        try:
            subprocess.run([
                "osascript", "-e",
                f'display notification "请去终端跑：{cmd}" with title "INTEL-OPS · {title}"',
            ], timeout=5, check=False)
        except Exception:
            pass


# ---- Phase runners --------------------------------------------------------

def _should_skip(name: str, force: bool, max_age_hours: float) -> bool:
    if force:
        return False
    return sync_state.is_fresh(name, max_age_hours)


def _enqueue_if_failed(name: str, result: dict) -> None:
    """主流水线某子任务失败 → 推到重试队列（如果该 kind 允许重试）。"""
    if result.get("success"):
        # 成功的话，把残留队列条目（如有）清掉
        retry_queue.remove_by_script(name)
        return
    kind = result.get("kind") or ("error" if result.get("exit_code") != 0 else "unknown")
    err = result.get("stderr_tail") or ""
    item_id = retry_queue.enqueue(name, err, kind)
    if item_id:
        print(f"  [retry-queue] {name} 已入队，下次同步时重试")
    else:
        if kind in retry_queue.PERMANENT_FAILURE_KINDS:
            print(f"  [retry-queue] {name} 失败原因 {kind}，不入队（需人工修）")
        else:
            print(f"  [retry-queue] {name} 已超过 max_attempts，永久失败")


def run_phase_0_retry(dry_run: bool) -> tuple[int, int]:
    """主流水线开始前先尝试重跑过期的失败任务。"""
    items = retry_queue.due_items()
    if not items:
        return (0, 0)
    print("\n" + "=" * 70)
    print(f"Phase 0/3 — 重试队列（{len(items)} 个到期项）")
    print("=" * 70)
    ok = fail = 0
    for it in items:
        name = it.get("script")
        cfg = TASK_REGISTRY.get(name)
        if not cfg:
            # 不在 daily registry — 可能是 weekly 任务（如 iap_pricing / weekly_review），
            # 留给 weekly_sync 去处理；不清除条目
            print(f"  [skip-not-daily] {name}（不在 daily TASK_REGISTRY，留给 weekly_sync）")
            continue
        attempts = it.get("attempts", 1)
        if dry_run:
            print(f"  [dry-run] {name} (attempts={attempts}, label={cfg['label']})")
            continue
        print(f"  [retry] {name} (attempts={attempts}/{it.get('max_attempts')})")
        result = _run_one(name, cfg["label"], cfg["args"], cfg["timeout"])
        _post_process(result, cfg["kind"])
        tag = "✓" if result["success"] else "✗"
        kind_msg = result.get("kind") or ""
        print(f"    [{tag}] {name}  {result['duration_sec']}s  exit={result['exit_code']}  {kind_msg}")
        if result["success"]:
            retry_queue.remove(it["id"])
            ok += 1
        else:
            ek = result.get("kind") or "error"
            updated = retry_queue.update_retry(it["id"], result.get("stderr_tail") or "", ek)
            if updated is None:
                if ek in retry_queue.PERMANENT_FAILURE_KINDS:
                    print(f"    [retry-queue] {name} 改判为永久失败（{ek}），已移出队列")
                else:
                    print(f"    [retry-queue] {name} 达 max_attempts，永久失败移出队列")
            fail += 1
    print(f"[phase0] 完成：ok={ok} fail={fail}")
    return (ok, fail)


def run_phase_1(force: bool, max_age_hours: float, dry_run: bool) -> tuple[int, int, list[str], list[dict]]:
    """并行跑所有抓取源；返回 (ok, fail, expired_cookies, failures_detail)。

    failures_detail = [{"name", "kind", "duration_sec"}, ...] 给飞书卡片用。
    """
    print("\n" + "=" * 70)
    print(f"Phase 1/3 — 抓取源（{len(PHASE_1_FETCHERS)} 个并行）")
    print("=" * 70)
    expired: list[str] = []
    failures: list[dict] = []
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
        return (len(pending), 0, [], [])

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
            _enqueue_if_failed(name, result)
            tag = "✓" if result["success"] else "✗"
            ekind = result.get("kind") or ""
            print(f"  [{tag}] {name}  {result['duration_sec']}s  exit={result['exit_code']}  {ekind}")
            if result["success"]:
                ok += 1
            else:
                fail += 1
                failures.append({
                    "name": name,
                    "kind": ekind or "error",
                    "duration_sec": result.get("duration_sec", 0),
                })
                if result.get("kind") == "login_required":
                    expired.append(name)
    if skipped:
        print(f"[phase1] {len(skipped)} 个跳过：{skipped}")
    print(f"[phase1] 完成：ok={ok} fail={fail}")
    return (ok, fail, expired, failures)


def run_phase_2(force: bool, max_age_hours: float, dry_run: bool) -> tuple[int, int, list[dict]]:
    """串行跑 AI 重活；失败不阻塞后续。返回 (ok, fail, failures_detail)。"""
    print("\n" + "=" * 70)
    print(f"Phase 2/3 — AI 分析（{len(PHASE_2_AI)} 个串行）")
    print("=" * 70)
    ok = fail = 0
    failures: list[dict] = []
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
        _enqueue_if_failed(name, result)
        tag = "✓" if result["success"] else "✗"
        print(f"  [{tag}] {name}  {result['duration_sec']}s  exit={result['exit_code']}")
        if result["success"]:
            ok += 1
        else:
            fail += 1
            failures.append({
                "name": name,
                "kind": result.get("kind") or "error",
                "duration_sec": result.get("duration_sec", 0),
            })
    print(f"[phase2] 完成：ok={ok} fail={fail}")
    return (ok, fail, failures)


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
    ap.add_argument("--retry-only", action="store_true",
                    help="只跑 Phase 0（重试队列），不跑主流水线 — 用于小时级 launchd")
    args = ap.parse_args(argv)

    t0 = time.monotonic()
    print(f"=== daily_sync 开始 {datetime.now().isoformat(timespec='seconds')} ===")
    print(f"force={args.force}  max-age={args.max_age_hours}h  dry-run={args.dry_run}"
          + ("  retry-only=True" if args.retry_only else ""))

    # --retry-only：只清理队列，不跑主流水线
    if args.retry_only:
        p0_ok, p0_fail = run_phase_0_retry(args.dry_run)
        queue_size = len(retry_queue.snapshot().get("items") or [])
        total = time.monotonic() - t0
        print("\n" + "=" * 70)
        print(f"=== daily_sync --retry-only 完成 — {total/60:.1f} min ===")
        print(f"  Phase 0: ok={p0_ok} fail={p0_fail}  剩余 {queue_size} 项")
        print("=" * 70)
        # 飞书：只在本轮真处理过任务时通知（避免每小时空跑刷屏）
        if not args.dry_run and (p0_ok + p0_fail) > 0:
            try:
                color = "green" if p0_fail == 0 else "orange"
                feishu_notify.send_card(
                    "🔁 重试队列",
                    fields=[
                        {"label": "本轮处理", "value": f"✓ {p0_ok} 恢复  /  ✗ {p0_fail} 仍失败"},
                        {"label": "队列剩余", "value": f"{queue_size} 项"},
                    ],
                    color=color,
                    actions=[{"text": "看同步日志",
                              "url": feishu_notify.dashboard_url("/system/sync-log")}],
                    footer=datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                )
            except Exception as e:
                print(f"[feishu] 重试卡片发送失败: {e}", file=sys.stderr)
        return 0 if p0_fail == 0 else 1

    # Phase 0：重试队列里到期的失败任务（不一定每次都有）
    p0_ok, p0_fail = run_phase_0_retry(args.dry_run)
    p1_ok, p1_fail, expired, p1_failures = run_phase_1(args.force, args.max_age_hours, args.dry_run)
    p2_ok, p2_fail, p2_failures = run_phase_2(args.force, args.max_age_hours, args.dry_run)
    p3_ok = run_phase_3(args.dry_run)

    total = time.monotonic() - t0
    total_fail = p0_fail + p1_fail + p2_fail + (0 if p3_ok else 1)
    total_ok = p0_ok + p1_ok + p2_ok + (1 if p3_ok else 0)
    queue_size = len(retry_queue.snapshot().get("items") or [])
    all_failures = p1_failures + p2_failures
    if not p3_ok:
        all_failures.append({"name": "aggregate", "kind": "error", "duration_sec": 0})

    print("\n" + "=" * 70)
    print(f"=== daily_sync 完成 — 总耗时 {total/60:.1f} min ===")
    print(f"  Phase 0 (retry): ok={p0_ok} fail={p0_fail}")
    print(f"  Phase 1 (fetch): ok={p1_ok} fail={p1_fail}")
    print(f"  Phase 2 (AI):    ok={p2_ok} fail={p2_fail}")
    print(f"  Phase 3 (agg):   {'ok' if p3_ok else 'fail'}")
    print(f"  retry_queue 当前条目: {queue_size}")
    if all_failures:
        print("  失败明细:")
        for f in all_failures:
            print(f"    ✗ {f['name']}  kind={f['kind']}  {f['duration_sec']}s")
    print("=" * 70)
    sys.stdout.flush()  # 确保 nohup log 落盘，避免之前末尾段崩溃看不到 traceback

    # 飞书优先发：放在所有可能崩溃的代码（_notify osascript / atexit）之前，保证一定发出去
    # 之前 daily_sync 跑完后没收到飞书 → 主进程在 print 总览后异常 exit，没走到下面的 send_card
    if not args.dry_run:
        if total_fail == 0:
            color = "green"
        elif total_fail <= 2:
            color = "orange"
        else:
            color = "red"
        # 失败明细字段（仅在有失败时加）
        fail_field = None
        if all_failures:
            lines = []
            for f in all_failures[:10]:   # 最多显示 10 条避免卡片太长
                lines.append(f"• **{f['name']}** — {f['kind']} ({f['duration_sec']:.0f}s)")
            if len(all_failures) > 10:
                lines.append(f"... 还有 {len(all_failures) - 10} 个")
            fail_field = {"label": "✗ 失败明细", "value": "\n".join(lines)}

        fields = [
            {"label": "总览",
             "value": f"✓ {total_ok} 成功  /  ✗ {total_fail} 失败  ·  ⏱ {total/60:.1f} min"},
            {"label": "Phase 0 · 重试队列",
             "value": f"✓ {p0_ok} / ✗ {p0_fail}"},
            {"label": "Phase 1 · 抓取（10 源并行）",
             "value": f"✓ {p1_ok} / ✗ {p1_fail}"},
            {"label": "Phase 2 · AI 分析（串行）",
             "value": f"✓ {p2_ok} / ✗ {p2_fail}"},
            {"label": "Phase 3 · 聚合 + 看板",
             "value": "✓" if p3_ok else "✗ 失败"},
            {"label": "重试队列剩余",
             "value": f"{queue_size} 项" + ("（下次同步重试）" if queue_size else "")},
        ]
        if fail_field:
            fields.append(fail_field)

        try:
            actions = [
                {"text": "看预警中心", "url": feishu_notify.dashboard_url("/alerts", since="24h")},
                {"text": "看同步日志", "url": feishu_notify.dashboard_url("/system/sync-log"),
                 "type": "default"},
            ]
            feishu_notify.send_card(
                "📊 每日抓取完成",
                fields=fields,
                color=color,
                actions=actions,
                footer=datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            )
        except Exception as e:
            print(f"[feishu] 结束卡片发送失败: {e}", file=sys.stderr)
            import traceback
            traceback.print_exc()
        sys.stdout.flush()
        sys.stderr.flush()

    # macOS 通知（保留，本机弹窗）— 包 try 兜底，不让任何异常吞掉返回值
    try:
        if expired:
            _notify("INTEL-OPS · Cookie 失效", f"{', '.join(expired)} 需要重新登录")
        if total_fail >= 3:
            _notify("INTEL-OPS · 同步告警", f"今日同步 {total_fail} 个任务失败，详情见 sync_log")
        elif total / 60 > 30:
            _notify("INTEL-OPS · 同步耗时告警", f"今日同步耗时 {total/60:.0f} 分钟（>30 min）")
    except Exception as e:
        print(f"[notify] macOS 通知异常: {e}", file=sys.stderr)

    return 0 if total_fail == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
