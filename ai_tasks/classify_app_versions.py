"""任务 11 — app_versions 分类（version_type + key_changes 中文亮点 + is_significant）。

产品动态页（/content/releases）卡头价值信号 + 重要更新置顶用。
- version_type: feature / bugfix / localization / performance / other
- key_changes: 1-3 个 ≤20 字中文短句（卡头 Pill 展示）
- is_significant: 是否值得置顶高亮

调用:
    from ai_tasks.classify_app_versions import classify_one, classify_pending
    classify_pending(limit=50)

铁律 4: fetch_unclassified() 只取 classified_at IS NULL 的行。
铁律 5: 失败 → failed_ai_jobs。
"""

from __future__ import annotations

import logging
from typing import Any

from shared.ai_client import run_task
from shared.dao import app_versions as dao_versions
from shared.dao import failed_ai_jobs as dao_failed

log = logging.getLogger("ai_tasks.classify_app_versions")

VALID_TYPES = {"feature", "bugfix", "localization", "performance", "other"}


def classify_one(
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
        "release_notes": release_notes.strip()[:4000],
    }
    try:
        result = run_task("version_classify", context=context)
    except Exception as e:
        dao_failed.push(
            task_name="version_classify",
            payload={"version_id": version_id, "competitor": competitor, "version": version},
            error_msg=str(e),
            error_kind="http",
        )
        log.warning(f"version_classify call failed version_id={version_id}: {e}")
        return {"version_id": version_id, "error": f"http: {e}"}

    if not isinstance(result, dict) or result.get("_parse_error"):
        dao_failed.push(
            task_name="version_classify",
            payload={"version_id": version_id, "competitor": competitor, "version": version},
            error_msg=str(result)[:1000],
            error_kind="json_parse",
        )
        return {"version_id": version_id, "error": "json_parse"}

    out = _normalize_result(result)
    if persist:
        dao_versions.update_classification(
            version_id,
            version_type=out["version_type"],
            key_changes=out["key_changes"],
            is_significant=out["is_significant"],
        )
    return {"version_id": version_id, **out}


def _normalize_result(raw: dict) -> dict:
    """兜底校验：version_type 不在白名单 → other；key_changes 强转 list of str；is_significant 强转 bool。"""
    vt = (raw.get("version_type") or "").strip().lower()
    if vt not in VALID_TYPES:
        vt = "other"

    kc = raw.get("key_changes") or []
    if not isinstance(kc, list):
        kc = []
    # 单条最多 30 字（prompt 要 ≤20，留 buffer）；最多 3 条
    kc = [str(x).strip()[:30] for x in kc if x and str(x).strip()][:3]

    sig = raw.get("is_significant")
    # 模型偶尔返回字符串 "true" / "false" — 标准化
    if isinstance(sig, str):
        sig = sig.lower() == "true"
    sig = bool(sig)
    # 一致性兜底：feature 类型默认重要；纯 bugfix + 空 key_changes 默认不重要
    if vt == "feature" and not kc:
        # feature 但抓不出亮点 — 模型可能太保守，按 sig 留
        pass
    elif vt == "bugfix" and not kc:
        sig = False

    return {"version_type": vt, "key_changes": kc, "is_significant": sig}


def classify_pending(*, limit: int = 50, dry_run: bool = False) -> dict:
    pending = dao_versions.fetch_unclassified(limit=limit)
    log.info(f"[version_classify] fetched {len(pending)} unclassified versions")
    if dry_run:
        return {"fetched": len(pending), "classified": 0, "errors": 0}
    classified = 0
    errors = 0
    for v in pending:
        out = classify_one(
            version_id=v["id"],
            competitor=v.get("competitor") or "",
            version=v.get("version") or "",
            release_notes=v.get("release_notes") or "",
        )
        if out.get("error"):
            errors += 1
        else:
            classified += 1
    log.info(f"[version_classify] done · classified={classified} errors={errors}")
    return {"fetched": len(pending), "classified": classified, "errors": errors}


if __name__ == "__main__":
    import argparse
    import json
    logging.basicConfig(level=logging.INFO,
                        format="%(asctime)s [%(levelname)s] %(message)s")
    ap = argparse.ArgumentParser()
    ap.add_argument("--limit", type=int, default=50)
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()
    print(json.dumps(classify_pending(limit=args.limit, dry_run=args.dry_run),
                     ensure_ascii=False, indent=2))
