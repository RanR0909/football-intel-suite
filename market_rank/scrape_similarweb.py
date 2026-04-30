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
  if (!main) return { error: 'no_main_or_body' };
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

  // ---- 1. Monthly visits ---------------------------------------
  // 两种渲染：
  //   trial：     "Monthly visits\n80.71M"           （在 Engagement overview）
  //   anonymous： "Total Visits\n\n85M"              （单值，不带 "Last 3 Months"）
  //   trial 也有："Total Visits\nLast 3 Months\n242.1M"  ← 3 月累加，不要这个
  // 优先用 "Monthly visits"；缺则 fallback 到 "Total Visits" 但只在没有 "Last 3 Months" 时
  let visitsRaw = extractAfter('Monthly visits', [
    'Monthly Unique', 'Visit Duration', 'Pages /', 'Bounce Rate',
  ], /[\d.]+\s*[KMB]/i);
  if (!visitsRaw) {
    // anonymous 模式 — "Total Visits" 是月值，且后面紧跟数字，没有 "Last 3 Months"
    const tvIdx = text.indexOf('Total Visits');
    if (tvIdx >= 0) {
      const block = text.slice(tvIdx, tvIdx + 200);
      // 排除 "Total Visits Last 3 Months" — 那是 trial 的 3 月累加值
      if (!/Total Visits\s*\n\s*Last 3 Months/i.test(block)) {
        const m = block.match(/Total Visits\s*\n\s*\n?\s*([\d.]+\s*[KMB])/i);
        if (m) visitsRaw = m[1];
      }
    }
  }
  if (visitsRaw) {
    out.monthly_visits = visitsRaw.trim();
    out.monthly_visits_num = parseVisits(visitsRaw);
  }

  // ---- 2. Bounce Rate -----------------------------------------
  const brRaw = extractAfter('Bounce Rate', [
    'See trends', 'Visits over time', 'Marketing Channels', 'Geography',
    'Pages per Visit', 'Avg Visit Duration',
  ], /[\d.]+\s*%/);
  if (brRaw) out.bounce_rate = parsePct(brRaw);

  // ---- 3. Pages / Visit ---------------------------------------
  // anonymous label = "Pages per Visit"；trial label = "Pages / Visit"
  let ppvRaw = extractAfter('Pages / Visit', [
    'Bounce Rate', 'See trends', 'Marketing Channels',
  ], /[\d.]+/);
  if (!ppvRaw) {
    ppvRaw = extractAfter('Pages per Visit', [
      'Avg Visit Duration', 'Bounce Rate', 'See trends', 'Marketing Channels',
    ], /[\d.]+/);
  }
  if (ppvRaw) out.pages_per_visit = parseFloat(ppvRaw);

  // ---- 4. Visit Duration --------------------------------------
  const durRaw = extractAfter('Visit Duration', [
    'Pages /', 'Bounce Rate', 'See trends',
  ], /\d{1,2}:\d{2}:\d{2}/);
  if (durRaw) {
    out.avg_visit_duration = durRaw.trim();
    out.avg_visit_duration_sec = parseDuration(durRaw);
  }

  // (注意：device split / 6 大流量来源 / top_keywords 仅 Premium Trial 期间可见，
  //  trial 过期后 Similarweb 把它们 gated 掉，所以 schema 不收这些字段，
  //  避免长期出现 null 列。如需恢复可参考 git log + migration 0006/0007/0008。)

  // ---- 5. Ranks (Global / Country / Category) ----------------
  // anonymous + trial 都有，但布局不同：
  //   anonymous: "Global Rank\n#635\n10\n\nCountry Rank\n#298\n1\n\nBrazil\n\nCategory Rank\n#4"
  //   trial:     "Global rank\n#635\nCountry rank\nBrazil\n#298\nIndustry rank\n.../Sports\n#9"
  // 双向匹配（label + 数字，两种顺序）
  const grm = text.match(/Global\s+[Rr]ank\s*\n+\s*#\s*(\d[\d,]*)/);
  if (grm) out.global_rank = parseInt(grm[1].replace(/,/g, ''));

  // anonymous 顺序：#rank → country
  let crm = text.match(/Country\s+[Rr]ank\s*\n+\s*#\s*(\d[\d,]*)\s*\n+\s*\d?\s*\n*\s*([A-Z][A-Za-z .'-]{2,40})/);
  if (!crm) {
    // trial 顺序：country → #rank
    crm = text.match(/Country\s+[Rr]ank\s*\n+\s*([A-Z][A-Za-z .'-]{2,40})\s*\n+\s*#\s*(\d[\d,]*)/);
    if (crm) {
      out.country_rank = parseInt(crm[2].replace(/,/g, ''));
      out.country_rank_country = crm[1].trim();
    }
  } else {
    out.country_rank = parseInt(crm[1].replace(/,/g, ''));
    out.country_rank_country = crm[2].trim();
  }

  // Category Rank or Industry rank (trial 用 Industry rank)
  const catRm = text.match(/(?:Category|Industry)\s+[Rr]ank\s*\n+(?:[^#\n]*\n+)?\s*#\s*(\d[\d,]*)/);
  if (catRm) out.category_rank = parseInt(catRm[1].replace(/,/g, ''));

  // ---- 6. Top Countries -------------------------------------
  // 三种布局：
  //   (a) anonymous list: "Top Countries\nBrazil\n14.89%\n6.62%\nUnited States\n10.04%\n..."
  //   (b) trial columnar: "Top Countries\n...\nCountry\nTurkey\nThailand\n...\nTraffic Share\n9.82%\n8.39%\n..."
  // 先试 (a)，再 fallback 到 (b)
  const tcIdx = text.indexOf('Top Countries');
  if (tcIdx >= 0) {
    let tcBlock = text.slice(tcIdx, tcIdx + 2000);
    for (const stop of ['See all countries', 'See more countries', 'Demographics', 'Audience',
                         'Marketing Channels', 'Outgoing']) {
      const i = tcBlock.indexOf(stop);
      if (i > 0) { tcBlock = tcBlock.slice(0, i); break; }
    }

    // 布局 (a)：name \n pct% 交替
    const cre = /\n\s*([A-Z][A-Za-z .'-]{2,40})\s*\n\s*([\d.]+)\s*%/g;
    const countries_a = [];
    let cm;
    while ((cm = cre.exec(tcBlock)) && countries_a.length < 5) {
      const name = cm[1].trim();
      if (/^(Others|Top Countries|Country|Share|Change|Traffic Share|All traffic)$/i.test(name)) continue;
      countries_a.push({ country: name, share: parsePct(cm[2]) });
    }

    // 布局 (b)：先 N 个 name，然后 "Traffic Share"，然后 N 个 %
    const colMatch = tcBlock.match(
      /Country\s*\n([\s\S]+?)\nTraffic Share\s*\n([\s\S]+?)(?:\nChange|\n$)/
    );
    let countries_b = [];
    if (colMatch) {
      const names = colMatch[1].split('\n').map(s => s.trim()).filter(s => s && !/^(Others)$/i.test(s));
      const pcts = colMatch[2].match(/[\d.]+\s*%/g) || [];
      for (let i = 0; i < Math.min(names.length, pcts.length, 5); i++) {
        countries_b.push({ country: names[i], share: parsePct(pcts[i]) });
      }
    }

    // 选 captures 多的那个
    const countries = countries_b.length > countries_a.length ? countries_b : countries_a;
    if (countries.length) out.top_countries = countries;
  }

  // ---- 7. Demographics — 年龄 / 性别（anonymous 也有）-------
  // "Age Distribution\n22.44%\n30.16%\n20.78%\n13.09%\n8.69%\n4.84%\n
  //  18 - 24\n25 - 34\n35 - 44\n45 - 54\n55 - 64\n65+"
  // OR "Gender Distribution\nFemale\n23.59%\nMale\n76.41%"
  const fm = text.match(/Female\s*\n\s*([\d.]+)\s*%/);
  const mm2 = text.match(/Male\s*\n\s*([\d.]+)\s*%/);
  if (fm) out.female_share = parsePct(fm[1]);
  if (mm2) out.male_share = parsePct(mm2[1]);

  // ---- 8. Similar sites（anonymous 顶部 5–10 个）-----------
  const ssIdx = text.indexOf('Competitors & Similar Sites');
  if (ssIdx >= 0) {
    let ssBlock = text.slice(ssIdx, ssIdx + 3000);
    const stopAt = ssBlock.indexOf('See all competitors');
    if (stopAt > 0) ssBlock = ssBlock.slice(0, stopAt);
    // 抓 "<domain>.com\n<pct>%\nSports > ..." pattern
    const sre = /\n([a-z0-9][\w-]+(?:\.[a-z]{2,})+)\s*\n\s*([\d.]+)\s*%/gi;
    const similar = [];
    let sm;
    while ((sm = sre.exec(ssBlock)) && similar.length < 10) {
      similar.push({ domain: sm[1].toLowerCase(), affinity: parsePct(sm[2]) });
    }
    if (similar.length) out.similar_sites = similar;
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


_SAFE_BODY_TEXT_JS = (
    "() => { const e = document.querySelector('main') || document.body; "
    "return e ? (e.innerText || '') : ''; }"
)


async def _wait_overview_ready(page, timeout_s: int = PAGE_TIMEOUT_SEC) -> None:
    """等到核心 label 在页面文本里出现 — 比 body_len 阈值更可靠。"""
    REQUIRED_MARKERS = ["Total Visits", "Bounce Rate", "Monthly visits"]
    loop = asyncio.get_event_loop()
    deadline = loop.time() + timeout_s
    banner_dismissed = False
    while loop.time() < deadline:
        try:
            if await _detect_cloudflare(page):
                raise CloudflareBlocked("Similarweb 被 Cloudflare 拦截")
            if not banner_dismissed:
                await _dismiss_banners(page)
                banner_dismissed = True
            body_text = await page.evaluate(_SAFE_BODY_TEXT_JS)
        except CloudflareBlocked:
            raise
        except Exception:
            # 页面正在导航 / DOM 未稳定 → 重试
            body_text = ""
        if any(m in body_text for m in REQUIRED_MARKERS) and len(body_text) > 1500:
            return
        await asyncio.sleep(1.0)
    # 超时 — 记录调试信息
    try:
        body_text = await page.evaluate(_SAFE_BODY_TEXT_JS)
    except Exception:
        body_text = ""
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


async def _fetch_domain(page, domain: str, anonymous: bool = False) -> dict:
    url = f"https://www.similarweb.com/website/{domain}/"
    print(f"[{domain}] {url}")
    await page.goto(url, wait_until="domcontentloaded")
    # anonymous 第一次访问 CF 挑战要给充裕时间人工过
    timeout_s = 240 if anonymous else PAGE_TIMEOUT_SEC
    if anonymous:
        print(f"  [anonymous] 等最多 {timeout_s}s 让你手动过 CF challenge…")
    await _wait_overview_ready(page, timeout_s=timeout_s)
    # SPA 异步刷数据，多等几秒
    await asyncio.sleep(3)
    data = await page.evaluate(EXTRACT_JS)
    if data.get("error"):
        return data
    print(
        f"  -> visits={data.get('monthly_visits')}  dur={data.get('avg_visit_duration')}"
        f"  bounce={data.get('bounce_rate')}  ranks=G#{data.get('global_rank')}"
        f"/C#{data.get('country_rank')}/cat#{data.get('category_rank')}"
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


async def cmd_scrape(
    headed: bool = False,
    only_domain: str | None = None,
    anonymous: bool = False,
) -> Path:
    """正常 scrape 走 PROFILE_DIR；anonymous 走全新无痕 context（用于测真免费字段集）。"""
    if not anonymous and not PROFILE_DIR.exists():
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

    if anonymous:
        print("🕵️  ANONYMOUS 模式：不带任何账号 / 历史 cookie，验证真免费字段集")
        print("    （会强制 headed 模式让你手过 CF；本次结果不写 MySQL）")

    async with async_playwright() as p:
        # 通用 launch 参数
        common_args = dict(
            channel="chrome",
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
        if anonymous:
            # 全新无 profile context（不会带账号 cookie）
            browser = await p.chromium.launch(headless=False, **{
                k: v for k, v in common_args.items()
                if k in ("channel", "args")
            })
            ctx = await browser.new_context(
                viewport=common_args["viewport"],
                user_agent=common_args["user_agent"],
                locale=common_args["locale"],
            )
        else:
            ctx = await p.chromium.launch_persistent_context(
                str(PROFILE_DIR),
                headless=not headed,
                **common_args,
            )
        page = ctx.pages[0] if ctx.pages else await ctx.new_page()
        try:
            for app_name, domain in websites.items():
                try:
                    data = await _fetch_domain(page, domain, anonymous=anonymous)
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

                # 写 MySQL（anonymous 模式跳过，避免污染正常数据）
                if not anonymous and not data.get("error"):
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

    # 写 JSON 主输出（anonymous 走单独的 _anon 文件以免覆盖正常数据）
    out_path = DATA_OUT if not anonymous else DATA_OUT.with_name("async_similarweb_anon.json")
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(results, ensure_ascii=False, indent=2), encoding="utf-8")
    ok = sum(1 for r in results if not (r.get("data") or {}).get("error"))
    print(f"\n保存完成 -> {out_path}（{len(results)} record，{ok} 条有数据）")

    # 写 markdown 快照（anonymous 用单独文件名）
    RAW_OUT_DIR.mkdir(parents=True, exist_ok=True)
    md_suffix = "_anon" if anonymous else ""
    md_path = RAW_OUT_DIR / f"similarweb{md_suffix}_{today.isoformat()}.md"
    md_path.write_text("\n".join(md_sections), encoding="utf-8")
    print(f"markdown 快照 -> {md_path}")

    return out_path


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
        f"- **Ranks**: Global #{data.get('global_rank') or '—'}"
        f" · Country #{data.get('country_rank') or '—'} ({data.get('country_rank_country') or '—'})"
        f" · Category #{data.get('category_rank') or '—'}",
        "",
    ]
    if data.get("male_share") is not None or data.get("female_share") is not None:
        lines.append(
            f"- **Demographics**: Male {_fmt_pct(data.get('male_share'))}"
            f" · Female {_fmt_pct(data.get('female_share'))}"
        )
        lines.append("")
    cs = data.get("top_countries") or []
    if cs:
        lines.append("**Top Countries**:")
        for c in cs[:5]:
            lines.append(f"  - {c.get('country')} — {_fmt_pct(c.get('share'))}")
        lines.append("")
    ss = data.get("similar_sites") or []
    if ss:
        lines.append("**Similar Sites**:")
        for s in ss[:10]:
            lines.append(f"  - {s.get('domain')} — affinity {_fmt_pct(s.get('affinity'))}")
        lines.append("")
    return "\n".join(lines)


# ---- main ----------------------------------------------------------------


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("command", choices=["login", "scrape"], nargs="?", default="scrape")
    ap.add_argument("--headed", action="store_true")
    ap.add_argument("--domain", help="仅抓指定域名（smoke test 用）")
    ap.add_argument("--anonymous", action="store_true",
                    help="不带任何账号 / cookie，验证真免费字段集（结果不入 MySQL）")
    args = ap.parse_args()

    if args.command == "login":
        asyncio.run(cmd_login())
    else:
        try:
            asyncio.run(cmd_scrape(
                headed=args.headed,
                only_domain=args.domain,
                anonymous=args.anonymous,
            ))
        except CloudflareBlocked as e:
            print(f"❌ {e}", file=sys.stderr)
            sys.exit(2)


if __name__ == "__main__":
    main()
