import sqlite3
import os
import json
import time
from datetime import datetime
from typing import Optional

import paths

DB_PATH = str(paths.db_path())
CACHE_DIR = str(paths.cache_dir())

def get_connection():
    paths.ensure_dirs()
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    return conn

# Columns the VRChat API owns. Refreshing an existing avatar only ever touches
# these, so notes, favourites and categories survive a re-import.
API_FIELDS = (
    "name", "author", "author_id", "thumbnail_url", "description", "tags",
    "release_status", "version", "unity_version", "date_published",
    "date_updated", "downloads", "favorites_count", "rating", "is_public",
    "url",
)

# Added after 1.0; older libraries are upgraded in place by _add_missing_columns.
API_COLUMNS = {
    "author_id": "TEXT DEFAULT ''",
    "tags": "TEXT DEFAULT ''",
    "release_status": "TEXT DEFAULT ''",
    "version": "TEXT DEFAULT ''",
    "unity_version": "TEXT DEFAULT ''",
    "date_published": "INTEGER DEFAULT 0",
    "date_updated": "INTEGER DEFAULT 0",
    "downloads": "INTEGER DEFAULT 0",
    "favorites_count": "INTEGER DEFAULT 0",
    "rating": "REAL DEFAULT 0",
    "is_public": "INTEGER DEFAULT 1",
    "url": "TEXT DEFAULT ''",
}


def _add_missing_columns(conn):
    """Bring a pre-existing database up to the current schema."""
    existing = {row["name"] for row in conn.execute("PRAGMA table_info(avatars)")}
    for column, definition in API_COLUMNS.items():
        if column not in existing:
            conn.execute(f"ALTER TABLE avatars ADD COLUMN {column} {definition}")

    category_columns = {row["name"] for row in conn.execute("PRAGMA table_info(categories)")}
    if "sync_group_id" not in category_columns:
        # Links a local category to a VRChat favourite group it mirrors.
        conn.execute("ALTER TABLE categories ADD COLUMN sync_group_id TEXT DEFAULT ''")


