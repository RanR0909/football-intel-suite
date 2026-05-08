"""dashboard_server — INTEL-OPS REST API (v2.0 / 2026-04-30)

纯 API server，配套 React 前端（intel-ops-frontend/）。

旧版本职责：
- ❌ 服务静态 HTML（已废弃，由 React 前端取代）
- ❌ 触发 AI on-demand 按钮（review_3d / ads / community — v2 已下线）
- ❌ 触发抓取脚本（dashboard 不再做手动同步入口，统一走 daily_sync）

新版本职责（v2 仅做 REST API）：
- 14 个 GET / POST 端点，按 INTEL-OPS_前端实现文档_v2.md §8.1 实现
- CORS：默认允许 vite dev server (`localhost:5173`) + 同域

启动：
    python3 main_dashboard/dashboard_server.py        # 默认 :8899
    python3 main_dashboard/dashboard_server.py 9999   # 自定义端口
"""
from __future__ import annotations

import json
import logging
import os
import sys
from datetime import date, datetime, timedelta
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

_SCRIPT_DIR = Path(__file__).resolve().parent
_PROJECT_ROOT = _SCRIPT_DIR.parent

if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

try:
    from shared.env_loader import load_all as _load_env_all
    _load_env_all()
except Exception:
    pass

DATA_DIR = _PROJECT_ROOT / "data"
DASHBOARD_DATA_PATH = DATA_DIR / "dashboard_data.json"

# ---- 可选模块（缺失时各端点返回空 / 503）-------------------------------------

try:
    from shared import db as _db  # type: ignore
    from sqlalchemy import text as _sql_text
except Exception:
    _db = None
    _sql_text = None

try:
    from shared import sync_state as _sync_state  # type: ignore
except Exception:
    _sync_state = None

try:
    from shared import retry_queue as _retry_queue  # type: ignore
except Exception:
    _retry_queue = None

# ---- CORS --------------------------------------------------------------------

ALLOWED_ORIGINS = {
    "http://localhost:5173",   # Vite dev
    "http://localhost:4173",   # Vite preview
    "http://127.0.0.1:5173",
    "http://127.0.0.1:4173",
}

logging.basicConfig(level=logging.INFO,
                    format="%(asctime)s [%(levelname)s] %(message)s")
log = logging.getLogger("dashboard_server")


# ─────────────────────────── DB helpers ────────────────────────────


def _row_to_dict(row) -> dict:
    """SQLAlchemy Row → plain dict。

    JSON-safe：
      - datetime / date → ISO 字符串
      - Decimal         → float（SQLAlchemy DECIMAL 列）
    """
    out = {}
    for k, v in row._mapping.items():
        # datetime 是 date 的子类 → 一个 isinstance 同时覆盖两者
        if isinstance(v, (datetime, date)):
            out[k] = v.isoformat()
        elif v is not None and v.__class__.__name__ == "Decimal":
            out[k] = float(v)
        else:
            out[k] = v
    return out


def _query(sql: str, **params) -> list[dict]:
    if _db is None or _sql_text is None or not _db.is_mysql_enabled():
        return []
    try:
        with _db.session() as s:
            rows = s.execute(_sql_text(sql), params).fetchall()
            return [_row_to_dict(r) for r in rows]
    except Exception as e:
        log.warning(f"_query failed: {e}\nSQL={sql[:200]}")
        return []


def _execute(sql: str, **params) -> int:
    """Execute UPDATE/INSERT/DELETE; returns rowcount (-1 on error, 0 on no-op).

    Callers can distinguish "no rows matched" (return 0) from "DB error" (return -1)
    from "ok and affected N rows" (return N>0). Old call sites using `if _execute(...)`
    still work because both -1 and 0 are falsy in the boolean sense — but rowcount-aware
    paths (alert ack on derived id<0, retry on missing job) get to choose the right HTTP code.
    """
    if _db is None or _sql_text is None or not _db.is_mysql_enabled():
        return -1
    try:
        with _db.session() as s:
            res = s.execute(_sql_text(sql), params)
            return res.rowcount if res.rowcount is not None else 0
    except Exception as e:
        log.warning(f"_execute failed: {e}")
        return -1


# ─────────────────────────── Param parsing ──────────────────────────


class BadRequest(Exception):
    """Raised when a query/path param fails validation. do_GET / do_POST translate
    this to HTTP 400 with a clean message — no Python internals leak to the frontend."""


def _parse_int(q: dict, name: str, default: int, max_: int | None = None,
               min_: int | None = None) -> int:
    raw = q.get(name)
    if raw is None or raw == "":
        return default
    try:
        v = int(raw)
    except (ValueError, TypeError):
        raise BadRequest(f"invalid {name}: must be integer (got {raw!r})")
    if min_ is not None and v < min_:
        v = min_
    if max_ is not None and v > max_:
        v = max_
    return v


def _parse_float(q: dict, name: str, default: float) -> float:
    raw = q.get(name)
    if raw is None or raw == "":
        return default
    try:
        return float(raw)
    except (ValueError, TypeError):
        raise BadRequest(f"invalid {name}: must be number (got {raw!r})")


def _parse_path_id(raw: str, name: str = "id") -> int:
    try:
        return int(raw)
    except (ValueError, TypeError):
        raise BadRequest(f"invalid {name}: {raw!r}")


# ─────────────────────────── HTTP handler ──────────────────────────


