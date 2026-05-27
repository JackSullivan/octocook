"""Extract recipe data from a plain-text description using Claude."""

import anthropic
from pydantic import BaseModel, Field

from scraper import RecipeData


class _Ingredient(BaseModel):
    line: str = Field(
        description=(
            "Full ingredient line exactly as given, including quantities and "
            'units (e.g. "2 cups all-purpose flour", "1 tsp kosher salt").'
        ),
    )
    name: str = Field(
        description=(
            "Just the ingredient name — the food, no quantity, no unit, no prep descriptor. "
            "Lowercase. Examples: \"all-purpose flour\", \"kosher salt\". "
            'For "1½ cups roughly chopped cilantro" → "cilantro". '
            'Drop section headers like "Frosting:" — emit only real ingredients.'
        ),
    )


class _ParsedRecipe(BaseModel):
    """Structured recipe extracted from plain text."""

    title: str = Field(description="Recipe name.")
    author: str = Field(
        default="",
        description="Recipe author or chef if attributed; otherwise empty.",
    )
    prep_time: str = Field(
        default="",
        description='Active/hands-on time, human-readable (e.g. "20 min", "1 hr 15 min"). Empty if not given.',
    )
    total_time: str = Field(
        default="",
        description='Total time including resting/cooking, human-readable. Empty if not given.',
    )
    ingredients: list[_Ingredient] = Field(
        default_factory=list,
        description="Each ingredient as both the full line and the bare ingredient name.",
    )
    instructions: list[str] = Field(
        default_factory=list,
        description="Ordered list of preparation steps, one entry per numbered/bulleted step.",
    )
    tags: list[str] = Field(
        default_factory=list,
        description=(
            "Short descriptive tags — cuisine, course, technique, dietary "
            '(e.g. "italian", "weeknight", "vegetarian", "dessert"). Lowercase, 1-3 words each.'
        ),
    )
    servings: str = Field(
        default="",
        description='Yield or servings as stated (e.g. "Serves 4", "Makes 12 cookies").',
    )


_SYSTEM_PROMPT = """You are extracting a single recipe from plain text provided by the user.

The text may be a pasted web recipe, typed notes, or a rough description. Extract all available fields accurately. Preserve the exact wording of ingredients and instructions where possible — do not paraphrase, summarize, or invent quantities. If a field is not present, leave it empty rather than guessing."""


def parse_recipe_from_text(text: str, source: str = "Text") -> RecipeData:
    """Send plain recipe text to Claude and return a RecipeData object."""
    if not text.strip():
        raise ValueError("Recipe text is empty.")

    client = anthropic.Anthropic()

    message = client.messages.parse(
        model="claude-sonnet-4-6",
        max_tokens=8096,
        system=_SYSTEM_PROMPT,
        messages=[{"role": "user", "content": text}],
        output_format=_ParsedRecipe,
    )
    parsed = message.parsed_output

    full_lines = [i.line for i in parsed.ingredients]
    bare_names = [i.name for i in parsed.ingredients if i.name.strip()]

    json_ld: dict = {
        "@context": "https://schema.org",
        "@type": "Recipe",
        "name": parsed.title,
        "author": parsed.author,
        "recipeIngredient": full_lines,
        "recipeInstructions": parsed.instructions,
        "keywords": parsed.tags,
    }
    if parsed.prep_time:
        json_ld["prepTime"] = parsed.prep_time
    if parsed.total_time:
        json_ld["totalTime"] = parsed.total_time
    if parsed.servings:
        json_ld["recipeYield"] = parsed.servings
    json_ld["sourceText"] = source

    return RecipeData(
        title=parsed.title,
        author=parsed.author,
        url="",
        prep_time=parsed.prep_time,
        total_time=parsed.total_time,
        ingredients=bare_names,
        tags=sorted({t.strip().lower() for t in parsed.tags if t.strip()}),
        source_site=source,
        json_ld=json_ld,
    )
