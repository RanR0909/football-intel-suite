#!/usr/bin/env python3
"""AppMagic Sports News chart scraper（合并自仓库根目录的原型脚本）。

CLI:
    python3 -m market_rank.scrape_appmagic login          # 弹浏览器手动登录（一次）
    python3 -m market_rank.scrape_appmagic                # 抓取（默认）
    python3 -m market_rank.scrape_appmagic --headed       # 调试时显示浏览器

输出：appmagic_output/sports_news_<TS>.json （写法与原型脚本一致，便于离线复盘）
"""

from __future__ import annotations

import argparse
import asyncio
import json
import re
import sys
from datetime import datetime
from pathlib import Path

from playwright.async_api import async_playwright

# ---- 常量 -----------------------------------------------------------------
TAG_ID = 243526  # AppMagic Sports News
TAG_NAME = "Sports News"
PROFILE_DIR = Path.home() / ".appmagic-profile"
_SCRIPT_DIR = Path(__file__).resolve().parent
_PROJECT_ROOT = _SCRIPT_DIR.parent
OUTPUT_DIR = _PROJECT_ROOT / "appmagic_output"

# 加载 .env.local + ~/.intelops-secrets
import sys
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))
try:
    from shared.env_loader import load_all as _load_env_all
    _load_env_all()
except Exception:
    pass

COUNTRIES = [
    ("US", "United States"),
    ("NG", "Nigeria"),
    ("MY", "Malaysia"),
    ("ID", "Indonesia"),
    ("SA", "Saudi Arabia"),
    ("AE", "United Arab Emirates"),
    ("JP", "Japan"),
    ("CA", "Canada"),
    ("VN", "Vietnam"),
    ("GB", "United Kingdom"),
    ("BR", "Brazil"),
    ("RU", "Russia"),
]

# 跟踪应用 token（lowercase，无空格无符号）— 与 data/competitors.json 的 9 个竞品对应
TRACKED_APPS = [
    "onefootball",
    "fotmob",
    "sofascore",
    "flashscore",
    "aiscore",
    "besoccer",
    "livescore",
    "365score",
    "310score",
]


# ---- 工具 -----------------------------------------------------------------
def app_token(name: str) -> str:
    """提取应用名首段并归一化：'FotMob - Soccer Live Scores' -> 'fotmob'。"""
    if not name:
        return ""
    chunk = re.split(r"[:\-\s]", name, maxsplit=1)[0]
    return re.sub(r"[^a-z0-9]", "", chunk.lower())


def match_tracked(name: str) -> str | None:
    """匹配规则：token 必须等于 key 或以 key 起头（避免 'Live xxx' 假阳性匹配到 livescore）。

    保留 token.startswith(key) 是为了让 '365Scores' (token=365scores) 匹配到 key='365score'。
    去掉 key.startswith(token) 那个方向（之前会让 token='live' 匹配到 'livescore'）。
    """
    token = app_token(name)
    if not token:
        return None
    # 至少 4 字符的 token 才参与前缀匹配，避免 token='3' 匹配 '365score'
    if len(token) < 4:
        return None
    for key in TRACKED_APPS:
        if token == key or token.startswith(key):
            return key
    return None


def pick_tracked(items: list[dict]) -> list[dict]:
    out = []
    for it in items:
        key = match_tracked(it.get("name", ""))
        if key:
            out.append({"app_key": key, **it})
    return out


# ---- DOM 解析（AppMagic 内嵌 web component）-------------------------------
EXTRACT_JS = r"""
() => {
  const cols = document.querySelectorAll('div.col');
  const firstCol = Array.from(cols).find(c => c.querySelectorAll('top-apps-item').length > 0);
  if (!firstCol) return [];
  const items = Array.from(firstCol.querySelectorAll('top-apps-item'));
  return items.map((el, idx) => {
    const text = (el.innerText || '').trim();
    const lines = text.split('\n').map(s => s.trim()).filter(Boolean);
    const expected = String(idx + 1);
    const rankIdx = lines.findIndex(l => l === expected);
    let delta = null, name = '', publisher = '', downloads = null;
    if (rankIdx > 0) delta = lines.slice(0, rankIdx).join(' ') || null;
    if (rankIdx >= 0) {
      name = lines[rankIdx + 1] || '';
      publisher = lines[rankIdx + 2] || '';
      const dl = lines[rankIdx + 3];
      if (dl && /^[~>$\d]/.test(dl)) downloads = dl;
    } else {
      name = lines[0] || '';
      publisher = lines[1] || '';
    }
    return { rank: idx + 1, delta, name, publisher, downloads };
  });
}
"""


# ---- 登录态检测 -----------------------------------------------------------
class LoginRequired(RuntimeError):
    """当前登录态失效或不存在；需要 user 重跑 `login` 命令。"""


async def _detect_login_required(page) -> bool:
    """检测页面是否被重定向到登录或要求登录。AppMagic 未登录时会跳到 /sign-in 或显示登录 modal。"""
    cur = page.url or ""
    if "sign-in" in cur or "login" in cur or "/auth" in cur:
        return True
    # 检查页面有无 "sign in" / "log in" 按钮且无 chart 区
    try:
        body_html = await page.evaluate(
            "() => document.body && document.body.innerHTML.length || 0"
        )
        has_signin = await page.evaluate(
            "() => !!document.querySelector('a[href*=\"sign-in\"], button:has-text(\"Sign in\")')"
        )
        has_chart = await page.evaluate(
            "() => document.querySelectorAll('top-apps-item').length > 0"
        )
        return bool(has_signin and not has_chart and body_html > 1000)
    except Exception:
        return False


