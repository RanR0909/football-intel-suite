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
    python3 main_dashboard/dashboard_server.py        # 默认 :8000
    python3 main_dashboard/dashboard_server.py 8001   # 自定义端口
"""
from __future__ import annotations

import json
import logging
import os
import sys
from datetime import datetime, timedelta
from http.server import BaseHTTPRequestHandler, HTTPServer
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
    """SQLAlchemy Row → plain dict（datetime → ISO 字符串）"""
    out = {}
    for k, v in row._mapping.items():
        if isinstance(v, datetime):
            out[k] = v.isoformat()
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


def _execute(sql: str, **params) -> bool:
    if _db is None or _sql_text is None or not _db.is_mysql_enabled():
        return False
    try:
        with _db.session() as s:
            s.execute(_sql_text(sql), params)
        return True
    except Exception as e:
        log.warning(f"_execute failed: {e}")
        return False


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
        self._cors_headers()
        self.end_headers()
        self.wfile.write(body)

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
        except Exception as e:
            log.exception("POST handler error")
            self._send_500(str(e))

    # ─────────────────── endpoint implementations ───────────────────

    def api_dashboard_data(self):
        """GET /api/data/dashboard_data — 完整聚合数据"""
        if not DASHBOARD_DATA_PATH.exists():
            return self._send_json({"error": "dashboard_data.json not generated yet",
                                    "hint": "run: python3 main_dashboard/generate_dashboard.py"},
                                   status=503)
        try:
            data = json.loads(DASHBOARD_DATA_PATH.read_text(encoding="utf-8"))
            return self._send_json(data)
        except Exception as e:
            return self._send_500(f"failed to read dashboard_data.json: {e}")

    def api_status(self):
        """GET /api/status — 各源最近抓取 / retry queue / failed jobs / 死信 / 候选数"""
        # 各源 last_success
        sources_status = {}
        if _sync_state:
            try:
                snap = _sync_state.snapshot() or {}
                sources_status = snap
            except Exception:
                pass

        # retry queue
        retry_size = 0
        if _retry_queue:
            try:
                retry_size = len(_retry_queue.snapshot().get("items") or [])
            except Exception:
                pass

        # failed_ai_jobs (unresolved)
        failed_ai = _query(
            "SELECT task_name, COUNT(*) as n FROM failed_ai_jobs "
            "WHERE resolved_at IS NULL GROUP BY task_name"
        )

        # candidates (待审阅 = is_relevant=true + reviewed=false 不直接存，前端 localStorage 判定)
        candidate_count = _query(
            "SELECT COUNT(*) as n FROM app_classifications "
            "WHERE is_relevant = 1 AND topic IN ('football','multi_sport') "
            "AND confidence >= 0.85"
        )

        # alerts new
        alerts_new = _query(
            "SELECT COUNT(*) as n FROM alerts WHERE status = 'new' "
            "AND fired_at >= DATE_SUB(NOW(), INTERVAL 7 DAY)"
        )

        return self._send_json({
            "sources": sources_status,
            "retry_queue_size": retry_size,
            "failed_ai_jobs": {r["task_name"]: r["n"] for r in failed_ai},
            "candidates_count": (candidate_count[0]["n"] if candidate_count else 0),
            "alerts_new_7d": (alerts_new[0]["n"] if alerts_new else 0),
            "ts": datetime.utcnow().isoformat(),
        })

    def api_alerts(self):
        """GET /api/alerts?status=&type=&severity=&since= — 预警事件"""
        q = self._qs()
        status = q.get("status", "")
        atype = q.get("type", "")
        sev = q.get("severity", "")
        since = q.get("since", "")  # ISO 或 24h / 7d / 30d 简写
        limit = min(int(q.get("limit") or 200), 1000)

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
        return self._send_json({"alerts": rows, "count": len(rows)})

    def api_alert_ack(self, alert_id: str):
        """POST /api/alerts/:id/ack — 标记预警已读"""
        ok = _execute("UPDATE alerts SET status = 'ack' WHERE id = :id",
                      id=int(alert_id))
        return self._send_json({"ok": ok, "id": alert_id})

    def api_reviews(self):
        """GET /api/reviews?competitor=&label=&region=&since=&limit="""
        q = self._qs()
        competitor = q.get("competitor", "")
        label = q.get("label", "")
        region = q.get("region", "")
        since = q.get("since", "")
        limit = min(int(q.get("limit") or 100), 500)

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
                wheres.append("r.fetched_at >= :cutoff")
                params["cutoff"] = cutoff

        sql = (
            "SELECT r.id, c.name as competitor, r.region_code, r.platform, "
            "r.score, r.version, r.content, r.label, r.language, "
            "r.translated_text, r.at, r.labeled_at "
            "FROM reviews r JOIN competitors c ON c.id = r.competitor_id "
            f"WHERE {' AND '.join(wheres)} "
            "ORDER BY r.at DESC LIMIT :limit"
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

        return self._send_json({"reviews": rows, "count": len(rows)})

    def api_iap(self):
        """GET /api/iap?competitor=&region=&limit="""
        q = self._qs()
        competitor = q.get("competitor", "")
        region = q.get("region", "")
        limit = min(int(q.get("limit") or 500), 5000)
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
        limit = min(int(q.get("limit") or 200), 2000)
        wheres = ["1=1"]
        params = {"limit": limit}
        if source:
            wheres.append("m.source = :source")
            params["source"] = source
        if region:
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
        """GET /api/news?since=&limit= — 直接读 async_google_news.json + 关联 alerts"""
        path = DATA_DIR / "async_google_news.json"
        if not path.exists():
            return self._send_json({"news": [], "count": 0})
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            return self._send_json({"news": [], "count": 0})

        q = self._qs()
        since = q.get("since", "")
        limit = min(int(q.get("limit") or 200), 1000)
        cutoff = self._parse_since(since) if since else None

        news = []
        for rec in data:
            app = rec.get("competitor")
            for item in (rec.get("data") or {}).get("items", []):
                pub_iso = item.get("pub_iso") or ""
                if cutoff and pub_iso and pub_iso < cutoff.isoformat():
                    continue
                news.append({
                    "competitor": app,
                    "title": item.get("title"),
                    "link": item.get("link"),
                    "source": item.get("source"),
                    "desc": item.get("desc"),
                    "pub_iso": pub_iso,
                    "is_biz": bool(item.get("is_biz")),
                })
        news.sort(key=lambda x: x.get("pub_iso") or "", reverse=True)
        return self._send_json({"news": news[:limit], "count": min(len(news), limit)})

    def api_ads(self):
        """GET /api/ads?competitor=&country=&limit="""
        q = self._qs()
        competitor = q.get("competitor", "")
        country = q.get("country", "") or q.get("region", "")
        limit = min(int(q.get("limit") or 200), 1000)
        wheres = ["1=1"]
        params = {"limit": limit}
        if competitor:
            wheres.append("c.name = :competitor")
            params["competitor"] = competitor
        if country:
            wheres.append("a.region = :country")
            params["country"] = country
        sql = (
            "SELECT a.id, c.name as competitor, a.region, a.ad_id, "
            "a.body_text, a.media_url, a.fetched_at "
            "FROM ad_creatives a JOIN competitors c ON c.id = a.competitor_id "
            f"WHERE {' AND '.join(wheres)} "
            "ORDER BY a.fetched_at DESC LIMIT :limit"
        )
        rows = _query(sql, **params)
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

    def api_candidates(self):
        """GET /api/candidates?topic=&conf_min=&limit= — 候选 app（不含已 in competitors 的）"""
        q = self._qs()
        topic = q.get("topic", "")
        conf_min = float(q.get("conf_min") or 0.85)
        limit = min(int(q.get("limit") or 100), 500)

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
            "NOT EXISTS (SELECT 1 FROM competitors c "
            "WHERE c.ios_app_id = a.app_id AND a.platform = 'ios')"
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
        return self._send_json({"candidates": rows, "count": len(rows)})

    def api_failed_ai_jobs(self):
        """GET /api/failed-ai-jobs?resolved=false&task=&limit="""
        q = self._qs()
        resolved = q.get("resolved", "false").lower()
        task = q.get("task", "")
        limit = min(int(q.get("limit") or 100), 500)
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
        sql = (
            "SELECT id, task_name, payload_json, error_msg, error_kind, "
            "attempts, first_failed_at, last_attempt_at, resolved_at "
            "FROM failed_ai_jobs "
            f"WHERE {' AND '.join(wheres)} "
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
        """POST /api/failed-ai-jobs/:id/retry — 重置死信任务（标 resolved_at=NULL + attempts=0）

        实际重试由 ai_pipeline 的下次运行处理（若 task 实现了 死信回拉逻辑）。
        当前简化：只重置标记，让人手动重跑。
        """
        ok = _execute(
            "UPDATE failed_ai_jobs SET resolved_at = NULL, attempts = 0, "
            "last_attempt_at = NOW() WHERE id = :id",
            id=int(job_id),
        )
        return self._send_json({
            "ok": ok,
            "id": job_id,
            "note": "标记已重置；下次 ai_pipeline 跑会重新拉这条。如需立即重试，请手动跑 python3 -m ai_tasks.run_pipeline",
        })

    def api_sync_log(self):
        """GET /api/sync-log?source=&status=&limit="""
        q = self._qs()
        source = q.get("source", "")
        status = q.get("status", "")
        limit = min(int(q.get("limit") or 50), 500)
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
    port = int(sys.argv[1]) if len(sys.argv) > 1 else 8000
    host = "0.0.0.0"
    log.info(f"INTEL-OPS API server listening on http://{host}:{port}")
    log.info(f"  CORS allowed origins: {sorted(ALLOWED_ORIGINS)}")
    log.info(f"  React dev: cd intel-ops-frontend && pnpm dev")
    HTTPServer((host, port), APIHandler).serve_forever()


if __name__ == "__main__":
    main()
