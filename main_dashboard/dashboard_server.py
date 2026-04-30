#!/usr/bin/env python3
"""
INTEL-OPS 竞品情报看板 · 后端 API 服务器
提供 HTTP API 端点，让前端按钮可以直接调用后端脚本。
"""

import json
import os
import subprocess
import sys
import threading
from pathlib import Path
from http.server import HTTPServer, BaseHTTPRequestHandler
from urllib.parse import urlparse, parse_qs

# ---------------------------------------------------------------------------
# 路径
# ---------------------------------------------------------------------------
_SCRIPT_DIR = Path(__file__).resolve().parent
_PROJECT_ROOT = _SCRIPT_DIR.parent
DATA_DIR = _PROJECT_ROOT / "data"

# 使 data_pipeline 包可导入
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

# 兜底加载 .env.local（绕过 启动看板.command 直接跑 python 也能读到 key）
try:
    from shared.env_loader import load_all as _load_env_all
    _load_env_all()  # .env.local + ~/.intelops-secrets fallback
except Exception:
    pass

# sync_state 持久化（与 scripts/daily_sync.py 共享同一份 state）
try:
    from shared import sync_state as _sync_state  # type: ignore
except Exception:
    _sync_state = None  # 不致命；失败时只是不更新 state

try:
    from shared import retry_queue as _retry_queue  # type: ignore
except Exception:
    _retry_queue = None  # 不致命

try:
    from shared import db as _shared_db  # type: ignore
    from shared.dao import sync_log as _dao_sync_log  # type: ignore
except Exception:
    _shared_db = None
    _dao_sync_log = None

# 哪些 script_name 对应一个 sync_state 源（其余按钮不污染 state）
SCRIPT_TO_STATE_NAME = {
    "reddit_crawl": "reddit",
    "twitter_crawl": "twitter",
    "iap_pricing_crawl": "iap_pricing",
    "google_news": "google_news",
    "appstore_rank": "appstore_rank",
    "androidrank": "androidrank",
    "comment_fetch": "comment_fetch",
    "comment_label": "comment_label",
    "commercial_strategy": "commercial_strategy",
    "strategy_monitor": "strategy_monitor",
    "market_rank": "appmagic",          # market_rank/run_headless.py = scrape_appmagic + adapter
    "fb_adlib": "fb_adlib",
    "sensor_tower": "sensor_tower",
}
# 这些是 Playwright 源 — 检测 LoginRequired 时同步标 cookie_status
PLAYWRIGHT_STATE_NAMES = {"appmagic", "fb_adlib", "sensor_tower"}

# API Key 从环境变量获取
CLAUDE_API_KEY = os.environ.get("CLAUDE_API_KEY", "")

