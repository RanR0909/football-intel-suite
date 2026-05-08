#!/usr/bin/env python3
"""Sensor Tower 概览页抓取 — Playwright 持久 profile（替代失效的 token 版）。

CLI:
    python3 -m market_rank.scrape_sensor_tower login    # 一次性手动登录免费账号
    python3 -m market_rank.scrape_sensor_tower scrape   # 抓取（默认）
    python3 -m market_rank.scrape_sensor_tower --headed # 调试时显示浏览器

输出：data/async_sensor_tower.json
  [{source, competitor, region, timestamp, data: {downloads, rating, ratings_count, raw_text}}]

设计：
- 免费账号能看到月下载估算 / 评分 / 评分数（收入估算锁付费 → 已弃）
- 每个 competitor 一次概览页（默认 iOS / 美国），共 9 个请求
- DOM 不稳定 → 用 heuristic：扫所有元素文本，抓"Downloads / Ratings"附近的数字
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

from playwright.async_api import async_playwright

_SCRIPT_DIR = Path(__file__).resolve().parent
_PROJECT_ROOT = _SCRIPT_DIR.parent

if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

# 加载 .env.local + ~/.intelops-secrets — 让 MYSQL_DSN / REDIS_URL / cookie 都能读到
try:
    from shared.env_loader import load_all as _load_env_all
    _load_env_all()
except Exception:
    pass

from competitors import get_comment_competitors  # type: ignore
from shared.dao import rank as dao_rank  # type: ignore

PROFILE_DIR = Path.home() / ".sensortower-profile"
DATA_OUT = _PROJECT_ROOT / "data" / "async_sensor_tower.json"

PAGE_TIMEOUT_SEC = 30
SCRAPE_REGION = "US"   # 概览页默认市场（免费账号能切其他国家）
DEFAULT_PLATFORM = "ios"   # 通过 --platform CLI 切换；daily_sync 拆 ios/android 两个 task


# ---- DOM 提取（基于全文 regex — 比 element walking 更可靠）-----------------
# Sensor Tower SPA 渲染结构：
#   "Downloads\nby Sensor Tower\nWorldwide • Last Month\n200K\nRevenue\n..."
# 中间隔 2-3 行说明文字，所以扫文本块比扫 DOM 元素更稳。
EXTRACT_JS = r"""
() => {
  const main = document.querySelector('main') || document.body;
  const text = main.innerText || '';
  const out = {
    downloads: null,
    revenue: null,
    rating: null,
    ratings_count: null,
    category_rank: null,
    raw_text: text.slice(0, 4000),
  };

  function parseNum(s) {
    if (!s) return null;
    const t = String(s).replace(/[~$,\s>+#]/g, '').trim();
    const m = t.match(/^([\d.]+)\s*([KMB]?)/i);
    if (!m) return null;
    let n = parseFloat(m[1]);
    if (isNaN(n)) return null;
    const sfx = (m[2] || '').toUpperCase();
    if (sfx === 'K') n *= 1e3;
    else if (sfx === 'M') n *= 1e6;
    else if (sfx === 'B') n *= 1e9;
    return n;
  }

  // 在 label 与下一个 sentinel 之间，找第一个 token 像数字的
  function extractInBlock(label, sentinels) {
    const labelIdx = text.indexOf(label);
    if (labelIdx < 0) return null;
    // 找到 label 之后第一个 sentinel 的位置
    let endIdx = text.length;
    for (const s of sentinels) {
      const i = text.indexOf(s, labelIdx + label.length);
      if (i > 0 && i < endIdx) endIdx = i;
    }
    const block = text.slice(labelIdx + label.length, endIdx);
    // 跳过 "Upgrade to access this metric"
    if (/Upgrade to access/i.test(block)) return null;
    // 抓 block 内所有数字 token
    const tokens = block.split(/\s+/).filter(Boolean);
    for (const tok of tokens) {
      // 跳过明显是噪音的（短数字 < 10 但不是评分；或空字符串）
      const v = parseNum(tok);
      if (v === null) continue;
      // 评分专门处理：4.7 / 3.5 这种带小数 ≤ 5
      if (v <= 5 && tok.includes('.')) {
        return { kind: 'rating', value: v };
      }
      return { kind: 'num', value: v };
    }
    return null;
  }

  // Downloads（在 Worldwide • Last Month 段）
  const dl = extractInBlock('Downloads', ['Revenue', 'RPD', 'Avg. DAU', 'Category']);
  if (dl) out.downloads = dl.value;

  // Revenue
  const rv = extractInBlock('Revenue', ['RPD', 'Avg. DAU', 'Category', 'About']);
  if (rv) out.revenue = rv.value;

  // Category Ranking（"#74" 这种）
  const cr = extractInBlock('Category Ranking', ['Top Personas', 'About', 'Category Rankings']);
  if (cr) out.category_rank = cr.value;

  // Avg. Rating（在 Ratings and Reviews section）
  const ar = extractInBlock('Avg. Rating', ['Total Ratings', 'Number of Ratings', 'Rating Distribution', 'Reviews', 'Top Reviews']);
  if (ar && ar.kind === 'rating') out.rating = ar.value;
  else if (ar && ar.value <= 5) out.rating = ar.value;

  // Total Ratings
  const tr = extractInBlock('Total Ratings', ['Rating Distribution', 'Top Reviews', 'About']);
  if (tr) out.ratings_count = tr.value;

  return out;
}
"""


class LoginRequired(RuntimeError):
    """需要重新登录 Sensor Tower。"""


async def _detect_login_required(page) -> bool:
    cur = page.url or ""
    if "/users/sign-in" in cur or "/auth" in cur or "/login" in cur:
        return True
    try:
        has_signin = await page.evaluate(
            "() => !!document.querySelector('a[href*=\"sign-in\"], a[href*=\"login\"]')"
        )
        has_overview = await page.evaluate(
            "() => !!document.querySelector('main') && document.body.innerText.length > 2000"
        )
        return bool(has_signin and not has_overview)
    except Exception:
        return False


async def _wait_overview_ready(page, timeout_s: int = PAGE_TIMEOUT_SEC) -> None:
    """等概览页主区域渲染。"""
    loop = asyncio.get_event_loop()
    deadline = loop.time() + timeout_s
    while loop.time() < deadline:
        if await _detect_login_required(page):
            raise LoginRequired("Sensor Tower 未登录或登录态过期")
        body_len = await page.evaluate(
            "() => (document.querySelector('main') || document.body).innerText.length"
        )
        if body_len and body_len > 2000:
            return
        await asyncio.sleep(0.5)
    if await _detect_login_required(page):
        raise LoginRequired("Sensor Tower 未登录或登录态过期（页面加载超时）")
    raise TimeoutError(f"Sensor Tower 概览页未在 {timeout_s}s 内加载完成")


async def _fetch_app(page, app_name: str, app_id: str, platform: str) -> dict:
    url = (
        f"https://app.sensortower.com/overview/{app_id}"
        f"?country={SCRAPE_REGION}&os={platform}"
    )
    print(f"[{app_name}] [{platform}] {url}")
    await page.goto(url, wait_until="domcontentloaded")
    await _wait_overview_ready(page)
    # 给 SPA 异步刷数据一点时间
    await asyncio.sleep(2)
    data = await page.evaluate(EXTRACT_JS)
    print(
        f"  -> downloads={data.get('downloads')} revenue={data.get('revenue')}"
        f" rating={data.get('rating')} ratings_count={data.get('ratings_count')}"
        f" rank=#{data.get('category_rank')}"
    )
    return data


# ---- 命令：login ----------------------------------------------------------

async def cmd_login() -> None:
    PROFILE_DIR.mkdir(parents=True, exist_ok=True)
    async with async_playwright() as p:
        ctx = await p.chromium.launch_persistent_context(
            str(PROFILE_DIR),
            headless=False,
            viewport={"width": 1400, "height": 900},
            args=["--disable-blink-features=AutomationControlled"],
        )
        page = ctx.pages[0] if ctx.pages else await ctx.new_page()
        # Sensor Tower 是 SPA，老的 /users/sign-in 路径已废，直接打主页
        await page.goto("https://app.sensortower.com/")
        print("浏览器已打开 https://app.sensortower.com/")
        print("  1. 右上角点 'Sign In'（已有账号）或 'Sign Up'（免费注册）")
        print("  2. 邮箱 + 密码登录 / 注册")
        print("  3. 登录后能看到 dashboard 即可关闭窗口")
        print("  cookie 会保存到 ~/.sensortower-profile，下次抓取自动认证")
        try:
            while ctx.pages:
                await asyncio.sleep(1)
        except KeyboardInterrupt:
            pass
        finally:
            try:
                await ctx.close()
            except Exception:
                pass
    print(f"profile 已保存到：{PROFILE_DIR}")


# ---- 命令：scrape ---------------------------------------------------------

async def cmd_scrape(headed: bool = False, platform: str = DEFAULT_PLATFORM) -> Path:
    if not PROFILE_DIR.exists():
        raise LoginRequired(
            f"找不到 {PROFILE_DIR}。请先跑：\n"
            f"  python3 -m market_rank.scrape_sensor_tower login"
        )
    if platform not in ("ios", "android"):
        raise ValueError(f"--platform 必须是 ios / android，收到: {platform!r}")

    competitors = get_comment_competitors()
    results: list[dict] = []
    now_iso = datetime.now(timezone.utc).isoformat()

    async with async_playwright() as p:
        ctx = await p.chromium.launch_persistent_context(
            str(PROFILE_DIR),
            headless=not headed,
            viewport={"width": 1400, "height": 900},
            args=["--disable-blink-features=AutomationControlled"],
        )
        page = ctx.pages[0] if ctx.pages else await ctx.new_page()
        try:
            for app_name, comp in competitors.items():
                # iOS 用 ios numeric id；Android 用 gp_package（com.xxx.yyy 字符串）
                if platform == "ios":
                    app_id = str(comp.get("ios") or comp.get("app_id") or "")
                else:
                    app_id = str(comp.get("gp_package") or comp.get("android") or "")
                if not app_id:
                    print(f"[{app_name}] 没有 {platform} id，跳过", file=sys.stderr)
                    continue
                try:
                    data = await _fetch_app(page, app_name, app_id, platform)
                except LoginRequired:
                    raise
                except Exception as e:
                    print(f"  ERROR: {e}", file=sys.stderr)
                    data = {"error": str(e)}
                rec = {
                    "source": "sensor_tower",
                    "platform": platform,
                    "competitor": app_name,
                    "region": SCRAPE_REGION.lower(),
                    "timestamp": now_iso,
                    "data": data,
                }
                results.append(rec)
                await asyncio.sleep(2)  # 节流
        finally:
            try:
                await ctx.close()
            except Exception:
                pass

    # JSON 输出按 platform 拆：
    #   ios     -> async_sensor_tower.json     （保持原路径，data_pipeline.aggregator 在读）
    #   android -> async_sensor_tower_android.json
    if platform == "ios":
        out_path = DATA_OUT
    else:
        out_path = _PROJECT_ROOT / "data" / f"async_sensor_tower_{platform}.json"
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(results, ensure_ascii=False, indent=2), encoding="utf-8")
    ok = sum(1 for r in results if not (r.get("data") or {}).get("error"))
    print(f"\n保存完成 -> {out_path}（{len(results)} record，{ok} 条有数据）")

    # 双写 MySQL: market_rank_snapshots
    db_rows = []
    for r in results:
        d = r.get("data") or {}
        if d.get("error"):
            continue
        # downloads / revenue 在 sensor_tower 是 number（200000 / 100000）
        dl = d.get("downloads")
        rv = d.get("revenue")
        rk = d.get("category_rank")
        db_rows.append({
            "name": r.get("competitor"),
            "competitor": r.get("competitor"),     # 都是 tracked
            "platform": r.get("platform") or platform,
            "region": r.get("region", "us").lower(),
            "rank": int(rk) if rk else None,
            "delta": None,
            "downloads": f"{int(dl/1000)}K" if dl and dl >= 1000 else (str(int(dl)) if dl else None),
            "downloads_num": int(dl) if dl else None,
            "revenue_num": int(rv) if rv else None,
        })
    if db_rows:
        n_db = dao_rank.bulk_insert_rank_snapshots("sensor_tower", db_rows)
        if n_db:
            print(f"  MySQL: 写入 {n_db} 条 rank_snapshot ({platform})")
    return out_path


# ---- main -----------------------------------------------------------------

def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("command", choices=["login", "scrape"], nargs="?", default="scrape")
    ap.add_argument("--headed", action="store_true")
    ap.add_argument("--platform", choices=["ios", "android"], default=DEFAULT_PLATFORM,
                    help=f"抓 ios 或 android 平台（默认 {DEFAULT_PLATFORM}）")
    args = ap.parse_args()

    if args.command == "login":
        asyncio.run(cmd_login())
    else:
        try:
            asyncio.run(cmd_scrape(headed=args.headed, platform=args.platform))
        except LoginRequired as e:
            print(f"❌ {e}", file=sys.stderr)
            sys.exit(2)


if __name__ == "__main__":
    main()
