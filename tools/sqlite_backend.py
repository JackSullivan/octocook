"""SQLite-backed RecipeBackend implementation."""

from __future__ import annotations

import json
import os
import sqlite3
import uuid
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterator

from recipe_backend import RecipeBackend
from recipe_utils import pick_icon
from scraper import RecipeData


_DEFAULT_DB_PATH = Path(__file__).resolve().parent.parent / "server" / "octocook.db"

_SCHEMA = """
CREATE TABLE IF NOT EXISTS recipes (
    id TEXT PRIMARY KEY,
    title TEXT NOT NULL,
    icon TEXT NOT NULL DEFAULT '🍽️',
    url TEXT,
    source TEXT,
    rating TEXT DEFAULT '🤷‍♂️',
    json_ld TEXT NOT NULL,
    created_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS ix_recipes_title ON recipes (title);
"""


def _db_path() -> Path:
    return Path(os.environ.get("OCTOCOOK_DB", _DEFAULT_DB_PATH))


@contextmanager
def _connect() -> Iterator[sqlite3.Connection]:
    conn = sqlite3.connect(_db_path())
    conn.row_factory = sqlite3.Row
    try:
        yield conn
        conn.commit()
    finally:
        conn.close()


class SQLiteRecipeBackend(RecipeBackend):
    def __init__(self) -> None:
        with _connect() as conn:
            conn.executescript(_SCHEMA)

    def list_recipes(self) -> list[dict]:
        with _connect() as conn:
            rows = conn.execute(
                "SELECT id, title, icon, source, rating FROM recipes ORDER BY title"
            ).fetchall()
        return [
            {
                "id": r["id"],
                "title": r["title"],
                "icon": r["icon"] or "🍽️",
                "found_in": r["source"] or "",
                "rating": r["rating"] or "",
                "page_id": r["id"],
            }
            for r in rows
        ]

    def find_recipe(self, title: str) -> dict:
        with _connect() as conn:
            rows = conn.execute(
                "SELECT id, title, icon FROM recipes WHERE title = ?", (title,)
            ).fetchall()
        if not rows:
            raise LookupError(f"No recipe found with title {title!r}.")
        if len(rows) > 1:
            raise LookupError(
                f"Multiple recipes match {title!r} ({len(rows)} found). "
                "Use a unique title."
            )
        r = rows[0]
        return {"id": r["id"], "title": r["title"], "icon": r["icon"] or "🍽️"}

    def get_recipe_metadata(self, recipe_id: str) -> dict:
        with _connect() as conn:
            row = conn.execute(
                "SELECT title, icon, source, rating, url FROM recipes WHERE id = ?",
                (recipe_id,),
            ).fetchone()
        if row is None:
            raise LookupError(f"Recipe {recipe_id!r} not found.")
        return {
            "title": row["title"],
            "icon": row["icon"] or "🍽️",
            "found_in": row["source"] or "",
            "rating": row["rating"] or "",
            "source_url": row["url"],
        }

    def get_recipe_json_ld(self, recipe_id: str) -> dict:
        with _connect() as conn:
            row = conn.execute(
                "SELECT json_ld FROM recipes WHERE id = ?", (recipe_id,)
            ).fetchone()
        if row is None:
            raise LookupError(f"Recipe {recipe_id!r} not found.")
        return json.loads(row["json_ld"])

    def update_recipe_json_ld(self, recipe_id: str, json_ld: dict) -> None:
        with _connect() as conn:
            conn.execute(
                "UPDATE recipes SET json_ld = ? WHERE id = ?",
                (json.dumps(json_ld, ensure_ascii=False), recipe_id),
            )

    def append_recipe_json_ld(self, recipe_id: str, json_ld: dict) -> None:
        self.update_recipe_json_ld(recipe_id, json_ld)

    def create_recipe(
        self,
        recipe: RecipeData,
        image_paths: list[str] | None = None,
    ) -> str:
        recipe_id = uuid.uuid4().hex[:12]
        icon = pick_icon(recipe)
        created_at = datetime.now(timezone.utc).isoformat()
        json_ld = recipe.json_ld if recipe.json_ld else {}
        with _connect() as conn:
            conn.execute(
                "INSERT INTO recipes (id, title, icon, url, source, rating, json_ld, created_at) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    recipe_id,
                    recipe.title,
                    icon,
                    recipe.url or None,
                    recipe.source_site or None,
                    "🤷‍♂️",
                    json.dumps(json_ld, ensure_ascii=False),
                    created_at,
                ),
            )
        return f"sqlite:{recipe_id}"
