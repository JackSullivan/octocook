#!/usr/bin/env python3
"""CLI: enrich a recipe in Notion with structured cookSteps for the scheduler."""

import argparse
import json
import sys

from dotenv import load_dotenv

from notion_client_wrapper import (
    find_recipe_json_ld_block,
    find_recipe_page,
    update_json_ld_block,
)
from recipe_enrichment import enrich_recipe


def main():
    parser = argparse.ArgumentParser(
        description=(
            "Decompose a recipe's narrative instructions into structured cookSteps "
            "(duration, tools, dependencies) and write them back into the recipe's "
            "JSON-LD code block on its Notion page."
        ),
    )
    parser.add_argument("title", help="Exact recipe title in Notion.")
    parser.add_argument(
        "--inventory", default="inventory.yaml",
        help="Path to inventory YAML (default: inventory.yaml).",
    )
    parser.add_argument(
        "--substitutions", default="substitutions.yaml",
        help="Path to substitutions YAML (default: substitutions.yaml).",
    )
    parser.add_argument(
        "--dry-run", action="store_true",
        help="Print the proposed cookSteps without writing to Notion.",
    )
    parser.add_argument(
        "-y", "--yes", action="store_true",
        help="Skip the confirmation prompt and write to Notion immediately.",
    )
    parser.add_argument(
        "--force", action="store_true",
        help="Re-enrich even if the recipe already has cookSteps.",
    )
    args = parser.parse_args()

    load_dotenv()

    print(f"Looking up recipe: {args.title}")
    try:
        page = find_recipe_page(args.title)
        block_id, json_ld = find_recipe_json_ld_block(page["id"])
    except LookupError as e:
        print(f"Error: {e}", file=sys.stderr)
        sys.exit(1)

    existing = json_ld.get("cookSteps")
    if existing and not args.force:
        print(
            f"Recipe already has {len(existing)} cookSteps. "
            "Pass --force to re-enrich.",
            file=sys.stderr,
        )
        sys.exit(0)

    print("Calling Claude to extract structured steps...")
    try:
        cook_steps = enrich_recipe(
            json_ld,
            inventory_path=args.inventory,
            substitutions_path=args.substitutions,
        )
    except Exception as e:
        print(f"Error during enrichment: {e}", file=sys.stderr)
        sys.exit(1)

    print(f"\nExtracted {len(cook_steps)} steps:")
    for s in cook_steps:
        kind = "active" if s["active"] else "passive"
        deps = f" (after {','.join(s['depends_on'])})" if s["depends_on"] else ""
        tools = ", ".join(s["tools"]) if s["tools"] else "(no tool)"
        print(
            f"  {s['id']}  {s['duration_min']:>3}m  [{kind:7}]  "
            f"{s['description']}  — {tools}{deps}"
        )

    if args.dry_run:
        print("\nDry run — not writing to Notion.")
        return

    if not args.yes:
        try:
            answer = input("\nWrite these cookSteps to Notion? [y/N]: ").strip().lower()
        except EOFError:
            answer = ""
        if answer not in ("y", "yes"):
            print("Aborted — Notion not modified.")
            return

    json_ld["cookSteps"] = cook_steps
    print("Updating Notion JSON-LD block...")
    update_json_ld_block(block_id, json_ld)
    print(f"Done! Page: {page['url']}")


if __name__ == "__main__":
    main()
