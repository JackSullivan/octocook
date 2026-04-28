"""Notion API client for creating recipe rows in the database."""

import json
import os

from notion_client import Client

from scraper import RecipeData


def get_client() -> Client:
    api_key = os.environ.get("NOTION_API_KEY")
    if not api_key:
        raise RuntimeError("NOTION_API_KEY environment variable is not set")
    return Client(auth=api_key)


def get_database_id() -> str:
    db_id = os.environ.get("NOTION_RECIPES_DB_ID")
    if not db_id:
        raise RuntimeError("NOTION_RECIPES_DB_ID environment variable is not set")
    return db_id


def build_properties(recipe: RecipeData) -> dict:
    """Build the Notion page properties dict from scraped recipe data."""
    props = {}

    # Name (title)
    props["Name"] = {
        "title": [{"text": {"content": recipe.title}}]
    }

    # Rating (select) — default to shrug emoji
    props["Rating"] = {
        "select": {"name": "🤷"}
    }

    # Link (url)
    props["Link"] = {
        "url": recipe.url
    }

    # Tags (multi_select)
    if recipe.tags:
        props["Tags"] = {
            "multi_select": [{"name": tag} for tag in recipe.tags]
        }

    # Active Time (select)
    if recipe.prep_time:
        props["Active Time"] = {
            "select": {"name": recipe.prep_time}
        }

    # Total Time (select)
    if recipe.total_time:
        props["Total Time"] = {
            "select": {"name": recipe.total_time}
        }

    # Notable Ingredients (multi_select)
    if recipe.ingredients:
        # Notion multi-select option names max out at 100 chars
        props["Notable Ingredients"] = {
            "multi_select": [
                {"name": ing[:100]} for ing in recipe.ingredients
            ]
        }

    # Found in (select)
    if recipe.source_site:
        props["Found in"] = {
            "select": {"name": recipe.source_site}
        }

    # Recipe (rich_text) — JSON-LD as a JSON string
    if recipe.json_ld:
        json_str = json.dumps(recipe.json_ld, indent=2, ensure_ascii=False)
        # Notion rich_text blocks max at 2000 chars each
        chunks = [json_str[i:i + 2000] for i in range(0, len(json_str), 2000)]
        props["Recipe"] = {
            "rich_text": [{"text": {"content": chunk}} for chunk in chunks]
        }

    # Referred By (rich_text)
    if recipe.author:
        props["Referred By"] = {
            "rich_text": [{"text": {"content": recipe.author}}]
        }

    return props


def create_recipe_page(recipe: RecipeData) -> str:
    """Create a new page in the Notion recipes database. Returns the page URL."""
    client = get_client()
    db_id = get_database_id()
    properties = build_properties(recipe)

    page = client.pages.create(
        parent={"database_id": db_id},
        properties=properties,
    )

    return page["url"]
