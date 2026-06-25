"""
Supabase data access layer. Isolated here on purpose: fetch_all.py and the
fetchers/enrich.py know nothing about where data ends up -- they just
produce NewsItem objects. This module is the only place that knows about
Supabase, so swapping storage later (e.g. to Render Postgres) only touches
this one file.

Enhanced: Automatically falls back to a local SQLite database (signal.db)
if SUPABASE_URL or SUPABASE_SERVICE_KEY are not set in the environment.
"""
import os
import json
import sqlite3
from datetime import datetime
from typing import Optional, Any

from dotenv import load_dotenv
# Find .env in backend directory relative to this file location
backend_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
load_dotenv(os.path.join(backend_dir, ".env"))

from .schema import NewsItem

_client: Optional[Any] = None
_use_sqlite: bool = False

class SQLiteQueryBuilder:
    def __init__(self, db_path: str, table_name: str):
        self.db_path = db_path
        self.table_name = table_name
        self._select_fields = "*"
        self._eq_filters: dict[str, Any] = {}
        self._order_by: Optional[str] = None
        self._order_desc = False
        self._limit: Optional[int] = None
        self._upsert_data: Optional[Any] = None
        self._on_conflict: Optional[str] = None

    def select(self, fields: str = "*"):
        self._select_fields = fields
        return self

    def eq(self, field: str, value: Any):
        self._eq_filters[field] = value
        return self

    def order(self, field: str, desc: bool = False):
        self._order_by = field
        self._order_desc = desc
        return self

    def limit(self, count: int):
        self._limit = count
        return self

    def upsert(self, data: Any, on_conflict: Optional[str] = None):
        self._upsert_data = data
        self._on_conflict = on_conflict
        return self

    def execute(self):
        # Check if this is an upsert operation
        if self._upsert_data is not None:
            data = self._upsert_data
            if not isinstance(data, list):
                data = [data]

            conn = sqlite3.connect(self.db_path)
            cursor = conn.cursor()
            for item in data:
                item = dict(item)
                if "stack_tags" in item and isinstance(item["stack_tags"], list):
                    item["stack_tags"] = json.dumps(item["stack_tags"])
                if "dept" in item and isinstance(item["dept"], list):
                    item["dept"] = json.dumps(item["dept"])
                if "is_builder_idea" in item:
                    item["is_builder_idea"] = 1 if item["is_builder_idea"] else 0

                columns = list(item.keys())
                placeholders = ", ".join(["?"] * len(columns))
                col_names = ", ".join(columns)

                query = f"INSERT INTO {self.table_name} ({col_names}) VALUES ({placeholders})"
                if self._on_conflict == "url":
                    update_clauses = [f"{col} = excluded.{col}" for col in columns if col != "url"]
                    query += f" ON CONFLICT(url) DO UPDATE SET " + ", ".join(update_clauses)

                cursor.execute(query, list(item.values()))
            conn.commit()
            conn.close()

            class Result:
                def __init__(self):
                    self.data = []
            return Result()

        else:
            # Select query
            conn = sqlite3.connect(self.db_path)
            conn.row_factory = sqlite3.Row
            cursor = conn.cursor()

            query = f"SELECT {self._select_fields} FROM {self.table_name}"
            params = []
            if self._eq_filters:
                where_clauses = [f"{k} = ?" for k in self._eq_filters.keys()]
                query += " WHERE " + " AND ".join(where_clauses)
                params = list(self._eq_filters.values())

            if self._order_by:
                direction = "DESC" if self._order_desc else "ASC"
                query += f" ORDER BY {self._order_by} {direction}"

            if self._limit is not None:
                query += f" LIMIT {self._limit}"

            cursor.execute(query, params)
            rows = cursor.fetchall()
            conn.close()

            data = []
            for row in rows:
                row_dict = dict(row)
                # Parse stack_tags back into list of strings if they exist
                if "stack_tags" in row_dict and isinstance(row_dict["stack_tags"], str):
                    try:
                        row_dict["stack_tags"] = json.loads(row_dict["stack_tags"])
                    except Exception:
                        row_dict["stack_tags"] = []
                if "dept" in row_dict and isinstance(row_dict["dept"], str):
                    try:
                        row_dict["dept"] = json.loads(row_dict["dept"])
                    except Exception:
                        row_dict["dept"] = []
                if "is_builder_idea" in row_dict:
                    row_dict["is_builder_idea"] = bool(row_dict["is_builder_idea"])
                data.append(row_dict)

            class Result:
                def __init__(self, data):
                    self.data = data
            return Result(data)


