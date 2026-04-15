"""SQLite-based recipe history."""
from __future__ import annotations
import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from app.config import get_settings


def _db_path() -> Path:
    settings = get_settings()
    return Path(settings.history_db_path)


def init_db() -> None:
    db = _db_path()
    db.parent.mkdir(parents=True, exist_ok=True)
    with sqlite3.connect(db) as conn:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS recipe_history (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                extracted_at TEXT NOT NULL,
                title TEXT,
                source_url TEXT,
                image_url TEXT,
                recipe_json TEXT NOT NULL,
                imported_at TEXT,
                tandoor_recipe_id INTEGER
            )
        """)
        conn.commit()


def save_recipe(extract_data: dict) -> int:
    recipe = extract_data.get("recipe", {})
    now = datetime.now(timezone.utc).isoformat()
    with sqlite3.connect(_db_path()) as conn:
        cur = conn.execute(
            """INSERT INTO recipe_history
               (extracted_at, title, source_url, image_url, recipe_json)
               VALUES (?, ?, ?, ?, ?)""",
            (
                now,
                recipe.get("title"),
                recipe.get("source_url"),
                recipe.get("image_url"),
                json.dumps(extract_data),
            ),
        )
        conn.commit()
        return cur.lastrowid


def get_all() -> list[dict]:
    with sqlite3.connect(_db_path()) as conn:
        conn.row_factory = sqlite3.Row
        rows = conn.execute(
            "SELECT * FROM recipe_history ORDER BY extracted_at DESC"
        ).fetchall()
    result = []
    for r in rows:
        entry = dict(r)
        entry["recipe_data"] = json.loads(entry.pop("recipe_json"))
        result.append(entry)
    return result


def delete_recipe(history_id: int) -> None:
    with sqlite3.connect(_db_path()) as conn:
        conn.execute("DELETE FROM recipe_history WHERE id = ?", (history_id,))
        conn.commit()


def update_image_url(history_id: int, image_url: str) -> None:
    with sqlite3.connect(_db_path()) as conn:
        conn.execute(
            "UPDATE recipe_history SET image_url = ? WHERE id = ?",
            (image_url, history_id),
        )
        conn.commit()


def mark_imported(history_id: int, tandoor_recipe_id: Optional[int]) -> None:
    now = datetime.now(timezone.utc).isoformat()
    with sqlite3.connect(_db_path()) as conn:
        conn.execute(
            "UPDATE recipe_history SET imported_at = ?, tandoor_recipe_id = ? WHERE id = ?",
            (now, tandoor_recipe_id, history_id),
        )
        conn.commit()
