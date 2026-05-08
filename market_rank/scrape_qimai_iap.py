#!/usr/bin/env python3
"""qimai.cn IAP 抓取 — 替代废掉的 Apple HTML 直抓（被 IP redirect 卡死）。

为什么换：从中国 IP 直接请求 apps.apple.com/<region>/app/... 全部被 Apple 强制
redirect 到 storefront=cn 的 Today 推荐页（不是真实 app 详情），抓不到 IAP。
qimai.cn 是国内成熟的 App Store 数据中转，已经替我们抓好了 IAP，登录一次即可。

CLI:
    python3 -m market_rank.scrape_qimai_iap login    # 一次性手动登录 qimai 免费账号
    python3 -m market_rank.scrape_qimai_iap scrape   # 抓取所有 10 竞品（默认）
    python3 -m market_rank.scrape_qimai_iap --headed # 调试时显示浏览器

输出：
- data/async_iap_pricing.json — 与 async_crawler/sources/iap_pricing.py 同 shape，
  下游 DAO 通用
- MySQL iap_items 表

数据来源：qimai 内购列表写在页面 Vue 组件 historyData = [[price, title], ...]
"""

from __future__ import annotations

import argparse
import asyncio
import json
import logging
import sys
from datetime import datetime, timezone
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

from competitors import load_competitors  # type: ignore
from shared.dao import iap as dao_iap  # type: ignore

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger("scrape_qimai_iap")

# 持久状态：与其它 Playwright scraper 风格一致，放在 ~/.qimai-profile/
STATE_DIR = Path.home() / ".qimai-profile"
STATE_FILE = STATE_DIR / "state.json"

DATA_OUT = _PROJECT_ROOT / "data" / "async_iap_pricing.json"
RAW_OUT = _PROJECT_ROOT / "data" / "raw" / "iap_pricing.json"

QIMAI_URL = "https://www.qimai.cn/app/baseinfo/appid/{appid}/country/{country}"
# 默认抓美区 — 价格 USD，对全球订阅定价的参考意义最强
# (历史曾用 cn，2026-05 改为 us 因 cn 价格 CNY 单一区参考价值低)
DEFAULT_COUNTRY = "us"

# Vue historyData 提取（来源：qimai_iap_scraper/qimai_iap.py）
EXTRACT_JS = r"""
() => new Promise((resolve) => {
  const start = Date.now();
  const TIMEOUT = 20000;
  function findInVue(root) {
    let found = null;
    (function walk(c, depth) {
      if (depth > 40 || !c || found) return;
      const data = c._data || c.$data;
      if (data && Array.isArray(data.historyData) && data.historyData.length) {
        const sample = data.historyData[0];
        if (Array.isArray(sample) && sample.length === 2) {
          found = data.historyData;
          return;
        }
      }
      if (c.$children) c.$children.forEach((ch) => walk(ch, depth + 1));
    })(root, 0);
    return found;
  }
  const tick = () => {
    const root = document.querySelector('#app') && document.querySelector('#app').__vue__;
    if (root) {
      const data = findInVue(root);
      if (data) return resolve({ ok: true, data });
    }
    if (Date.now() - start > TIMEOUT) return resolve({ ok: false, reason: 'timeout' });
    setTimeout(tick, 250);
  };
  tick();
});
"""


def _parse_price_num(price_str: str) -> float | None:
    """'¥28.00' → 28.0；'30元' → 30.0；'免费' / 空 → None"""
    import re
    if not price_str:
        return None
    m = re.search(r"([\d]+(?:[.,]\d+)?)", price_str)
    if not m:
        return None
    try:
        return float(m.group(1).replace(",", "."))
    except ValueError:
        return None


def _detect_currency(price_str: str) -> str:
    if not price_str:
        return ""
    if "¥" in price_str or "￥" in price_str or "元" in price_str:
        return "CNY"
    if "$" in price_str:
        return "USD"
    if "€" in price_str:
        return "EUR"
    if "£" in price_str:
        return "GBP"
    return ""


async def fetch_iap_for_app(page, app_id: int, country: str) -> list[dict]:
    """抓单个 app 的 IAP 列表。返回 [{name, price, price_num, currency, category}]。"""
    url = QIMAI_URL.format(appid=app_id, country=country)
    await page.goto(url, wait_until="domcontentloaded", timeout=45000)
    try:
        await page.wait_for_load_state("networkidle", timeout=15000)
    except Exception:
        pass

    result = await page.evaluate(EXTRACT_JS)
    if not result or not result.get("ok"):
        return []

    iaps = []
    for entry in result["data"]:
        if not isinstance(entry, list) or len(entry) < 2:
            continue
        price_str, name = entry[0], entry[1]
        if not name:
            continue
        iaps.append({
            "name": str(name)[:120],
            "price": str(price_str)[:60],
            "price_num": _parse_price_num(str(price_str)),
            "currency": _detect_currency(str(price_str)),
            "category": "iap",
        })
    return iaps


