#!/usr/bin/env python3
"""CLI: schedule one or more recipes from Notion to minimize total cook time."""

import argparse
import re
import sys

from dotenv import load_dotenv

from notion_client_wrapper import find_recipe_json_ld_block, find_recipe_page
from scheduler import (
    Inventory,
    Step,
    SubstitutionGraph,
    UnsupportedToolError,
    format_schedule,
    solve,
)


def _slugify(name: str) -> str:
    """Compact identifier for use as a step-id prefix."""
    s = re.sub(r"[^a-zA-Z0-9]+", "_", name).strip("_").lower()
    return s or "recipe"


def _load_recipe_steps(title: str) -> list[Step]:
    """Fetch a recipe from Notion and return its cookSteps as Step objects.

    Step ids are namespaced with a recipe slug so they're globally unique
    across the joint schedule.
    """
    page = find_recipe_page(title)
    _, json_ld = find_recipe_json_ld_block(page["id"])
    cook_steps = json_ld.get("cookSteps")
    if not cook_steps:
        raise RuntimeError(
            f"Recipe {title!r} has no cookSteps. "
            f"Run: python enrich_recipe.py {title!r}"
        )

    slug = _slugify(title)
    return [
        Step(
            id=f"{slug}.{raw['id']}",
            recipe=title,
            description=raw["description"],
            duration_min=int(raw["duration_min"]),
            active=bool(raw["active"]),
            tools=list(raw.get("tools", [])),
            depends_on=[f"{slug}.{d}" for d in raw.get("depends_on", [])],
        )
        for raw in cook_steps
    ]


def main():
    parser = argparse.ArgumentParser(
        description=(
            "Build a joint cooking schedule for one or more recipes. "
            "Reads cookSteps from each recipe's Notion page (run enrich_recipe.py first), "
            "then minimizes total time subject to your kitchen inventory."
        ),
    )
    parser.add_argument(
        "titles", nargs="+",
        help="One or more recipe titles in Notion to cook simultaneously.",
    )
    parser.add_argument(
        "--inventory", default="inventory.yaml",
        help="Path to inventory YAML (default: inventory.yaml).",
    )
    parser.add_argument(
        "--substitutions", default="substitutions.yaml",
        help="Path to substitutions YAML (default: substitutions.yaml).",
    )
    args = parser.parse_args()

    load_dotenv()

    all_steps: list[Step] = []
    for title in args.titles:
        print(f"Loading: {title}")
        try:
            all_steps.extend(_load_recipe_steps(title))
        except (LookupError, RuntimeError) as e:
            print(f"Error: {e}", file=sys.stderr)
            sys.exit(1)

    print(f"Loaded {len(all_steps)} steps across {len(args.titles)} recipe(s).\n")

    inventory = Inventory.from_yaml(args.inventory)
    subs = SubstitutionGraph.from_yaml(args.substitutions)

    try:
        schedule = solve(all_steps, inventory, subs)
    except UnsupportedToolError as e:
        print(f"Error: {e}", file=sys.stderr)
        sys.exit(1)

    print(format_schedule(schedule))


if __name__ == "__main__":
    main()
