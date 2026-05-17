"""Decompose a recipe's narrative instructions into structured cook steps.

Calls Claude Sonnet 4.6 with the existing recipe JSON-LD and returns a list
of atomic steps with duration estimates, tool requirements, and dependencies
suitable for the constraint-based scheduler.
"""

from __future__ import annotations

from pathlib import Path

import anthropic
import yaml
from pydantic import BaseModel, Field


_SYSTEM_PROMPT = """You decompose cooking recipes into structured, schedulable steps.

For each recipe you receive (as a JSON-LD Recipe object), produce an ordered list of atomic steps. Each step must be either FULLY ACTIVE (cook is busy the whole time, e.g. chopping, stirring, sauteing) or FULLY PASSIVE (the tool is occupied but the cook is free, e.g. oven baking, dough rising, simmering covered without stirring, OVEN PREHEATING). If a single instruction in the recipe mixes both — e.g. "sear, then simmer covered for 20 min" — split it into separate active and passive steps.

Oven preheats are always PASSIVE — the cook sets the temperature and walks away while the oven warms up. Estimate `duration_min` as the oven's actual warm-up time (typically 10-15 minutes), not the few seconds it takes to press the button.

For each step:

- `id`: a unique-within-recipe identifier like "S0", "S1", "S2", in cooking order.
- `description`: a brief imperative phrase (e.g. "Saute onions until translucent"). Keep it short — under 60 characters.
- `duration_min`: integer minutes for this step alone. Realistic estimates for a competent home cook. If the recipe gives a range, pick the midpoint.
- `active`: true if the cook must be present and working the whole time; false if the cook can walk away (oven, fridge, rising, simmering covered).
- `tools`: list of tool names this step occupies. Use the controlled vocabulary listed below when possible. Omit the cook from this list — the scheduler infers it from `active`. Tools that are essentially always available (spatula, tongs, measuring cups) can be omitted unless they're a real bottleneck.
- `depends_on`: list of step ids that must finish before this step starts. Most steps just depend on the previous one, but you may have parallel preparation (e.g. chopping while water heats).
- `ingredients`: list of ingredient lines this step uses, copied VERBATIM from the recipe's `recipeIngredient` list (with quantities and units exactly as printed, e.g. "1 large onion, diced", "4 cloves garlic, minced"). Attach each ingredient to the step where it's FIRST prepped or measured — typically a chopping, measuring, or mixing step. A later step that combines or cooks already-prepped ingredients should have an empty `ingredients` list (don't repeat them). Technique-only steps (preheating, kneading, baking, resting) also use an empty list. Every ingredient from `recipeIngredient` should appear in exactly one step's list.

Be realistic about parallelism: if a step requires the cook's attention but the previous step was passive (e.g. oven baking), the new step does NOT depend on the bake — they can overlap (the cook works while the oven bakes).

Controlled vocabulary for tool names (use these exact strings when the tool fits):

%s

If a recipe needs a tool not in this vocabulary, use a clear lowercase snake_case name (e.g. "tortilla_press", "dutch_oven"). The scheduler will look it up in the substitutions graph or report it as missing."""


class _StructuredStep(BaseModel):
    id: str = Field(description="Unique within this recipe, e.g. 'S0', 'S1'.")
    description: str = Field(description="Brief imperative phrase under ~60 characters.")
    duration_min: int = Field(description="Integer minutes for this step alone.")
    active: bool = Field(
        description="True = cook is busy the whole time; False = cook is free (oven, rise, simmer)."
    )
    tools: list[str] = Field(
        default_factory=list,
        description="Tools this step occupies. Use controlled vocabulary; omit 'cook'.",
    )
    depends_on: list[str] = Field(
        default_factory=list,
        description="Step ids within the same recipe that must finish first.",
    )
    ingredients: list[str] = Field(
        default_factory=list,
        description=(
            "Ingredient lines copied verbatim from recipeIngredient that this step "
            "introduces. Empty for technique-only or combine steps."
        ),
    )


class _StructuredRecipe(BaseModel):
    cook_steps: list[_StructuredStep] = Field(
        description="Ordered list of atomic, schedulable steps."
    )


def _load_tool_vocabulary(
    inventory_path: str | Path,
    substitutions_path: str | Path,
) -> list[str]:
    """Union of tool names from inventory + substitutions, alphabetized."""
    vocab: set[str] = set()
    with open(inventory_path) as f:
        inv = yaml.safe_load(f) or {}
        vocab.update(str(k) for k in inv.keys())
    with open(substitutions_path) as f:
        subs = yaml.safe_load(f) or {}
        for tool, chain in subs.items():
            vocab.add(str(tool))
            for entry in chain or []:
                if entry.get("tool"):
                    vocab.add(str(entry["tool"]))
    vocab.discard("cook")
    return sorted(vocab)


def _normalize_steps(steps: list[dict]) -> list[dict]:
    """Apply deterministic post-processing to LLM-extracted steps.

    Defensive overrides for known model failure modes — applied even when the
    prompt covers the same case.
    """
    for s in steps:
        # Preheats are always passive — the oven warms up on its own.
        if "preheat" in s["description"].lower():
            s["active"] = False
    return steps


def enrich_recipe(
    recipe_json_ld: dict,
    inventory_path: str | Path = "inventory.yaml",
    substitutions_path: str | Path = "substitutions.yaml",
) -> list[dict]:
    """Return a list of cookStep dicts to attach to the recipe's JSON-LD.

    The returned dicts mirror the scheduler.Step fields and can be embedded
    under the JSON-LD key "cookSteps".
    """
    vocab = _load_tool_vocabulary(inventory_path, substitutions_path)
    system = _SYSTEM_PROMPT % "\n".join(f"  - {t}" for t in vocab)

    import json
    user_text = (
        "Decompose this recipe into structured steps:\n\n"
        f"```json\n{json.dumps(recipe_json_ld, indent=2, ensure_ascii=False)}\n```"
    )

    client = anthropic.Anthropic()
    response = client.messages.parse(
        model="claude-sonnet-4-6",
        max_tokens=8000,
        system=system,
        messages=[{"role": "user", "content": user_text}],
        output_format=_StructuredRecipe,
    )
    parsed: _StructuredRecipe = response.parsed_output
    steps = [step.model_dump() for step in parsed.cook_steps]
    return _normalize_steps(steps)
