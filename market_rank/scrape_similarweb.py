#!/usr/bin/env python3
"""Similarweb 公开页抓取 — 9 个竞品官网的流量 / 设备 / 停留 / 6 大流量来源。

CLI:
    python3 -m market_rank.scrape_similarweb              # 抓所有竞品
    python3 -m market_rank.scrape_similarweb --domain sofascore.com   # 只抓一个
    python3 -m market_rank.scrape_similarweb --headed     # 显示浏览器调试
    python3 -m market_rank.scrape_similarweb login        # 一次性手动过 Cloudflare（profile 持久化）

输出：
- data/async_similarweb.json  — 标准 shape
- MySQL website_traffic 表（每月 1 行 / 竞品，月内 UPSERT）
- data/raw/similarweb_<DATE>.md  — 人类可读快照

设计：
- Similarweb 不登录就能看 6 大流量来源 + 设备占比 + 月访问量 + Avg Visit Duration + Pages/Visit + Bounce Rate
- 公开页有 Cloudflare 防护：纯 headless 容易 403。所以走"持久化 profile + 一次性人工过 challenge"模式
- 数据按"月"对齐（snapshot_month = 当月 1 号），每周抓一次，月内更新同一行
"""

from __future__ import annotations

import argparse
import asyncio
import json
import re
import sys
from datetime import date, datetime, timezone
from pathlib import Path

from playwright.async_api import async_playwright

_SCRIPT_DIR = Path(__file__).resolve().parent
_PROJECT_ROOT = _SCRIPT_DIR.parent

if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

try:
    from shared.env_loader import load_all as _load_env_all
    _load_env_all()
except Exception:
    pass

from competitors import get_website_competitors  # type: ignore
from shared.dao import website_traffic as dao_traffic  # type: ignore

PROFILE_DIR = Path.home() / ".similarweb-profile"
DATA_OUT = _PROJECT_ROOT / "data" / "async_similarweb.json"
RAW_OUT_DIR = _PROJECT_ROOT / "data" / "raw"

PAGE_TIMEOUT_SEC = 90   # Similarweb SPA 慢，charts 要 60s+


# ---- DOM 提取 JS ----------------------------------------------------------
# Similarweb 公开页的核心结构：
#   - "Total Visits" / "Last Month" 标签 + 数字（"30.5M"）
#   - "Avg Visit Duration" / "Pages per Visit" / "Bounce Rate"
#   - "Device Distribution" → Desktop / Mobile 两个百分比
#   - "Marketing Channels Distribution" / "Traffic Sources" → 6 个百分比（Direct / Search / Social / Referrals / Mail / Display Ads）
#   - "Top Countries" → top 5 国家
# 由于 Similarweb 经常 A/B 改 DOM，这里走"全文 + label 锚点"策略：抓 main innerText
# 然后正则匹配，比 element walking 更稳。

