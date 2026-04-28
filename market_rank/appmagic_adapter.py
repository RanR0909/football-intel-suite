"""把 AppMagic 抓取产物适配为现有 data 文件结构。

输入：appmagic_output/sports_news_<TS>.json（最近一份）
输出：
  - data/market_rank.json            （沿用旧 shape，competitor_performance + leaderboard 来自 worldwide）
  - data/market_rank_by_country.json （新增 12 国分榜，per-country leaderboard + tracked competitors）
  - data/ranking_history.json        （增量更新：当日 worldwide rank 写入）

App 名 → competitors.json key 映射通过 token 模糊匹配（同 scrape_appmagic.match_tracked）。
"""

from __future__ import annotations

import json
import re
import sys
from datetime import datetime
from pathlib import Path
from typing import Optional

_SCRIPT_DIR = Path(__file__).resolve().parent
_PROJECT_ROOT = _SCRIPT_DIR.parent
DATA_DIR = _PROJECT_ROOT / "data"
APPMAGIC_DIR = _PROJECT_ROOT / "appmagic_output"

if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

from competitors import get_market_rank_competitors  # type: ignore
from shared.dao import rank as dao_rank  # type: ignore


# ---- 工具 -----------------------------------------------------------------

def _app_token(name: str) -> str:
    if not name:
        return ""
    chunk = re.split(r"[:\-\s]", name, maxsplit=1)[0]
    return re.sub(r"[^a-z0-9]", "", chunk.lower())


def _build_token_to_name() -> dict[str, str]:
    """{token → competitors.json 中的标准 name}"""
    out: dict[str, str] = {}
    for name in get_market_rank_competitors().keys():
        tok = _app_token(name)
        if tok:
            out[tok] = name
    return out


def _resolve_competitor_name(raw_name: str, token_map: dict[str, str]) -> Optional[str]:
    """把 AppMagic 的 raw name 映射到 competitors.json 的标准 name。

    匹配规则：tok 必须等于 known_tok 或以 known_tok 起头（避免 'live' → LiveScore 假阳性）。
    去掉 known_tok.startswith(tok) 这个方向。
    """
    tok = _app_token(raw_name)
    if not tok or len(tok) < 4:  # 太短的 token 不参与（如 '3' / 'liv'）
        return None
    if tok in token_map:
        return token_map[tok]
    for known_tok, std_name in token_map.items():
        if tok == known_tok or tok.startswith(known_tok):
            return std_name
    return None


def _parse_delta(delta_str: Optional[str]) -> Optional[int]:
    """AppMagic 的 delta 文本 '↑3' / '↓7' / '+12' / '-5' → int。"""
    if delta_str is None:
        return None
    s = str(delta_str).strip()
    if not s or s in ("—", "-", "→", "0"):
        return 0
    sign = 1
    if s[0] in "↑+":
        sign = -1  # 排名上升 = rank 数字减少 → 负 delta
        s = s[1:]
    elif s[0] in "↓-":
        sign = 1   # 排名下降 = rank 数字增加 → 正 delta
        s = s[1:]
    s = re.sub(r"[^\d]", "", s)
    if not s:
        return None
    try:
        return sign * int(s)
    except ValueError:
        return None


def _parse_downloads(downloads_str: Optional[str]) -> Optional[float]:
    """AppMagic 下载量字符串 '~10K' / '>1M' / '12345' → float。"""
    if not downloads_str:
        return None
    s = str(downloads_str).strip().lstrip(">~")
    m = re.match(r"^([\d,.]+)\s*([KMB]?)\s*$", s, re.IGNORECASE)
    if not m:
        return None
    num_str = m.group(1).replace(",", "")
    try:
        num = float(num_str)
    except ValueError:
        return None
    suffix = m.group(2).upper()
    if suffix == "K":
        num *= 1_000
    elif suffix == "M":
        num *= 1_000_000
    elif suffix == "B":
        num *= 1_000_000_000
    return num


def _latest_appmagic_file() -> Optional[Path]:
    if not APPMAGIC_DIR.exists():
        return None
    files = sorted(APPMAGIC_DIR.glob("sports_news_*.json"), key=lambda p: p.stat().st_mtime, reverse=True)
    return files[0] if files else None


# ---- 主入口 ---------------------------------------------------------------

