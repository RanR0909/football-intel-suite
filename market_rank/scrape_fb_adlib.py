#!/usr/bin/env python3
"""Meta 广告库（Ad Library）公开网页抓取 — Playwright 持久 profile。

CLI:
    python3 -m market_rank.scrape_fb_adlib login    # 一次性登录 / 接受 Cookie
    python3 -m market_rank.scrape_fb_adlib scrape   # 抓取（默认）
    python3 -m market_rank.scrape_fb_adlib --headed # 调试时显示浏览器

输出：data/async_fb_adlib.json （shape 与旧 fb_adlib.py 兼容，aggregator 直接消费）
  [{source, competitor, region, timestamp, data: {ad_count, ads: [{ad_id, text, start_date, country, platform, media_url, page_name}]}}]

设计：
- 不需要 Meta Developer 账号 / token
- 不需要 FB 个人账号登录（公开广告非政治类匿名可见）
  但首次需点 "Accept Cookies" → profile 持久化跳过后续 banner
- 每个 (竞品, 国家) 一次 search query：
    https://www.facebook.com/ads/library/?active_status=active&ad_type=all&country=<CC>&q=<APP_NAME>
- 每页向下滚动 2 次（约 30 条广告），DOM 提取 Library ID / 文案 / 起始日 / 平台
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import quote

from playwright.async_api import async_playwright

_SCRIPT_DIR = Path(__file__).resolve().parent
_PROJECT_ROOT = _SCRIPT_DIR.parent

if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

# 加载 .env.local + ~/.intelops-secrets
try:
    from shared.env_loader import load_all as _load_env_all
    _load_env_all()
except Exception:
    pass

from competitors import get_comment_competitors  # type: ignore
from regions import load_regions  # type: ignore  # noqa: F401  (预留：region → AD_COUNTRIES 映射)
from shared.dao import ads as dao_ads  # type: ignore

PROFILE_DIR = Path.home() / ".meta-adlib-profile"
DATA_OUT = _PROJECT_ROOT / "data" / "async_fb_adlib.json"

# Meta 广告库的国家列表（对应 regions.json 子集，按主要市场选）
AD_COUNTRIES = ["US", "GB", "BR", "DE", "JP"]
SEARCH_LIMIT_PER_QUERY = 30   # 每个 (comp, country) 抓多少条上限
SCROLL_TIMES = 2              # 向下滚动次数（每次约+10条）
PAGE_TIMEOUT_SEC = 25


# ---- DOM 提取（heuristic — Meta 经常改 class，按 text pattern 找）------
EXTRACT_JS = r"""
() => {
  // 找到所有含 "Library ID:" 的元素，往上找广告卡 root
  const cards = [];
  const seen = new Set();
  const all = document.querySelectorAll('div, span');
  for (const el of all) {
    const text = (el.innerText || '').trim();
    if (!text.startsWith('Library ID')) continue;
    // 向上爬 root（足够大的容器）
    let parent = el;
    for (let i = 0; i < 12; i++) {
      if (!parent.parentElement) break;
      parent = parent.parentElement;
      const t = (parent.innerText || '');
      if (t.length > 250 && (t.includes('Started running') || t.includes('Library ID'))) {
        break;
      }
    }
    if (seen.has(parent)) continue;
    seen.add(parent);
    const fullText = (parent.innerText || '').slice(0, 2000);
    const idMatch = fullText.match(/Library ID[:：]\s*([0-9]+)/);
    const startMatch = fullText.match(/Started running on\s+([^\n]+)/i);
    const platformsMatch = fullText.match(/Platforms?\s+([^\n]+)/i);
    // 找广告页名（页面内常见格式：第一行 = page name）
    const lines = fullText.split('\n').map(s => s.trim()).filter(Boolean);
    const pageName = lines[0] || '';
    // 找 media URL（卡片内第一个 <img> 或 video src）
    let mediaUrl = '';
    const img = parent.querySelector('img[src*="scontent"], img[src*="fbcdn"], video');
    if (img) mediaUrl = img.src || img.currentSrc || '';
    // 抽出"广告文案"：去掉 metadata 行后的剩余（保留前 500 字）
    const metaPrefixes = ['Library ID', 'Started running', 'Platforms', 'Active', 'Inactive', 'Sponsored'];
    const bodyLines = lines.filter(l =>
      !metaPrefixes.some(p => l.startsWith(p)) && l.length > 4
    );
    const adText = bodyLines.slice(0, 6).join(' · ').slice(0, 500);
    cards.push({
      ad_id: idMatch ? idMatch[1] : '',
      text: adText,
      start_date: startMatch ? startMatch[1].trim() : '',
      platform: platformsMatch ? platformsMatch[1].trim() : '',
      page_name: pageName,
      media_url: mediaUrl,
    });
  }
  return cards;
}
"""


class CookieAcceptOrLoginRequired(RuntimeError):
    """检测到要登录或 cookie banner 未点过；提示重跑 login。"""


async def _accept_cookies_if_needed(page) -> None:
    """匿名访问时常见的"Allow all cookies"按钮（不点击会阻塞 DOM）。"""
    try:
        # 可能的 button 文本
        for label in ["Allow all cookies", "Accept all", "Decline optional cookies"]:
            btn = page.get_by_role("button", name=label)
            if await btn.count() > 0:
                await btn.first.click(timeout=3000)
                await asyncio.sleep(1)
                return
    except Exception:
        pass


async def _scroll_and_collect(page, query_url: str, max_cards: int = SEARCH_LIMIT_PER_QUERY) -> list[dict]:
    await page.goto(query_url, wait_until="domcontentloaded")
    # 等首屏加载（Meta 渲染慢）
    try:
        await page.wait_for_selector("text=Library ID", timeout=PAGE_TIMEOUT_SEC * 1000)
    except Exception:
        # 没有 "Library ID" → 该 query 0 结果，或反爬
        return []
    await _accept_cookies_if_needed(page)
    await asyncio.sleep(1)
    # 滚动加载更多
    for _ in range(SCROLL_TIMES):
        await page.evaluate("() => window.scrollBy(0, document.body.scrollHeight)")
        await asyncio.sleep(2)
    cards = await page.evaluate(EXTRACT_JS)
    # 去重 by ad_id（同一广告偶尔会重复出现）
    seen, dedup = set(), []
    for c in cards:
        aid = c.get("ad_id") or ""
        if not aid or aid in seen:
            continue
        seen.add(aid)
        dedup.append(c)
        if len(dedup) >= max_cards:
            break
    return dedup


# ---- 命令：login（首次 / cookie 失效后）-----------------------------------

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
        await page.goto("https://www.facebook.com/ads/library/?active_status=active&ad_type=all&country=US&q=football")
        print("浏览器已打开。")
        print("  1. 如有 'Allow all cookies' / 类似 banner 弹出 → 点 Accept")
        print("  2. （可选）登录 FB 账号 — 不登录也能抓非政治类公开广告")
        print("  3. 看到广告列表后关闭浏览器即可")
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

async def cmd_scrape(headed: bool = False) -> Path:
    if not PROFILE_DIR.exists():
        # 不强制 — 可以匿名抓，但提示用户跑 login 一次会更稳
        print(
            f"⚠ 未找到 {PROFILE_DIR}（建议先跑：python3 -m market_rank.scrape_fb_adlib login）",
            file=sys.stderr,
        )
        PROFILE_DIR.mkdir(parents=True, exist_ok=True)

    competitors = list(get_comment_competitors().keys())
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
            for app_name in competitors:
                for country in AD_COUNTRIES:
                    url = (
                        "https://www.facebook.com/ads/library/"
                        f"?active_status=active&ad_type=all&country={country}"
                        f"&q={quote(app_name)}"
                    )
                    print(f"[{app_name}/{country}] 抓取中...")
                    try:
                        cards = await _scroll_and_collect(page, url)
                    except Exception as e:
                        print(f"  ERROR: {e}", file=sys.stderr)
                        cards = []
                    # 每条 ad 标注 country
                    for c in cards:
                        c["country"] = country.lower()
                    rec = {
                        "source": "fb_adlib",
                        "competitor": app_name,
                        "region": country.lower(),
                        "timestamp": now_iso,
                        "data": {
                            "ad_count": len(cards),
                            "ads": cards,
                        },
                    }
                    results.append(rec)
                    # 双写 MySQL ad_creatives
                    n_db = dao_ads.upsert_ad_creatives(app_name, country.lower(), cards) if cards else 0
                    print(f"  -> {len(cards)} 条广告  DB+{n_db}")
                    await asyncio.sleep(1.5)  # 节流
        finally:
            try:
                await ctx.close()
            except Exception:
                pass

    DATA_OUT.parent.mkdir(parents=True, exist_ok=True)
    DATA_OUT.write_text(json.dumps(results, ensure_ascii=False, indent=2), encoding="utf-8")
    total_ads = sum((r.get("data") or {}).get("ad_count", 0) for r in results)
    print(f"\n保存完成 -> {DATA_OUT}（{len(results)} record, 总 {total_ads} 条广告）")
    return DATA_OUT


# ---- main -----------------------------------------------------------------

def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("command", choices=["login", "scrape"], nargs="?", default="scrape")
    ap.add_argument("--headed", action="store_true")
    args = ap.parse_args()

    if args.command == "login":
        asyncio.run(cmd_login())
    else:
        asyncio.run(cmd_scrape(headed=args.headed))


if __name__ == "__main__":
    main()