EXTRACT_JS = r"""
() => {
  const main = document.querySelector('main') || document.body;
  const text = main.innerText || '';
  const out = {
    raw_text: text.slice(0, 8000),
  };

  // ---- 工具：把 "30.5M" / "1.2B" / "<5K" 转成数字 ----------------
  function parseVisits(s) {
    if (!s) return null;
    const t = String(s).replace(/[~,<>\s]/g, '');
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

  // 时长 "00:05:23" → 323
  function parseDuration(s) {
    if (!s) return null;
    const m = String(s).match(/(\d{1,2}):(\d{2}):(\d{2})/);
    if (m) return (+m[1]) * 3600 + (+m[2]) * 60 + (+m[3]);
    return null;
  }

  // 百分比 "32.5%" → 0.325；"<1%" → 0.005；约定输入永远来自页面 % 显示
  function parsePct(s) {
    if (s == null) return null;
    let t = String(s).trim();
    if (!t) return null;
    if (t.startsWith('<')) {
      const n = parseFloat(t.replace(/[<%\s]/g, ''));
      if (isNaN(n)) return null;
      return n / 200;  // "<1%" 取上限一半
    }
    const n = parseFloat(t.replace(/[%\s]/g, ''));
    if (isNaN(n) || n < 0) return null;
    return n / 100;
  }

  // 在 label 与 sentinel 之间提取第一个匹配 regex 的 token
  function extractAfter(label, sentinels, regex) {
    const idx = text.indexOf(label);
    if (idx < 0) return null;
    let end = text.length;
    for (const s of sentinels) {
      const i = text.indexOf(s, idx + label.length);
      if (i > 0 && i < end) end = i;
    }
    const block = text.slice(idx + label.length, end);
    const m = block.match(regex);
    return m ? m[0] : null;
  }

  // ---- 1. Monthly visits（在 Engagement overview 区块）---------
  // "Monthly visits\n80.71M\nMonthly Unique Visitors\n..."
  // 必须 K/M/B 后缀避免误匹配
  const visitsRaw = extractAfter('Monthly visits', [
    'Monthly Unique', 'Visit Duration', 'Pages /', 'Bounce Rate',
  ], /[\d.]+\s*[KMB]/i);
  if (visitsRaw) {
    out.monthly_visits = visitsRaw.trim();
    out.monthly_visits_num = parseVisits(visitsRaw);
  }

  // ---- 2. Bounce Rate -----------------------------------------
  const brRaw = extractAfter('Bounce Rate', [
    'See trends', 'Visits over time', 'Marketing Channels', 'Geography',
  ], /[\d.]+\s*%/);
  if (brRaw) out.bounce_rate = parsePct(brRaw);

  // ---- 3. Pages / Visit ---------------------------------------
  // 注意 Similarweb 的 label 是 "Pages / Visit"（两个空格 + 斜杠）
  const ppvRaw = extractAfter('Pages / Visit', [
    'Bounce Rate', 'See trends', 'Marketing Channels',
  ], /[\d.]+/);
  if (ppvRaw) out.pages_per_visit = parseFloat(ppvRaw);

  // ---- 4. Visit Duration --------------------------------------
  const durRaw = extractAfter('Visit Duration', [
    'Pages /', 'Bounce Rate', 'See trends',
  ], /\d{1,2}:\d{2}:\d{2}/);
  if (durRaw) {
    out.avg_visit_duration = durRaw.trim();
    out.avg_visit_duration_sec = parseDuration(durRaw);
  }

  // ---- 5. Device distribution (Desktop / Mobile Web) ----------
  // "Device distribution\n...Desktop\n59.48%\nMobile Web\n40.52%"
  const devIdx = text.indexOf('Device distribution');
  if (devIdx >= 0) {
    const devBlock = text.slice(devIdx, devIdx + 600);
    const md = devBlock.match(/Desktop\s*\n?\s*([\d.]+)\s*%/);
    const mm = devBlock.match(/Mobile(?:\s*Web)?\s*\n?\s*([\d.]+)\s*%/);
    if (md) out.desktop_share = parsePct(md[1]);
    if (mm) out.mobile_share = parsePct(mm[1]);
  }

  // ---- 6. Marketing Channels — 10 channels chart -------------
  // Similarweb 新版 chart 渲染顺序：
  //   labels: Direct / Search-Organic / Search-Paid / Referrals / Display
  //           / Social-Organic / Social-Paid / [Gen AI] / Email / Affiliates
  //   axis:   0% / 25% / 50% / 75%
  //   values: <Direct%> <Search-Organic%> ... 同顺序排列
  // 锚点 = chart axis 行。Similarweb 有 3 种 axis 渲染：
  //   - "0% / 25% / 50% / 75%"          (sofascore — 当数据有突出 100%-级值时不显)
  //   - "0% / 25% / 50% / 75% / 100%"   (flashscore — Direct 占 75%+)
  //   - "0% / 50% / 100%"               (fotmob — Direct 占 70%+)
  // 我们要 match 整个 axis 块然后从其 *末尾* 之后开始抓 channel 值
  const axisMatch = text.match(
    /(?:0%\s*\n\s*25%\s*\n\s*50%\s*\n\s*75%(?:\s*\n\s*100%)?|0%\s*\n\s*50%\s*\n\s*100%)\s*\n([\s\S]+)/
  );
  if (axisMatch) {
    // 取 axis 后 → 第一个 section 边界。Similarweb chart 末尾固定是 "See full overview" 链接。
    let after = axisMatch[1];
    const stops = ['See full overview', 'See more', 'Marketing Channels overview'];
    let stopAt = after.length;
    for (const s of stops) {
      const i = after.indexOf(s);
      if (i > 0 && i < stopAt) stopAt = i;
    }
    after = after.slice(0, Math.min(stopAt, 600));
    const pcts = [];
    const re = /(<?\s*[\d.]+)\s*%/g;
    let m;
    while ((m = re.exec(after)) && pcts.length < 10) {
      pcts.push(parsePct(m[1]));
    }
    // 标签顺序：Direct / Search-Organic / Search-Paid / Referrals / Display / Social-Organic / Social-Paid /
    //            [Gen AI] / [Email] / [Affiliates]
    // 后 3 个是否存在 → 看 chart label 区域有没有出现这些 label
    const hasGenAI      = /Gen AI\s*\n/.test(text);
    const hasEmail      = /Email\s*\n/.test(text);
    const hasAffiliates = /Affiliates\s*\n/.test(text);

    if (pcts.length >= 7) {
      out.direct_share   = pcts[0];
      out.search_share   = (pcts[1] || 0) + (pcts[2] || 0);   // organic + paid
      out.referral_share = pcts[3];
      out.display_share  = pcts[4];
      out.social_share   = (pcts[5] || 0) + (pcts[6] || 0);   // organic + paid

      // 后续 channel 位置自适应（哪个不存在就跳）
      let pos = 7;
      if (hasGenAI && pos < pcts.length) {
        out.genai_share = pcts[pos++];
      }
      if (hasEmail && pos < pcts.length) {
        out.mail_share = pcts[pos++];
      }
      if (hasAffiliates && pos < pcts.length) {
        out.affiliate_share = pcts[pos++];
      }
    }
    out._channel_pcts_raw = pcts;  // 调试用
  }

  // ---- 7. Top Countries（country rank 区块）-------------------
  // "Country rank\nBrazil\n#298\n..." 单一国家；如需 top 5 要去 Geography tab
  // 这里先抓"Country rank"下唯一的国家名 + Geography 区域下的 list
  const cRankIdx = text.indexOf('Country rank');
  if (cRankIdx >= 0) {
    const rb = text.slice(cRankIdx, cRankIdx + 400);
    const m = rb.match(/Country rank\s*\n\s*([A-Z][A-Za-z .'-]{2,40})\s*\n\s*#\s*(\d+)/);
    if (m) {
      out.top_countries = [{
        country: m[1].trim(),
        rank: parseInt(m[2]),
      }];
    }
  }

  // ---- 8. Top Keywords（在 Search 区域，可能没有）-----------
  // 实际渲染：5 个 keyword 一段 + 5 个 % 一段（不是交叉），格式：
  //   "Top organic non-branded search terms\n
  //    real madridAds\nbrazil vs franceAds\nchampions leagueAds\nrezultatiAds\nXAds\n
  //    1.98%\n0.63%\n..."
  const kwIdx = text.indexOf('Top organic non-branded search terms');
  if (kwIdx >= 0) {
    let kb = text.slice(kwIdx);
    // 截到下一个 section 边界
    const stopMarkers = ['See more search terms', 'Paid Search', 'See full overview', 'Referrals'];
    let stopAt = kb.length;
    for (const m of stopMarkers) {
      const i = kb.indexOf(m);
      if (i > 0 && i < stopAt) stopAt = i;
    }
    kb = kb.slice(0, stopAt);
    // 跳过 header — 找到 "All traffic\n" 之后才开始
    const startMarker = 'All traffic';
    const startIdx = kb.indexOf(startMarker);
    if (startIdx > 0) kb = kb.slice(startIdx + startMarker.length);

    // 先抓所有 "<kw>Ads"（kw 必须以小写字母 / 数字开头，避免吃 "Top" 这种）
    const kwRe = /(?:^|\n)\s*([a-z0-9][\w\s.'-]{1,60}?)Ads\s*(?=\n)/gi;
    const kwList = [];
    let km;
    while ((km = kwRe.exec(kb)) && kwList.length < 10) {
      const kw = km[1].trim();
      if (kw.length >= 2) kwList.push(kw);
    }
    // 再抓所有 % 值
    const pctRe = /([\d.]+)\s*%/g;
    const pctList = [];
    let pm;
    while ((pm = pctRe.exec(kb)) && pctList.length < kwList.length + 5) {
      pctList.push(parsePct(pm[1]));
    }
    const pairs = [];
    for (let i = 0; i < kwList.length && i < pctList.length; i++) {
      pairs.push({ kw: kwList[i], share: pctList[i] });
    }
    if (pairs.length) out.top_keywords = pairs;
  }

  return out;
}
"""