async def login_flow():
    """开 headed Chrome（用系统 Chrome 不是 chromium），手动登录后保存 storage_state。

    qimai 反爬会检测 Playwright/chromium 指纹（导致 SPA 弹 /404），所以：
    - 用系统 Chrome（channel='chrome'）而非 bundled chromium
    - 关 AutomationControlled blink feature
    - 设 user-agent 为正常 Chrome
    """
    STATE_DIR.mkdir(parents=True, exist_ok=True)
    async with async_playwright() as pw:
        browser = await pw.chromium.launch(
            channel="chrome",  # 用系统 Chrome，比 chromium 更不容易被反爬识别
            headless=False,
            args=["--disable-blink-features=AutomationControlled"],
        )
        ctx = await browser.new_context(
            locale="zh-CN",
            user_agent=(
                "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/138.0.0.0 Safari/537.36"
            ),
            viewport={"width": 1400, "height": 900},
        )
        page = await ctx.new_page()
        await page.goto("https://www.qimai.cn/")
        print(
            "\n浏览器已打开。\n"
            "  1. 在 qimai.cn 首页右上角找「登录」按钮\n"
            "  2. 用账号/微信/手机号登录\n"
            "  3. 看到自己的头像/昵称就说明登录成功\n"
            "  4. 回到这个终端按 Enter（保存 cookie）\n"
            "\n注意：不要在弹窗里乱点链接（点错跳到详情页会被反爬弹 /404，登录前那是正常的）。",
            file=sys.stderr,
        )
        await asyncio.get_event_loop().run_in_executor(None, sys.stdin.readline)
        await ctx.storage_state(path=str(STATE_FILE))
        print(f"✓ 登录态已保存到 {STATE_FILE}", file=sys.stderr)
        await browser.close()


async def scrape(headed: bool = False, country: str = DEFAULT_COUNTRY) -> int:
    if not STATE_FILE.exists():
        log.error(f"未登录。先跑：python3 -m market_rank.scrape_qimai_iap login")
        return 2

    competitors = load_competitors()
    targets = [(name, int(entry["ios"])) for name, entry in competitors.items() if entry.get("ios")]
    log.info(f"抓取 {len(targets)} 个 app，country={country}")

    results = []
    total_db = 0
    failed = []
    async with async_playwright() as pw:
        # 抓取也走系统 Chrome + 关 AutomationControlled，与 login 一致避免反爬
        browser = await pw.chromium.launch(
            channel="chrome",
            headless=not headed,
            args=["--disable-blink-features=AutomationControlled"],
        )
        ctx = await browser.new_context(
            storage_state=str(STATE_FILE),
            user_agent=(
                "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/138.0.0.0 Safari/537.36"
            ),
            locale="zh-CN",
            viewport={"width": 1400, "height": 900},
        )
        page = await ctx.new_page()

        for i, (name, app_id) in enumerate(targets):
            log.info(f"[{i+1}/{len(targets)}] {name} (ios={app_id})")
            try:
                iaps = await fetch_iap_for_app(page, app_id, country)
            except Exception as e:
                log.warning(f"  ✗ {name} 抓取异常: {e}")
                failed.append(f"{name}:{e}")
                iaps = []

            rec = {
                "timestamp": datetime.now(timezone.utc).isoformat(),
                "source": "iap_pricing",
                "competitor": name,
                "region": country,
                "data": {"iap_count": len(iaps), "iaps": iaps},
            }
            results.append(rec)

            if iaps:
                n = dao_iap.bulk_insert_iap(name, country, iaps)
                total_db += n
                log.info(f"  ✓ {len(iaps)} 条 IAP，写入 MySQL {n} 行")
            else:
                log.info(f"  · 无 IAP 列表")

        await browser.close()

    DATA_OUT.parent.mkdir(parents=True, exist_ok=True)
    DATA_OUT.write_text(json.dumps(results, ensure_ascii=False, indent=2), encoding="utf-8")
    RAW_OUT.parent.mkdir(parents=True, exist_ok=True)
    RAW_OUT.write_text(json.dumps(results, ensure_ascii=False, indent=2), encoding="utf-8")

    log.info(f"完成：{len(results)} app，MySQL 写入 {total_db} IAP 条目，失败 {len(failed)}")
    if failed:
        log.warning(f"失败详情: {failed}")
    return 0 if total_db > 0 else 1


def main():
    p = argparse.ArgumentParser()
    p.add_argument("command", nargs="?", default="scrape", choices=["login", "scrape"])
    p.add_argument("--headed", action="store_true", help="抓取时显示浏览器（调试）")
    p.add_argument("--country", default=DEFAULT_COUNTRY, help="qimai country 参数（默认 us）")
    args = p.parse_args()
    if args.command == "login":
        asyncio.run(login_flow())
        return 0
    return asyncio.run(scrape(headed=args.headed, country=args.country))


if __name__ == "__main__":
    sys.exit(main())
