"""shared.dao — 数据访问对象层。

每个抓取脚本写完 JSON 后调对应 dao 函数把数据塞进 MySQL。
所有函数遵循同一约定：
- MYSQL_DSN 未配置 → 静默 return 0（dao 不抛，业务无感）
- 写入失败 → log.warning + return 0（不影响 JSON 主路径）
- 返回插入 / upsert 的行数

公共 helper：
- get_or_create_competitor(name) → competitor_id
- 调用方传 competitor name，dao 内部转 id
"""

from __future__ import annotations

import logging
from typing import Optional

from shared import db as _db

log = logging.getLogger("shared.dao")

_competitor_id_cache: dict[str, int] = {}


def resolve_competitor_id(name: str, sess=None) -> Optional[int]:
    """name → id；带进程级缓存。lookup 表是 alembic seed 灌的，新增 competitor 才需 INSERT。

    如果传入 sess（已有 session），就在那个 session 里查；否则起一个新 session。
    """
    if not name:
        return None
    if name in _competitor_id_cache:
        return _competitor_id_cache[name]

    from shared.models import Competitor

    def _query(s):
        row = s.query(Competitor).filter(Competitor.name == name).first()
        return row.id if row else None

    if sess is not None:
        cid = _query(sess)
    else:
        if not _db.is_mysql_enabled():
            return None
        with _db.session() as s:
            cid = _query(s)

    if cid:
        _competitor_id_cache[name] = cid
    return cid


def clear_competitor_cache() -> None:
    """测试用。"""
    _competitor_id_cache.clear()
