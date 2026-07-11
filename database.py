import sqlite3
import os
import time
from datetime import datetime
from typing import Optional

DB_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "avatar_library.db")
CACHE_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "cache")

os.makedirs(CACHE_DIR, exist_ok=True)

def get_connection():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    return conn

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
    """)
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
    allowed = {"name", "author", "thumbnail_url", "thumbnail_path", "description", "notes", "favorite"}
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
        parts.append("AND (a.name LIKE ? OR a.author LIKE ? OR a.avatar_id LIKE ? OR a.notes LIKE ?)")
        like = f"%{search}%"
        params.extend([like, like, like, like])
    
    order = "ASC" if sort_dir.upper() == "ASC" else "DESC"
    col = sort_by if sort_by in ("name", "author", "date_added", "favorite") else "date_added"
    parts.append(f"ORDER BY a.{col} {order}")
    
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
