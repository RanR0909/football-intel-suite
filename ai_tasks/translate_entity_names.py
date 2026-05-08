"""任务 8 — entity_aliases.primary_name (多语言) → 简洁中文 (chinese_name)。

GP Reviews 4 个聚合 tab（problems / praise / localization / churn）+ Social 帖子的
player / league 维度展示的是 entity_aliases.primary_name。primary_name 实际是
entity_extract AI 抽出的原文，**多语言混杂**（11 英 + 9 葡/西/阿 + 0 中文）。

本任务批量给 primary_name 翻译为简洁中文（≤10 字名词性短语）写入 chinese_name 列。
前端 fallback 链：chinese_name → primary_name。

调用:
    from ai_tasks.translate_entity_names import translate_one, translate_pending
    translate_one(canonical_id="bug_inappropriate_ads", entity_type="bug", primary_name="ads")
    translate_pending(limit=200)

存储: 写回 entity_aliases.chinese_name + translated_at（dao.entity_aliases.set_chinese_name）

铁律 4: fetch_untranslated() 只取 chinese_name IS NULL 的行，不重复跑。
铁律 5: 任一调用失败 → failed_ai_jobs。
"""

from __future__ import annotations

import logging
from typing import Any

from shared.ai_client import run_task
from shared.dao import entity_aliases as dao_entity
from shared.dao import failed_ai_jobs as dao_failed

log = logging.getLogger("ai_tasks.translate_entity_names")


def translate_one(
    *,
    canonical_id: str,
    entity_type: str,
    primary_name: str,
    persist: bool = True,
) -> dict[str, Any]:
    """单条 entity → 中文翻译 + 入库。失败则写 failed_ai_jobs。"""
    if not canonical_id or not primary_name:
        return {"canonical_id": canonical_id, "error": "empty input"}

    context = {
        "canonical_id": canonical_id[:64],
        "entity_type": (entity_type or "")[:32],
        "primary_name": primary_name.strip()[:255],
    }
    try:
        result = run_task("entity_translate", context=context)
    except Exception as e:
        dao_failed.push(
            task_name="entity_translate",
            payload={"canonical_id": canonical_id, "primary_name": primary_name},
            error_msg=str(e),
            error_kind="http",
        )
        log.warning(f"entity_translate call failed canonical_id={canonical_id}: {e}")
        return {"canonical_id": canonical_id, "error": f"http: {e}"}

    if not isinstance(result, dict) or result.get("_parse_error"):
        dao_failed.push(
            task_name="entity_translate",
            payload={"canonical_id": canonical_id, "primary_name": primary_name},
            error_msg=str(result)[:1000],
            error_kind="json_parse",
        )
        return {"canonical_id": canonical_id, "error": "json_parse"}

    chinese_name = (result.get("chinese_name") or "").strip()
    # 校验：只要非空即接受。常见的合理输出有三类：
    #   a) 中文翻译（CJK，最常见）
    #   b) 原样品牌/平台名（iOS/Sofascore/USDT — prompt 规则要求保留）
    #   c) 剥前缀的别名（@PolymarketFC → PolymarketFC; @laoctavasports → La Octava Sports）
    # 前端展示时 chinese_name 与 primary_name 完全一致就不附原文，否则附小字交叉确认。
    # garbage 由下面的 20 字截断兜底；过长说明 AI 出戏，前端能一眼看出。
    if not chinese_name:
        dao_failed.push(
            task_name="entity_translate",
            payload={"canonical_id": canonical_id, "primary_name": primary_name},
            error_msg="empty chinese_name",
            error_kind="validation",
        )
        return {"canonical_id": canonical_id, "error": "empty"}

    # 长度兜底：超 20 字截断（prompt 要 ≤10 字，给 buffer）
    if len(chinese_name) > 20:
        chinese_name = chinese_name[:20]

    if persist:
        dao_entity.set_chinese_name(canonical_id, chinese_name)

    return {"canonical_id": canonical_id, "chinese_name": chinese_name}


def _has_cjk(s: str) -> bool:
    """判断字符串是否包含 CJK 字符（中日韩统一表意）。"""
    return any("一" <= c <= "鿿" for c in s)


def translate_pending(*, limit: int = 200, dry_run: bool = False) -> dict:
    """批量跑：取 chinese_name IS NULL 的 entity，逐条翻译。"""
    pending = dao_entity.fetch_untranslated(limit=limit)
    log.info(f"[entity_translate] fetched {len(pending)} untranslated entities")

    if dry_run:
        return {"fetched": len(pending), "translated": 0, "errors": 0}

    translated = 0
    errors = 0
    for e in pending:
        out = translate_one(
            canonical_id=e["canonical_id"],
            entity_type=e["entity_type"] or "",
            primary_name=e["primary_name"] or "",
        )
        if out.get("error"):
            errors += 1
        else:
            translated += 1
        if translated % 50 == 0 and translated > 0:
            log.info(f"  translated {translated}/{len(pending)}")

    log.info(f"[entity_translate] done · translated={translated} errors={errors}")
    return {
        "fetched": len(pending),
        "translated": translated,
        "errors": errors,
    }


if __name__ == "__main__":
    import argparse
    import json

    logging.basicConfig(level=logging.INFO,
                        format="%(asctime)s [%(levelname)s] %(message)s")
    ap = argparse.ArgumentParser()
    ap.add_argument("--limit", type=int, default=200)
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    result = translate_pending(limit=args.limit, dry_run=args.dry_run)
    print(json.dumps(result, ensure_ascii=False, indent=2))
