"""Notion API client for creating recipe rows in the database."""

import json
import mimetypes
import os

from notion_client import Client
from notion_client.helpers import iterate_paginated_api

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

    # Link (url) — only set when we actually have one (cookbook recipes have none)
    if recipe.url:
        props["Link"] = {"url": recipe.url}

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


def _upload_file_to_notion(client: Client, path: str) -> str:
    """Upload a single local file to Notion and return its file_upload id.

    Uses Notion's single-part File Upload API (suitable for files <= 20 MB).
    """
    filename = os.path.basename(path)
    content_type, _ = mimetypes.guess_type(filename)
    if content_type is None:
        content_type = "application/octet-stream"

    upload = client.file_uploads.create(mode="single_part", filename=filename)
    with open(path, "rb") as f:
        client.file_uploads.send(
            file_upload_id=upload["id"],
            file=(filename, f, content_type),
        )
    return upload["id"]


def create_recipe_page(
    recipe: RecipeData,
    image_paths: list[str] | None = None,
) -> str:
    """Create a new page in the Notion recipes database. Returns the page URL.

    If image_paths is provided, each image is uploaded to Notion and appended
    as an image block on the new page (alongside the JSON-LD code block).
    """
    client = get_client()
    db_id = get_database_id()
    properties = build_properties(recipe)

    page = client.pages.create(
        parent={"database_id": db_id},
        properties=properties,
        icon={"type": "emoji", "emoji": _pick_icon(recipe)},
    )

    children: list[dict] = []

    if image_paths:
        for path in image_paths:
            file_upload_id = _upload_file_to_notion(client, path)
            children.append({
                "object": "block",
                "type": "image",
                "image": {
                    "type": "file_upload",
                    "file_upload": {"id": file_upload_id},
                },
            })

    if recipe.json_ld:
        json_str = json.dumps(recipe.json_ld, indent=2, ensure_ascii=False)
        chunks = _chunk_utf16(json_str, 2000)
        children.append({
            "object": "block",
            "type": "code",
            "code": {
                "language": "json",
                "rich_text": [
                    {"type": "text", "text": {"content": chunk}}
                    for chunk in chunks
                ],
            },
        })

    if children:
        client.blocks.children.append(block_id=page["id"], children=children)

    return page["url"]


def _get_data_source_id(client: Client, db_id: str) -> str:
    """Resolve a database's primary data source id (Notion 2025-09-03 API)."""
    db = client.databases.retrieve(database_id=db_id)
    sources = db.get("data_sources") or []
    if not sources:
        raise RuntimeError(
            f"Database {db_id} has no data sources — cannot query."
        )
    return sources[0]["id"]


def _select_name(prop: dict | None) -> str:
    """Extract the option name from a Notion select property, or empty string."""
    if not prop:
        return ""
    sel = prop.get("select") or {}
    return sel.get("name", "") or ""


def list_recipes() -> list[dict]:
    """Return every recipe in the database, lightest payload first.

    Each entry: {title, icon, found_in, rating, page_id}. icon is the page
    emoji if any, else a placeholder.
    """
    client = get_client()
    db_id = get_database_id()
    data_source_id = _get_data_source_id(client, db_id)

    recipes: list[dict] = []
    for page in iterate_paginated_api(
        client.data_sources.query,
        data_source_id=data_source_id,
    ):
        props = page.get("properties", {}) or {}
        name_prop = props.get("Name", {})
        title_parts = name_prop.get("title") or []
        title = "".join(t.get("plain_text", "") for t in title_parts).strip()
        if not title:
            continue
        icon = ""
        page_icon = page.get("icon") or {}
        if page_icon.get("type") == "emoji":
            icon = page_icon.get("emoji", "")
        recipes.append({
            "title": title,
            "icon": icon or "🍽️",
            "found_in": _select_name(props.get("Found in")),
            "rating": _select_name(props.get("Rating")),
            "page_id": page["id"],
        })

    recipes.sort(key=lambda r: r["title"].lower())
    return recipes


def find_recipe_page(title: str) -> dict:
    """Look up a recipe page by exact title. Returns the page object."""
    client = get_client()
    db_id = get_database_id()
    data_source_id = _get_data_source_id(client, db_id)
    result = client.data_sources.query(
        data_source_id=data_source_id,
        filter={"property": "Name", "title": {"equals": title}},
    )
    matches = result.get("results", [])
    if not matches:
        raise LookupError(f"No recipe found with title {title!r}.")
    if len(matches) > 1:
        raise LookupError(
            f"Multiple recipes match {title!r} ({len(matches)} found). "
            "Use a unique title."
        )
    return matches[0]


def find_recipe_json_ld_block(page_id: str) -> tuple[str, dict]:
    """Find the JSON-LD Recipe code block on a page.

    Returns (block_id, parsed_json). Raises LookupError if not found.
    """
    client = get_client()
    for block in iterate_paginated_api(client.blocks.children.list, block_id=page_id):
        if block.get("type") != "code":
            continue
        code = block.get("code", {})
        if code.get("language") != "json":
            continue
        text = "".join(rt.get("text", {}).get("content", "") for rt in code.get("rich_text", []))
        try:
            data = json.loads(text)
        except json.JSONDecodeError:
            continue
        if isinstance(data, dict) and data.get("@type") == "Recipe":
            return block["id"], data
    raise LookupError(f"No JSON-LD Recipe code block found on page {page_id}.")


def update_json_ld_block(block_id: str, json_ld: dict) -> None:
    """Replace the contents of an existing JSON-LD code block in place."""
    client = get_client()
    json_str = json.dumps(json_ld, indent=2, ensure_ascii=False)
    chunks = _chunk_utf16(json_str, 2000)
    client.blocks.update(
        block_id=block_id,
        code={
            "language": "json",
            "rich_text": [
                {"type": "text", "text": {"content": chunk}}
                for chunk in chunks
            ],
        },
    )


def append_json_ld_block(page_id: str, json_ld: dict) -> str:
    """Append a fresh JSON-LD Recipe code block to a page. Returns the new block id.

    Used to retro-fit older recipe pages (which lack the JSON-LD body) so the
    enrichment pipeline can work on them.
    """
    client = get_client()
    json_str = json.dumps(json_ld, indent=2, ensure_ascii=False)
    chunks = _chunk_utf16(json_str, 2000)
    response = client.blocks.children.append(
        block_id=page_id,
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
    return response["results"][0]["id"]
