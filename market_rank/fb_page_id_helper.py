#!/usr/bin/env python3
"""交互式 helper — 帮你手填 fb_page_id 到 competitors.json。

discover-pages 自动模式（Meta advertiser search + DOM 反查）已确认失败：
- FB 反爬强；headed/headless 都 0 候选
- Graph API 需要 access token
- 直接 curl FB Page HTML 也被 redirect 到登录

最终最稳的方法：人手在浏览器里点一下，复制 URL 数字。本脚本辅助：
  · 给每个竞品打印搜索 URL（你 Cmd+Click 或复制到浏览器）
  · 你看到 advertiser 卡片 → 点进 → URL 含 view_all_page_id=N
  · 把 N（或整个 URL）粘到终端 → 自动 parse + 写回 JSON
  · 留空跳过该竞品
  · 已有 fb_page_id 的自动跳过

10 竞品 × 30 秒 ≈ 5 分钟。
"""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path
from urllib.parse import quote

_PROJECT_ROOT = Path(__file__).resolve().parent.parent
JSON_PATH = _PROJECT_ROOT / "data" / "competitors.json"


def _parse_page_id(s: str) -> str | None:
    """从用户输入抽 page_id：支持纯数字 / view_all_page_id= URL / id= URL。"""
    s = (s or "").strip()
    if not s:
        return None
    # 纯数字
    if s.isdigit() and len(s) >= 8:
        return s
    # view_all_page_id=
    m = re.search(r"view_all_page_id=(\d{8,})", s)
    if m:
        return m.group(1)
    # /profile.php?id=
    m = re.search(r"[?&]id=(\d{8,})", s)
    if m:
        return m.group(1)
    return None


def main() -> int:
    if not JSON_PATH.exists():
        print(f"❌ {JSON_PATH} 不存在", file=sys.stderr)
        return 1
    raw = json.loads(JSON_PATH.read_text(encoding="utf-8"))
    apps = raw.get("competitors") if isinstance(raw, dict) and "competitors" in raw else raw
    if not isinstance(apps, dict):
        print(f"❌ {JSON_PATH} 顶层不是 dict", file=sys.stderr)
        return 1

    print("=" * 64)
    print(" FB Page ID 手填工具")
    print("=" * 64)
    print()
    print("流程：")
    print("  1. 复制下面的 URL 到浏览器")
    print("  2. 在 advertiser pages 列表里找到该竞品 → 点击进入")
    print("  3. 复制新页面的 URL 整段（含 view_all_page_id=N）粘到终端")
    print("     （也可以只输 page_id 数字）")
    print("  4. 留空 [Enter] = 跳过该竞品")
    print()

    updates: dict[str, str] = {}
    skipped: list[str] = []
    for app_name, comp in apps.items():
        existing = comp.get("fb_page_id")
        if existing:
            print(f"[{app_name}] 已有 fb_page_id={existing}，跳过")
            continue
        # 构造 URL — search_type=page 是 advertiser search
        url = (
            "https://www.facebook.com/ads/library/"
            f"?active_status=all&country=ALL&q={quote(app_name)}&search_type=page"
        )
        print()
        print(f"━━━ [{app_name}] ━━━")
        print(f"  Cmd+Click → {url}")
        try:
            raw_input_str = input(f"  page_id 或 URL（[Enter] 跳过）: ")
        except (EOFError, KeyboardInterrupt):
            print("\n中断，已收集的待写回保留")
            break
        page_id = _parse_page_id(raw_input_str)
        if not page_id:
            print(f"  ⏭  跳过（输入未识别 / 留空）")
            skipped.append(app_name)
            continue
        updates[app_name] = page_id
        print(f"  ✓ {app_name} → page_id={page_id}")

    if not updates:
        print(f"\n没有要更新的（全跳过 / 全已有）。")
        return 0

    print()
    print("=" * 64)
    print(f" 将写入 {len(updates)} 个 page_id 到 {JSON_PATH}:")
    print("=" * 64)
    for name, pid in updates.items():
        print(f"  {name:<14} → {pid}")
    if skipped:
        print(f"\n跳过 ({len(skipped)} 个，下次可重跑补): {skipped}")
    print()
    confirm = input("确认写入？ [y/N]: ").strip().lower()
    if confirm != "y":
        print("取消，未写入")
        return 0

    for name, pid in updates.items():
        if "competitors" in raw and isinstance(raw["competitors"], dict):
            raw["competitors"][name]["fb_page_id"] = pid
        else:
            raw[name]["fb_page_id"] = pid
    JSON_PATH.write_text(
        json.dumps(raw, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    print(f"✓ 已写回 {JSON_PATH}")
    print()
    print("下一步：")
    print("  # 清旧脏数据")
    print("  python3 -c \"import sys; sys.path.insert(0,'.'); "
          "from shared import env_loader; env_loader.load_all(); "
          "from shared import db; from sqlalchemy import text; "
          "s = db.session().__enter__(); s.execute(text('DELETE FROM ad_creatives')); "
          "print('cleared')\"")
    print("  # 重抓 — 这次走 page_id 精确匹配")
    print("  python3 -m market_rank.scrape_fb_adlib scrape")
    return 0


if __name__ == "__main__":
    sys.exit(main())