def adapt(appmagic_path: Optional[Path] = None) -> dict:
    """读 AppMagic JSON → 写 3 个 data 文件。返回 summary。"""
    src = appmagic_path or _latest_appmagic_file()
    if not src:
        raise FileNotFoundError("找不到 appmagic_output/sports_news_*.json，请先跑 scraper")
    raw = json.loads(src.read_text(encoding="utf-8"))

    registry = get_market_rank_competitors()
    token_map = _build_token_to_name()

    today = datetime.now().strftime("%Y-%m-%d")

    # ---- (1) market_rank.json ----------------------------------------------
    ww_all = (raw.get("worldwide") or {}).get("all") or []
    ww_tracked = (raw.get("worldwide") or {}).get("tracked") or []

    # 名 → competitor
    competitor_performance: dict[str, dict] = {}
    for name in registry:
        competitor_performance[name] = {
            "rank": None,
            "delta": None,
            "app_id": str(registry[name].get("app_id") or registry[name].get("ios") or ""),
        }
    for it in ww_tracked:
        std_name = _resolve_competitor_name(it.get("name", ""), token_map)
        if not std_name or std_name not in competitor_performance:
            continue
        competitor_performance[std_name]["rank"] = it.get("rank")
        competitor_performance[std_name]["delta"] = _parse_delta(it.get("delta"))

    leaderboard = []
    for it in ww_all[:100]:
        std_name = _resolve_competitor_name(it.get("name", ""), token_map)
        leaderboard.append({
            "rank": it.get("rank"),
            "name": it.get("name") or "",
            "app_id": "",  # AppMagic 不返回 ID；仅 tracked 的能映射，其他留空
            "artist": it.get("publisher") or "",
            "delta": _parse_delta(it.get("delta")),
            "downloads": _parse_downloads(it.get("downloads")),
            "is_known": std_name is not None,
        })

    fast_movers = []
    for it in ww_tracked:
        d = _parse_delta(it.get("delta"))
        if d is None or abs(d) < 10:
            continue
        fast_movers.append({
            "rank": it.get("rank"),
            "name": it.get("name") or "",
            "delta": d,
            "artist": it.get("publisher") or "",
        })

    market_rank = {
        "generated_at": raw.get("generated_at") or datetime.now().isoformat(),
        "date": today,
        "total_apps": len(ww_all),
        "competitor_performance": competitor_performance,
        "new_contenders": [],   # AppMagic 不区分新晋（前 100 都给）
        "fast_movers": fast_movers,
        "ai_brief": None,
        "leaderboard": leaderboard,
        "source": "appmagic",
    }
    market_rank_path = DATA_DIR / "market_rank.json"
    market_rank_path.write_text(
        json.dumps(market_rank, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )

    # ---- (2) market_rank_by_country.json -----------------------------------
    by_country = {}
    for code, country_data in (raw.get("countries") or {}).items():
        all_items = country_data.get("all") or []
        tracked_items = country_data.get("tracked") or []
        # 把 tracked 解析到标准 name
        tracked_resolved = []
        tracked_map: dict[str, dict] = {}
        for it in tracked_items:
            std_name = _resolve_competitor_name(it.get("name", ""), token_map)
            if not std_name:
                continue
            entry = {
                "competitor": std_name,
                "rank": it.get("rank"),
                "delta": _parse_delta(it.get("delta")),
                "name": it.get("name") or "",
                "publisher": it.get("publisher") or "",
            }
            tracked_resolved.append(entry)
            tracked_map[std_name] = entry
        # leaderboard
        lb = []
        for it in all_items[:100]:
            std_name = _resolve_competitor_name(it.get("name", ""), token_map)
            lb.append({
                "rank": it.get("rank"),
                "name": it.get("name") or "",
                "publisher": it.get("publisher") or "",
                "delta": _parse_delta(it.get("delta")),
                "is_tracked": std_name is not None,
                "competitor": std_name,
            })
        by_country[code.lower()] = {
            "country_name": country_data.get("name") or code,
            "leaderboard": lb,
            "tracked_competitors": tracked_resolved,
            "tracked_map": tracked_map,
            "error": country_data.get("error"),
        }
    by_country_path = DATA_DIR / "market_rank_by_country.json"
    by_country_path.write_text(
        json.dumps({
            "generated_at": raw.get("generated_at") or datetime.now().isoformat(),
            "date": today,
            "source": "appmagic",
            "countries": by_country,
        }, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )

    # ---- (3) ranking_history.json — 增量当日 worldwide ---------------------
    history_path = DATA_DIR / "ranking_history.json"
    try:
        history = json.loads(history_path.read_text(encoding="utf-8")) if history_path.exists() else {}
    except Exception:
        history = {}
    if not isinstance(history, dict):
        history = {}
    today_snapshot = history.get(today) or {}
    for name, perf in competitor_performance.items():
        aid = perf.get("app_id")
        rank = perf.get("rank")
        if aid and rank is not None:
            today_snapshot[str(aid)] = rank
    if today_snapshot:
        history[today] = today_snapshot
        history_path.write_text(
            json.dumps(history, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

    # ---- (4) MySQL: market_rank_snapshots（worldwide + 12 国 leaderboard）----
    db_rows = []
    today_dt = datetime.now().date()
    # 全球榜
    for it in ww_all[:100]:
        std_name = _resolve_competitor_name(it.get("name", ""), token_map)
        db_rows.append({
            "name": it.get("name") or "",
            "competitor": std_name,
            "region": None,   # worldwide
            "rank": it.get("rank"),
            "delta": _parse_delta(it.get("delta")),
            "downloads": str(it.get("downloads") or "")[:32] or None,
        })
    # 各国
    for code, country_data in (raw.get("countries") or {}).items():
        for it in (country_data.get("all") or [])[:100]:
            std_name = _resolve_competitor_name(it.get("name", ""), token_map)
            db_rows.append({
                "name": it.get("name") or "",
                "competitor": std_name,
                "region": code.lower(),
                "rank": it.get("rank"),
                "delta": _parse_delta(it.get("delta")),
                "downloads": None,
            })
    n_db = dao_rank.bulk_insert_rank_snapshots("appmagic", db_rows, snapshot_date=today_dt)

    return {
        "market_rank": str(market_rank_path),
        "by_country": str(by_country_path),
        "ranking_history": str(history_path),
        "tracked_count": sum(1 for p in competitor_performance.values() if p["rank"] is not None),
        "country_count": len(by_country),
        "mysql_rank_rows": n_db,
    }


if __name__ == "__main__":
    summary = adapt()
    print(json.dumps(summary, ensure_ascii=False, indent=2))
