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


_ICON_KEYWORDS: list[tuple[str, str]] = [
    # Order matters: more specific keywords first.
    ("pizza", "🍕"),
    ("spaghetti", "🍝"),
    ("pasta", "🍝"),
    ("ramen", "🍜"),
    ("noodle", "🍜"),
    ("burger", "🍔"),
    ("sandwich", "🥪"),
    ("taco", "🌮"),
    ("burrito", "🌯"),
    ("sushi", "🍣"),
    ("dumpling", "🥟"),
    ("paneer", "🍛"),
    ("curry", "🍛"),
    ("biryani", "🍛"),
    ("dal", "🍛"),
    ("indian", "🍛"),
    ("rice", "🍚"),
    ("risotto", "🍚"),
    ("soup", "🍲"),
    ("stew", "🍲"),
    ("chili", "🌶️"),
    ("salad", "🥗"),
    ("bread", "🍞"),
    ("toast", "🍞"),
    ("bagel", "🥯"),
    ("pancake", "🥞"),
    ("waffle", "🧇"),
    ("omelette", "🍳"),
    ("egg", "🥚"),
    ("breakfast", "🍳"),
    ("cake", "🍰"),
    ("cupcake", "🧁"),
    ("cookie", "🍪"),
    ("brownie", "🍫"),
    ("pie", "🥧"),
    ("ice cream", "🍦"),
    ("donut", "🍩"),
    ("doughnut", "🍩"),
    ("chocolate", "🍫"),
    ("chicken", "🍗"),
    ("turkey", "🦃"),
    ("steak", "🥩"),
    ("beef", "🥩"),
    ("bacon", "🥓"),
    ("pork", "🥓"),
    ("salmon", "🐟"),
    ("tuna", "🐟"),
    ("fish", "🐟"),
    ("shrimp", "🍤"),
    ("crab", "🦀"),
    ("lobster", "🦞"),
    ("seafood", "🦐"),
    ("mushroom", "🍄"),
    ("potato", "🥔"),
    ("tomato", "🍅"),
    ("avocado", "🥑"),
    ("vegan", "🥬"),
    ("vegetarian", "🥕"),
    ("vegetable", "🥦"),
    ("smoothie", "🥤"),
    ("cocktail", "🍹"),
    ("tea", "🍵"),
    ("coffee", "☕"),
    ("drink", "🍸"),
]


def _pick_icon(recipe: RecipeData) -> str:
    """Best-guess emoji icon based on recipe title and tags."""
    haystack = " ".join([recipe.title or "", *(recipe.tags or [])]).lower()
    for keyword, emoji in _ICON_KEYWORDS:
        if keyword in haystack:
            return emoji
    return "🍽️"


def _chunk_utf16(s: str, max_units: int = 2000) -> list[str]:
    """Split s into chunks no longer than max_units UTF-16 code units each.

    Notion's rich_text length limit is measured in UTF-16 code units, so a
    character outside the BMP (e.g. some emoji) counts as 2.
    """
    chunks: list[str] = []
    current: list[str] = []
    current_units = 0
    for ch in s:
        units = 2 if ord(ch) > 0xFFFF else 1
        if current_units + units > max_units:
            chunks.append("".join(current))
            current = [ch]
            current_units = units
        else:
            current.append(ch)
            current_units += units
    if current:
        chunks.append("".join(current))
    return chunks


def build_properties(recipe: RecipeData) -> dict:
    """Build the Notion page properties dict from scraped recipe data."""
    props = {}

    # Name (title)
    props["Name"] = {
        "title": [{"text": {"content": recipe.title}}]
    }

    # Rating (select) — default to man-shrugging emoji
    props["Rating"] = {
        "select": {"name": "🤷‍♂️"}
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

    # Notable Ingredients (multi_select) — Notion forbids commas in option
    # names, so split each ingredient on commas and treat each piece as its
    # own tag. Dedupe while preserving order.
    if recipe.ingredients:
        seen: set[str] = set()
        tags: list[str] = []
        for ing in recipe.ingredients:
            for piece in ing.split(","):
                name = piece.strip()[:100]
                if name and name not in seen:
                    seen.add(name)
                    tags.append(name)
        if tags:
            props["Notable Ingredients"] = {
                "multi_select": [{"name": name} for name in tags]
            }

    # Found in (select)
    if recipe.source_site:
        props["Found in"] = {
            "select": {"name": recipe.source_site}
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
        icon={"type": "emoji", "emoji": _pick_icon(recipe)},
    )

    if recipe.json_ld:
        json_str = json.dumps(recipe.json_ld, indent=2, ensure_ascii=False)
        chunks = _chunk_utf16(json_str, 2000)
        client.blocks.children.append(
            block_id=page["id"],
            children=[{
                "object": "block",
                "type": "code",
                "code": {
                    "language": "json",
                    "rich_text": [
                        {"type": "text", "text": {"content": chunk}}
                        for chunk in chunks
                    ],
                },
            }],
        )

    return page["url"]