# ---------------------------------------------------------------------------
# 脚本配置
# ---------------------------------------------------------------------------
SCRIPTS = {
    "daily_report": {
        "path": str(_PROJECT_ROOT / "competitor_comment" / "auto_report.py"),
        "cwd": str(_PROJECT_ROOT / "competitor_comment"),
        "label": "滚动评论监测",
    },
    "weekly_review": {
        "path": str(_PROJECT_ROOT / "competitor_comment" / "weekly_review.py"),
        "cwd": str(_PROJECT_ROOT / "competitor_comment"),
        "label": "周报生成",
    },
    "strategy_monitor": {
        "path": str(_PROJECT_ROOT / "strategy_monitor" / "run_headless.py"),
        "cwd": str(_PROJECT_ROOT / "strategy_monitor"),
        "label": "产品动态同步",
    },
    "market_rank": {
        "path": str(_PROJECT_ROOT / "market_rank" / "run_headless.py"),
        "cwd": str(_PROJECT_ROOT / "market_rank"),
        "label": "排名数据同步",
    },
    "competitor_detail": {
        "path": str(_PROJECT_ROOT / "competitor_comment" / "competitor_detail.py"),
        "cwd": str(_PROJECT_ROOT / "competitor_comment"),
        "label": "深度分析",
    },
    "generate_dashboard": {
        "path": str(_PROJECT_ROOT / "main_dashboard" / "generate_dashboard.py"),
        "cwd": str(_PROJECT_ROOT / "main_dashboard"),
        "label": "看板生成",
    },
    "all_competitor_details": {
        "path": str(_PROJECT_ROOT / "competitor_comment" / "run_all_details.py"),
        "cwd": str(_PROJECT_ROOT / "competitor_comment"),
        "label": "全竞品深度分析",
    },
    "commercial_strategy": {
        "path": str(_PROJECT_ROOT / "commercial_strategy" / "run_headless.py"),
        "cwd": str(_PROJECT_ROOT / "commercial_strategy"),
        "label": "商业策略分析",
    },
    "commercial_weekly": {
        "path": str(_PROJECT_ROOT / "commercial_strategy" / "run_headless.py"),
        "args": ["--weekly"],
        "cwd": str(_PROJECT_ROOT / "commercial_strategy"),
        "label": "商业策略周报",
    },
    # AppMagic 登录（一次性手动）— 弹浏览器，登录完关窗口
    "appmagic_login": {
        "path": "-m",
        "module": "market_rank.scrape_appmagic",
        "args": ["login"],
        "cwd": str(_PROJECT_ROOT),
        "label": "AppMagic 登录（手动）",
    },
    # Meta 广告库（Playwright 持久 profile，替代 token-based 旧 fb_adlib）
    "fb_adlib_login": {
        "path": "-m",
        "module": "market_rank.scrape_fb_adlib",
        "args": ["login"],
        "cwd": str(_PROJECT_ROOT),
        "label": "Meta 广告库登录（手动）",
    },
    "fb_adlib": {
        "path": "-m",
        "module": "market_rank.scrape_fb_adlib",
        "args": ["scrape"],
        "cwd": str(_PROJECT_ROOT),
        "label": "Meta 广告投放抓取（Playwright）",
    },
    # Sensor Tower 概览页（Playwright 持久 profile，免费账号即可）
    "sensor_tower_login": {
        "path": "-m",
        "module": "market_rank.scrape_sensor_tower",
        "args": ["login"],
        "cwd": str(_PROJECT_ROOT),
        "label": "Sensor Tower 登录（手动）",
    },
    "sensor_tower": {
        "path": "-m",
        "module": "market_rank.scrape_sensor_tower",
        "args": ["scrape"],
        "cwd": str(_PROJECT_ROOT),
        "label": "Sensor Tower 抓取（Playwright）",
    },
    "reddit_crawl": {
        "path": "-m",
        "module": "async_crawler",
        "args": ["--sources", "reddit"],
        "cwd": str(_PROJECT_ROOT),
        "label": "Reddit 社媒抓取",
    },
    "twitter_crawl": {
        "path": "-m",
        "module": "async_crawler",
        "args": ["--sources", "twitter"],
        "cwd": str(_PROJECT_ROOT),
        "label": "X (Twitter) 社媒抓取",
    },
    "iap_pricing_crawl": {
        "path": "-m",
        "module": "async_crawler",
        "args": ["--sources", "iap_pricing"],
        "cwd": str(_PROJECT_ROOT),
        "label": "IAP 定价抓取",
    },
    "google_news": {
        "path": "-m",
        "module": "async_crawler",
        "args": ["--sources", "google_news"],
        "cwd": str(_PROJECT_ROOT),
        "label": "Google 商业新闻抓取",
    },
    # ---- daily_sync 用到的额外抓取源（手动同步与自动同步任务图对齐） ----
    "appstore_rank": {
        "path": "-m",
        "module": "async_crawler",
        "args": ["--sources", "appstore_rank"],
        "cwd": str(_PROJECT_ROOT),
        "label": "App Store 体育榜",
    },
    "androidrank": {
        "path": "-m",
        "module": "async_crawler",
        "args": ["--sources", "androidrank"],
        "cwd": str(_PROJECT_ROOT),
        "label": "Androidrank 历史",
    },
    "comment_fetch": {
        "path": "-m",
        "module": "competitor_comment.comment_fetch",
        "cwd": str(_PROJECT_ROOT),
        "label": "评论抓取（GP+iOS）",
    },
    "comment_label": {
        "path": "-m",
        "module": "competitor_comment.comment_label",
        "cwd": str(_PROJECT_ROOT),
        "label": "评论 AI 标签",
    },
    # 一键自动同步（前后端共用 daily_sync orchestrator；与 launchd 同一份代码）
    "daily_sync": {
        "path": str(_PROJECT_ROOT / "scripts" / "daily_sync.py"),
        "cwd": str(_PROJECT_ROOT),
        "label": "全量自动同步（与定时任务同入口）",
    },
    # 已弃用（AI v2 / 2026-04-30）：review_3d / competitor_detail / weekly_review / commercial_strategy
    # 不再注册到 SCRIPTS — 点击 UI 按钮会被 do_POST 拒掉为 unknown script。
}