class SQLiteSupabaseClient:
    def __init__(self, db_path: str = "signal.db"):
        self.db_path = db_path
        self._init_db()

    def _init_db(self):
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS items (
                url TEXT PRIMARY KEY,
                title TEXT NOT NULL,
                source TEXT NOT NULL,
                tier INTEGER NOT NULL,
                category TEXT NOT NULL,
                published_at TEXT,
                engagement_raw REAL DEFAULT 0,
                summary TEXT DEFAULT '',
                is_builder_idea BOOLEAN DEFAULT 0,
                stack_tags TEXT DEFAULT '[]',
                dedup_key TEXT DEFAULT '',
                dept TEXT DEFAULT '[]',
                updated_at TEXT
            )
        """)
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS summary_cache (
                url TEXT PRIMARY KEY,
                summary TEXT NOT NULL,
                created_at TEXT
            )
        """)
        # Indexes for fast querying
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_items_published_at ON items (published_at DESC)")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_items_is_builder_idea ON items (is_builder_idea)")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_items_source ON items (source)")
        conn.commit()
        conn.close()

    def table(self, table_name: str):
        return SQLiteQueryBuilder(self.db_path, table_name)


def get_client() -> Any:
    global _client, _use_sqlite
    if _client is None:
        url = os.environ.get("SUPABASE_URL")
        key = os.environ.get("SUPABASE_SERVICE_KEY") or os.environ.get("SUPABASE_SECRET_KEY")
        if not url or not key:
            db_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
            db_path = os.path.join(db_dir, "signal.db")
            print(f"\n[db.py] WARNING: SUPABASE_URL or SUPABASE_SERVICE_KEY not found in environment.")
            print(f"[db.py] Falling back to local SQLite database: {db_path}\n")
            _client = SQLiteSupabaseClient(db_path)
            _use_sqlite = True
        else:
            # Import dynamically to avoid crash if supabase module isn't installed
            from supabase import create_client
            _client = create_client(url, key)
            _use_sqlite = False
    return _client


def _item_to_row(item: NewsItem) -> dict:
    row = item.to_dict()
    # Postgres wants None for a missing timestamp, not the string "None".
    if row.get("published_at") is None:
        row["published_at"] = None
    row["updated_at"] = datetime.utcnow().isoformat()
    return row


def save_items(items: list[NewsItem]) -> int:
    """Upserts every item by URL. Re-running a fetch updates existing rows
    instead of duplicating them, which is a free side benefit of moving off
    timestamped JSON files -- there's only ever one row per URL."""
    if not items:
        return 0
    client = get_client()
    rows = [_item_to_row(i) for i in items]
    # Batch in chunks -- a single huge upsert payload risks hitting request
    # size limits on a big fetch; 200 rows per call keeps it comfortable.
    CHUNK = 200
    saved = 0
    for i in range(0, len(rows), CHUNK):
        chunk = rows[i:i + CHUNK]
        client.table("items").upsert(chunk, on_conflict="url").execute()
        saved += len(chunk)
    return saved


def load_items() -> list[dict]:
    """Reads back every item, newest first. Used by /api/items and /api/status."""
    client = get_client()
    result = (
        client.table("items")
        .select("*")
        .order("published_at", desc=True)
        .limit(2000)  # generous ceiling -- well above realistic item counts
        .execute()
    )
    return result.data or []