async def wait_chart_ready(page, timeout_s: int = 30, min_items: int = 50) -> int:
    """等到 top-apps-item 数量稳定。登录态失效时抛 LoginRequired。"""
    loop = asyncio.get_event_loop()
    deadline = loop.time() + timeout_s
    last = -1
    stable = 0
    while loop.time() < deadline:
        # 早期登录检测
        if await _detect_login_required(page):
            raise LoginRequired("AppMagic 未登录或登录态已过期")
        count = await page.evaluate(
            "() => document.querySelectorAll('top-apps-item').length"
        )
        if count >= min_items and count == last:
            stable += 1
            if stable >= 3:
                return count
        else:
            stable = 0
            last = count
        await asyncio.sleep(0.5)
    # 超时再做一次登录检测兜底
    if await _detect_login_required(page):
        raise LoginRequired("AppMagic 未登录或登录态已过期（chart 加载超时）")
    raise TimeoutError(f"chart 未在 {timeout_s}s 内加载稳定（最后数量 {last}）")


async def fetch_chart(page, url: str, drop_downloads: bool = False) -> list[dict]:
    await page.goto(url, wait_until="domcontentloaded")
    await wait_chart_ready(page)
    items = await page.evaluate(EXTRACT_JS)
    if drop_downloads:
        for it in items:
            it.pop("downloads", None)
    return items


# ---- 命令：login ---------------------------------------------------------
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
        await page.goto("https://appmagic.rocks/top-charts/apps")
        print("浏览器已打开。手动完成登录，登录成功后关闭窗口即可。")
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
    print(f"登录态已保存到：{PROFILE_DIR}")


# ---- 命令：scrape -------------------------------------------------------
async def cmd_scrape(headed: bool = False) -> Path:
    if not PROFILE_DIR.exists():
        raise LoginRequired(
            f"找不到登录态目录 {PROFILE_DIR}。请运行：\n"
            f"  python3 -m market_rank.scrape_appmagic login"
        )
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    result = {
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "tag_id": TAG_ID,
        "tag_name": TAG_NAME,
        "tracked_apps": list(TRACKED_APPS),
        "worldwide": {"all": [], "tracked": []},
        "countries": {},
    }

    async with async_playwright() as p:
        ctx = await p.chromium.launch_persistent_context(
            str(PROFILE_DIR),
            headless=not headed,
            viewport={"width": 1400, "height": 900},
            args=["--disable-blink-features=AutomationControlled"],
        )
        page = ctx.pages[0] if ctx.pages else await ctx.new_page()

        try:
            # 全球榜（含 downloads）
            url = f"https://appmagic.rocks/top-charts/apps?tag={TAG_ID}"
            print("[worldwide] 抓取中...")
            ww_items = await fetch_chart(page, url, drop_downloads=False)
            ww_tracked = pick_tracked(ww_items)
            result["worldwide"]["all"] = ww_items
            result["worldwide"]["tracked"] = ww_tracked
            print(f"  -> 全部 {len(ww_items)} 条；命中 {len(ww_tracked)} 个目标 App")

            # 分国榜
            for code, country_name in COUNTRIES:
                url = f"https://appmagic.rocks/top-charts/apps?tag={TAG_ID}&country={code}"
                print(f"[{code}] {country_name} 抓取中...")
                try:
                    items = await fetch_chart(page, url, drop_downloads=True)
                    tracked = pick_tracked(items)
                    result["countries"][code] = {
                        "name": country_name,
                        "all": items,
                        "tracked": tracked,
                    }
                    print(f"  -> 全部 {len(items)} 条；命中 {len(tracked)} 个目标 App")
                except LoginRequired:
                    raise  # 登录失效 → 立即终止，由上层处理
                except Exception as e:
                    print(f"  ERROR: {e}", file=sys.stderr)
                    result["countries"][code] = {
                        "name": country_name,
                        "all": [],
                        "tracked": [],
                        "error": str(e),
                    }
                await asyncio.sleep(2)
        finally:
            try:
                await ctx.close()
            except Exception:
                pass

    fname = f"sports_news_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"
    out_path = OUTPUT_DIR / fname
    out_path.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"\n保存完成 -> {out_path}")
    return out_path


def main() -> None:
    parser = argparse.ArgumentParser(description="AppMagic Sports News chart scraper")
    parser.add_argument(
        "command",
        choices=["login", "scrape"],
        nargs="?",
        default="scrape",
        help="login: 手动登录；scrape: 抓取（默认）",
    )
    parser.add_argument("--headed", action="store_true", help="抓取时显示浏览器")
    args = parser.parse_args()

    if args.command == "login":
        asyncio.run(cmd_login())
    else:
        try:
            asyncio.run(cmd_scrape(headed=args.headed))
        except LoginRequired as e:
            print(f"❌ {e}", file=sys.stderr)
            print(
                "   请运行：python3 -m market_rank.scrape_appmagic login",
                file=sys.stderr,
            )
            sys.exit(2)  # 与一般错误（exit 1）区分


if __name__ == "__main__":
    main()
