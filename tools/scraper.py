"""Recipe extraction from URLs using recipe-scrapers and JSON-LD parsing."""

import json
import re
from dataclasses import dataclass, field
from urllib.parse import urlparse

import requests
from bs4 import BeautifulSoup
from recipe_scrapers import scrape_html


@dataclass
class RecipeData:
    title: str = ""
    author: str = ""
    url: str = ""
    prep_time: str = ""
    total_time: str = ""
    ingredients: list[str] = field(default_factory=list)
    tags: list[str] = field(default_factory=list)
    source_site: str = ""
    json_ld: dict = field(default_factory=dict)


def fetch_page(url: str) -> str:
    headers = {
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/120.0.0.0 Safari/537.36"
        )
    }
    resp = requests.get(url, headers=headers, timeout=15)
    resp.raise_for_status()
    return resp.text


def extract_json_ld_recipe(html: str) -> dict | None:
    """Extract the JSON-LD Recipe object from the page HTML."""
    soup = BeautifulSoup(html, "html.parser")
    for script in soup.find_all("script", type="application/ld+json"):
        try:
            data = json.loads(script.string)
        except (json.JSONDecodeError, TypeError):
            continue

        # Could be a single object or a list
        candidates = data if isinstance(data, list) else [data]
        for item in candidates:
            if isinstance(item, dict):
                if item.get("@type") == "Recipe":
                    return item
                # Check @graph arrays (common pattern)
                if "@graph" in item:
                    for node in item["@graph"]:
                        if isinstance(node, dict) and node.get("@type") == "Recipe":
                            return node
    return None


def format_duration(minutes: str | int | None) -> str:
    """Format minutes into a human-readable duration string."""
    if not minutes:
        return ""
    try:
        mins = int(minutes)
    except (ValueError, TypeError):
        return str(minutes)

    if mins < 60:
        return f"{mins} min"
    hours = mins // 60
    remaining = mins % 60
    if remaining == 0:
        return f"{hours} hr" if hours == 1 else f"{hours} hrs"
    return f"{hours} hr {remaining} min" if hours == 1 else f"{hours} hrs {remaining} min"


def normalize_ingredient(ingredient: str) -> str:
    """Strip quantities, units, and parentheticals from an ingredient string."""
    # Remove parenthetical notes like "(about 2 cups)" or "(optional)"
    text = re.sub(r"\(.*?\)", "", ingredient)
    # Remove leading quantities: numbers, fractions, ranges
    text = re.sub(
        r"^[\d½⅓⅔¼¾⅕⅖⅗⅘⅙⅚⅛⅜⅝⅞/.\-–\s]+", "", text
    )
    # Remove common units
    units = (
        r"\b(cups?|tablespoons?|tbsp|teaspoons?|tsp|ounces?|oz|pounds?|lbs?|"
        r"grams?|g|kilograms?|kg|milliliters?|ml|liters?|l|pinch(?:es)?|"
        r"dash(?:es)?|cloves?|stalks?|sprigs?|bunche?s?|cans?|packages?|"
        r"pieces?|slices?|heads?|large|medium|small|whole|fresh|dried|"
        r"chopped|minced|diced|sliced|crushed|ground|packed)\b"
    )
    text = re.sub(units, "", text, flags=re.IGNORECASE)
    # Remove "of" if it's the first word now
    text = re.sub(r"^\s*of\s+", "", text, flags=re.IGNORECASE)
    # Clean up whitespace and punctuation
    text = re.sub(r"\s*,\s*$", "", text)
    text = re.sub(r"\s+", " ", text).strip().lower()
    return text


def extract_tags(scraper, json_ld: dict | None) -> list[str]:
    """Derive tags from recipe metadata."""
    tags = set()

    # From JSON-LD
    if json_ld:
        for key in ("recipeCategory", "recipeCuisine", "keywords"):
            val = json_ld.get(key)
            if isinstance(val, str):
                for item in val.split(","):
                    item = item.strip()
                    if item:
                        tags.add(item.lower())
            elif isinstance(val, list):
                for item in val:
                    if isinstance(item, str) and item.strip():
                        tags.add(item.strip().lower())

    # From scraper as fallback
    try:
        category = scraper.category()
        if category:
            tags.add(category.strip().lower())
    except (AttributeError, NotImplementedError):
        pass

    try:
        cuisine = scraper.cuisine()
        if cuisine:
            tags.add(cuisine.strip().lower())
    except (AttributeError, NotImplementedError):
        pass

    return sorted(tags)


def scrape_recipe(url: str) -> RecipeData:
    """Scrape a recipe from the given URL and return structured data."""
    html = fetch_page(url)
    scraper = scrape_html(html, org_url=url, wild_mode=True)
    json_ld = extract_json_ld_recipe(html)

    # Build JSON-LD Recipe object — use the raw one if available,
    # otherwise construct a minimal one from scraped fields
    if json_ld:
        recipe_obj = json_ld
    else:
        recipe_obj = {
            "@context": "https://schema.org",
            "@type": "Recipe",
            "name": scraper.title(),
            "author": scraper.author(),
            "recipeIngredient": scraper.ingredients(),
            "recipeInstructions": scraper.instructions(),
        }
        try:
            recipe_obj["prepTime"] = scraper.prep_time()
        except (AttributeError, NotImplementedError):
            pass
        try:
            recipe_obj["totalTime"] = scraper.total_time()
        except (AttributeError, NotImplementedError):
            pass

    # Extract individual fields
    raw_ingredients = scraper.ingredients()
    normalized = []
    for ing in raw_ingredients:
        normed = normalize_ingredient(ing)
        if normed and len(normed) > 1:
            normalized.append(normed)
    # Deduplicate while preserving order
    seen = set()
    unique_ingredients = []
    for ing in normalized:
        if ing not in seen:
            seen.add(ing)
            unique_ingredients.append(ing)

    # Source site name
    parsed = urlparse(url)
    domain = parsed.netloc.removeprefix("www.")
    # Prettify common domains
    site_names = {
        "seriouseats.com": "Serious Eats",
        "bonappetit.com": "Bon Appetit",
        "nytimes.com": "NYT Cooking",
        "cooking.nytimes.com": "NYT Cooking",
        "food52.com": "Food52",
        "epicurious.com": "Epicurious",
        "allrecipes.com": "Allrecipes",
        "foodnetwork.com": "Food Network",
        "budgetbytes.com": "Budget Bytes",
        "thekitchn.com": "The Kitchn",
        "smittenkitchen.com": "Smitten Kitchen",
        "kingarthurbaking.com": "King Arthur Baking",
    }
    source_site = site_names.get(domain, domain)

    # Times
    try:
        prep = format_duration(scraper.prep_time())
    except (AttributeError, NotImplementedError):
        prep = ""
    try:
        total = format_duration(scraper.total_time())
    except (AttributeError, NotImplementedError):
        total = ""

    # Author
    author = scraper.author() or ""

    return RecipeData(
        title=scraper.title(),
        author=author,
        url=url,
        prep_time=prep,
        total_time=total,
        ingredients=unique_ingredients,
        tags=extract_tags(scraper, json_ld),
        source_site=source_site,
        json_ld=recipe_obj,
    )