class APIHandler(BaseHTTPRequestHandler):
    server_version = "INTEL-OPS-API/2.0"

    def log_message(self, format, *args):
        log.info(f"{self.client_address[0]} - {format % args}")

    # ---- low-level helpers ----

    def _send_json(self, payload, status=200):
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        # M4: 禁缓存 — 避免 /api/status 等高频接口被代理/浏览器缓存。
        # React 端 TanStack Query 自己已做 staleTime 控制，no-store 只影响中间层。
        self.send_header("Cache-Control", "no-store, no-cache, must-revalidate")
        self.send_header("Pragma", "no-cache")
        self._cors_headers()
        self.end_headers()
        self.wfile.write(body)

    def _send_400(self, msg):
        self._send_json({"error": msg}, status=400)

    def _send_404(self, msg="Not Found"):
        self._send_json({"error": msg}, status=404)

    def _send_500(self, msg):
        self._send_json({"error": msg}, status=500)

    def _cors_headers(self):
        origin = self.headers.get("Origin", "")
        allow = origin if origin in ALLOWED_ORIGINS else "*"
        self.send_header("Access-Control-Allow-Origin", allow)
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")
        self.send_header("Access-Control-Max-Age", "3600")

    def _read_body(self) -> dict:
        n = int(self.headers.get("Content-Length") or 0)
        if n == 0:
            return {}
        raw = self.rfile.read(n)
        try:
            return json.loads(raw.decode("utf-8"))
        except Exception:
            return {}

    def _qs(self) -> dict:
        return {k: (v[0] if v else "") for k, v in
                parse_qs(urlparse(self.path).query).items()}

    # ---- CORS preflight ----

    def do_OPTIONS(self):
        self.send_response(204)
        self._cors_headers()
        self.end_headers()

    # ---- routes ----

    def do_GET(self):
        path = urlparse(self.path).path
        try:
            # === Aggregate ===
            if path == "/api/data/dashboard_data":
                return self.api_dashboard_data()
            if path == "/api/status":
                return self.api_status()

            # === Alerts ===
            if path == "/api/alerts":
                return self.api_alerts()

            # === Reviews ===
            if path == "/api/reviews":
                return self.api_reviews()

            # === IAP / Rank / News / Ads / Website ===
            if path == "/api/iap":
                return self.api_iap()
            if path == "/api/rank":
                return self.api_rank()
            if path == "/api/news":
                return self.api_news()
            if path == "/api/ads":
                return self.api_ads()
            if path == "/api/website":
                return self.api_website()
            if path == "/api/community":
                return self.api_community()

            # === Versions (spec: 后端协作清单 §4.2) ===
            if path == "/api/versions":
                return self.api_versions()
            if path.startswith("/api/versions/") and path.endswith("/related-reviews"):
                vid = path.split("/")[-2]
                return self.api_version_related_reviews(vid)

            # === Aggregated content endpoints (spec §4.2) ===
            if path == "/api/reviews/aggregated":
                return self.api_reviews_aggregated()
            if path == "/api/community-posts/aggregated":
                return self.api_community_aggregated()
            if path == "/api/ads/aggregated":
                return self.api_ads_aggregated()

            # === System ===
            if path == "/api/candidates":
                return self.api_candidates()
            if path == "/api/failed-ai-jobs":
                return self.api_failed_ai_jobs()
            if path == "/api/sync-log":
                return self.api_sync_log()

            # === Health ===
            if path == "/api/health":
                return self._send_json({"status": "ok",
                                        "ts": datetime.utcnow().isoformat()})

            self._send_404(f"Unknown GET path: {path}")
        except BadRequest as e:
            self._send_400(str(e))
        except Exception as e:
            log.exception("GET handler error")
            self._send_500(str(e))

    def do_POST(self):
        path = urlparse(self.path).path
        try:
            # POST /api/alerts/:id/ack
            if path.startswith("/api/alerts/") and path.endswith("/ack"):
                aid = path.split("/")[-2]
                return self.api_alert_ack(aid)
            # POST /api/failed-ai-jobs/:id/retry
            if path.startswith("/api/failed-ai-jobs/") and path.endswith("/retry"):
                jid = path.split("/")[-2]
                return self.api_failed_ai_retry(jid)
            self._send_404(f"Unknown POST path: {path}")
        except BadRequest as e:
            self._send_400(str(e))
        except Exception as e:
            log.exception("POST handler error")
            self._send_500(str(e))

    # ─────────────────── endpoint implementations ───────────────────

    def api_dashboard_data(self):
        """GET /api/data/dashboard_data — 完整聚合数据"""
        if not DASHBOARD_DATA_PATH.exists():
            return self._send_json({"error": "dashboard_data.json not generated yet",
                                    "hint": "run: python3 -m data_pipeline.aggregator"},
                                   status=503)
        try:
            data = json.loads(DASHBOARD_DATA_PATH.read_text(encoding="utf-8"))
            return self._send_json(data)
        except Exception as e:
            return self._send_500(f"failed to read dashboard_data.json: {e}")

    def api_status(self):
        """GET /api/status — 各源最近抓取 / retry queue / AI 失败队列 / 候选数

        sources schema 对前端的形状（与 types/api.ts StatusResponse 对齐）：
            sources: Record<source_name, {
                last_success, last_attempt, last_failure,
                failure_kind, failure_msg, cookie_status,
                consecutive_failures,
                status: "ok" | "fail" | "pending"   # 后端派生的简化标记
            }>
        sync_state.snapshot() 原生形状是 {version: 1, sources: {...}}，这里展平后再
        往每个 source 插入派生 status，让 SyncStatusBar 直接读 sources[k].status。
        """
        sources_status: dict = {}
        if _sync_state:
            try:
                snap = _sync_state.snapshot() or {}
                inner = snap.get("sources") if isinstance(snap, dict) else None
                # 兼容老/新形状：snap 可能是 {version, sources} 也可能直接是 sources map
                if isinstance(inner, dict):
                    sources_status = inner
                elif isinstance(snap, dict):
                    sources_status = snap
            except Exception:
                pass

        # 派生每个 source 的 status badge — SyncStatusBar 用它决定颜色
        for name, s in list(sources_status.items()):
            if not isinstance(s, dict):
                continue
            cf = int(s.get("consecutive_failures") or 0)
            if cf > 0:
                s["status"] = "fail"
            elif s.get("last_success"):
                s["status"] = "ok"
            else:
                s["status"] = "pending"

        # retry queue
        retry_size = 0
        if _retry_queue:
            try:
                retry_size = len(_retry_queue.snapshot().get("items") or [])
            except Exception:
                pass

        # failed_ai_jobs (unresolved) — 与 /api/failed-ai-jobs 的 latest_round 口径对齐：
        # 每个 task 只算其最近一次失败 6h 内的记录，避免上轮老死信永远把侧栏徽章顶到 99+
        failed_ai = _query(
            "SELECT f.task_name, COUNT(*) as n FROM failed_ai_jobs f "
            "WHERE f.resolved_at IS NULL "
            "  AND f.last_attempt_at >= ("
            "    SELECT MAX(last_attempt_at) - INTERVAL 6 HOUR "
            "    FROM failed_ai_jobs WHERE task_name = f.task_name AND resolved_at IS NULL"
            "  ) "
            "GROUP BY f.task_name"
        )

        # candidates (待审阅 = is_relevant=true + reviewed=false 不直接存，前端 localStorage 判定)
        candidate_count = _query(
            "SELECT COUNT(*) as n FROM app_classifications "
            "WHERE is_relevant = 1 AND topic IN ('football','multi_sport') "
            "AND confidence >= 0.85"
        )
        cand_n = (candidate_count[0]["n"] if candidate_count else 0)
        # 表为空 → 用派生候选数
        if cand_n == 0:
            cand_n = len(self._derive_candidates_from_rank(limit=100))

        # alerts new（表为空 → 用派生 alerts 总数；保持 sidebar 红点准确）
        alerts_new = _query(
            "SELECT COUNT(*) as n FROM alerts WHERE status = 'new' "
            "AND fired_at >= DATE_SUB(NOW(), INTERVAL 7 DAY)"
        )
        alerts_n = (alerts_new[0]["n"] if alerts_new else 0)
        if alerts_n == 0:
            # 派生：5 类各取 sub_limit=20，union 后大概 < 100
            tmp = []
            tmp.extend(self._derive_release_alerts_from_json(limit=20))
            tmp.extend(self._derive_ranking_alerts_from_db(limit=20))
            tmp.extend(self._derive_news_alerts_from_json(limit=20))
            tmp.extend(self._derive_churn_alerts_from_db(limit=20))
            tmp.extend(self._derive_rating_alerts_from_db(limit=20))
            alerts_n = len(tmp)

        return self._send_json({
            "sources": sources_status,
            "retry_queue_size": retry_size,
            "failed_ai_jobs": {r["task_name"]: r["n"] for r in failed_ai},
            "candidates_count": cand_n,
            "alerts_new_7d": alerts_n,
            "ts": datetime.utcnow().isoformat(),
        })

    def api_alerts(self):
        """GET /api/alerts?status=&type=&severity=&since= — 预警事件"""
        q = self._qs()
        status = q.get("status", "")
        atype = q.get("type", "")
        sev = q.get("severity", "")
        since = q.get("since", "")  # ISO 或 24h / 7d / 30d 简写
        limit = _parse_int(q, "limit", default=200, max_=1000, min_=1)

        wheres = ["1=1"]
        params = {}
        if status:
            wheres.append("status = :status")
            params["status"] = status
        if atype:
            wheres.append("alert_type = :atype")
            params["atype"] = atype
        if sev:
            wheres.append("severity = :sev")
            params["sev"] = sev
        if since:
            cutoff = self._parse_since(since)
            if cutoff:
                wheres.append("fired_at >= :cutoff")
                params["cutoff"] = cutoff

        sql = (
            "SELECT id, alert_type, severity, app_name, competitor_id, "
            "metadata_json, title, rule_triggered, fired_at, status "
            f"FROM alerts WHERE {' AND '.join(wheres)} "
            "ORDER BY fired_at DESC LIMIT :limit"
        )
        params["limit"] = limit
        rows = _query(sql, **params)
        # 解析 metadata_json
        for r in rows:
            mj = r.pop("metadata_json", None)
            try:
                r["metadata"] = json.loads(mj) if mj else {}
            except Exception:
                r["metadata"] = {}
        # 回退：alerts 表为空时从 dashboard_data.json 派生（避免「产品动态/排名异动」面板空白）
        # 当 alerts 表为空（alert_engine 未跑）时，从 JSON / 现有 MySQL 数据派生几类常见 alerts。
        # 不指定 type 时各类各取 sub_limit 条均衡分布；指定 type 时只派生对应一种到 limit。
        derive_all = not atype
        sub_limit = max(20, limit // 5) if derive_all else limit
        if not rows and (derive_all or atype == "release"):
            rows.extend(self._derive_release_alerts_from_json(limit=sub_limit))
        if derive_all or atype == "ranking":
            rows.extend(self._derive_ranking_alerts_from_db(limit=sub_limit))
        if derive_all or atype == "news":
            rows.extend(self._derive_news_alerts_from_json(limit=sub_limit))
        if derive_all or atype == "churn":
            rows.extend(self._derive_churn_alerts_from_db(limit=sub_limit))
        if derive_all or atype == "rating":
            rows.extend(self._derive_rating_alerts_from_db(limit=sub_limit))
        # 总长度截到 limit
        if len(rows) > limit:
            rows = rows[:limit]
        # since 过滤兜底（派生 alerts 不走 SQL，自己 filter）
        # L7: 用 datetime 解析比较，不再字符串比较 — 防止格式异常 (如 "T00:00:00") 误通过
        if since and rows:
            cutoff = self._parse_since(since)
            if cutoff:
                def _within(fa: str) -> bool:
                    if not fa:
                        return False
                    try:
                        return datetime.fromisoformat(fa.replace("Z", "+00:00").rstrip("Z")) >= cutoff
                    except Exception:
                        return False
                rows = [r for r in rows if _within(r.get("fired_at") or "")]
        return self._send_json({"alerts": rows, "count": len(rows)})

    @staticmethod
    def _derive_release_alerts_from_json(limit: int) -> list:
        """从 dashboard_data.json product_updates.items 派生 release alerts。"""
        try:
            fp = Path(__file__).resolve().parent.parent / "data" / "dashboard_data.json"
            blob = json.loads(fp.read_text(encoding="utf-8"))
        except Exception:
            return []
        items = (blob.get("product_updates") or {}).get("items") or []
        out = []
        for i, it in enumerate(items[:limit]):
            # L7: 缺日期的派生 alert 直接跳过 — 否则 fired_at 会拼成 "T00:00:00"，
            # 字符串排序时 "T" > "2026-..."，错误地通过 since 过滤。
            d = it.get("date")
            if not d:
                continue
            out.append({
                "id": -1000 - i,  # 负 id 区分非 DB 来源
                "alert_type": "release",
                "severity": "info",
                "app_name": it.get("competitor"),
                "competitor_id": None,
                "title": it.get("summary") or f"{it.get('competitor')} {it.get('version','')}",
                "rule_triggered": "version_feature",
                "fired_at": f"{d}T00:00:00",
                "status": "new",
                "metadata": {
                    "version": it.get("version"),
                    "type": it.get("type"),
                    "tags": it.get("tags") or [],
                    "source_url": it.get("source_url"),
                },
            })
        return out

    @staticmethod
    def _derive_ranking_alerts_from_db(limit: int) -> list:
        """从 market_rank_snapshots 直接派生 ranking alerts（最近一天 |delta|≥10）。"""
        try:
            rows = _query("""
                SELECT m.source, m.region_code, COALESCE(c.name, m.name) AS app,
                       m.rank_value, m.delta, m.snapshot_date
                FROM market_rank_snapshots m
                LEFT JOIN competitors c ON c.id = m.competitor_id
                WHERE m.snapshot_date = CURDATE()
                  AND m.delta IS NOT NULL
                  AND ABS(m.delta) >= 10
                ORDER BY ABS(m.delta) DESC LIMIT :lim
            """, lim=limit)
        except Exception:
            return []
        out = []
        for i, r in enumerate(rows or []):
            # L7: 同 release alert，缺 snapshot_date 的条目会拼出 "T00:00:00" 误过过滤。
            sd = r.get("snapshot_date")
            if not sd:
                continue
            delta = r.get("delta") or 0
            sev = "danger" if abs(delta) >= 20 else "warn"
            region = (r.get("region_code") or "").upper() or "全球"
            app = r.get("app") or "—"
            out.append({
                "id": -2000 - i,
                "alert_type": "ranking",
                "severity": sev,
                "app_name": app,
                "competitor_id": None,
                "title": f"{app} 排名变 {int(delta):+d}（{region}）",
                "rule_triggered": "rank_jump_abs",
                "fired_at": f"{sd}T00:00:00",
                "status": "new",
                "metadata": {
                    "delta": int(delta),
                    "rank_value": r.get("rank_value"),
                    "region": r.get("region_code"),
                    "source": r.get("source"),
                },
            })
        return out

    @staticmethod
    def _derive_news_alerts_from_json(limit: int) -> list:
        """从 async_google_news.json 派生 news alerts（每竞品取前 N 条）。"""
        fp = Path(__file__).resolve().parent.parent / "data" / "async_google_news.json"
        if not fp.exists():
            return []
        try:
            blob = json.loads(fp.read_text(encoding="utf-8"))
        except Exception:
            return []
        out = []
        for rec in blob if isinstance(blob, list) else []:
            comp = rec.get("competitor", "")
            for it in (rec.get("data") or {}).get("items", [])[:5]:
                if len(out) >= limit: break
                title = it.get("title") or ""
                pub = it.get("pub") or it.get("published") or ""
                # 解析 RFC2822 → ISO（粗）
                from email.utils import parsedate_to_datetime
                try:
                    dt = parsedate_to_datetime(pub)
                    fired = dt.isoformat()
                except Exception:
                    fired = pub or ""
                out.append({
                    "id": -3000 - len(out),
                    "alert_type": "news",
                    "severity": "info",
                    "app_name": comp,
                    "competitor_id": None,
                    "title": title[:200],
                    "rule_triggered": "biz_news",
                    "fired_at": fired,
                    "status": "new",
                    "metadata": {"source_url": it.get("link"), "source": it.get("source")},
                })
            if len(out) >= limit: break
        return out

    @staticmethod
    def _derive_churn_alerts_from_db(limit: int) -> list:
        """从 reviews label='churn_signal' 派生 churn alerts。"""
        try:
            rows = _query("""
                SELECT r.id, c.name AS competitor, r.region_code, r.score,
                       LEFT(r.content, 120) AS content, r.fetched_at, r.labeled_at
                FROM reviews r JOIN competitors c ON c.id = r.competitor_id
                WHERE r.label = 'churn_signal'
                ORDER BY r.fetched_at DESC LIMIT :lim
            """, lim=limit)
        except Exception:
            return []
        out = []
        for i, r in enumerate(rows or []):
            out.append({
                "id": -4000 - i,
                "alert_type": "churn",
                "severity": "danger",
                "app_name": r.get("competitor"),
                "competitor_id": None,
                "title": f"{r.get('competitor')}（{(r.get('region_code') or '').upper()}）{r.get('content','')}",
                "rule_triggered": "churn_signal_review",
                "fired_at": (r.get("fetched_at").isoformat() if hasattr(r.get("fetched_at"), "isoformat") else str(r.get("fetched_at") or "")),
                "status": "new",
                "metadata": {"score": r.get("score"), "region": r.get("region_code")},
            })
        return out

    @staticmethod
    def _derive_rating_alerts_from_db(limit: int) -> list:
        """从 reviews label='complaint' 派生 rating alerts（投诉聚集）。"""
        try:
            rows = _query("""
                SELECT r.id, c.name AS competitor, r.region_code, r.score,
                       LEFT(r.content, 120) AS content, r.fetched_at
                FROM reviews r JOIN competitors c ON c.id = r.competitor_id
                WHERE r.label = 'complaint' AND r.score <= 2
                ORDER BY r.fetched_at DESC LIMIT :lim
            """, lim=limit)
        except Exception:
            return []
        out = []
        for i, r in enumerate(rows or []):
            out.append({
                "id": -5000 - i,
                "alert_type": "rating",
                "severity": "warn",
                "app_name": r.get("competitor"),
                "competitor_id": None,
                "title": f"{r.get('competitor')}（{(r.get('region_code') or '').upper()}）★{r.get('score')} {r.get('content','')}",
                "rule_triggered": "negative_review",
                "fired_at": (r.get("fetched_at").isoformat() if hasattr(r.get("fetched_at"), "isoformat") else str(r.get("fetched_at") or "")),
                "status": "new",
                "metadata": {"score": r.get("score"), "region": r.get("region_code")},
            })
        return out

    def api_alert_ack(self, alert_id: str):
        """POST /api/alerts/:id/ack — 标记预警已读

        派生 alert (id<0) 来自 JSON fallback，不在 alerts 表里 — 直接 ack 不会持久化，
        重新加载就会再次出现。这里返 400 让前端显示"该预警来自 JSON fallback，无法标记"。
        DB 中真实存在的 id 但本次 UPDATE 影响 0 行（已被 ack 或 dismiss）→ 200，幂等。
        """
        aid = _parse_path_id(alert_id, "alert id")
        if aid < 0:
            raise BadRequest("derived alert (id<0) cannot be acked — it is regenerated from JSON fallback each request")
        rc = _execute("UPDATE alerts SET status = 'ack' WHERE id = :id", id=aid)
        if rc < 0:
            return self._send_500("DB error while updating alert")
        if rc == 0:
            return self._send_404(f"alert {aid} not found")
        return self._send_json({"ok": True, "id": aid, "affected": rc})

    def api_reviews(self):
        """GET /api/reviews?competitor=&label=&region=&since=&limit="""
        q = self._qs()
        competitor = q.get("competitor", "")
        label = q.get("label", "")
        region = q.get("region", "")
        since = q.get("since", "")
        limit = _parse_int(q, "limit", default=100, max_=500, min_=1)

        wheres = ["r.labeled_at IS NOT NULL"]
        params = {}
        if competitor:
            wheres.append("c.name = :competitor")
            params["competitor"] = competitor
        if label:
            wheres.append("r.label = :label")
            params["label"] = label
        if region:
            wheres.append("r.region_code = :region")
            params["region"] = region
        if since:
            cutoff = self._parse_since(since)
            if cutoff:
                # 优先按 review 时间（Apple 写的），其次 fetched_at —— 否则全部今天抓的会全命中
                wheres.append("COALESCE(r.at, r.fetched_at) >= :cutoff")
                params["cutoff"] = cutoff

        # ─── 去重：reviews 表 86% 重复（GP 同一英文评论被 12 个 country
        #     各 INSERT 一次）。用 GROUP BY (competitor, platform, content,
        #     score, version) 合并，regions 字段聚合所有命中的区域 CSV。
        #     id 取 MIN，时间取 MIN — 保留最早记录。
        sql = (
            "SELECT MIN(r.id) as id, c.name as competitor, "
            "GROUP_CONCAT(DISTINCT r.region_code "
            "             ORDER BY r.region_code SEPARATOR ',') as regions, "
            "r.platform, r.score, r.version, r.content, r.label, r.language, "
            "r.translated_text, MIN(r.at) as at, MIN(r.labeled_at) as labeled_at "
            "FROM reviews r JOIN competitors c ON c.id = r.competitor_id "
            f"WHERE {' AND '.join(wheres)} "
            "GROUP BY c.name, r.platform, r.score, r.version, r.content, "
            "         r.label, r.language, r.translated_text "
            "ORDER BY MIN(COALESCE(r.at, r.fetched_at)) DESC LIMIT :limit"
        )
        params["limit"] = limit
        rows = _query(sql, **params)

        # 加 entities（按 review_id 一次 IN 查）
        if rows:
            ids = [r["id"] for r in rows]
            ent_sql = (
                "SELECT review_id, canonical_id, entity_type, raw_value "
                "FROM comment_entities WHERE review_id IN :ids"
            )
            # SQLAlchemy 不直接支持 tuple expansion 用 :ids，改用 inline list
            placeholders = ",".join(str(i) for i in ids)
            ent_rows = _query(
                f"SELECT review_id, canonical_id, entity_type, raw_value "
                f"FROM comment_entities WHERE review_id IN ({placeholders})"
            )
            by_rid = {}
            for er in ent_rows:
                by_rid.setdefault(er["review_id"], []).append({
                    "canonical_id": er["canonical_id"],
                    "type": er["entity_type"],
                    "raw_value": er["raw_value"],
                })
            for r in rows:
                r["entities"] = by_rid.get(r["id"], [])

        # 拆 regions CSV → 数组（前端按 chip 渲染），region_code 留第一个保持兼容
        for r in rows:
            csv = r.pop("regions", "") or ""
            regions = [x for x in csv.split(",") if x]
            r["regions"] = regions
            r["region_code"] = regions[0] if regions else None

        return self._send_json({"reviews": rows, "count": len(rows)})

    def api_iap(self):
        """GET /api/iap?competitor=&region=&limit="""
        q = self._qs()
        competitor = q.get("competitor", "")
        region = q.get("region", "")
        limit = _parse_int(q, "limit", default=500, max_=5000, min_=1)
        wheres = ["1=1"]
        params = {"limit": limit}
        if competitor:
            wheres.append("c.name = :competitor")
            params["competitor"] = competitor
        if region:
            wheres.append("i.region_code = :region")
            params["region"] = region
        sql = (
            "SELECT i.id, c.name as competitor, i.region_code, i.name, "
            "i.price, i.price_num, i.currency, i.category, i.fetched_at "
            "FROM iap_items i JOIN competitors c ON c.id = i.competitor_id "
            f"WHERE {' AND '.join(wheres)} "
            "ORDER BY i.fetched_at DESC LIMIT :limit"
        )
        rows = _query(sql, **params)
        return self._send_json({"iap_items": rows, "count": len(rows)})

    def api_rank(self):
        """GET /api/rank?source=&region=&competitor=&date="""
        q = self._qs()
        source = q.get("source", "")
        region = q.get("region", "")
        competitor = q.get("competitor", "")
        date = q.get("date", "")
        limit = _parse_int(q, "limit", default=200, max_=2000, min_=1)
        wheres = ["1=1"]
        params = {"limit": limit}
        if source:
            wheres.append("m.source = :source")
            params["source"] = source
        if region == "global":
            wheres.append("m.region_code IS NULL")
        elif region:
            wheres.append("m.region_code = :region")
            params["region"] = region
        if competitor:
            wheres.append("c.name = :competitor")
            params["competitor"] = competitor
        if date:
            wheres.append("m.snapshot_date = :date")
            params["date"] = date
        else:
            wheres.append("m.snapshot_date >= DATE_SUB(CURDATE(), INTERVAL 7 DAY)")
        sql = (
            "SELECT m.id, m.source, m.region_code, c.name as competitor, "
            "m.name, m.rank_value, m.delta, m.downloads, m.downloads_num, "
            "m.revenue_num, m.snapshot_date, m.fetched_at "
            "FROM market_rank_snapshots m "
            "LEFT JOIN competitors c ON c.id = m.competitor_id "
            f"WHERE {' AND '.join(wheres)} "
            "ORDER BY m.snapshot_date DESC, m.rank_value ASC LIMIT :limit"
        )
        rows = _query(sql, **params)
        return self._send_json({"rankings": rows, "count": len(rows)})

    def api_news(self):
        """GET /api/news?since=&category=&app=&business_only=&limit=
        从 news_items 表读（task #5 news_classifier 写入分类字段）。
        默认只返回 is_business=true 的条目；business_only=0 可看全部。
        category= funding/acquisition/partnership/launch/strategy/hiring/legal/other
        app= 9 竞品名 + AllFootball
        """
        q = self._qs()
        since = q.get("since", "7d")
        category = q.get("category", "")
        app = q.get("app", "") or q.get("competitor", "")
        business_only = q.get("business_only", "1") != "0"
        limit = _parse_int(q, "limit", default=200, max_=1000, min_=1)

        wheres = ["1=1"]
        params = {"limit": limit}
        if business_only:
            wheres.append("is_business = 1")
        if category:
            wheres.append("business_category = :category")
            params["category"] = category
        if app:
            wheres.append("app_name = :app")
            params["app"] = app
        cutoff = self._parse_since(since) if since else None
        if cutoff:
            wheres.append("published_at >= :cutoff")
            params["cutoff"] = cutoff

        sql = (
            "SELECT id, title, snippet, source, url, published_at, "
            "matched_keyword, app_name, fetched_at, "
            "is_business, business_category, competitors_mentioned, "
            "classification_confidence, classified_at "
            "FROM news_items "
            f"WHERE {' AND '.join(wheres)} "
            "ORDER BY published_at DESC LIMIT :limit"
        )
        rows = _query(sql, **params)
        # JSON 字段反序列化
        for r in rows:
            cm = r.get("competitors_mentioned")
            try:
                r["competitors_mentioned"] = json.loads(cm) if cm else []
            except Exception:
                r["competitors_mentioned"] = []
            cc = r.get("classification_confidence")
            if cc is not None:
                try:
                    r["classification_confidence"] = float(cc)
                except (TypeError, ValueError):
                    r["classification_confidence"] = None

        # 兜底：仅当 news_items 表本身完全空时回退读 JSON
        # （google_news 跑过但还没 ingest 入库 + 还没跑 news_classifier 的早期场景）
        # 注意：不能用 `if not rows`！过滤后空 ≠ 表空 — 24h since 过滤后 0 条
        # 但表里有 63 条已分类，错误触发 fallback 会让 JSON 里的比赛预告
        # 涌入前端展示在"等待分类"桶，造成"今日 11 条 > 7d 2 条"自相矛盾。
        if not rows:
            empty_table = _query("SELECT 1 AS x FROM news_items LIMIT 1")
            if not empty_table:
                rows = self._derive_news_from_json(cutoff, limit, business_only)

        return self._send_json({"news": rows, "count": len(rows)})

    @staticmethod
    def _derive_news_from_json(cutoff, limit: int, business_only: bool = True) -> list:
        """news_items 表空时退化读 async_google_news.json（保持前端不空白）。

        business_only=True 时只返回 google_news 标记 is_biz=True 的条目（关键词 fuzzy 命中），
        防御性 — 跟 SQL 路径的 `WHERE is_business=1` 行为对齐，避免 fallback 数据
        被当成"等待分类"展示。
        """
        path = DATA_DIR / "async_google_news.json"
        if not path.exists():
            return []
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            return []
        out = []
        cutoff_iso = cutoff.isoformat() if cutoff else None
        for rec in data:
            app = rec.get("competitor")
            for item in (rec.get("data") or {}).get("items", []):
                pub_iso = item.get("pub_iso") or ""
                if cutoff_iso and pub_iso and pub_iso < cutoff_iso:
                    continue
                is_biz = bool(item.get("is_biz"))
                if business_only and not is_biz:
                    continue
                out.append({
                    "id": -1,
                    "title": item.get("title"),
                    "snippet": item.get("desc"),
                    "source": item.get("source"),
                    "url": item.get("link"),
                    "published_at": pub_iso,
                    "matched_keyword": "biz" if is_biz else "broad",
                    "app_name": app,
                    "fetched_at": None,
                    "is_business": is_biz,
                    "business_category": None,
                    "competitors_mentioned": [],
                    "classification_confidence": None,
                    "classified_at": None,
                })
        out.sort(key=lambda x: x.get("published_at") or "", reverse=True)
        return out[:limit]

    def api_ads(self):
        """GET /api/ads?competitor=&country=&selling_point=&audience=&tone=&limit=
        透传 task #7 ad_selling_point 写入的 selling_points / audience / tone 字段。
        """
        q = self._qs()
        competitor = q.get("competitor", "")
        country = q.get("country", "") or q.get("region", "")
        selling_point = q.get("selling_point", "")
        audience = q.get("audience", "")
        tone = q.get("tone", "")
        limit = _parse_int(q, "limit", default=200, max_=1000, min_=1)

        wheres = ["1=1"]
        params = {"limit": limit}
        if competitor:
            wheres.append("c.name = :competitor")
            params["competitor"] = competitor
        if country:
            wheres.append("a.region_code = :country")
            params["country"] = country
        if audience:
            wheres.append("a.audience = :audience")
            params["audience"] = audience
        if tone:
            wheres.append("a.tone = :tone")
            params["tone"] = tone
        if selling_point:
            # JSON_CONTAINS — MySQL 8 原生支持
            wheres.append("JSON_CONTAINS(a.selling_points, JSON_QUOTE(:sp))")
            params["sp"] = selling_point

        sql = (
            "SELECT a.id, c.name as competitor, a.region_code as region, a.ad_id, "
            "a.text as body_text, a.media_url, a.start_date, a.platform, a.page_name, "
            "a.fetched_at, "
            "a.selling_points, a.audience, a.tone, "
            "a.selling_classified_at, a.selling_confidence "
            "FROM ad_creatives a JOIN competitors c ON c.id = a.competitor_id "
            f"WHERE {' AND '.join(wheres)} "
            "ORDER BY a.fetched_at DESC LIMIT :limit"
        )
        rows = _query(sql, **params)
        for r in rows:
            sp = r.get("selling_points")
            try:
                r["selling_points"] = json.loads(sp) if sp else []
            except Exception:
                r["selling_points"] = []
            sc = r.get("selling_confidence")
            if sc is not None:
                try:
                    r["selling_confidence"] = float(sc)
                except (TypeError, ValueError):
                    r["selling_confidence"] = None
        return self._send_json({"ads": rows, "count": len(rows)})

    def api_website(self):
        """GET /api/website?competitor=&month="""
        q = self._qs()
        competitor = q.get("competitor", "")
        month = q.get("month", "")
        wheres = ["1=1"]
        params = {}
        if competitor:
            wheres.append("c.name = :competitor")
            params["competitor"] = competitor
        if month:
            wheres.append("w.snapshot_month = :month")
            params["month"] = month
        sql = (
            "SELECT w.id, c.name as competitor, w.domain, w.snapshot_month, "
            "w.monthly_visits, w.monthly_visits_num, "
            "w.avg_visit_duration, w.avg_visit_duration_sec, "
            "w.pages_per_visit, w.bounce_rate, "
            "w.global_rank, w.country_rank, w.country_rank_country, w.category_rank, "
            "w.male_share, w.female_share, "
            "w.top_countries_json, w.similar_sites_json, w.fetched_at "
            "FROM website_traffic w JOIN competitors c ON c.id = w.competitor_id "
            f"WHERE {' AND '.join(wheres)} "
            "ORDER BY w.snapshot_month DESC, c.name"
        )
        rows = _query(sql, **params)
        for r in rows:
            for k in ("top_countries_json", "similar_sites_json"):
                v = r.pop(k, None)
                key = k.replace("_json", "")
                try:
                    r[key] = json.loads(v) if v else []
                except Exception:
                    r[key] = []
        return self._send_json({"website": rows, "count": len(rows)})

    def api_community(self):
        """GET /api/community?source=&competitor=&topic=&mentioned=&since=&limit=
        透传 task #6 post_topic_classifier 写入的 primary_topic / secondary_topics /
        competitor_mentioned 字段。
        """
        q = self._qs()
        source = q.get("source", "")
        competitor = q.get("competitor", "")
        topic = q.get("topic", "")
        mentioned = q.get("mentioned", "")
        since = q.get("since", "")
        limit = _parse_int(q, "limit", default=50, max_=500, min_=1)

        wheres = ["1=1"]
        params = {"limit": limit}
        if source:
            wheres.append("p.source = :source")
            params["source"] = source
        if competitor:
            wheres.append("c.name = :competitor")
            params["competitor"] = competitor
        if topic:
            wheres.append("p.primary_topic = :topic")
            params["topic"] = topic
        if mentioned:
            wheres.append("p.competitor_mentioned = :mentioned")
            params["mentioned"] = mentioned
        if since:
            cutoff = self._parse_since(since)
            if cutoff:
                wheres.append("COALESCE(p.created_utc, p.fetched_at) >= :cutoff")
                params["cutoff"] = cutoff

        sql = (
            "SELECT p.id, c.name as competitor, p.source, p.post_id, p.subreddit, "
            "p.title, p.selftext, p.score, p.num_comments, p.url, "
            "p.created_utc, p.fetched_at, "
            "p.primary_topic, p.secondary_topics, p.competitor_mentioned, "
            "p.topic_classified_at, p.topic_confidence "
            "FROM community_posts p JOIN competitors c ON c.id = p.competitor_id "
            f"WHERE {' AND '.join(wheres)} "
            "ORDER BY p.score DESC, p.created_utc DESC LIMIT :limit"
        )
        rows = _query(sql, **params)
        for r in rows:
            st = r.get("secondary_topics")
            try:
                r["secondary_topics"] = json.loads(st) if st else []
            except Exception:
                r["secondary_topics"] = []
            tc = r.get("topic_confidence")
            if tc is not None:
                try:
                    r["topic_confidence"] = float(tc)
                except (TypeError, ValueError):
                    r["topic_confidence"] = None
        return self._send_json({"posts": rows, "count": len(rows)})

    # ─────────────── Versions (spec §4.2) ───────────────

    def api_versions(self):
        """GET /api/versions?competitor=&since=30d&limit= — app_versions 列表"""
        q = self._qs()
        competitor = q.get("competitor", "")
        since = q.get("since", "30d")
        limit = _parse_int(q, "limit", default=200, max_=1000, min_=1)

        wheres = ["1=1"]
        params = {"limit": limit}
        if competitor:
            wheres.append("c.name = :competitor")
            params["competitor"] = competitor
        cutoff = self._parse_since(since) if since else None
        if cutoff:
            wheres.append("v.released_at >= :cutoff")
            params["cutoff"] = cutoff

        sql = (
            "SELECT v.id, c.name as competitor, v.platform, v.version, "
            "v.release_notes, v.release_notes_lang, "
            "v.release_notes_translated_zh as release_notes_zh, "
            "v.translated_at, v.released_at, v.first_seen_at "
            "FROM app_versions v JOIN competitors c ON c.id = v.competitor_id "
            f"WHERE {' AND '.join(wheres)} "
            "ORDER BY v.released_at DESC, v.id DESC LIMIT :limit"
        )
        rows = _query(sql, **params)
        return self._send_json({"versions": rows, "count": len(rows)})

    def api_version_related_reviews(self, version_id_str: str):
        """GET /api/versions/:id/related-reviews — 该版本下评论统计 + 高频实体 Top"""
        try:
            vid = int(version_id_str)
        except (TypeError, ValueError):
            return self._send_json({"error": "invalid version id"}, status=400)

        # 取版本元数据 + competitor_id
        version_rows = _query(
            "SELECT v.id, v.competitor_id, v.version, v.released_at, c.name as competitor "
            "FROM app_versions v JOIN competitors c ON c.id = v.competitor_id "
            "WHERE v.id = :vid",
            vid=vid,
        )
        if not version_rows:
            return self._send_json({"error": "version not found"}, status=404)
        v = version_rows[0]

        # 关联评论：reviews.version 字符串匹配
        review_count_rows = _query(
            "SELECT COUNT(*) as n FROM reviews "
            "WHERE competitor_id = :cid AND version = :ver",
            cid=v["competitor_id"], ver=v["version"],
        )
        review_count = (review_count_rows[0]["n"] if review_count_rows else 0)

        # label 分布
        label_dist_rows = _query(
            "SELECT label, COUNT(*) as n FROM reviews "
            "WHERE competitor_id = :cid AND version = :ver "
            "AND label IS NOT NULL "
            "GROUP BY label ORDER BY n DESC",
            cid=v["competitor_id"], ver=v["version"],
        )
        label_distribution = {r["label"]: r["n"] for r in label_dist_rows}

        # 高频实体（comment_entities 关联到该版本的 reviews）
        top_entities_rows = _query("""
            SELECT ce.canonical_id,
                   ea.primary_name,
                   ea.entity_type,
                   COUNT(DISTINCT ce.review_id) as n
            FROM comment_entities ce
            JOIN reviews r ON r.id = ce.review_id
            LEFT JOIN entity_aliases ea ON ea.canonical_id = ce.canonical_id
            WHERE r.competitor_id = :cid AND r.version = :ver
            GROUP BY ce.canonical_id, ea.primary_name, ea.entity_type
            ORDER BY n DESC LIMIT 10
        """, cid=v["competitor_id"], ver=v["version"])

        # 评分变化（vs 上一版本）
        rating_rows = _query(
            "SELECT AVG(rating) as avg_rating FROM reviews "
            "WHERE competitor_id = :cid AND version = :ver AND rating IS NOT NULL",
            cid=v["competitor_id"], ver=v["version"],
        )
        rating_after = float(rating_rows[0]["avg_rating"]) if rating_rows and rating_rows[0]["avg_rating"] is not None else None

        # 上一版本评分（先找 released_at < this 的最近一个 version）
        rating_before = None
        prev_version_rows = _query(
            "SELECT version FROM app_versions "
            "WHERE competitor_id = :cid AND released_at < :rel "
            "ORDER BY released_at DESC LIMIT 1",
            cid=v["competitor_id"],
            rel=v["released_at"] or datetime.utcnow(),
        )
        if prev_version_rows:
            prev_ver = prev_version_rows[0]["version"]
            prev_rating_rows = _query(
                "SELECT AVG(rating) as avg_rating FROM reviews "
                "WHERE competitor_id = :cid AND version = :ver AND rating IS NOT NULL",
                cid=v["competitor_id"], ver=prev_ver,
            )
            if prev_rating_rows and prev_rating_rows[0]["avg_rating"] is not None:
                rating_before = float(prev_rating_rows[0]["avg_rating"])

        return self._send_json({
            "version_id": vid,
            "competitor": v["competitor"],
            "version": v["version"],
            "review_count": review_count,
            "label_distribution": label_distribution,
            "rating_change": {
                "before": rating_before,
                "after": rating_after,
                "delta": (rating_after - rating_before) if (rating_after is not None and rating_before is not None) else None,
            },
            "top_entities": [
                {"canonical_id": r["canonical_id"],
                 "primary_name": r.get("primary_name") or r["canonical_id"],
                 "entity_type": r.get("entity_type"),
                 "count": r["n"]}
                for r in top_entities_rows
            ],
        })

    # ─────────────── Aggregated content (spec §4.2) ───────────────

    def api_reviews_aggregated(self):
        """GET /api/reviews/aggregated?tab=problems|praise|localization|churn
        按 entity 聚合的评论数据，给 GP 评论页 4 个 tab 用。

        - problems     bug 实体 + complaint 标签
        - praise       feature 实体 + positive 标签
        - localization localization / language 实体
        - churn        churn_signal 标签 + competitor 实体
        """
        q = self._qs()
        tab = (q.get("tab") or "problems").lower()
        limit = _parse_int(q, "limit", default=50, max_=200, min_=1)

        if tab == "problems":
            entity_filter = "ea.entity_type = 'bug'"
            label_filter = "r.label = 'complaint'"
        elif tab == "praise":
            entity_filter = "ea.entity_type = 'feature'"
            label_filter = "r.label = 'positive'"
        elif tab == "localization":
            entity_filter = "ea.entity_type IN ('localization', 'language')"
            label_filter = "1=1"
        elif tab == "churn":
            entity_filter = "ea.entity_type = 'competitor'"
            label_filter = "r.label = 'churn_signal'"
        else:
            return self._send_json({"error": f"invalid tab: {tab}"}, status=400)

        # 主聚合：按 canonical_id 累计提及数 + 各竞品分布 + 各区域分布
        # 注意 dedup：reviews 表 86% 重复（同一英文 GP 评论被 12 国 INSERT 12 次）。
        # COUNT(DISTINCT ce.review_id) 把 12 个不同 review_id 算 12 次 — 数字虚高。
        # 改用 CONCAT(competitor_id, platform, content, score, version) 作 dedup key,
        # 跟 /api/reviews 那边的 GROUP BY 维度保持一致。
        DEDUP_KEY = (
            "CONCAT_WS('|', r.competitor_id, r.platform, r.content, "
            "          IFNULL(r.score, ''), IFNULL(r.version, ''))"
        )
        rows = _query(f"""
            SELECT ce.canonical_id,
                   ea.primary_name,
                   ea.entity_type,
                   COUNT(DISTINCT {DEDUP_KEY}) as total_mentions
            FROM comment_entities ce
            JOIN reviews r ON r.id = ce.review_id
            LEFT JOIN entity_aliases ea ON ea.canonical_id = ce.canonical_id
            WHERE {entity_filter} AND {label_filter}
            GROUP BY ce.canonical_id, ea.primary_name, ea.entity_type
            ORDER BY total_mentions DESC LIMIT :lim
        """, lim=limit)

        out = []
        for r in rows:
            cid = r["canonical_id"]
            # 各竞品分布 — 同样 dedup
            by_comp_rows = _query(f"""
                SELECT cp.name as competitor,
                       COUNT(DISTINCT {DEDUP_KEY}) as n
                FROM comment_entities ce
                JOIN reviews r ON r.id = ce.review_id
                JOIN competitors cp ON cp.id = r.competitor_id
                WHERE ce.canonical_id = :cid AND {label_filter}
                GROUP BY cp.name ORDER BY n DESC LIMIT 10
            """, cid=cid)
            # 各区域分布 — 不 dedup（同一评论在多区域出现是真的多区域热度）
            by_region_rows = _query(f"""
                SELECT r.region_code as region, COUNT(*) as n
                FROM comment_entities ce
                JOIN reviews r ON r.id = ce.review_id
                WHERE ce.canonical_id = :cid AND {label_filter}
                GROUP BY r.region_code ORDER BY n DESC LIMIT 5
            """, cid=cid)
            # 代表评论
            sample_rows = _query(f"""
                SELECT r.id, COALESCE(r.translated_text, r.content) as text_zh,
                       cp.name as competitor, r.region_code as region, r.score as score
                FROM comment_entities ce
                JOIN reviews r ON r.id = ce.review_id
                JOIN competitors cp ON cp.id = r.competitor_id
                WHERE ce.canonical_id = :cid AND {label_filter}
                ORDER BY COALESCE(r.at, r.fetched_at) DESC LIMIT 1
            """, cid=cid)
            out.append({
                "canonical_id": cid,
                "primary_name": r.get("primary_name") or cid,
                "entity_type": r.get("entity_type"),
                "total_mentions": r["total_mentions"],
                "by_competitor": {x["competitor"]: x["n"] for x in by_comp_rows},
                "by_region": {(x["region"] or "").upper(): x["n"] for x in by_region_rows},
                "representative_review": sample_rows[0] if sample_rows else None,
            })

        return self._send_json({"tab": tab, "items": out, "count": len(out)})

    def api_community_aggregated(self):
        """GET /api/community-posts/aggregated?dim=topic|player|league|competitor
        社媒帖子按维度聚合。
        """
        q = self._qs()
        dim = (q.get("dim") or "topic").lower()
        limit = _parse_int(q, "limit", default=50, max_=200, min_=1)
        since = q.get("since", "30d")
        cutoff = self._parse_since(since) if since else None

        params = {"lim": limit}
        time_clause = ""
        if cutoff:
            time_clause = "AND COALESCE(p.created_utc, p.fetched_at) >= :cutoff"
            params["cutoff"] = cutoff

        if dim == "topic":
            rows = _query(f"""
                SELECT p.primary_topic as topic,
                       COUNT(*) as post_count,
                       SUM(COALESCE(p.score, 0)) as total_score,
                       COUNT(DISTINCT p.competitor_mentioned) as comp_count
                FROM community_posts p
                WHERE p.primary_topic IS NOT NULL {time_clause}
                GROUP BY p.primary_topic
                ORDER BY post_count DESC LIMIT :lim
            """, **params)
            return self._send_json({"dim": dim, "items": rows, "count": len(rows)})

        if dim == "competitor":
            # 按 competitor_mentioned 聚合 + 每个竞品的 Top 3 话题
            rows = _query(f"""
                SELECT p.competitor_mentioned as competitor,
                       COUNT(*) as post_count,
                       SUM(COALESCE(p.score, 0)) as total_score
                FROM community_posts p
                WHERE p.competitor_mentioned IS NOT NULL {time_clause}
                GROUP BY p.competitor_mentioned
                ORDER BY post_count DESC LIMIT :lim
            """, **params)
            for r in rows:
                # 该竞品下 top topic
                topics = _query(f"""
                    SELECT p.primary_topic as topic, COUNT(*) as n
                    FROM community_posts p
                    WHERE p.competitor_mentioned = :c AND p.primary_topic IS NOT NULL {time_clause}
                    GROUP BY p.primary_topic ORDER BY n DESC LIMIT 3
                """, c=r["competitor"], **{k: v for k, v in params.items() if k != "lim"})
                r["top_topics"] = topics
            return self._send_json({"dim": dim, "items": rows, "count": len(rows)})

        if dim in ("player", "league"):
            # 走 community_post_entities × entity_aliases (migration 0016 + post_entity_extract task)
            entity_type = "player" if dim == "player" else "league"
            rows = _query(f"""
                SELECT ea.canonical_id,
                       ea.primary_name,
                       COUNT(DISTINCT cpe.post_id) as post_count,
                       SUM(COALESCE(p.score, 0)) as total_score
                FROM community_post_entities cpe
                JOIN community_posts p ON p.id = cpe.post_id
                JOIN entity_aliases ea ON ea.canonical_id = cpe.canonical_id
                WHERE ea.entity_type = :etype {time_clause}
                GROUP BY ea.canonical_id, ea.primary_name
                ORDER BY post_count DESC, total_score DESC LIMIT :lim
            """, etype=entity_type, **params)
            # 每行附带 Top 3 提及该实体的竞品 + 几个高频共现实体
            for r in rows:
                cid = r["canonical_id"]
                # 命中该 player/league 时主要是哪几个竞品在讨论
                comps = _query(f"""
                    SELECT c.name as competitor, COUNT(DISTINCT p.id) as n
                    FROM community_post_entities cpe
                    JOIN community_posts p ON p.id = cpe.post_id
                    JOIN competitors c ON c.id = p.competitor_id
                    WHERE cpe.canonical_id = :cid {time_clause}
                    GROUP BY c.name ORDER BY n DESC LIMIT 3
                """, cid=cid, **{k: v for k, v in params.items() if k != "lim"})
                r["top_competitors"] = comps
                # 高频共现实体（同 post 里同时出现的其他实体，按出现次数）
                cooc = _query(f"""
                    SELECT ea2.primary_name as name, ea2.entity_type as etype,
                           COUNT(DISTINCT cpe2.post_id) as n
                    FROM community_post_entities cpe1
                    JOIN community_post_entities cpe2 ON cpe2.post_id = cpe1.post_id
                                                     AND cpe2.canonical_id != cpe1.canonical_id
                    JOIN entity_aliases ea2 ON ea2.canonical_id = cpe2.canonical_id
                    WHERE cpe1.canonical_id = :cid
                    GROUP BY ea2.primary_name, ea2.entity_type
                    ORDER BY n DESC LIMIT 5
                """, cid=cid)
                r["cooccurring"] = cooc
            return self._send_json({"dim": dim, "items": rows, "count": len(rows)})

        return self._send_json({"error": f"invalid dim: {dim}"}, status=400)

    def api_ads_aggregated(self):
        """GET /api/ads/aggregated?dim=selling_point|region|competitor
        广告创意按维度聚合（task #7 ad_selling_point 输出）。
        """
        q = self._qs()
        dim = (q.get("dim") or "selling_point").lower()
        limit = _parse_int(q, "limit", default=50, max_=200, min_=1)

        if dim == "selling_point":
            # 用 JSON_TABLE 拆 selling_points 数组（MySQL 8）
            rows = _query("""
                SELECT jt.sp as selling_point,
                       COUNT(*) as creative_count,
                       COUNT(DISTINCT a.competitor_id) as comp_count
                FROM ad_creatives a
                JOIN JSON_TABLE(
                    COALESCE(a.selling_points, '[]'),
                    '$[*]' COLUMNS (sp VARCHAR(64) PATH '$')
                ) jt
                WHERE a.selling_classified_at IS NOT NULL
                GROUP BY jt.sp
                ORDER BY creative_count DESC LIMIT :lim
            """, lim=limit)
            for r in rows:
                # 该卖点的 Top 竞品
                tops = _query("""
                    SELECT c.name as competitor, COUNT(*) as n
                    FROM ad_creatives a
                    JOIN competitors c ON c.id = a.competitor_id
                    JOIN JSON_TABLE(
                        COALESCE(a.selling_points, '[]'),
                        '$[*]' COLUMNS (sp VARCHAR(64) PATH '$')
                    ) jt
                    WHERE jt.sp = :sp
                    GROUP BY c.name ORDER BY n DESC LIMIT 3
                """, sp=r["selling_point"])
                r["top_competitors"] = tops
            return self._send_json({"dim": dim, "items": rows, "count": len(rows)})

        if dim == "region":
            rows = _query("""
                SELECT a.region_code as region,
                       COUNT(*) as creative_count,
                       COUNT(DISTINCT a.competitor_id) as comp_count
                FROM ad_creatives a
                GROUP BY a.region_code
                ORDER BY creative_count DESC LIMIT :lim
            """, lim=limit)
            return self._send_json({"dim": dim, "items": rows, "count": len(rows)})

        if dim == "competitor":
            # 每个竞品的卖点构成
            rows = _query("""
                SELECT c.name as competitor,
                       COUNT(*) as creative_count
                FROM ad_creatives a
                JOIN competitors c ON c.id = a.competitor_id
                GROUP BY c.name ORDER BY creative_count DESC LIMIT :lim
            """, lim=limit)
            for r in rows:
                # 拆 selling_points 算占比
                sps = _query("""
                    SELECT jt.sp as selling_point, COUNT(*) as n
                    FROM ad_creatives a
                    JOIN competitors c ON c.id = a.competitor_id
                    JOIN JSON_TABLE(
                        COALESCE(a.selling_points, '[]'),
                        '$[*]' COLUMNS (sp VARCHAR(64) PATH '$')
                    ) jt
                    WHERE c.name = :c
                    GROUP BY jt.sp ORDER BY n DESC LIMIT 8
                """, c=r["competitor"])
                r["selling_points_breakdown"] = sps
            return self._send_json({"dim": dim, "items": rows, "count": len(rows)})

        return self._send_json({"error": f"invalid dim: {dim}"}, status=400)

    def api_candidates(self):
        """GET /api/candidates?topic=&conf_min=&limit= — 候选 app（不含已 in competitors 的）"""
        q = self._qs()
        topic = q.get("topic", "")
        conf_min = _parse_float(q, "conf_min", default=0.85)
        limit = _parse_int(q, "limit", default=100, max_=500, min_=1)

        wheres = ["a.is_relevant = 1", "a.confidence >= :cmin"]
        params = {"cmin": conf_min, "limit": limit}
        if topic:
            topics = [t.strip() for t in topic.split(",") if t.strip()]
            placeholders = ",".join(f":t{i}" for i in range(len(topics)))
            wheres.append(f"a.topic IN ({placeholders})")
            for i, t in enumerate(topics):
                params[f"t{i}"] = t
        else:
            wheres.append("a.topic IN ('football','multi_sport')")

        # 排除已在 competitors 的
        wheres.append(
            # COLLATE 显式归一：competitors.ios_app_id 是 utf8mb4_0900_ai_ci，
            # app_classifications.app_id 是 utf8mb4_unicode_ci，直接 = 会触发
            # "Illegal mix of collations" 错。
            "NOT EXISTS (SELECT 1 FROM competitors c "
            "WHERE c.ios_app_id COLLATE utf8mb4_unicode_ci = a.app_id "
            "AND a.platform = 'ios')"
        )

        sql = (
            "SELECT a.id, a.app_id, a.platform, a.bundle_id, a.name, a.publisher, "
            "a.category, a.description_excerpt, a.matched_keywords, "
            "a.is_relevant, a.topic, a.categories, a.confidence, a.rejection_reason, "
            "a.classified_at "
            "FROM app_classifications a "
            f"WHERE {' AND '.join(wheres)} "
            "ORDER BY a.confidence DESC, a.classified_at DESC LIMIT :limit"
        )
        rows = _query(sql, **params)
        for r in rows:
            for k in ("matched_keywords", "categories"):
                v = r.get(k)
                try:
                    r[k] = json.loads(v) if v else []
                except Exception:
                    r[k] = []
        # 回退：app_classifications 0 行（AI 分类未跑）→ 从 market_rank_snapshots 派生潜在候选
        if not rows:
            rows = self._derive_candidates_from_rank(limit=limit)
        return self._send_json({"candidates": rows, "count": len(rows)})

    @staticmethod
    def _derive_candidates_from_rank(limit: int) -> list:
        """app_classifications 空时 fallback：market_rank_snapshots 里 top 50 但不在 competitors 的 app。"""
        try:
            rows = _query("""
                SELECT m.name AS name, m.source, m.region_code,
                       MIN(m.rank_value) AS best_rank,
                       MAX(m.snapshot_date) AS latest_date,
                       COUNT(DISTINCT m.region_code) AS region_coverage
                FROM market_rank_snapshots m
                LEFT JOIN competitors c ON c.id = m.competitor_id
                WHERE m.competitor_id IS NULL
                  AND m.name IS NOT NULL
                  AND CHAR_LENGTH(m.name) >= 4
                  AND m.name NOT REGEXP '^[0-9]+$'
                  AND m.rank_value <= 50
                GROUP BY m.name, m.source, m.region_code
                ORDER BY region_coverage DESC, best_rank ASC
                LIMIT :lim
            """, lim=limit)
        except Exception:
            return []
        out = []
        for i, r in enumerate(rows or []):
            out.append({
                "id": -7000 - i,
                "app_id": None,
                "platform": "ios",
                "bundle_id": None,
                "name": r.get("name"),
                "publisher": None,
                "category": "Sports",
                "description_excerpt": f"来自 {r.get('source')} {(r.get('region_code') or 'global').upper()} 榜，最高 #{r.get('best_rank')}",
                "matched_keywords": [],
                "is_relevant": 1,
                "topic": "football",
                "categories": ["sports"],
                "confidence": 0.7,  # 派生默认中信
                "rejection_reason": None,
                "classified_at": str(r.get("latest_date") or ""),
            })
        return out

    def api_failed_ai_jobs(self):
        """GET /api/failed-ai-jobs?resolved=false&task=&latest_round=true&limit=

        latest_round=true (默认): 每个 task 只返回距其最近一次失败 6h 内的记录。
        把"上轮已死信、本轮没新错"的老条目从默认视图隐藏，避免持续累加观感。
        """
        q = self._qs()
        resolved = q.get("resolved", "false").lower()
        task = q.get("task", "")
        latest_round = q.get("latest_round", "true").lower() in ("1", "true", "yes")
        limit = _parse_int(q, "limit", default=100, max_=500, min_=1)
        wheres = []
        params = {"limit": limit}
        if resolved == "false":
            wheres.append("resolved_at IS NULL")
        elif resolved == "true":
            wheres.append("resolved_at IS NOT NULL")
        if task:
            wheres.append("task_name = :task")
            params["task"] = task
        if not wheres:
            wheres.append("1=1")
        where_sql = " AND ".join(wheres)
        if latest_round:
            sql = (
                "SELECT id, task_name, payload_json, error_msg, error_kind, "
                "attempts, first_failed_at, last_attempt_at, resolved_at "
                "FROM failed_ai_jobs f "
                f"WHERE {where_sql} "
                "  AND last_attempt_at >= ("
                "    SELECT MAX(last_attempt_at) - INTERVAL 6 HOUR "
                f"    FROM failed_ai_jobs WHERE task_name = f.task_name AND ({where_sql})"
                "  ) "
                "ORDER BY last_attempt_at DESC LIMIT :limit"
            )
        else:
            sql = (
                "SELECT id, task_name, payload_json, error_msg, error_kind, "
                "attempts, first_failed_at, last_attempt_at, resolved_at "
                "FROM failed_ai_jobs "
                f"WHERE {where_sql} "
                "ORDER BY last_attempt_at DESC LIMIT :limit"
            )
        rows = _query(sql, **params)
        for r in rows:
            v = r.pop("payload_json", None)
            try:
                r["payload"] = json.loads(v) if v else {}
            except Exception:
                r["payload"] = {}
        return self._send_json({"jobs": rows, "count": len(rows)})

    def api_failed_ai_retry(self, job_id: str):
        """POST /api/failed-ai-jobs/:id/retry — 重置失败任务（标 resolved_at=NULL + attempts=0）

        实际重试由 ai_pipeline 的下次运行处理（若 task 实现了从失败队列回拉的逻辑）。
        当前简化：只重置标记，让人手动重跑。
        不存在的 job_id 返 404 — 之前会假成功导致前端 UI 误导。
        """
        jid = _parse_path_id(job_id, "job id")
        rc = _execute(
            "UPDATE failed_ai_jobs SET resolved_at = NULL, attempts = 0, "
            "last_attempt_at = NOW() WHERE id = :id",
            id=jid,
        )
        if rc < 0:
            return self._send_500("DB error while resetting job")
        if rc == 0:
            return self._send_404(f"failed_ai_job {jid} not found")
        return self._send_json({
            "ok": True,
            "id": jid,
            "affected": rc,
            "note": "标记已重置；下次 ai_pipeline 跑会重新拉这条。如需立即重试，请手动跑 python3 -m ai_tasks.run_pipeline",
        })

    def api_sync_log(self):
        """GET /api/sync-log?source=&status=&limit="""
        q = self._qs()
        source = q.get("source", "")
        status = q.get("status", "")
        limit = _parse_int(q, "limit", default=50, max_=500, min_=1)
        wheres = ["1=1"]
        params = {"limit": limit}
        if source:
            wheres.append("script = :source")
            params["source"] = source
        if status == "success":
            wheres.append("success = 1")
        elif status == "fail":
            wheres.append("success = 0")
        sql = (
            "SELECT id, script, label, competitor, started_at, finished_at, "
            "duration_sec, success, error_kind, stdout_tail, stderr_tail, cmd "
            "FROM sync_log "
            f"WHERE {' AND '.join(wheres)} "
            "ORDER BY started_at DESC LIMIT :limit"
        )
        rows = _query(sql, **params)
        return self._send_json({"logs": rows, "count": len(rows)})

    # ─────────────────── helpers ───────────────────

    @staticmethod
    def _parse_since(since: str) -> datetime | None:
        """'24h' / '7d' / '30d' / ISO 字符串 → datetime（UTC）"""
        if not since:
            return None
        try:
            if since.endswith("h"):
                return datetime.utcnow() - timedelta(hours=int(since[:-1]))
            if since.endswith("d"):
                return datetime.utcnow() - timedelta(days=int(since[:-1]))
            return datetime.fromisoformat(since.replace("Z", "+00:00"))
        except Exception:
            return None


# ─────────────────────────── main ──────────────────────────────────


def main():
    port = int(sys.argv[1]) if len(sys.argv) > 1 else 8899
    host = "0.0.0.0"
    log.info(f"INTEL-OPS API server listening on http://{host}:{port}")
    log.info(f"  CORS allowed origins: {sorted(ALLOWED_ORIGINS)}")
    log.info(f"  React dev: cd intel-ops-frontend && pnpm dev")
    # M5: ThreadingHTTPServer 让多个 React 页面并行 fetch /api/* 不互相阻塞。
    # daemon_threads=True → 主进程 Ctrl+C 时不被守护线程拖住。
    server = ThreadingHTTPServer((host, port), APIHandler)
    server.daemon_threads = True
    server.serve_forever()


if __name__ == "__main__":
    main()
