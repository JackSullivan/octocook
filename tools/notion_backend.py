"""Notion-backed RecipeBackend implementation."""

from __future__ import annotations

import notion_client_wrapper as _ncw
from recipe_backend import RecipeBackend
from scraper import RecipeData


class NotionRecipeBackend(RecipeBackend):
    def list_recipes(self) -> list[dict]:
        return _ncw.list_recipes()

    def find_recipe(self, title: str) -> dict:
        page = _ncw.find_recipe_page(title)
        props = page.get("properties", {})
        name_prop = props.get("Name", {})
        title_parts = name_prop.get("title") or []
        page_title = "".join(t.get("plain_text", "") for t in title_parts).strip()
        icon = ""
        page_icon = page.get("icon") or {}
        if page_icon.get("type") == "emoji":
            icon = page_icon.get("emoji", "")
        return {
            "id": page["id"],
            "title": page_title,
            "icon": icon or "🍽️",
        }

    def get_recipe_metadata(self, recipe_id: str) -> dict:
        client = _ncw.get_client()
        try:
            page = client.pages.retrieve(page_id=recipe_id)
        except Exception as e:
            raise LookupError(f"Recipe {recipe_id!r} not found: {e}") from e

        props = page.get("properties", {})
        name_prop = props.get("Name", {})
        title_parts = name_prop.get("title") or []
        title = "".join(t.get("plain_text", "") for t in title_parts).strip()
        if not title:
            raise LookupError(f"Recipe page {recipe_id} has no title.")

        icon = ""
        page_icon = page.get("icon") or {}
        if page_icon.get("type") == "emoji":
            icon = page_icon.get("emoji", "")

        found_in = ""
        found_prop = props.get("Found in", {}) or {}
        sel = found_prop.get("select") or {}
        found_in = sel.get("name", "") or ""

        rating = ""
        rating_prop = props.get("Rating", {}) or {}
        rating_sel = rating_prop.get("select") or {}
        rating = rating_sel.get("name", "") or ""

        source_url = None
        link_prop = props.get("Link", {}) or {}
        source_url = link_prop.get("url")

        return {
            "title": title,
            "icon": icon or "🍽️",
            "found_in": found_in,
            "rating": rating,
            "source_url": source_url,
        }

    def get_recipe_json_ld(self, recipe_id: str) -> dict:
        _, json_ld = _ncw.find_recipe_json_ld_block(recipe_id)
        return json_ld

    def update_recipe_json_ld(self, recipe_id: str, json_ld: dict) -> None:
        block_id, _ = _ncw.find_recipe_json_ld_block(recipe_id)
        _ncw.update_json_ld_block(block_id, json_ld)

    def append_recipe_json_ld(self, recipe_id: str, json_ld: dict) -> None:
        _ncw.append_json_ld_block(recipe_id, json_ld)

    def create_recipe(
        self,
        recipe: RecipeData,
        image_paths: list[str] | None = None,
    ) -> str:
        return _ncw.create_recipe_page(recipe, image_paths=image_paths)
