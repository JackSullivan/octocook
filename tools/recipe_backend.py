"""Abstract RecipeBackend interface and backend factory."""

from __future__ import annotations

import os
from abc import ABC, abstractmethod

from scraper import RecipeData


class RecipeBackend(ABC):
    @abstractmethod
    def list_recipes(self) -> list[dict]:
        """Return all recipes sorted by title.

        Each entry: {id, title, icon, found_in, rating}.
        """

    @abstractmethod
    def find_recipe(self, title: str) -> dict:
        """Look up a recipe by exact title.

        Returns a dict with at least {id, title, icon}.
        Raises LookupError if not found or ambiguous.
        """

    @abstractmethod
    def get_recipe_metadata(self, recipe_id: str) -> dict:
        """Return lightweight metadata for a recipe.

        Returns {title, icon, found_in, rating, source_url}.
        source_url is the original recipe URL, or None for cookbook recipes.
        Raises LookupError if the recipe does not exist.
        """

    @abstractmethod
    def get_recipe_json_ld(self, recipe_id: str) -> dict:
        """Return the full JSON-LD dict for a recipe.

        Raises LookupError if the recipe has no JSON-LD (not yet ingested or
        the JSON-LD block is missing).
        """

    @abstractmethod
    def update_recipe_json_ld(self, recipe_id: str, json_ld: dict) -> None:
        """Overwrite the stored JSON-LD for a recipe."""

    @abstractmethod
    def append_recipe_json_ld(self, recipe_id: str, json_ld: dict) -> None:
        """Embed JSON-LD for a recipe that has none (enrichment recovery path)."""

    @abstractmethod
    def create_recipe(
        self,
        recipe: RecipeData,
        image_paths: list[str] | None = None,
    ) -> str:
        """Persist a new recipe. Returns a human-readable location string."""


def get_backend() -> RecipeBackend:
    """Instantiate the backend selected by OCTOCOOK_BACKEND (default: notion)."""
    name = os.environ.get("OCTOCOOK_BACKEND", "notion").lower()
    if name == "sqlite":
        from sqlite_backend import SQLiteRecipeBackend
        return SQLiteRecipeBackend()
    from notion_backend import NotionRecipeBackend
    return NotionRecipeBackend()