# ---- 流程控制 -------------------------------------------------------------


class CloudflareBlocked(RuntimeError):
    """页面被 Cloudflare 拦截。"""


async def _detect_cloudflare(page) -> bool:
    """检测当前页是否在 CF challenge / 拦截页。"""
    try:
        url = page.url or ""
        if "challenge" in url or "/cdn-cgi/" in url:
            return True
        title = (await page.title()) or ""
        if "Just a moment" in title or "Attention Required" in title:
            return True
        # 检测页面文字
        body_text = await page.evaluate(
            "() => (document.body && document.body.innerText || '').slice(0, 800)"
        )
        if "Verify you are human" in body_text or "Please enable JS" in body_text:
            return True
        return False
    except Exception:
        return False


async def _dismiss_banners(page) -> None:
    """关掉 cookie / GDPR banner（OneTrust 等），失败不抛。"""
    selectors = [
        "#onetrust-accept-btn-handler",
        "button#onetrust-accept-btn-handler",
        "button[id*='accept']",
        "button[aria-label*='accept' i]",
        "button:has-text('Accept All')",
        "button:has-text('I Accept')",
    ]
    for sel in selectors:
        try:
            btn = await page.query_selector(sel)
            if btn and await btn.is_visible():
                await btn.click(timeout=2000)
                await asyncio.sleep(0.5)
                return
        except Exception:
            continue


