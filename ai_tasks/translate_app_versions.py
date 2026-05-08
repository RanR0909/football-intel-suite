"""任务 10 — app_versions.release_notes (英/葡/西/etc) → 中文。

产品动态页 (/content/releases) 展开版本时显示完整中文翻译。
迁移 0015 时 schema 早就有 release_notes_translated_zh 字段但从未填过。

调用:
    from ai_tasks.translate_app_versions import translate_one, translate_pending
    translate_pending(limit=50)

存储: 写回 app_versions.release_notes_translated_zh + translated_at
      （dao.app_versions.update_translation）

铁律 4: fetch_untranslated() 只取 translated_at IS NULL 的行。
铁律 5: 失败 → failed_ai_jobs。
"""

from __future__ import annotations

import logging
from typing import Any

from shared.ai_client import run_task
from shared.dao import app_versions as dao_versions
from shared.dao import failed_ai_jobs as dao_failed

log = logging.getLogger("ai_tasks.translate_app_versions")


def translate_one(
    *,
    version_id: int,
    competitor: str,
    version: str,
    release_notes: str,
    persist: bool = True,
) -> dict[str, Any]:
    if not release_notes or not release_notes.strip():
        return {"version_id": version_id, "error": "empty release_notes"}

    context = {
        "competitor": (competitor or "")[:64],
        "version": (version or "")[:64],
        "release_notes": release_notes.strip()[:4000],   # 截断防 prompt 过长
    }
    try:
        result = run_task("version_translate", context=context)
    except Exception as e:
        dao_failed.push(
            task_name="version_translate",
            payload={"version_id": version_id, "competitor": competitor, "version": version},
            error_msg=str(e),
            error_kind="http",
        )
        log.warning(f"version_translate call failed version_id={version_id}: {e}")
        return {"version_id": version_id, "error": f"http: {e}"}

    if not isinstance(result, dict) or result.get("_parse_error"):
        dao_failed.push(
            task_name="version_translate",
            payload={"version_id": version_id, "competitor": competitor, "version": version},
            error_msg=str(result)[:1000],
            error_kind="json_parse",
        )
        return {"version_id": version_id, "error": "json_parse"}

    zh = (result.get("release_notes_zh") or "").strip()
    if not zh:
        dao_failed.push(
            task_name="version_translate",
            payload={"version_id": version_id, "competitor": competitor, "version": version},
            error_msg="empty release_notes_zh",
            error_kind="validation",
        )
        return {"version_id": version_id, "error": "empty_zh"}

    if persist:
        dao_versions.update_translation(version_id, zh)
    return {"version_id": version_id, "release_notes_zh_len": len(zh)}


def translate_pending(*, limit: int = 50, dry_run: bool = False) -> dict:
    pending = dao_versions.fetch_untranslated(limit=limit)
    log.info(f"[version_translate] fetched {len(pending)} untranslated versions")
    if dry_run:
        return {"fetched": len(pending), "translated": 0, "errors": 0}
    translated = 0
    errors = 0
    for v in pending:
        out = translate_one(
            version_id=v["id"],
            competitor=v.get("competitor") or "",
            version=v.get("version") or "",
            release_notes=v.get("release_notes") or "",
        )
        if out.get("error"):
            errors += 1
        else:
            translated += 1
    log.info(f"[version_translate] done · translated={translated} errors={errors}")
    return {"fetched": len(pending), "translated": translated, "errors": errors}


if __name__ == "__main__":
    import argparse
    import json
    logging.basicConfig(level=logging.INFO,
                        format="%(asctime)s [%(levelname)s] %(message)s")
    ap = argparse.ArgumentParser()
    ap.add_argument("--limit", type=int, default=50)
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()
    print(json.dumps(translate_pending(limit=args.limit, dry_run=args.dry_run),
                     ensure_ascii=False, indent=2))
