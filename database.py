import os
import time
from typing import Any, Dict, List, Optional

from motor.motor_asyncio import AsyncIOMotorClient, AsyncIOMotorDatabase

DATABASE_URL = os.environ.get("DATABASE_URL", "mongodb://localhost:27017")
DATABASE_NAME = os.environ.get("DATABASE_NAME", "appdb")

_client: Optional[AsyncIOMotorClient] = None
_db: Optional[AsyncIOMotorDatabase] = None


def get_db() -> AsyncIOMotorDatabase:
    global _client, _db
    if _db is None:
        _client = AsyncIOMotorClient(DATABASE_URL)
        _db = _client[DATABASE_NAME]
    return _db


# Exported for convenience
_db_instance = get_db()
db = _db_instance


async def create_document(collection_name: str, data: Dict[str, Any]) -> str:
    now = time.time()
    doc = {**data, "created_at": now, "updated_at": now}
    res = await db[collection_name].insert_one(doc)
    return str(res.inserted_id)


async def get_documents(collection_name: str, filter_dict: Dict[str, Any], limit: int = 50) -> List[Dict[str, Any]]:
    cursor = db[collection_name].find(filter_dict).limit(limit)
    results: List[Dict[str, Any]] = []
    async for item in cursor:
        results.append(item)
    return results
