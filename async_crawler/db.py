"""Database — 非全局状态，支持增量写入"""
import json
import logging
from pathlib import Path
from datetime import datetime, timezone

from async_crawler.config import MONGO_URI, MONGO_DB

DATA_DIR = Path(__file__).resolve().parent.parent / "data"
log = logging.getLogger("crawler.db")


class Database:
    def __init__(self):
        self._db = None
        self._client = None

    async def connect(self, uri: str = MONGO_URI, db_name: str = MONGO_DB):
        try:
            import motor.motor_asyncio
            self._client = motor.motor_asyncio.AsyncIOMotorClient(uri, serverSelectionTimeoutMS=3000)
            await self._client.server_info()
            self._db = self._client[db_name]
            log.info(f"MongoDB 已连接: {db_name}")
        except Exception as e:
            log.warning(f"MongoDB 不可用，降级为 JSON: {e}")

    async def save(self, collection: str, docs: list[dict]):
        if not docs:
            return
        if self._db is not None:
            col = self._db[collection]
            for doc in docs:
                key = {k: doc[k] for k in ("source", "competitor") if k in doc}
                if "region" in doc:
                    key["region"] = doc["region"]
                await col.update_one(key, {"$set": doc}, upsert=True)
            log.info(f"[Mongo] {collection}: {len(docs)} upserted")
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
        if self._client:
            self._client.close()
