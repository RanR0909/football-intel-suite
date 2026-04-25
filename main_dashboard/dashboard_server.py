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
}

# ---------------------------------------------------------------------------
# 运行状态追踪
# ---------------------------------------------------------------------------
_running_tasks = {}
_tasks_lock = threading.Lock()


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
        """在后台线程中运行脚本"""
        config = SCRIPTS[script_name]
        script_path = config["path"]
        cwd = config.get("cwd", os.path.dirname(script_path))

        # 构建命令
        cmd = [sys.executable, script_path]
        cmd.extend(config.get("args", []))
        if script_name == "competitor_detail" and competitor:
            cmd.extend([competitor, "--days", days])

        # 设置环境变量
        env = os.environ.copy()
        if api_key:
            env["CLAUDE_API_KEY"] = api_key
        elif CLAUDE_API_KEY:
            env["CLAUDE_API_KEY"] = CLAUDE_API_KEY

        # 更新状态
        with _tasks_lock:
            _running_tasks[script_name] = {
                "running": True,
                "label": config["label"],
                "started_at": __import__("datetime").datetime.now().isoformat(),
                "output": "",
            }

        try:
            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=600,
                cwd=cwd,
                env=env,
            )
            with _tasks_lock:
                _running_tasks[script_name] = {
                    "running": False,
                    "label": config["label"],
                    "success": result.returncode == 0,
                    "output": (result.stdout or "")[-500:] + (result.stderr or "")[-500:],
                    "finished_at": __import__("datetime").datetime.now().isoformat(),
                }
        except subprocess.TimeoutExpired:
            with _tasks_lock:
                _running_tasks[script_name] = {
                    "running": False,
                    "label": config["label"],
                    "success": False,
                    "output": "执行超时（600秒）",
                    "finished_at": __import__("datetime").datetime.now().isoformat(),
                }
        except Exception as e:
            with _tasks_lock:
                _running_tasks[script_name] = {
                    "running": False,
                    "label": config["label"],
                    "success": False,
                    "output": str(e),
                    "finished_at": __import__("datetime").datetime.now().isoformat(),
                }


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
╚══════════════════════════════════════════════════╝
    """)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\n[INFO] 服务器已停止")
        server.server_close()


if __name__ == "__main__":
    main()
