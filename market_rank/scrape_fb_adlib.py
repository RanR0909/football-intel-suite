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


# ---- DOM 提取（heuristic — Meta 经常改 class，按 多语言文本前缀 + 向上爬 root）------
# Fix 3 (2026-05-06):
#   · Meta 不用 [role="article"] 包广告卡 — 改回旧策略 (找 ID 文本元素 → 爬 root)
#   · 中文界面实测：「资料库编号」（不是「广告资料库 ID」）+「开始投放」+「赞助内容」
#   · 多语言：英文 / 中文 / 法语 都覆盖
EXTRACT_JS = r"""
() => {
  const cards = [];
  const seen = new Set();
  // 文本前缀 → 各语言 Library ID 标签
  const ID_RE = /^(Library ID|资料库编号|ID de la bibliothèque)/i;
  const ID_EXTRACT = /(?:Library ID|资料库编号|ID de la bibliothèque)[:：\s]*([0-9]{10,})/i;

  const all = document.querySelectorAll('div, span');
  for (const el of all) {
    const text = (el.innerText || '').trim();
    if (!ID_RE.test(text)) continue;
    // 向上爬 root（同时含 ID + 投放时间 / 平台 = 完整广告卡）
    let parent = el;
    for (let i = 0; i < 12; i++) {
      if (!parent.parentElement) break;
      parent = parent.parentElement;
      const t = parent.innerText || '';
      if (t.length > 250 && /(Started running|开始投放|Diffusion lancée|Library ID|资料库编号)/i.test(t)) {
        break;
      }
    }
    if (seen.has(parent)) continue;
    seen.add(parent);

    const fullText = (parent.innerText || '').slice(0, 2000);
    const idMatch = fullText.match(ID_EXTRACT);
    if (!idMatch) continue;
    // Fix 4 (2026-05-08): 之前 start_date 经常拿到 "平台"、platform 拿到零宽空格 —
    //   多语言 DOM 中"开始投放"和"平台"标签经常紧挨着，没有日期/平台值时
    //   贪婪 [^\n]+ 会把下一个 label 字符串本身当成 value 抓回来。
    //   修复：捕获后做内容校验 — 日期必须含年份(20XX)，平台必须含 Facebook/Instagram/Audience。
    const startMatch = fullText.match(
      /(?:Started running on|开始投放|Diffusion lancée le)[:：\s]*\n?\s*([^\n]+)/i
    );
    const platformsMatch = fullText.match(
      /(?:Platforms?|平台|Plateformes?)[:：\s]*\n?\s*([^\n]+)/i
    );
    // 校验日期：必须含 20XX 年份；否则视为 label-only 漏值，置空。
    let startDate = startMatch ? startMatch[1].trim() : '';
    if (!/\b20\d{2}\b/.test(startDate)) startDate = '';
    // 校验平台：剥零宽字符 + 控制符；必须含已知平台关键字 (Facebook/Instagram/Audience/Messenger/Threads)，
    // 否则视为 label-only 漏值，置空。
    let platform = platformsMatch ? platformsMatch[1].trim() : '';
    platform = platform.replace(/[​-‏⁠ ]/g, '').trim();
    if (!/Facebook|Instagram|Audience|Messenger|Threads/i.test(platform)) platform = '';

    const lines = fullText.split('\n').map(s => s.trim()).filter(Boolean);
    const pageName = lines[0] || '';
    let mediaUrl = '';
    const img = parent.querySelector('img[src*="scontent"], img[src*="fbcdn"], video');
    if (img) mediaUrl = img.src || img.currentSrc || '';
    // 文案：去掉 metadata 行
    const metaPrefixes = [
      'Library ID', '资料库编号', 'ID de la bibliothèque',
      'Started running', '开始投放', 'Platforms', '平台', 'Plateformes',
      'Active', '投放中', 'Inactive', '已停',
      'Sponsored', '赞助内容', '赞助',
      'EU transparency', '欧盟境内',
    ];
    const bodyLines = lines.filter(l =>
      !metaPrefixes.some(p => l.startsWith(p)) && l.length > 4
    );
    const adText = bodyLines.slice(0, 6).join(' · ').slice(0, 500);
    cards.push({
      ad_id: idMatch[1],
      text: adText,
      start_date: startDate,
      platform: platform,
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
    # Fix 2 (2026-05-06): 等首屏加载 — Meta 不用 ARIA role 包卡片，纯文本侦测。
    # 中文界面实测关键词："资料库编号"（不是"广告资料库 ID"）/ "开始投放" / "赞助内容"
    try:
        await page.wait_for_function(
            r"""() => {
                const t = document.body.innerText || '';
                // 找到广告卡（多语言）
                if (/Library ID|资料库编号|ID de la bibliothèque/i.test(t)) return true;
                // 明确 0 结果
                if (/no\s+results|没有结果|0\s+results?\s+found/i.test(t)) return true;
                // 需登录（Meta 现在搜广告库强制登录）
                if (/^(log\s*in|登录|登入|S'identifier)$/im.test(t)) return true;
                return false;
            }""",
            timeout=PAGE_TIMEOUT_SEC * 1000,
        )
    except Exception:
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

def _merge_results_to_json(new_records: list[dict], country_filter: str) -> int:
    """合并 new_records 到 DATA_OUT；同 country 的旧记录会被覆盖。

    用 fcntl 文件锁防 race（多个 per-country 进程并发跑时）。
    返回最终 JSON 里的总 record 数。
    """
    import fcntl
    DATA_OUT.parent.mkdir(parents=True, exist_ok=True)
    DATA_OUT.touch(exist_ok=True)

    with open(DATA_OUT, "r+", encoding="utf-8") as f:
        # 排他锁，阻塞直到拿到（其他进程 release 才能进）
        fcntl.flock(f.fileno(), fcntl.LOCK_EX)
        try:
            content = f.read().strip()
            existing = json.loads(content) if content else []
            if not isinstance(existing, list):
                existing = []
            # 删掉本次 country 的旧记录（按 (competitor, region) 唯一）
            cf = country_filter.lower()
            existing = [r for r in existing if (r.get("region") or "").lower() != cf]
            # 加新记录
            existing.extend(new_records)
            f.seek(0)
            f.truncate()
            f.write(json.dumps(existing, ensure_ascii=False, indent=2))
            return len(existing)
        finally:
            fcntl.flock(f.fileno(), fcntl.LOCK_UN)


async def cmd_scrape(headed: bool = False, countries: list[str] | None = None) -> Path:
    """抓 fb 广告库。

    countries: 要抓的国家代码列表（如 ["US"]），缺省 = AD_COUNTRIES 全跑。
    daily_sync 使用 per-country 调用（每次 ~3-5 min，远低于 timeout）。
    """
    if not PROFILE_DIR.exists():
        print(
            f"⚠ 未找到 {PROFILE_DIR}（建议先跑：python3 -m market_rank.scrape_fb_adlib login）",
            file=sys.stderr,
        )
        PROFILE_DIR.mkdir(parents=True, exist_ok=True)

    target_countries = [c.upper() for c in (countries or AD_COUNTRIES)]
    competitors = list(get_comment_competitors().keys())
    results: list[dict] = []
    now_iso = datetime.now(timezone.utc).isoformat()

    print(f"[fb_adlib] 抓取国家：{target_countries}（{len(competitors)} 竞品 × {len(target_countries)} 国 = {len(competitors) * len(target_countries)} query）")

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
                for country in target_countries:
                    # Fix 1 (2026-05-06): URL 参数对齐 Meta 当前默认行为。
                    # 旧版只有 active_status / ad_type / country / q，Meta 默认走"广告主精确匹配"
                    # → 用 q=SofaScore 找不到（FB Page name 不一定叫 SofaScore）→ 0 条。
                    # 加 search_type=keyword_unordered 强制关键词模糊匹配（与 Chrome 手动访问一致）。
                    url = (
                        "https://www.facebook.com/ads/library/"
                        f"?active_status=active&ad_type=all&country={country}"
                        f"&is_targeted_country=false&media_type=all"
                        f"&q={quote(app_name)}&search_type=keyword_unordered"
                    )
                    print(f"[{app_name}/{country}] 抓取中...")
                    try:
                        cards = await _scroll_and_collect(page, url)
                    except Exception as e:
                        print(f"  ERROR: {e}", file=sys.stderr)
                        cards = []
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
                    # 双写 MySQL（dao_ads.upsert_ad_creatives 内置去重 + dedup）
                    n_db = dao_ads.upsert_ad_creatives(app_name, country.lower(), cards) if cards else 0
                    print(f"  -> {len(cards)} 条广告  DB+{n_db}")
                    await asyncio.sleep(1.5)
        finally:
            try:
                await ctx.close()
            except Exception:
                pass

    # 合并到主 JSON 文件（带文件锁防 race）— 只覆盖本次涉及的国家
    total_in_json = 0
    for country in target_countries:
        country_results = [r for r in results if (r.get("region") or "").lower() == country.lower()]
        total_in_json = _merge_results_to_json(country_results, country)
    total_ads = sum((r.get("data") or {}).get("ad_count", 0) for r in results)
    print(f"\n保存完成 -> {DATA_OUT}（本次写 {len(results)} record，文件总 {total_in_json} record；本次共 {total_ads} 条广告）")
    return DATA_OUT


# ---- main -----------------------------------------------------------------

def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("command", choices=["login", "scrape"], nargs="?", default="scrape")
    ap.add_argument("--headed", action="store_true")
    ap.add_argument(
        "--country",
        action="append",
        help="指定单个国家（可多次传：--country US --country GB）；缺省 = 全部 5 国",
    )
    args = ap.parse_args()

    if args.command == "login":
        asyncio.run(cmd_login())
    else:
        asyncio.run(cmd_scrape(headed=args.headed, countries=args.country))


if __name__ == "__main__":
    main()
