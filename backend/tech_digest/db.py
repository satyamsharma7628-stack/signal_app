"""
Supabase data access layer with automatic local SQLite fallback (signal.db).
Includes feed items, summary cache, user profiles, saved items, and cached
Daily/Weekly newsletter issues.
"""
import os
import json
import sqlite3
from datetime import datetime, timezone
from typing import Optional, Any

from dotenv import load_dotenv
backend_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
load_dotenv(os.path.join(backend_dir, ".env"))

from .schema import NewsItem

_client: Optional[Any] = None
_use_sqlite: bool = False

JSON_LIST_COLUMNS = ("stack_tags", "dept", "preferred_depts", "preferred_sources", "items")
BOOL_COLUMNS = ("is_builder_idea", "daily_newsletter", "weekly_newsletter")


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
        self._is_delete: bool = False

    def select(self, fields: str = "*"):
        self._select_fields = fields
        return self

    def eq(self, field: str, value: Any):
        if field in BOOL_COLUMNS and isinstance(value, bool):
            self._eq_filters[field] = 1 if value else 0
        else:
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

    def delete(self):
        self._is_delete = True
        return self

    def execute(self):
        if self._is_delete:
            conn = sqlite3.connect(self.db_path)
            cursor = conn.cursor()
            query = f"DELETE FROM {self.table_name}"
            params = []
            if self._eq_filters:
                where_clauses = [f"{k} = ?" for k in self._eq_filters.keys()]
                query += " WHERE " + " AND ".join(where_clauses)
                params = list(self._eq_filters.values())
            cursor.execute(query, params)
            conn.commit()
            conn.close()

            class Result:
                def __init__(self):
                    self.data = []
            return Result()

        if self._upsert_data is not None:
            data = self._upsert_data
            if not isinstance(data, list):
                data = [data]

            conn = sqlite3.connect(self.db_path)
            cursor = conn.cursor()
            for item in data:
                item = dict(item)
                for col in JSON_LIST_COLUMNS:
                    if col in item and isinstance(item[col], (list, dict)):
                        item[col] = json.dumps(item[col])
                for bcol in BOOL_COLUMNS:
                    if bcol in item:
                        item[bcol] = 1 if item[bcol] else 0

                columns = list(item.keys())
                placeholders = ", ".join(["?"] * len(columns))
                col_names = ", ".join(columns)

                query = f"INSERT INTO {self.table_name} ({col_names}) VALUES ({placeholders})"
                if self._on_conflict:
                    conflict_cols = [c.strip() for c in self._on_conflict.split(",")]
                    update_clauses = [
                        f"{col} = excluded.{col}"
                        for col in columns
                        if col not in conflict_cols
                    ]
                    if update_clauses:
                        query += (
                            f" ON CONFLICT({', '.join(conflict_cols)}) DO UPDATE SET "
                            + ", ".join(update_clauses)
                        )
                    else:
                        query += f" ON CONFLICT({', '.join(conflict_cols)}) DO NOTHING"

                cursor.execute(query, list(item.values()))
            conn.commit()
            conn.close()

            class Result:
                def __init__(self, rows):
                    self.data = rows
            return Result(data)

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
            for col in JSON_LIST_COLUMNS:
                if col in row_dict and isinstance(row_dict[col], str):
                    try:
                        row_dict[col] = json.loads(row_dict[col])
                    except Exception:
                        row_dict[col] = []
            for bcol in BOOL_COLUMNS:
                if bcol in row_dict:
                    row_dict[bcol] = bool(row_dict[bcol])
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
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS user_profiles (
                user_id TEXT PRIMARY KEY,
                email TEXT NOT NULL,
                full_name TEXT DEFAULT '',
                avatar_url TEXT DEFAULT '',
                preferred_depts TEXT DEFAULT '[]',
                preferred_sources TEXT DEFAULT '[]',
                subscription_tier TEXT DEFAULT 'free',
                daily_newsletter BOOLEAN DEFAULT 0,
                weekly_newsletter BOOLEAN DEFAULT 0,
                created_at TEXT,
                updated_at TEXT
            )
        """)
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS user_saved_items (
                user_id TEXT NOT NULL,
                item_url TEXT NOT NULL,
                title TEXT NOT NULL,
                source TEXT DEFAULT '',
                category TEXT DEFAULT '',
                summary TEXT DEFAULT '',
                custom_note TEXT DEFAULT '',
                dept TEXT DEFAULT '[]',
                stack_tags TEXT DEFAULT '[]',
                saved_at TEXT,
                updated_at TEXT,
                PRIMARY KEY (user_id, item_url)
            )
        """)
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS newsletter_issues (
                issue_key TEXT PRIMARY KEY,
                kind TEXT NOT NULL,
                subject TEXT NOT NULL,
                html_body TEXT NOT NULL,
                items TEXT DEFAULT '[]',
                created_at TEXT
            )
        """)
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_items_published_at ON items (published_at DESC)")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_items_is_builder_idea ON items (is_builder_idea)")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_items_source ON items (source)")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_user_saved_items_user ON user_saved_items (user_id, saved_at DESC)")
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
            from supabase import create_client
            _client = create_client(url, key)
            _use_sqlite = False
    return _client


def _item_to_row(item: NewsItem) -> dict:
    row = item.to_dict()
    if row.get("published_at") is None:
        row["published_at"] = None
    row["updated_at"] = datetime.now(timezone.utc).isoformat()
    return row


def save_items(items: list[NewsItem]) -> int:
    if not items:
        return 0
    client = get_client()
    rows = [_item_to_row(i) for i in items]
    CHUNK = 200
    saved = 0
    for i in range(0, len(rows), CHUNK):
        chunk = rows[i:i + CHUNK]
        client.table("items").upsert(chunk, on_conflict="url").execute()
        saved += len(chunk)
    return saved


def load_items() -> list[dict]:
    client = get_client()
    result = (
        client.table("items")
        .select("*")
        .order("published_at", desc=True)
        .limit(2000)
        .execute()
    )
    return result.data or []


# ── User Authentication & Personal Section Helpers ──────────────────────────

def verify_user_token(token: str) -> Optional[dict]:
    if not token:
        return None

    client = get_client()

    if token.startswith("demo:"):
        parts = token.split(":", 2)
        email = parts[1] if len(parts) > 1 and parts[1] else "demo@signal.local"
        name = parts[2] if len(parts) > 2 and parts[2] else email.split("@")[0].title()
        return {
            "user_id": f"demo_{email.lower()}",
            "email": email.lower(),
            "full_name": name,
            "avatar_url": "",
        }

    if _use_sqlite:
        return None

    try:
        res = client.auth.get_user(token)
        user = getattr(res, "user", None)
        if user:
            meta = getattr(user, "user_metadata", {}) or {}
            return {
                "user_id": str(user.id),
                "email": user.email or "",
                "full_name": meta.get("full_name") or meta.get("name") or (user.email or "").split("@")[0],
                "avatar_url": meta.get("avatar_url") or meta.get("picture") or "",
            }
    except Exception as e:
        print(f"[auth] Supabase get_user check warning: {e}")

    # Fallback: decode Supabase JWT payload so a slightly stale 1-hour access token
    # doesn't block user saves/notes before the frontend refreshes it.
    try:
        import base64
        parts = token.split(".")
        if len(parts) == 3:
            padded = parts[1] + "=" * (-len(parts[1]) % 4)
            payload = json.loads(base64.urlsafe_b64decode(padded.encode("utf-8")).decode("utf-8"))
            sub = payload.get("sub")
            email = payload.get("email") or ""
            if sub and email:
                meta = payload.get("user_metadata") or {}
                return {
                    "user_id": str(sub),
                    "email": email,
                    "full_name": meta.get("full_name") or meta.get("name") or email.split("@")[0],
                    "avatar_url": meta.get("avatar_url") or meta.get("picture") or "",
                }
    except Exception as e:
        print(f"[auth] JWT decode fallback failed: {e}")
    return None


def get_or_create_user_profile(user_info: dict) -> dict:
    client = get_client()
    user_id = user_info["user_id"]
    now_iso = datetime.now(timezone.utc).isoformat()

    existing = (
        client.table("user_profiles")
        .select("*")
        .eq("user_id", user_id)
        .limit(1)
        .execute()
    )
    if existing.data:
        profile = existing.data[0]
        updated_fields = {
            "user_id": user_id,
            "email": user_info.get("email") or profile.get("email", ""),
            "full_name": user_info.get("full_name") or profile.get("full_name", ""),
            "avatar_url": user_info.get("avatar_url") or profile.get("avatar_url", ""),
            "preferred_depts": profile.get("preferred_depts") or [],
            "preferred_sources": profile.get("preferred_sources") or [],
            "subscription_tier": profile.get("subscription_tier") or "free",
            "daily_newsletter": bool(profile.get("daily_newsletter", True)),
            "weekly_newsletter": bool(profile.get("weekly_newsletter", False)),
            "created_at": profile.get("created_at") or now_iso,
            "updated_at": now_iso,
        }
        client.table("user_profiles").upsert(updated_fields, on_conflict="user_id").execute()
        return updated_fields

    new_profile = {
        "user_id": user_id,
        "email": user_info.get("email", ""),
        "full_name": user_info.get("full_name", ""),
        "avatar_url": user_info.get("avatar_url", ""),
        "preferred_depts": [],
        "preferred_sources": [],
        "subscription_tier": "free",
        "daily_newsletter": True,
        "weekly_newsletter": False,
        "created_at": now_iso,
        "updated_at": now_iso,
    }
    client.table("user_profiles").upsert(new_profile, on_conflict="user_id").execute()
    return new_profile


def update_user_preferences(
    user_id: str,
    preferred_depts: list[str],
    preferred_sources: list[str],
) -> dict:
    client = get_client()
    existing = (
        client.table("user_profiles")
        .select("*")
        .eq("user_id", user_id)
        .limit(1)
        .execute()
    )
    now_iso = datetime.now(timezone.utc).isoformat()
    base = existing.data[0] if existing.data else {"user_id": user_id, "email": "", "created_at": now_iso}
    updated = {
        **base,
        "preferred_depts": preferred_depts,
        "preferred_sources": preferred_sources,
        "updated_at": now_iso,
    }
    client.table("user_profiles").upsert(updated, on_conflict="user_id").execute()
    return updated


def update_user_newsletter_prefs(
    user_id: str,
    daily_newsletter: bool,
    weekly_newsletter: bool,
) -> dict:
    client = get_client()
    existing = (
        client.table("user_profiles")
        .select("*")
        .eq("user_id", user_id)
        .limit(1)
        .execute()
    )
    now_iso = datetime.now(timezone.utc).isoformat()
    base = existing.data[0] if existing.data else {"user_id": user_id, "email": "", "created_at": now_iso}
    updated = {
        **base,
        "daily_newsletter": bool(daily_newsletter),
        "weekly_newsletter": bool(weekly_newsletter),
        "updated_at": now_iso,
    }
    client.table("user_profiles").upsert(updated, on_conflict="user_id").execute()
    return updated


def list_newsletter_subscribers(kind: str = "daily") -> list[dict]:
    client = get_client()
    col = "weekly_newsletter" if kind == "weekly" else "daily_newsletter"
    res = (
        client.table("user_profiles")
        .select("*")
        .eq(col, True)
        .limit(5000)
        .execute()
    )
    return res.data or []


def get_newsletter_issue(issue_key: str) -> Optional[dict]:
    client = get_client()
    res = (
        client.table("newsletter_issues")
        .select("*")
        .eq("issue_key", issue_key)
        .limit(1)
        .execute()
    )
    if res.data:
        return res.data[0]
    return None


def save_newsletter_issue(issue: dict) -> dict:
    client = get_client()
    client.table("newsletter_issues").upsert(issue, on_conflict="issue_key").execute()
    return issue


def list_saved_items(user_id: str) -> list[dict]:
    client = get_client()
    res = (
        client.table("user_saved_items")
        .select("*")
        .eq("user_id", user_id)
        .order("saved_at", desc=True)
        .limit(500)
        .execute()
    )
    return res.data or []


def save_or_update_user_item(user_id: str, payload: dict) -> dict:
    client = get_client()
    now_iso = datetime.now(timezone.utc).isoformat()
    existing = (
        client.table("user_saved_items")
        .select("*")
        .eq("user_id", user_id)
        .eq("item_url", payload["item_url"])
        .limit(1)
        .execute()
    )
    saved_at = existing.data[0].get("saved_at") if existing.data else now_iso
    row = {
        "user_id": user_id,
        "item_url": payload["item_url"],
        "title": payload.get("title", ""),
        "source": payload.get("source", ""),
        "category": payload.get("category", ""),
        "summary": payload.get("summary", ""),
        "custom_note": payload.get("custom_note", ""),
        "dept": payload.get("dept") or [],
        "stack_tags": payload.get("stack_tags") or [],
        "saved_at": saved_at,
        "updated_at": now_iso,
    }
    client.table("user_saved_items").upsert(row, on_conflict="user_id,item_url").execute()
    return row


def delete_saved_item(user_id: str, item_url: str) -> bool:
    client = get_client()
    (
        client.table("user_saved_items")
        .delete()
        .eq("user_id", user_id)
        .eq("item_url", item_url)
        .execute()
    )
    return True
