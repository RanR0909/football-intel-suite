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
    let mediaUrl = '';
    const img = parent.querySelector('img[src*="scontent"], img[src*="fbcdn"], video');
    if (img) mediaUrl = img.src || img.currentSrc || '';
    // metadata 行前缀（多语言）
    const metaPrefixes = [
      'Library ID', '资料库编号', 'ID de la bibliothèque',
      'Started running', '开始投放', 'Platforms', '平台', 'Plateformes',
      'Active', '投放中', 'Inactive', '已停',
      'Sponsored', '赞助内容', '赞助',
      'EU transparency', '欧盟境内',
    ];

    // Fix 5 (2026-05-08): page_name + page_id 双轨提取
    //   旧版用 lines[0] 拿广告主名字，但 FB 卡片首行经常是 metadata（"Active"/"Library ID"），
    //   导致 376/376 page_name 全空。
    //   新方案：
    //   1. 优先从 DOM link 找 — 广告卡顶部有 <a> 链向广告主主页，
    //      href 形如 "/<vanity>/" 或 "?id=<page_id>"，link 内文本是 page name
    //   2. fallback：扫 lines 找第一个非 metadata 短行（< 60 字 + 非纯标点）
    let pageName = '';
    let pageId = '';
    const advertiserLinks = parent.querySelectorAll('a[href]');
    for (const a of advertiserLinks) {
      const href = a.getAttribute('href') || '';
      // 跳过广告库自身链接
      if (href.includes('/ads/library')) continue;
      if (href.includes('/profile.php?id=')) {
        const m = href.match(/[?&]id=(\d+)/);
        if (m) pageId = m[1];
        const txt = (a.innerText || '').trim();
        if (txt && txt.length < 60 && !pageName) pageName = txt;
        if (pageId && pageName) break;
      } else if (/^https?:\/\/(www\.)?facebook\.com\/[^\/?#]+\/?$/.test(href)
                 || /^\/[^\/?#]+\/?$/.test(href)) {
        // vanity URL: facebook.com/sofascore 或 /sofascore/
        const txt = (a.innerText || '').trim();
        if (txt && txt.length < 60 && !pageName) pageName = txt;
        // vanity URL 拿不到 numeric page_id，由后端 discover 流程补
      }
    }
    // fallback: 扫 lines 找首行非 metadata 短行
    if (!pageName) {
      for (const l of lines) {
        if (l.length < 2 || l.length > 80) continue;
        if (metaPrefixes.some(p => l.startsWith(p))) continue;
        // 排除全数字 / 全标点 / Library ID 这种
        if (/^[\d\s.\-,:#]+$/.test(l)) continue;
        pageName = l;
        break;
      }
    }

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
      page_id: pageId,
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
    comp_dict = get_comment_competitors()
    competitors = list(comp_dict.keys())
    results: list[dict] = []
    now_iso = datetime.now(timezone.utc).isoformat()

    # 统计 page_id 配置情况：有 fb_page_id 的走精确，无的回退到关键词搜索（污染严重）
    with_page_id = [n for n in competitors if comp_dict[n].get("fb_page_id")]
    without_page_id = [n for n in competitors if not comp_dict[n].get("fb_page_id")]
    print(f"[fb_adlib] 抓取国家：{target_countries} · {len(competitors)} 竞品")
    print(f"  · 精确 (fb_page_id): {len(with_page_id)} 个 — {with_page_id}")
    if without_page_id:
        print(f"  · 关键词回退（污染高）: {len(without_page_id)} 个 — {without_page_id}")
        print(f"    建议先跑 discover-pages 命令补全 fb_page_id")

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
                fb_page_id = comp_dict[app_name].get("fb_page_id")
                for country in target_countries:
                    # 优先用 view_all_page_id (精确，仅该 page 投的广告)；缺失则关键词回退
                    if fb_page_id:
                        url = (
                            "https://www.facebook.com/ads/library/"
                            f"?active_status=active&ad_type=all&country={country}"
                            f"&view_all_page_id={fb_page_id}"
                            f"&is_targeted_country=false&media_type=all"
                        )
                        mode = f"page_id={fb_page_id}"
                    else:
                        # 回退：search_type=keyword_unordered 关键词模糊匹配（污染严重）
                        url = (
                            "https://www.facebook.com/ads/library/"
                            f"?active_status=active&ad_type=all&country={country}"
                            f"&is_targeted_country=false&media_type=all"
                            f"&q={quote(app_name)}&search_type=keyword_unordered"
                        )
                        mode = f"keyword='{app_name}'"
                    print(f"[{app_name}/{country}] 抓取中 ({mode})...")
                    try:
                        cards = await _scroll_and_collect(page, url)
                    except Exception as e:
                        print(f"  ERROR: {e}", file=sys.stderr)
                        cards = []
                    # 关键词模式下做后过滤：只留 page_name 含竞品名 fuzzy 匹配的
                    if not fb_page_id and cards:
                        norm_app = app_name.lower().replace(" ", "")
                        kept = [c for c in cards if norm_app in (c.get("page_name") or "").lower().replace(" ", "")]
                        if len(kept) < len(cards):
                            print(f"  关键词后过滤：{len(cards)} → {len(kept)} 条 (剥离 page_name 不含 '{app_name}' 的)")
                        cards = kept
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


# ---- 命令：discover-pages（自动找 fb_page_id 写回 competitors.json）----------

# advertiser search 页面 DOM 抽取：找所有 <a href="...view_all_page_id=N..."> 链接
DISCOVER_JS = r"""
() => {
  const out = [];
  const seen = new Set();
  // advertiser search 结果 = 含 view_all_page_id= 链接
  const links = document.querySelectorAll('a[href*="view_all_page_id="]');
  for (const a of links) {
    const m = a.href.match(/view_all_page_id=(\d+)/);
    if (!m) continue;
    const pageId = m[1];
    if (seen.has(pageId)) continue;
    seen.add(pageId);
    // 找 advertiser name — 优先 link 内文本；空则爬 parent 找首行有意义文本
    let name = (a.innerText || '').trim();
    if (!name) {
      let p = a.parentElement;
      for (let i = 0; i < 4 && p; i++) {
        const lines = (p.innerText || '').split('\n').map(s => s.trim()).filter(Boolean);
        for (const l of lines) {
          if (l.length > 1 && l.length < 80 && !/^[\d\s.\-]+$/.test(l)) {
            name = l;
            break;
          }
        }
        if (name) break;
        p = p.parentElement;
      }
    }
    out.push({ page_id: pageId, name: name || '' });
    if (out.length >= 20) break;
  }
  return out;
};
"""


def _best_page_match(app_name: str, candidates: list[dict]) -> dict | None:
    """启发式选 advertiser search 结果里 name 与 app_name 最匹配的。"""
    if not candidates:
        return None
    import difflib
    norm_app = app_name.lower().replace(" ", "")
    # Tier 1: substring 包含
    for c in candidates:
        np = (c.get("name") or "").lower().replace(" ", "")
        if not np:
            continue
        if norm_app in np or np in norm_app:
            return c
    # Tier 2: SequenceMatcher ≥ 0.6
    scored = []
    for c in candidates:
        np = (c.get("name") or "").lower().replace(" ", "")
        if not np:
            continue
        ratio = difflib.SequenceMatcher(None, norm_app, np).ratio()
        scored.append((ratio, c))
    scored.sort(key=lambda x: x[0], reverse=True)
    return scored[0][1] if scored and scored[0][0] >= 0.6 else None


async def cmd_discover_pages(headed: bool = False, dry_run: bool = False) -> None:
    """访问 FB 广告库的 advertiser search 自动找每个竞品的 page_id 写回 competitors.json。

    advertiser search URL: facebook.com/ads/library/?country=ALL&q=<竞品>&search_type=page
    返回结果是 advertiser pages 而非 ads，每个卡片有 link 含 view_all_page_id=<id>。
    """
    competitors_path = _PROJECT_ROOT / "data" / "competitors.json"
    if not competitors_path.exists():
        print(f"❌ {competitors_path} 不存在", file=sys.stderr)
        sys.exit(1)
    raw = json.loads(competitors_path.read_text(encoding="utf-8"))
    apps = raw.get("competitors") if isinstance(raw, dict) and "competitors" in raw else raw
    if not isinstance(apps, dict):
        print(f"❌ competitors.json 格式不对（顶层应是 dict）", file=sys.stderr)
        sys.exit(1)
    target_apps = list(apps.keys())
    print(f"[discover] 共 {len(target_apps)} 个竞品要找 page_id")
    print(f"  已有 fb_page_id 的 (跳过): {[a for a in target_apps if apps[a].get('fb_page_id')]}")

    findings: dict[str, list[dict]] = {}
    async with async_playwright() as p:
        ctx = await p.chromium.launch_persistent_context(
            str(PROFILE_DIR),
            headless=not headed,
            viewport={"width": 1400, "height": 900},
            args=["--disable-blink-features=AutomationControlled"],
        )
        page = ctx.pages[0] if ctx.pages else await ctx.new_page()
        try:
            for app_name in target_apps:
                if apps[app_name].get("fb_page_id"):
                    continue   # 已有则跳过
                url = (
                    "https://www.facebook.com/ads/library/"
                    f"?country=ALL&q={quote(app_name)}&search_type=page"
                )
                print(f"\n[{app_name}] 搜 advertiser pages: {url}")
                try:
                    await page.goto(url, wait_until="domcontentloaded")
                    await _accept_cookies_if_needed(page)
                    await asyncio.sleep(3)
                    candidates = await page.evaluate(DISCOVER_JS)
                except Exception as e:
                    print(f"  ERROR: {e}", file=sys.stderr)
                    candidates = []
                findings[app_name] = candidates
                # 打印前 5 条
                for c in candidates[:5]:
                    print(f"    候选 page_id={c.get('page_id')} name={c.get('name')!r}")
                if not candidates:
                    print(f"    (找不到任何 advertiser page)")
                await asyncio.sleep(1.5)
        finally:
            try:
                await ctx.close()
            except Exception:
                pass

    print(f"\n[discover] 启发式 best-match：")
    updates: dict[str, str] = {}
    for app_name, candidates in findings.items():
        best = _best_page_match(app_name, candidates)
        if best:
            print(f"  ✓ {app_name:<14} → page_id={best['page_id']} name={best.get('name')!r}")
            updates[app_name] = best["page_id"]
        else:
            print(f"  ✗ {app_name:<14} → 找不到合适的 (top 候选: {candidates[:3]})")

    if dry_run:
        print(f"\n[dry-run] 不写回 competitors.json")
        return
    if not updates:
        print(f"\n[discover] 没有要更新的；competitors.json 不变")
        return

    # 写回
    for app_name, page_id in updates.items():
        if "competitors" in raw:
            raw["competitors"][app_name]["fb_page_id"] = page_id
        else:
            raw[app_name]["fb_page_id"] = page_id
    competitors_path.write_text(
        json.dumps(raw, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    print(f"\n[discover] 已写回 {competitors_path}（更新 {len(updates)} 个）")
    print(f"  下次 fb_adlib scrape 会自动用 page_id 精确匹配")


# ---- main -----------------------------------------------------------------

def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument(
        "command",
        choices=["login", "scrape", "discover-pages"],
        nargs="?", default="scrape",
        help="login: 首次登录 / cookie 刷新；scrape: 抓广告（默认）；"
             "discover-pages: 自动找每个竞品的 fb_page_id 写回 competitors.json",
    )
    ap.add_argument("--headed", action="store_true")
    ap.add_argument(
        "--country",
        action="append",
        help="指定单个国家（可多次传：--country US --country GB）；缺省 = 全部 5 国",
    )
    ap.add_argument("--dry-run", action="store_true",
                    help="discover-pages: 只打印不写回 JSON")
    args = ap.parse_args()

    if args.command == "login":
        asyncio.run(cmd_login())
    elif args.command == "discover-pages":
        asyncio.run(cmd_discover_pages(headed=args.headed, dry_run=args.dry_run))
    else:
        asyncio.run(cmd_scrape(headed=args.headed, countries=args.country))


if __name__ == "__main__":
    main()