async def _wait_overview_ready(page, timeout_s: int = PAGE_TIMEOUT_SEC) -> None:
    """等到核心 label 在页面文本里出现 — 比 body_len 阈值更可靠。"""
    REQUIRED_MARKERS = ["Total Visits", "Bounce Rate"]   # 任一出现即认为渲染开始
    loop = asyncio.get_event_loop()
    deadline = loop.time() + timeout_s
    banner_dismissed = False
    while loop.time() < deadline:
        if await _detect_cloudflare(page):
            raise CloudflareBlocked("Similarweb 被 Cloudflare 拦截")
        if not banner_dismissed:
            await _dismiss_banners(page)
            banner_dismissed = True
        body_text = await page.evaluate(
            "() => (document.querySelector('main') || document.body).innerText || ''"
        )
        if any(m in body_text for m in REQUIRED_MARKERS) and len(body_text) > 1500:
            return
        await asyncio.sleep(1.0)
    # 超时 — 记录调试信息
    body_text = await page.evaluate(
        "() => (document.querySelector('main') || document.body).innerText || ''"
    )
    cur_url = page.url or ""
    title = (await page.title()) or ""
    snippet = body_text[:1500].replace("\n", " | ")
    print(
        f"  [debug] timeout: url={cur_url!r} title={title!r}\n"
        f"  [debug] body_len={len(body_text)} text_head={snippet!r}",
        file=sys.stderr,
    )
    if await _detect_cloudflare(page):
        raise CloudflareBlocked("Similarweb 加载超时且疑似被 CF 拦截")
    raise TimeoutError(f"Similarweb 概览页未在 {timeout_s}s 内加载完成")


