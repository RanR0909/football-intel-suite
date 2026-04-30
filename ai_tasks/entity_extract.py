"""任务 2 — 9 类实体抽取 + canonical_id 归一。

Spec: AI_tasks_spec_v1_1.md
模型：claude-haiku-4-5

输入：{"comment_id", "translated_text", "raw_text", "label"}
输出：{"comment_id", "entities": [{type, raw_value, canonical_id, is_new_alias, is_new_canonical}]}

流程：
1. 取 entity_aliases 全量 list（紧凑送 prompt）
2. 调 AI 抽取
3. 对每个 entity：
   - is_new_canonical=True → entity_aliases 表 INSERT 新行（reviewed=False）
   - is_new_alias=True → entity_aliases 表加 alias 到对应 canonical（reviewed=False）
   - else → 直接用返回的 canonical_id
4. 把 (review_id, canonical_id) 写入 comment_entities

调用：
    from ai_tasks.entity_extract import extract_entities
    out = extract_entities(review_id=123, raw_text="...", translated_text="...", label="complaint")
"""

from __future__ import annotations

import json
import logging
import re
import unicodedata
from typing import Any

from shared.ai_client import run_task
from shared.dao import comment_entities as dao_links
from shared.dao import entity_aliases as dao_aliases
from shared.dao import failed_ai_jobs as dao_failed

log = logging.getLogger("ai_tasks.entity_extract")

VALID_TYPES = {
    "competitor", "feature", "league", "player", "device",
    "bug", "localization", "payment", "language",
}

_CANONICAL_ID_RE = re.compile(r"^[a-z0-9]+_[a-z0-9_]+$")


def _slugify(s: str) -> str:
    """简单 slug：lowercase + ASCII fold + 非字母数字替为下划线 + 折叠多 _。"""
    if not s:
        return "unknown"
    norm = unicodedata.normalize("NFKD", str(s))
    norm = "".join(c for c in norm if not unicodedata.combining(c))
    slug = re.sub(r"[^a-zA-Z0-9]+", "_", norm).strip("_").lower()
    return slug or "unknown"


def _validate_canonical_id(cid: str, ttype: str, raw_value: str) -> str:
    """canonical_id 不合法 → 重建（type_slug 规则）。"""
    cid = (cid or "").strip().lower()
    if cid and _CANONICAL_ID_RE.match(cid):
        return cid
    return f"{ttype}_{_slugify(raw_value)[:48]}"


def _build_canonical_list_json(*, max_per_type: int = 80) -> str:
    """给 prompt 看的 canonical 列表（按 type 分桶 + 每类截顶以省 token）。"""
    rows = dao_aliases.all_canonicals()
    if not rows:
        return "[]"
    by_type: dict[str, list] = {}
    for r in rows:
        by_type.setdefault(r["type"], []).append(r)
    compact: list[dict] = []
    for ttype, group in by_type.items():
        for r in group[:max_per_type]:
            compact.append({
                "canonical_id": r["canonical_id"],
                "type": r["type"],
                "primary_name": r["primary_name"],
                "aliases": r["aliases"][:10],   # 每个 canonical 最多送 10 个 alias
            })
    return json.dumps(compact, ensure_ascii=False, separators=(",", ":"))


def extract_entities(
    review_id: int | None,
    *,
    raw_text: str,
    translated_text: str,
    label: str = "",
) -> dict[str, Any]:
    """单条评论的实体抽取 + 归一。

    返回 {"comment_id", "entities": [...], "stats": {...}}
    """
    if not (raw_text or translated_text):
        return {"comment_id": review_id, "entities": []}

    context = {
        "label": label or "",
        "canonical_list_json": _build_canonical_list_json(),
        "raw_text": (raw_text or "").strip()[:2000],
        "translated_text": (translated_text or "").strip()[:2000],
    }
    try:
        result = run_task("entity_extract", context=context)
    except Exception as e:
        dao_failed.push(
            task_name="entity_extract",
            payload={
                "review_id": review_id,
                "raw_text": raw_text,
                "translated_text": translated_text,
                "label": label,
            },
            error_msg=str(e),
            error_kind="http",
        )
        log.warning(f"entity_extract failed for review_id={review_id}: {e}")
        return {"comment_id": review_id, "error": f"http: {e}"}

    if not isinstance(result, dict) or result.get("_parse_error"):
        dao_failed.push(
            task_name="entity_extract",
            payload={"review_id": review_id, "raw_text": raw_text},
            error_msg=str(result)[:1000],
            error_kind="json_parse",
        )
        return {"comment_id": review_id, "error": "json_parse"}

    raw_entities = result.get("entities") or []
    if not isinstance(raw_entities, list):
        return {"comment_id": review_id, "entities": []}

    # ---- 后处理：归一 / 验证 / 写库 ----
    cleaned: list[dict] = []
    new_canonical_count = 0
    new_alias_count = 0
    skipped = 0

    for ent in raw_entities:
        if not isinstance(ent, dict):
            skipped += 1
            continue
        ttype = (ent.get("type") or "").strip().lower()
        if ttype not in VALID_TYPES:
            # spec：unknown type 直接丢
            skipped += 1
            continue
        raw_value = (ent.get("raw_value") or "").strip()
        if not raw_value:
            skipped += 1
            continue

        is_new_canonical = bool(ent.get("is_new_canonical"))
        is_new_alias = bool(ent.get("is_new_alias"))
        cid = _validate_canonical_id(ent.get("canonical_id"), ttype, raw_value)

        # 即便 AI 说 is_new_canonical=False，我们也要确保 cid 在 entity_aliases 里存在
        # （AI 可能凭 prompt 列表猜了一个不存在的 cid）
        if is_new_canonical:
            dao_aliases.upsert_canonical(
                canonical_id=cid,
                entity_type=ttype,
                primary_name=raw_value[:255],
                aliases=[raw_value],
                reviewed=False,
            )
            new_canonical_count += 1
        else:
            # 验证 cid 是否真存在；不存在就退化为新建
            existing_cid = dao_aliases.lookup_by_alias(raw_value, type_filter=ttype)
            if existing_cid:
                # 直接复用查到的 cid（哪怕 AI 给的不一样）
                cid = existing_cid
            elif _canonical_exists(cid):
                if is_new_alias:
                    dao_aliases.add_alias(cid, raw_value)
                    new_alias_count += 1
            else:
                # AI 把 is_new_canonical 标错了 — 我们当成新 canonical 处理
                dao_aliases.upsert_canonical(
                    canonical_id=cid,
                    entity_type=ttype,
                    primary_name=raw_value[:255],
                    aliases=[raw_value],
                    reviewed=False,
                )
                new_canonical_count += 1

        cleaned.append({
            "type": ttype,
            "raw_value": raw_value,
            "canonical_id": cid,
            "is_new_alias": is_new_alias,
            "is_new_canonical": is_new_canonical,
        })

    if review_id and cleaned:
        dao_links.upsert_links(review_id, cleaned)

    return {
        "comment_id": review_id,
        "entities": cleaned,
        "stats": {
            "extracted": len(cleaned),
            "new_canonical": new_canonical_count,
            "new_alias": new_alias_count,
            "skipped": skipped,
        },
    }


def _canonical_exists(canonical_id: str) -> bool:
    """check existence — 简化方式，直接读 all_canonicals（带缓存）。"""
    if not canonical_id:
        return False
    # 性能 OK：list 在 dao 层每次查询都拉新，不在内存缓存
    for r in dao_aliases.all_canonicals():
        if r["canonical_id"] == canonical_id:
            return True
    return False
