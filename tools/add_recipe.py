#!/usr/bin/env python3
"""CLI tool to add a recipe from a URL to the Notion recipes database."""

import argparse
import sys

from dotenv import load_dotenv

from scraper import scrape_recipe
from notion_client_wrapper import create_recipe_page


def main():
    parser = argparse.ArgumentParser(
        description="Add a recipe from a URL to the Notion recipes database."
    )
    parser.add_argument("url", help="URL of the recipe page to scrape")
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Scrape and display the recipe without creating a Notion row",
    )
    args = parser.parse_args()

    load_dotenv()

    print(f"Scraping recipe from: {args.url}")
    try:
        recipe = scrape_recipe(args.url)
    except Exception as e:
        print(f"Error scraping recipe: {e}", file=sys.stderr)
        sys.exit(1)

    print(f"\n{'=' * 50}")
    print(f"  Title:        {recipe.title}")
    print(f"  Author:       {recipe.author}")
    print(f"  Active Time:  {recipe.prep_time or '(not found)'}")
    print(f"  Total Time:   {recipe.total_time or '(not found)'}")
    print(f"  Source:       {recipe.source_site}")
    print(f"  Tags:         {', '.join(recipe.tags) or '(none)'}")
    print(f"  Ingredients:  {len(recipe.ingredients)} found")
    for ing in recipe.ingredients:
        print(f"    - {ing}")
    print(f"  JSON-LD:      {'yes' if recipe.json_ld else 'no'}")
    print(f"{'=' * 50}\n")

    if args.dry_run:
        print("Dry run — skipping Notion row creation.")
        return

    print("Creating Notion row...")
    try:
        page_url = create_recipe_page(recipe)
    except Exception as e:
        print(f"Error creating Notion page: {e}", file=sys.stderr)
        sys.exit(1)

    print(f"Done! Notion page: {page_url}")


if __name__ == "__main__":
    main()