# ---------------------------------------------------------------------------
# 运行状态追踪
# ---------------------------------------------------------------------------
_running_tasks = {}
_tasks_lock = threading.Lock()

# ---------------------------------------------------------------------------
# 同步抓取日志（持久化到 data/sync_log.json，rolling 最近 50 条）
# ---------------------------------------------------------------------------
SYNC_LOG_PATH = DATA_DIR / "sync_log.json"
SYNC_LOG_MAX_ENTRIES = 50
_sync_log_lock = threading.Lock()


def _append_sync_log(entry: dict) -> None:
    """每次脚本运行结束后追加一条记录。线程安全。

    三路写入（任一失败不影响其他）：
      1. data/sync_log.json（rolling 50，与 dashboard 现状兼容）
      2. MySQL sync_log 表（长期遥测，仅 MYSQL_DSN 配置时）
      3. Redis sync_log:recent LIST（dashboard 实时面板，仅 REDIS_URL 配置时）
    """
    # 1. JSON
    with _sync_log_lock:
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
            SYNC_LOG_PATH.write_text(
                json.dumps(entries, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
        except Exception as e:
            print(f"[sync_log] JSON write failed: {e}", file=sys.stderr)

    # 2 + 3. MySQL + Redis（dao 内部各自降级）
    if _dao_sync_log is not None:
        try:
            _dao_sync_log.append_sync_log(entry)
        except Exception as e:
            print(f"[sync_log] dao append failed: {e}", file=sys.stderr)


class DashboardAPIHandler(BaseHTTPRequestHandler):
    """HTTP 请求处理器"""

    def log_message(self, format, *args):
        """减少日志输出"""
        pass

    def _send_json(self, data, status=200):
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")
        self.end_headers()
        self.wfile.write(json.dumps(data, ensure_ascii=False).encode("utf-8"))

    def do_OPTIONS(self):
        self.send_response(200)
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")
        self.end_headers()

    def do_POST(self):
        parsed = urlparse(self.path)
        path = parsed.path

        if path == "/api/ai/community-insights":
            self._handle_community_ai_post()
        elif path == "/api/ai/ads-strategy":
            self._handle_ads_ai_post()
        else:
            self._send_json({"status": "error", "message": "未知路径"}, 404)

    def _handle_community_ai_post(self):
        """启动一次社媒舆情 AI 分析（异步，立即返回 task_id）。"""
        try:
            length = int(self.headers.get("Content-Length", 0) or 0)
            body = json.loads(self.rfile.read(length) or b"{}") if length else {}
        except Exception:
            self._send_json({"status": "error", "message": "请求体不是合法 JSON"}, 400)
            return

        competitor = (body.get("competitor") or "").strip()
        if not competitor:
            self._send_json({"status": "error", "message": "缺少 competitor 字段"}, 400)
            return
        # date_range 接受 "7d" / "14d" / "30d" 或纯数字
        raw_range = str(body.get("date_range") or "7d").lower().rstrip("d")
        try:
            days = max(1, min(int(raw_range), 60))
        except Exception:
            days = 7

        api_key = body.get("api_key") or CLAUDE_API_KEY
        if not api_key:
            self._send_json({"status": "error", "message": "缺少 CLAUDE_API_KEY（环境变量或请求体均未提供）"}, 400)
            return

        task_key = f"community_ai:{competitor}"
        with _tasks_lock:
            existing = _running_tasks.get(task_key)
            if existing and existing.get("running"):
                self._send_json({"status": "error", "message": f"'{competitor}' 正在分析中，请等待"})
                return

        thread = threading.Thread(
            target=self._run_community_ai,
            args=(task_key, competitor, days, api_key),
            daemon=True,
        )
        thread.start()
        self._send_json({
            "status": "started",
            "task_id": task_key,
            "competitor": competitor,
            "date_range_days": days,
        })

    def _handle_ads_ai_post(self):
        """启动一次 Meta 广告投放策略 AI 分析（异步，立即返回 task_id）。"""
        try:
            length = int(self.headers.get("Content-Length", 0) or 0)
            body = json.loads(self.rfile.read(length) or b"{}") if length else {}
        except Exception:
            self._send_json({"status": "error", "message": "请求体不是合法 JSON"}, 400)
            return

        competitor = (body.get("competitor") or "").strip()
        if not competitor:
            self._send_json({"status": "error", "message": "缺少 competitor 字段"}, 400)
            return
        raw_range = str(body.get("date_range") or "7d").lower().rstrip("d")
        try:
            days = max(1, min(int(raw_range), 60))
        except Exception:
            days = 7

        api_key = body.get("api_key") or CLAUDE_API_KEY
        if not api_key:
            self._send_json({"status": "error", "message": "缺少 CLAUDE_API_KEY（环境变量或请求体均未提供）"}, 400)
            return

        task_key = f"ads_ai:{competitor}"
        with _tasks_lock:
            existing = _running_tasks.get(task_key)
            if existing and existing.get("running"):
                self._send_json({"status": "error", "message": f"'{competitor}' 正在分析中，请等待"})
                return

        thread = threading.Thread(
            target=self._run_ads_ai,
            args=(task_key, competitor, days, api_key),
            daemon=True,
        )
        thread.start()
        self._send_json({
            "status": "started",
            "task_id": task_key,
            "competitor": competitor,
            "date_range_days": days,
        })

    def _run_ads_ai(self, task_key, competitor, days, api_key):
        """已弃用（AI v2 架构 / 2026-04-30）— spec 不允许"主观策略分析 / 长文报告"。
        AI 广告分析被替换为：alerts.alert_type='ads' 的事实陈述（≤50 字）。
        """
        from datetime import datetime as _dt
        with _tasks_lock:
            _running_tasks[task_key] = {
                "running": False,
                "success": False,
                "label": f"AI 广告策略分析 · {competitor}",
                "error": "feature_deprecated_v2: 该功能已下线（AI 不再做主观策略报告）。"
                         "广告事件请查看 alerts 表 alert_type='ads' 字段。",
                "finished_at": _dt.now().isoformat(),
            }

    def _run_community_ai(self, task_key, competitor, days, api_key):
        """已弃用（AI v2 架构 / 2026-04-30）— spec 不允许"跨评论做趋势总结 / 长文舆情报告"。
        替代：comment_label 标签统计 + entity_extract 实体频次（在 dashboard 卡片直接展示，不需 AI）。
        """
        from datetime import datetime as _dt
        with _tasks_lock:
            _running_tasks[task_key] = {
                "running": False,
                "success": False,
                "label": f"AI 舆情分析 · {competitor}",
                "error": "feature_deprecated_v2: 该功能已下线（AI 不再做长文舆情总结）。"
                         "舆情数据请看 reviews.label 标签分布 + comment_entities 实体频次卡片。",
                "finished_at": _dt.now().isoformat(),
            }

    def do_GET(self):
        parsed = urlparse(self.path)
        path = parsed.path
        params = parse_qs(parsed.query)

        if path == "/api/status":
            # 返回所有任务状态
            with _tasks_lock:
                status_snapshot = dict(_running_tasks)
            self._send_json({
                "status": "ok",
                "tasks": status_snapshot,
            })

        elif path == "/api/data/competitor_comments":
            # 返回评论数据
            data = self._load_json_file("competitor_comments.json")
            self._send_json(data)

        elif path == "/api/data/weekly_review":
            # 返回周报数据
            data = self._load_json_file("weekly_review.json")
            self._send_json(data)

        elif path == "/api/data/strategy_monitor":
            data = self._load_json_file("strategy_monitor.json")
            self._send_json(data)

        elif path == "/api/data/market_rank":
            data = self._load_json_file("market_rank.json")
            self._send_json(data)

        elif path == "/api/data/ranking_history":
            data = self._load_json_file("ranking_history.json")
            self._send_json(data)

        elif path == "/api/sync_state":
            # 各源最新 last_success / cookie_status（与 daily_sync / 手动同步共用）
            try:
                if _sync_state is not None:
                    self._send_json(_sync_state.snapshot())
                else:
                    self._send_json({"version": 1, "sources": {}})
            except Exception as e:
                self._send_json({"status": "error", "message": str(e)}, 500)

        elif path == "/api/retry_queue":
            # 重试队列内容（前端"数据源状态"卡片用）
            try:
                if _retry_queue is not None:
                    self._send_json(_retry_queue.snapshot())
                else:
                    self._send_json({"version": 1, "items": []})
            except Exception as e:
                self._send_json({"status": "error", "message": str(e)}, 500)

        elif path == "/api/db/status":
            # MySQL + Redis 健康检查（dashboard 数据库健康卡片用）
            try:
                if _shared_db is not None:
                    self._send_json(_shared_db.health())
                else:
                    self._send_json({"mysql": {"enabled": False}, "redis": {"enabled": False}})
            except Exception as e:
                self._send_json({"status": "error", "message": str(e)}, 500)

        elif path == "/api/sync_log":
            # 同步抓取日志（最近 50 条）
            try:
                if SYNC_LOG_PATH.exists():
                    entries = json.loads(SYNC_LOG_PATH.read_text(encoding="utf-8")) or []
                else:
                    entries = []
                limit = int(params.get("limit", ["50"])[0])
                entries = entries[-limit:]
                self._send_json({
                    "entries": entries,
                    "total": len(entries),
                    "max_kept": SYNC_LOG_MAX_ENTRIES,
                })
            except Exception as e:
                self._send_json({"status": "error", "message": str(e)}, 500)

        elif path == "/api/data/dashboard_data":
            # 返回聚合后的统一数据（dashboard 唯一需要的产物）
            # 若 dashboard_data.json 不存在则即时聚合
            fp = DATA_DIR / "dashboard_data.json"
            if fp.exists():
                self._send_json(self._load_json_file("dashboard_data.json"))
            else:
                try:
                    from data_pipeline.aggregator import build_dashboard_data
                    from data_pipeline.schema import to_dict
                    self._send_json(to_dict(build_dashboard_data()))
                except Exception as e:
                    self._send_json({"status": "error", "message": str(e)}, 500)

        elif path == "/api/aggregate":
            # 手动触发聚合层：读 7 个原始 JSON → 写 dashboard_data.json
            try:
                from data_pipeline.aggregator import build_dashboard_data, OUTPUT_PATH as _AGG_OUT
                from data_pipeline.schema import to_dict
                payload = to_dict(build_dashboard_data())
                _AGG_OUT.parent.mkdir(parents=True, exist_ok=True)
                with open(_AGG_OUT, "w", encoding="utf-8") as f:
                    json.dump(payload, f, ensure_ascii=False, indent=2)
                self._send_json({
                    "status": "ok",
                    "competitors": len(payload.get("competitors") or {}),
                    "alerts": len(payload.get("alerts") or []),
                    "feed": len(payload.get("feed") or []),
                    "timeline": len((payload.get("views") or {}).get("timeline") or []),
                    "generated_at": (payload.get("meta") or {}).get("generated_at"),
                })
            except Exception as e:
                self._send_json({"status": "error", "message": str(e)}, 500)

        elif path == "/api/data/competitor_detail":
            name = params.get("name", [""])[0]
            if name:
                data = self._load_json_file(f"competitor_detail_{name}.json")
            else:
                # 返回所有深度分析数据
                data = {}
                for f in DATA_DIR.glob("competitor_detail_*.json"):
                    try:
                        d = json.loads(f.read_text(encoding="utf-8"))
                        n = d.get("competitor", "")
                        if n:
                            data[n] = d
                    except Exception:
                        pass
            self._send_json(data)

        elif path == "/api/data/review_3d":
            name = params.get("name", [""])[0]
            if not name:
                self._send_json({"status": "error", "message": "missing name"}, 400)
            else:
                data = self._load_json_file(f"review_3d_{name}.json")
                self._send_json(data or {})

        elif path == "/api/run":
            script_name = params.get("script", [""])[0]
            competitor = params.get("competitor", [""])[0]
            days = params.get("days", ["7"])[0]
            api_key = params.get("api_key", [""])[0] or CLAUDE_API_KEY

            if script_name not in SCRIPTS:
                self._send_json({"status": "error", "message": f"未知脚本: {script_name}"}, 400)
                return

            # 检查是否已在运行
            with _tasks_lock:
                if script_name in _running_tasks and _running_tasks[script_name].get("running"):
                    self._send_json({
                        "status": "error",
                        "message": f"'{SCRIPTS[script_name]['label']}' 正在运行中，请等待完成",
                    })
                    return

            # 启动后台线程运行脚本
            thread = threading.Thread(
                target=self._run_script,
                args=(script_name, competitor, days, api_key),
                daemon=True,
            )
            thread.start()

            self._send_json({
                "status": "started",
                "message": f"'{SCRIPTS[script_name]['label']}' 已启动",
            })

        elif path == "/":
            # 返回 HTML 看板
            html_path = _SCRIPT_DIR / "dashboard.html"
            if html_path.exists():
                self.send_response(200)
                self.send_header("Content-Type", "text/html; charset=utf-8")
                self.send_header("Access-Control-Allow-Origin", "*")
                self.end_headers()
                with open(html_path, "r", encoding="utf-8") as f:
                    self.wfile.write(f.read().encode("utf-8"))
            else:
                self._send_json({"status": "error", "message": "dashboard.html 未找到，请先生成看板"}, 404)

        else:
            self._send_json({"status": "error", "message": "未知路径"}, 404)

    def _load_json_file(self, filename):
        fp = DATA_DIR / filename
        if not fp.exists():
            return {}
        try:
            with open(fp, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            return {}

    def _run_script(self, script_name, competitor="", days="7", api_key=""):
        """在后台线程中运行脚本（结束后写一条 sync_log.json 记录）"""
        from datetime import datetime as _dt
        config = SCRIPTS[script_name]
        script_path = config["path"]
        cwd = config.get("cwd", os.path.dirname(script_path) or str(_PROJECT_ROOT))

        # 构建命令：支持 path="-m" 跑模块
        if script_path == "-m" and config.get("module"):
            cmd = [sys.executable, "-m", config["module"]]
        else:
            cmd = [sys.executable, script_path]
        cmd.extend(config.get("args", []))
        if script_name == "competitor_detail" and competitor:
            cmd.extend([competitor, "--days", days])
        if script_name == "review_3d" and competitor:
            cmd.extend([competitor, "--days", days])

        # 设置环境变量
        env = os.environ.copy()
        if api_key:
            env["CLAUDE_API_KEY"] = api_key
        elif CLAUDE_API_KEY:
            env["CLAUDE_API_KEY"] = CLAUDE_API_KEY

        # 入口时间
        started_at = _dt.now()
        with _tasks_lock:
            _running_tasks[script_name] = {
                "running": True,
                "label": config["label"],
                "started_at": started_at.isoformat(),
                "output": "",
            }

        # 默认值（任何分支都会写日志）
        success = False
        stdout_tail = ""
        stderr_tail = ""
        error_kind = None

        # 超时阈值：抓取类（评论 / Reddit / Twitter）可能耗时较长，给 1200s
        # 普通脚本 600s 够用；通过 SCRIPTS[name].get("timeout", 1200) 覆盖
        script_timeout = int(config.get("timeout", 1200))
        try:
            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=script_timeout,
                cwd=cwd,
                env=env,
            )
            success = (result.returncode == 0)
            stdout_tail = (result.stdout or "")[-1500:]
            stderr_tail = (result.stderr or "")[-1500:]
            # exit code 2 = AppMagic 登录失效（约定，见 market_rank/scrape_appmagic.py）
            if result.returncode == 2 and "LoginRequired" in (stderr_tail + stdout_tail) or "登录态" in stderr_tail:
                error_kind = "LOGIN_REQUIRED"
            with _tasks_lock:
                _running_tasks[script_name] = {
                    "running": False,
                    "label": config["label"],
                    "success": success,
                    "output": stdout_tail[-500:] + stderr_tail[-500:],
                    "finished_at": _dt.now().isoformat(),
                }
        except subprocess.TimeoutExpired:
            error_kind = "timeout"
            stderr_tail = f"执行超时（{script_timeout}秒）"
            with _tasks_lock:
                _running_tasks[script_name] = {
                    "running": False,
                    "label": config["label"],
                    "success": False,
                    "output": stderr_tail,
                    "finished_at": _dt.now().isoformat(),
                }
        except Exception as e:
            error_kind = type(e).__name__
            stderr_tail = str(e)
            with _tasks_lock:
                _running_tasks[script_name] = {
                    "running": False,
                    "label": config["label"],
                    "success": False,
                    "output": stderr_tail,
                    "finished_at": _dt.now().isoformat(),
                }

        # 持久化日志（无论成败）
        finished_at = _dt.now()
        _append_sync_log({
            "script": script_name,
            "label": config["label"],
            "competitor": competitor or None,
            "started_at": started_at.isoformat(),
            "finished_at": finished_at.isoformat(),
            "duration_sec": round((finished_at - started_at).total_seconds(), 2),
            "success": success,
            "error_kind": error_kind,
            "stdout_tail": stdout_tail,
            "stderr_tail": stderr_tail,
            "cmd": " ".join(cmd[:6]) + (" ..." if len(cmd) > 6 else ""),
        })

        # 同步写 sync_state（让手动同步 = 自动同步，state 共用）
        # 注意：daily_sync 这个特殊 script 自身在子进程里写 state，外层不双写。
        if _sync_state is not None and script_name != "daily_sync":
            state_name = SCRIPT_TO_STATE_NAME.get(script_name)
            if state_name:
                try:
                    if error_kind == "LOGIN_REQUIRED" and state_name in PLAYWRIGHT_STATE_NAMES:
                        _sync_state.mark_cookie_expired(state_name)
                        _sync_state.mark_failure(state_name, "login_required", stderr_tail or "")
                    elif success:
                        _sync_state.mark_success(state_name)
                        if state_name in PLAYWRIGHT_STATE_NAMES:
                            _sync_state.mark_cookie_ok(state_name)
                    else:
                        _sync_state.mark_failure(
                            state_name,
                            error_kind or "error",
                            stderr_tail or "",
                        )
                except Exception as exc:
                    print(f"[sync_state] {script_name} 写入失败: {exc}", file=sys.stderr)


def main():
    port = int(sys.argv[1]) if len(sys.argv) > 1 else 8899

    # 从环境变量获取 API Key
    global CLAUDE_API_KEY
    CLAUDE_API_KEY = os.environ.get("CLAUDE_API_KEY", "")

    server = HTTPServer(("0.0.0.0", port), DashboardAPIHandler)
    print(f"""
╔══════════════════════════════════════════════════╗
║     INTEL-OPS Dashboard Server                  ║
║     ─────────────────────────────               ║
║     看板地址: http://localhost:{port}              ║
║     API 地址: http://localhost:{port}/api/...      ║
║                                                  ║
║     可用 API:                                    ║
║       GET  /              → 看板 HTML            ║
║       GET  /api/status    → 任务状态             ║
║       GET  /api/run?script=daily_report          ║
║            &script=weekly_review                 ║
║            &script=strategy_monitor              ║
║            &script=market_rank                   ║
║            &script=competitor_detail&competitor=X ║
║            &script=generate_dashboard            ║
║       GET  /api/data/*    → JSON 数据            ║
║       GET  /api/data/dashboard_data → 统一聚合   ║
║       GET  /api/aggregate → 手动重跑聚合层       ║
║       POST /api/ai/community-insights            ║
║       POST /api/ai/ads-strategy                  ║
║            body: {{competitor, date_range?}}       ║
╚══════════════════════════════════════════════════╝
    """)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\n[INFO] 服务器已停止")
        server.server_close()


if __name__ == "__main__":
    main()
