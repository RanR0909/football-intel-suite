"""iTunes Lookup → app_versions 表（spec: 后端协作清单 §3.2）

每个 tracked competitor + baseline 调 iTunes Lookup API，拿：
  - version                         → app_versions.version
  - releaseNotes                    → app_versions.release_notes
  - currentVersionReleaseDate (ISO) → app_versions.released_at

按 (competitor_id, platform='ios', version) UPSERT。同一版本多次抓不会重复 INSERT，
但 releaseNotes 若空白则不覆盖已有内容（DAO upsert_version 内部已保护）。

bundle_id / gp 包名 / Android release notes 暂不抓 — Google Play 没有公开 lookup API，
后续可加 Play Store HTML 解析。

iTunes Lookup endpoint:
  https://itunes.apple.com/lookup?id={app_id}&country=us
"""
from __future__ import annotations

import sys
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

from async_crawler.base import BaseCrawler
from async_crawler import db
from competitors import load_competitors


def _parse_release_date(s: str | None) -> datetime | None:
    """iTunes 返回 ISO 8601 字符串如 '2025-04-15T08:00:00Z'。"""
    if not s:
        return None
    try:
        return datetime.fromisoformat(s.replace("Z", "+00:00"))
    except Exception:
        return None


class AppVersionsCrawler(BaseCrawler):
    source_name = "app_versions"
    rate_limit = 1.0

    async def crawl(self, database) -> list[dict]:
        all_apps = load_competitors()
        rows = []
        records_for_json = []

        for name, entry in all_apps.items():
            ios_id = entry.get("ios")
            if not ios_id:
                self.log.info(f"[{name}] 跳过（无 ios app id）")
                continue

            url = f"https://itunes.apple.com/lookup?id={ios_id}&country=us"
            self.log.info(f"[{name}] iTunes Lookup id={ios_id}...")
            try:
                data = await self.fetch_json(url)
            except Exception as e:
                self.log.warning(f"[{name}] lookup 失败: {e}")
                continue

            results = data.get("results") or []
            if not results:
                self.log.info(f"[{name}] 无结果（可能 app 下架）")
                continue
            r = results[0]

            version = (r.get("version") or "").strip()
            release_notes = r.get("releaseNotes") or ""
            released_at = _parse_release_date(r.get("currentVersionReleaseDate"))
            track_name = r.get("trackName") or ""

            if not version:
                self.log.warning(f"[{name}] iTunes 返回无 version 字段")
                continue

            rec = {
                "competitor": name,
                "platform": "ios",
                "version": version,
                "release_notes": release_notes,
                "released_at": released_at.isoformat() if released_at else None,
                "track_name": track_name,
                "ios_app_id": ios_id,
            }
            records_for_json.append(self.standardize(name, rec))

            rows.append({
                "competitor_name": name,
                "platform": "ios",
                "version": version,
                "release_notes": release_notes,
                "release_notes_lang": None,   # iTunes 不返回语言 — AI 检测时再回写
                "released_at": released_at,
            })

        # JSON 主路径
        if records_for_json:
            await database.save(self.source_name, records_for_json)

        # DB upsert（铁律 1：DB 失败不影响 JSON）
        if rows:
            try:
                from shared.dao import app_versions as dao_versions
                inserted = 0
                for r in rows:
                    if dao_versions.upsert_version(**r) is not None:
                        inserted += 1
                self.log.info(f"[app_versions] DB upsert {inserted}/{len(rows)}")
            except Exception as e:
                self.log.warning(f"[app_versions] DB upsert failed (JSON 仍可用): {e}")

        return records_for_json


async def crawl(session, database) -> list[dict]:
    return await AppVersionsCrawler(session).crawl(database)
