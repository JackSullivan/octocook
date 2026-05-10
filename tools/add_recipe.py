#!/usr/bin/env python3
"""CLI tool to add a recipe to the Notion recipes database.

Accepts either a single recipe URL or one-or-more image files (cookbook photos).
"""

import argparse
import os
import sys

from dotenv import load_dotenv

from scraper import RecipeData, scrape_recipe
from notion_client_wrapper import create_recipe_page


_IMAGE_EXTS = {".jpg", ".jpeg", ".png", ".gif", ".webp"}


def _looks_like_url(arg: str) -> bool:
    return arg.startswith(("http://", "https://"))


def _looks_like_image(arg: str) -> bool:
    return os.path.splitext(arg)[1].lower() in _IMAGE_EXTS


def _print_recipe(recipe: RecipeData) -> None:
    print(f"\n{'=' * 50}")
    print(f"  Title:        {recipe.title}")
    print(f"  Author:       {recipe.author}")
    print(f"  Active Time:  {recipe.prep_time or '(not found)'}")
    print(f"  Total Time:   {recipe.total_time or '(not found)'}")
    print(f"  Source:       {recipe.source_site}")
    if recipe.url:
        print(f"  URL:          {recipe.url}")
    print(f"  Tags:         {', '.join(recipe.tags) or '(none)'}")
    print(f"  Ingredients:  {len(recipe.ingredients)} found")
    for ing in recipe.ingredients:
        print(f"    - {ing}")
    print(f"  JSON-LD:      {'yes' if recipe.json_ld else 'no'}")
    print(f"{'=' * 50}\n")


def _confirm() -> bool:
    try:
        answer = input("Create Notion page? [y/N]: ").strip().lower()
    except EOFError:
        return False
    return answer in ("y", "yes")


def main():
    parser = argparse.ArgumentParser(
        description=(
            "Add a recipe to the Notion recipes database. "
            "Pass a recipe URL, or one or more cookbook image files."
        ),
    )
    parser.add_argument(
        "inputs",
        nargs="+",
        help="A recipe URL, or one or more image file paths.",
    )
    parser.add_argument(
        "--source",
        default="Cookbook",
        help='Source label for image-based recipes (e.g. cookbook name). Default: "Cookbook".',
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Parse and display the recipe without creating a Notion row.",
    )
    parser.add_argument(
        "-y", "--yes",
        action="store_true",
        help="Skip the confirmation prompt and write to Notion immediately.",
    )
    args = parser.parse_args()

    load_dotenv()

    urls = [a for a in args.inputs if _looks_like_url(a)]
    images = [a for a in args.inputs if not _looks_like_url(a)]

    if urls and images:
        print(
            "Error: mix of URLs and image paths. Pass either a single URL or only image paths.",
            file=sys.stderr,
        )
        sys.exit(2)

    image_paths_for_upload: list[str] = []

    if urls:
        if len(urls) > 1:
            print("Error: pass at most one URL.", file=sys.stderr)
            sys.exit(2)
        url = urls[0]
        print(f"Scraping recipe from: {url}")
        try:
            recipe = scrape_recipe(url)
        except Exception as e:
            print(f"Error scraping recipe: {e}", file=sys.stderr)
            sys.exit(1)
    else:
        for p in images:
            if not os.path.isfile(p):
                print(f"Error: not a file: {p}", file=sys.stderr)
                sys.exit(2)
            if not _looks_like_image(p):
                print(
                    f"Error: unsupported image extension on {p}. "
                    f"Supported: {sorted(_IMAGE_EXTS)}",
                    file=sys.stderr,
                )
                sys.exit(2)

        from vision_recipe import parse_recipe_from_images

        print(f"Parsing {len(images)} image(s) with Claude vision...")
        try:
            recipe = parse_recipe_from_images(images, source=args.source)
        except Exception as e:
            print(f"Error parsing recipe from images: {e}", file=sys.stderr)
            sys.exit(1)
        image_paths_for_upload = images

    _print_recipe(recipe)

    if args.dry_run:
        print("Dry run — skipping Notion row creation.")
        return

    if not args.yes and not _confirm():
        print("Aborted — no Notion page created.")
        return

    print("Creating Notion row...")
    try:
        page_url = create_recipe_page(recipe, image_paths=image_paths_for_upload or None)
    except Exception as e:
        print(f"Error creating Notion page: {e}", file=sys.stderr)
        sys.exit(1)

    print(f"Done! Notion page: {page_url}")


if __name__ == "__main__":
    main()