async def _fetch_domain(page, domain: str) -> dict:
    url = f"https://www.similarweb.com/website/{domain}/"
    print(f"[{domain}] {url}")
    await page.goto(url, wait_until="domcontentloaded")
    await _wait_overview_ready(page)
    # SPA 异步刷数据，多等几秒
    await asyncio.sleep(3)
    data = await page.evaluate(EXTRACT_JS)
    print(
        f"  -> visits={data.get('monthly_visits')}  dur={data.get('avg_visit_duration')}"
        f"  bounce={data.get('bounce_rate')}  desktop/mobile={data.get('desktop_share')}/{data.get('mobile_share')}"
    )
    return data


# ---- 命令：login ----------------------------------------------------------


async def cmd_login() -> None:
    PROFILE_DIR.mkdir(parents=True, exist_ok=True)
    async with async_playwright() as p:
        ctx = await p.chromium.launch_persistent_context(
            str(PROFILE_DIR),
            channel="chrome",
            headless=False,
            viewport={"width": 1400, "height": 900},
            user_agent=(
                "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
            ),
            locale="en-US",
            args=[
                "--disable-blink-features=AutomationControlled",
                "--disable-features=IsolateOrigins,site-per-process",
            ],
        )
        page = ctx.pages[0] if ctx.pages else await ctx.new_page()
        await page.goto("https://www.similarweb.com/website/sofascore.com/")
        print("浏览器已打开 Similarweb（sofascore.com 概览页）")
        print("  1. 如果出现 Cloudflare 'Verify you are human' → 完成验证")
        print("  2. 看到流量数据 + 6 个 Marketing Channels 渲染出来即可")
        print("  3. （可选）右上角 Sign Up 注册免费账号能解锁更多字段，但不强制")
        print("  4. 关闭浏览器窗口结束 — cookie 会保存到 ~/.similarweb-profile")
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


async def cmd_scrape(headed: bool = False, only_domain: str | None = None) -> Path:
    if not PROFILE_DIR.exists():
        raise CloudflareBlocked(
            f"找不到 {PROFILE_DIR}。请先跑：\n"
            f"  python3 -m market_rank.scrape_similarweb login"
        )

    websites = get_website_competitors()
    if only_domain:
        websites = {n: d for n, d in websites.items() if d == only_domain.lower()}
        if not websites:
            print(f"未找到域名 {only_domain}", file=sys.stderr)
            return DATA_OUT

    today = date.today()
    snapshot_month = today.replace(day=1)
    now_iso = datetime.now(timezone.utc).isoformat()

    results: list[dict] = []
    md_sections: list[str] = [f"# Website Traffic — Similarweb · {today.isoformat()}\n"]

    async with async_playwright() as p:
        ctx = await p.chromium.launch_persistent_context(
            str(PROFILE_DIR),
            channel="chrome",                       # 系统 Chrome 而非 Chromium — 过 CloudFront 指纹
            headless=not headed,
            viewport={"width": 1400, "height": 900},
            user_agent=(
                "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
            ),
            locale="en-US",
            args=[
                "--disable-blink-features=AutomationControlled",
                "--disable-features=IsolateOrigins,site-per-process",
            ],
        )
        page = ctx.pages[0] if ctx.pages else await ctx.new_page()
        try:
            for app_name, domain in websites.items():
                try:
                    data = await _fetch_domain(page, domain)
                except CloudflareBlocked:
                    print(f"  ⚠️  CF 拦截，停止抓取（请重新跑 login）", file=sys.stderr)
                    raise
                except Exception as e:
                    print(f"  ERROR ({app_name}/{domain}): {e}", file=sys.stderr)
                    data = {"error": str(e)}

                rec = {
                    "source": "similarweb",
                    "competitor": app_name,
                    "domain": domain,
                    "snapshot_month": snapshot_month.isoformat(),
                    "timestamp": now_iso,
                    "data": data,
                }
                results.append(rec)

                # 写 MySQL
                if not data.get("error"):
                    n = dao_traffic.upsert_website_traffic(
                        app_name, domain, snapshot_month, data,
                    )
                    if n:
                        print(f"    MySQL: upsert OK")

                md_sections.append(_md_section(app_name, domain, data))
                await asyncio.sleep(2)
        finally:
            try:
                await ctx.close()
            except Exception:
                pass

    # 写 JSON 主输出
    DATA_OUT.parent.mkdir(parents=True, exist_ok=True)
    DATA_OUT.write_text(json.dumps(results, ensure_ascii=False, indent=2), encoding="utf-8")
    ok = sum(1 for r in results if not (r.get("data") or {}).get("error"))
    print(f"\n保存完成 -> {DATA_OUT}（{len(results)} record，{ok} 条有数据）")

    # 写 markdown 快照
    RAW_OUT_DIR.mkdir(parents=True, exist_ok=True)
    md_path = RAW_OUT_DIR / f"similarweb_{today.isoformat()}.md"
    md_path.write_text("\n".join(md_sections), encoding="utf-8")
    print(f"markdown 快照 -> {md_path}")

    return DATA_OUT