def init_db():
    conn = get_connection()
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS avatars (
            avatar_id TEXT PRIMARY KEY,
            name TEXT NOT NULL DEFAULT 'Unknown',
            author TEXT DEFAULT '',
            thumbnail_url TEXT DEFAULT '',
            thumbnail_path TEXT DEFAULT '',
            description TEXT DEFAULT '',
            notes TEXT DEFAULT '',
            date_added INTEGER NOT NULL DEFAULT (strftime('%s','now')),
            favorite INTEGER NOT NULL DEFAULT 0
        );

        CREATE TABLE IF NOT EXISTS categories (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL UNIQUE,
            sort_order INTEGER NOT NULL DEFAULT 0,
            parent_id INTEGER REFERENCES categories(id) ON DELETE SET NULL
        );

        CREATE TABLE IF NOT EXISTS avatar_categories (
            avatar_id TEXT NOT NULL REFERENCES avatars(avatar_id) ON DELETE CASCADE,
            category_id INTEGER NOT NULL REFERENCES categories(id) ON DELETE CASCADE,
            PRIMARY KEY (avatar_id, category_id)
        );

        CREATE TABLE IF NOT EXISTS vrchat_favorites (
            favorite_id TEXT PRIMARY KEY,
            avatar_id TEXT NOT NULL,
            group_id TEXT NOT NULL DEFAULT '',
            date_added INTEGER NOT NULL DEFAULT (strftime('%s','now'))
        );

        CREATE INDEX IF NOT EXISTS idx_vrchat_favorites_avatar
            ON vrchat_favorites(avatar_id);
    """)
    _add_missing_columns(conn)
    conn.commit()
    conn.close()

init_db()

def add_avatar(avatar_id: str, name: str = "Unknown", author: str = "",
               thumbnail_url: str = "", description: str = "",
               notes: str = "", favorite: bool = False) -> bool:
    conn = get_connection()
    try:
        conn.execute("""
            INSERT OR IGNORE INTO avatars (avatar_id, name, author, thumbnail_url, description, notes, favorite)
            VALUES (?, ?, ?, ?, ?, ?, ?)
        """, (avatar_id, name, author, thumbnail_url, description, notes, int(favorite)))
        conn.commit()
        return True
    except sqlite3.Error:
        return False
    finally:
        conn.close()

def update_avatar(avatar_id: str, **kwargs) -> bool:
    allowed = {"name", "author", "thumbnail_url", "thumbnail_path", "description",
           "notes", "favorite"} | set(API_FIELDS)
    fields = {k: v for k, v in kwargs.items() if k in allowed}
    if not fields:
        return False
    set_clause = ", ".join(f"{k} = ?" for k in fields)
    values = list(fields.values()) + [avatar_id]
    conn = get_connection()
    try:
        conn.execute(f"UPDATE avatars SET {set_clause} WHERE avatar_id = ?", values)
        conn.commit()
        return True
    except sqlite3.Error:
        return False
    finally:
        conn.close()

def delete_avatar(avatar_id: str) -> bool:
    conn = get_connection()
    try:
        conn.execute("DELETE FROM avatars WHERE avatar_id = ?", (avatar_id,))
        conn.commit()
        return True
    except sqlite3.Error:
        return False
    finally:
        conn.close()

def get_avatar(avatar_id: str):
    conn = get_connection()
    row = conn.execute("SELECT * FROM avatars WHERE avatar_id = ?", (avatar_id,)).fetchone()
    conn.close()
    return row

SORT_COLUMNS = {
    "name": "a.name COLLATE NOCASE",
    "author": "a.author COLLATE NOCASE",
    "date_added": "a.date_added",
    "date_updated": "a.date_updated",
    "favorites_count": "a.favorites_count",
    "downloads": "a.downloads",
    "rating": "a.rating",
    "release_status": "a.release_status COLLATE NOCASE",
    "version": "a.version",
}

def get_all_avatars(category_id: Optional[int] = None, favorite_only: bool = False,
                    search: str = "", sort_by: str = "date_added", sort_dir: str = "DESC"):
    conn = get_connection()
    params = []
    parts = ["SELECT DISTINCT a.* FROM avatars a"]
    
    if category_id is not None:
        parts.append("JOIN avatar_categories ac ON a.avatar_id = ac.avatar_id")
        parts.append("WHERE ac.category_id = ?")
        params.append(category_id)
    else:
        parts.append("WHERE 1=1")
    
    if favorite_only:
        parts.append("AND a.favorite = 1")
    
    if search:
        parts.append("AND (a.name LIKE ? OR a.author LIKE ? OR a.avatar_id LIKE ? "
                     "OR a.notes LIKE ? OR a.tags LIKE ?)")
        like = f"%{search}%"
        params.extend([like, like, like, like, like])
    
    direction = "ASC" if str(sort_dir).upper() == "ASC" else "DESC"
    # Whitelisted, so no column name ever reaches the query from user input.
    column = SORT_COLUMNS.get(sort_by, "a.date_added")
    parts.append(f"ORDER BY {column} {direction}, a.name COLLATE NOCASE ASC")
    
    rows = conn.execute(" ".join(parts), params).fetchall()
    conn.close()
    return rows

def add_avatar_to_category(avatar_id: str, category_id: int) -> bool:
    conn = get_connection()
    try:
        conn.execute("INSERT OR IGNORE INTO avatar_categories VALUES (?, ?)", (avatar_id, category_id))
        conn.commit()
        return True
    except sqlite3.Error:
        return False
    finally:
        conn.close()

def remove_avatar_from_category(avatar_id: str, category_id: int) -> bool:
    conn = get_connection()
    try:
        conn.execute("DELETE FROM avatar_categories WHERE avatar_id = ? AND category_id = ?",
                     (avatar_id, category_id))
        conn.commit()
        return True
    except sqlite3.Error:
        return False
    finally:
        conn.close()

def get_avatar_categories(avatar_id: str):
    conn = get_connection()
    rows = conn.execute("""
        SELECT c.* FROM categories c
        JOIN avatar_categories ac ON c.id = ac.category_id
        WHERE ac.avatar_id = ?
        ORDER BY c.sort_order
    """, (avatar_id,)).fetchall()
    conn.close()
    return rows

def set_favorite_flag(avatar_id: str, favorite: bool) -> bool:
    """Set the local favourite flag to an exact value.

    toggle_favorite() flips whatever is there, which is wrong when the change
    came from the server and the local row may already be out of step.
    """
    conn = get_connection()
    try:
        conn.execute("UPDATE avatars SET favorite = ? WHERE avatar_id = ?",
                     (1 if favorite else 0, avatar_id))
        conn.commit()
        return True
    except sqlite3.Error:
        return False
    finally:
        conn.close()

def set_avatar_categories(avatar_id: str, category_ids) -> bool:
    """Put an avatar in exactly these categories, and no others.

    This is a transfer, not an append: a category missing from `category_ids`
    is removed. Doing it as one transaction means an interrupted save cannot
    leave the avatar filed in a mixture of old and new categories.

    Unknown ids are ignored rather than raising, so a category deleted in
    another window cannot break the save.
    """
    wanted = []
    for value in category_ids or []:
        try:
            category_id = int(value)
        except (TypeError, ValueError):
            continue
        if category_id not in wanted:
            wanted.append(category_id)

    conn = get_connection()
    try:
        if wanted:
            # Keep only ids that really exist, so a stale one cannot violate
            # the foreign key.
            marks = ",".join("?" * len(wanted))
            real = [row["id"] for row in conn.execute(
                f"SELECT id FROM categories WHERE id IN ({marks})",
                wanted).fetchall()]
        else:
            real = []

        conn.execute("DELETE FROM avatar_categories WHERE avatar_id = ?",
                     (avatar_id,))
        for category_id in real:
            conn.execute(
                "INSERT OR IGNORE INTO avatar_categories "
                "(avatar_id, category_id) VALUES (?, ?)",
                (avatar_id, category_id))
        conn.commit()
        return True
    except sqlite3.Error:
        return False
    finally:
        conn.close()

def toggle_favorite(avatar_id: str) -> bool:
    conn = get_connection()
    try:
        conn.execute("UPDATE avatars SET favorite = ~favorite & 1 WHERE avatar_id = ?", (avatar_id,))
        conn.commit()
        return True
    except sqlite3.Error:
        return False
    finally:
        conn.close()

def upsert_avatar(data: dict, category_id: Optional[int] = None) -> tuple:
    """Insert or refresh one avatar from an API payload.

    Returns (avatar_id, created) where created is True for a new row. Notes,
    favourite state and category membership are never overwritten, so importing
    the same avatar twice is safe.

    Accepts the shape returned by VRChatAPI.lookup_avatar / get_user_avatars.
    """
    avatar_id = data.get("id") or data.get("avatar_id")
    if not avatar_id:
        raise ValueError("payload has no avatar id")

    fields = {k: v for k, v in data.items() if k in API_FIELDS}
    if "tags" in fields and isinstance(fields["tags"], (list, tuple)):
        fields["tags"] = json.dumps(list(fields["tags"]))
    if "is_public" in fields:
        fields["is_public"] = int(bool(fields["is_public"]))

    conn = get_connection()
    try:
        row = conn.execute(
            "SELECT avatar_id FROM avatars WHERE avatar_id = ?", (avatar_id,)
        ).fetchone()
        created = row is None

        if created:
            columns = ["avatar_id"] + list(fields)
            placeholders = ", ".join("?" for _ in columns)
            conn.execute(
                f"INSERT INTO avatars ({', '.join(columns)}) VALUES ({placeholders})",
                [avatar_id] + list(fields.values()),
            )
        elif fields:
            assignments = ", ".join(f"{k} = ?" for k in fields)
            conn.execute(
                f"UPDATE avatars SET {assignments} WHERE avatar_id = ?",
                list(fields.values()) + [avatar_id],
            )

        if category_id is not None:
            conn.execute(
                "INSERT OR IGNORE INTO avatar_categories VALUES (?, ?)",
                (avatar_id, category_id),
            )

        conn.commit()
        return avatar_id, created
    finally:
        conn.close()


def record_favorites(favorites, mark_favorite=True) -> int:
    """Store a batch of VRChat favourites.

    `favorites` items need `favorite_id`, `avatar_id` and `group_id`. Passing
    an empty group_id keeps any existing group association, so a favourite that
    VRChat reports without tags does not lose its local category link.

    Returns the number of rows written.
    """
    if not favorites:
        return 0

    conn = get_connection()
    try:
        for favorite in favorites:
            avatar_id = favorite.get("avatar_id")
            favorite_id = favorite.get("favorite_id")
            if not avatar_id or not favorite_id:
                continue
            conn.execute(
                "INSERT INTO vrchat_favorites (favorite_id, avatar_id, group_id) "
                "VALUES (?, ?, ?) ON CONFLICT(favorite_id) DO UPDATE SET "
                "avatar_id = excluded.avatar_id, "
                "group_id = CASE WHEN excluded.group_id = '' THEN group_id "
                "ELSE excluded.group_id END",
                (favorite_id, avatar_id, favorite.get("group_id", "") or ""),
            )
            if mark_favorite:
                conn.execute("UPDATE avatars SET favorite = 1 WHERE avatar_id = ?",
                             (avatar_id,))
        conn.commit()
    finally:
        conn.close()

    return len(favorites)


def get_favorite_records(avatar_ids=None):
    """Stored favourites, optionally filtered to specific avatars."""
    conn = get_connection()
    try:
        if avatar_ids is None:
            rows = conn.execute("SELECT * FROM vrchat_favorites").fetchall()
        else:
            ids = list(avatar_ids)
            if not ids:
                return []
            placeholders = ", ".join("?" for _ in ids)
            rows = conn.execute(
                f"SELECT * FROM vrchat_favorites WHERE avatar_id IN ({placeholders})",
                ids).fetchall()
    finally:
        conn.close()
    return rows


def get_favorite_record(avatar_id: str):
    rows = get_favorite_records([avatar_id])
    return rows[0] if rows else None


def delete_favorite_record(avatar_id: str) -> bool:
    conn = get_connection()
    try:
        conn.execute("DELETE FROM vrchat_favorites WHERE avatar_id = ?", (avatar_id,))
        conn.commit()
        return True
    finally:
        conn.close()


def sync_favorite_groups(groups) -> dict:
    """Make sure a local category exists for each VRChat favourite group.

    Returns {group_id: category_id}. Existing links are reused, so categories
    keep whatever the user put in them across repeated syncs.
    """
    conn = get_connection()
    linked = {}
    try:
        for group in groups:
            group_id = group.get("id")
            if not group_id:
                continue
            row = conn.execute(
                "SELECT id FROM categories WHERE sync_group_id = ?", (group_id,)
            ).fetchone()
            if row is None:
                row = conn.execute(
                    "SELECT id FROM categories WHERE name = ? COLLATE NOCASE",
                    (group.get("name", ""),)).fetchone()
            if row is None:
                next_order = conn.execute(
                    "SELECT COALESCE(MAX(sort_order), -1) + 1 FROM categories"
                ).fetchone()[0]
                cursor = conn.execute(
                    "INSERT INTO categories (name, sort_order, sync_group_id) "
                    "VALUES (?, ?, ?)",
                    (group.get("name", group_id), next_order, group_id))
                linked[group_id] = cursor.lastrowid
            else:
                if group.get("name") and not conn.execute(
                    "SELECT sync_group_id FROM categories WHERE id = ?",
                    (row["id"],)).fetchone()[0]:
                    conn.execute("UPDATE categories SET sync_group_id = ? WHERE id = ?",
                                 (group_id, row["id"]))
                linked[group_id] = row["id"]
        conn.commit()
    finally:
        conn.close()
    return linked


def link_avatar_to_group_categories(avatar_id, category_ids):
    """Attach an avatar to the categories mirroring its VRChat groups."""
    if not category_ids:
        return
    conn = get_connection()
    try:
        for category_id in category_ids:
            conn.execute("INSERT OR IGNORE INTO avatar_categories VALUES (?, ?)",
                         (avatar_id, category_id))
        conn.commit()
    finally:
        conn.close()


def get_avatar_tags(avatar_id: str) -> list:
    """Tags for an avatar, stored as a JSON list."""
    row = get_avatar(avatar_id)
    if not row or not row["tags"]:
        return []
    try:
        tags = json.loads(row["tags"])
    except (json.JSONDecodeError, TypeError):
        return []
    return tags if isinstance(tags, list) else []


def search_tags(needle: str) -> list:
    """Distinct tags across the library that contain `needle`."""
    conn = get_connection()
    rows = conn.execute("SELECT tags FROM avatars WHERE tags LIKE ?",
                        (f"%{needle}%",)).fetchall()
    conn.close()

    found = set()
    for row in rows:
        try:
            tags = json.loads(row["tags"])
        except (json.JSONDecodeError, TypeError):
            continue
        if isinstance(tags, list):
            for tag in tags:
                text = str(tag).strip().lower()
                if needle.lower() in text:
                    found.add(text)
    return sorted(found)


def create_category(name: str) -> Optional[int]:
    conn = get_connection()
    try:
        max_order = conn.execute("SELECT COALESCE(MAX(sort_order), -1) + 1 FROM categories").fetchone()[0]
        cur = conn.execute("INSERT INTO categories (name, sort_order) VALUES (?, ?)", (name, max_order))
        conn.commit()
        return cur.lastrowid
    except sqlite3.IntegrityError:
        return None
    finally:
        conn.close()

def rename_category(category_id: int, new_name: str) -> bool:
    conn = get_connection()
    try:
        conn.execute("UPDATE categories SET name = ? WHERE id = ?", (new_name, category_id))
        conn.commit()
        return True
    except sqlite3.IntegrityError:
        return False
    finally:
        conn.close()

def delete_category(category_id: int) -> bool:
    conn = get_connection()
    try:
        conn.execute("DELETE FROM avatar_categories WHERE category_id = ?", (category_id,))
        conn.execute("DELETE FROM categories WHERE id = ?", (category_id,))
        conn.commit()
        return True
    except sqlite3.Error:
        return False
    finally:
        conn.close()

def reorder_category(category_id: int, new_order: int) -> bool:
    conn = get_connection()
    try:
        conn.execute("UPDATE categories SET sort_order = ? WHERE id = ?", (new_order, category_id))
        conn.commit()
        return True
    except sqlite3.Error:
        return False
    finally:
        conn.close()

def get_all_categories():
    conn = get_connection()
    rows = conn.execute("SELECT * FROM categories ORDER BY sort_order, name").fetchall()
    conn.close()
    return rows

def get_category_avatar_count(category_id: int) -> int:
    conn = get_connection()
    count = conn.execute("SELECT COUNT(*) FROM avatar_categories WHERE category_id = ?",
                         (category_id,)).fetchone()[0]
    conn.close()
    return count
