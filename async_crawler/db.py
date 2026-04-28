"""Database — JSON 落盘 helper（MongoDB scaffolding 已移除，2026-04-28）。

MySQL 主存储现在由 shared/dao/* 处理，各抓取脚本通过 dao 直接写。
这里保留 JSON 写入路径，让 aggregator 等老调用方继续工作。

调用语义保持兼容：
    db = Database()
    await db.connect()       # no-op，保留为了 main.py 调用兼容
    await db.save(name, docs)  # 写 data/async_<name>.json
    await db.close()         # no-op
"""

import json
import logging
from datetime import datetime, timezone
from pathlib import Path

DATA_DIR = Path(__file__).resolve().parent.parent / "data"
log = logging.getLogger("crawler.db")


class Database:
    """JSON-only 持久化（兼容旧 motor 调用方接口）。"""

    def __init__(self):
        self._db = None  # 保留属性供老代码 if self._db is not None 检查

    async def connect(self, *args, **kwargs):
        """空操作 — 保留接口兼容。"""
        return None

    async def save(self, collection: str, docs: list[dict]):
        if not docs:
            return
        self._save_json(collection, docs)

    def _save_json(self, collection: str, docs: list[dict]):
        DATA_DIR.mkdir(parents=True, exist_ok=True)
        path = DATA_DIR / f"async_{collection}.json"
        existing = {}
        if path.exists():
            try:
                for d in json.loads(path.read_text(encoding="utf-8")):
                    existing[self._key(d)] = d
            except Exception:
                pass
        for d in docs:
            existing[self._key(d)] = d
        path.write_text(json.dumps(list(existing.values()), ensure_ascii=False, indent=2), encoding="utf-8")
        log.info(f"[JSON] async_{collection}.json: {len(existing)} records")

    @staticmethod
    def _key(d: dict) -> str:
        return f"{d.get('source')}_{d.get('competitor')}_{d.get('region', '')}"

    async def close(self):
        return None


# ---- 模块级兼容 shim ------------------------------------------------------
# 旧代码（appstore_rank.py / reviews.py 等）有 `await db.save(name, docs)` 调法，
# 这里提供一个进程级单例 Database 让那种调法继续工作。

_global_db = None


async def save(collection: str, docs: list[dict]):
    """模块级 save（与 Database.save 等价；兼容旧调用方）。"""
    global _global_db
    if _global_db is None:
        _global_db = Database()
    await _global_db.save(collection, docs)