# ---- markdown ------------------------------------------------------------


def _fmt_pct(v) -> str:
    if v is None:
        return "—"
    try:
        return f"{float(v) * 100:.1f}%"
    except (TypeError, ValueError):
        return str(v)


def _md_section(app_name: str, domain: str, data: dict) -> str:
    if data.get("error"):
        return f"## {app_name} ({domain})\n\n_error: {data['error']}_\n"
    lines = [
        f"## {app_name} ({domain})",
        "",
        f"- **Monthly Visits**: {data.get('monthly_visits') or '—'}"
        f" ({data.get('monthly_visits_num') or '—'})",
        f"- **Avg Visit Duration**: {data.get('avg_visit_duration') or '—'}"
        f" ({data.get('avg_visit_duration_sec') or '—'}s)",
        f"- **Pages/Visit**: {data.get('pages_per_visit') or '—'}",
        f"- **Bounce Rate**: {_fmt_pct(data.get('bounce_rate'))}",
        f"- **Devices**: Desktop {_fmt_pct(data.get('desktop_share'))}"
        f" · Mobile {_fmt_pct(data.get('mobile_share'))}",
        "",
        "**6 Traffic Sources**:",
        f"  - Direct: {_fmt_pct(data.get('direct_share'))}",
        f"  - Search: {_fmt_pct(data.get('search_share'))}",
        f"  - Social: {_fmt_pct(data.get('social_share'))}",
        f"  - Referral: {_fmt_pct(data.get('referral_share'))}",
        f"  - Mail: {_fmt_pct(data.get('mail_share'))}",
        f"  - Display: {_fmt_pct(data.get('display_share'))}",
        "",
    ]
    cs = data.get("top_countries") or []
    if cs:
        lines.append("**Top Countries**:")
        for c in cs[:5]:
            lines.append(f"  - {c.get('country')} — {_fmt_pct(c.get('share'))}")
        lines.append("")
    kws = data.get("top_keywords") or []
    if kws:
        lines.append("**Top Keywords**:")
        for k in kws[:5]:
            lines.append(f"  - {k.get('kw')} — {_fmt_pct(k.get('share'))}")
        lines.append("")
    return "\n".join(lines)


# ---- main ----------------------------------------------------------------


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("command", choices=["login", "scrape"], nargs="?", default="scrape")
    ap.add_argument("--headed", action="store_true")
    ap.add_argument("--domain", help="仅抓指定域名（smoke test 用）")
    args = ap.parse_args()

    if args.command == "login":
        asyncio.run(cmd_login())
    else:
        try:
            asyncio.run(cmd_scrape(headed=args.headed, only_domain=args.domain))
        except CloudflareBlocked as e:
            print(f"❌ {e}", file=sys.stderr)
            sys.exit(2)


if __name__ == "__main__":
    main()
