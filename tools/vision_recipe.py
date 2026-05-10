"""Extract recipe data from one or more photos of a cookbook page using Claude vision."""

import base64
import os
from pathlib import Path

import anthropic
from pydantic import BaseModel, Field

from scraper import RecipeData


_MIME_BY_EXT = {
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".png": "image/png",
    ".gif": "image/gif",
    ".webp": "image/webp",
}


class _Ingredient(BaseModel):
    line: str = Field(
        description=(
            "Full ingredient line exactly as printed, including quantities and "
            'units (e.g. "2 cups all-purpose flour", "1 tsp kosher salt").'
        ),
    )
    name: str = Field(
        description=(
            "Just the ingredient name itself — the food, no quantity, no unit, "
            "no preparation descriptor. Lowercase. Examples: "
            '"all-purpose flour", "kosher salt", "puff pastry", "cilantro", '
            '"unsalted butter". For "1½ cups roughly chopped cilantro" → "cilantro". '
            'For "1 x 14-oz puff pastry sheet, defrosted" → "puff pastry". '
            'Drop section headers like "Frosting:" — emit only real ingredients.'
        ),
    )


class _ParsedRecipe(BaseModel):
    """Structured recipe extracted from cookbook photos."""

    title: str = Field(description="Recipe name as printed in the cookbook.")
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
        description="Each ingredient as both the full printed line and the bare ingredient name.",
    )
    instructions: list[str] = Field(
        default_factory=list,
        description="Ordered list of preparation steps, one entry per numbered/bulleted step.",
    )
    tags: list[str] = Field(
        default_factory=list,
        description=(
            "Short descriptive tags for the recipe — cuisine, course, technique, dietary "
            '(e.g. "italian", "weeknight", "vegetarian", "dessert"). Lowercase, 1-3 words each.'
        ),
    )
    servings: str = Field(
        default="",
        description='Yield or servings as printed (e.g. "Serves 4", "Makes 12 cookies").',
    )


def _encode_image(path: str) -> dict:
    suffix = Path(path).suffix.lower()
    media_type = _MIME_BY_EXT.get(suffix)
    if media_type is None:
        raise ValueError(
            f"Unsupported image type {suffix!r} for {path}. "
            f"Supported: {sorted(_MIME_BY_EXT)}"
        )
    with open(path, "rb") as f:
        data = base64.standard_b64encode(f.read()).decode("utf-8")
    return {
        "type": "image",
        "source": {"type": "base64", "media_type": media_type, "data": data},
    }


_SYSTEM_PROMPT = """You are extracting a single recipe from photos of a cookbook page.

The user will provide one or more images. They may be:
- Different pages of the same recipe (continuation onto the next page)
- A photo of the recipe text plus a photo of the finished dish
- Close-ups of the ingredient list, instructions, or headnotes

Combine information across all images to produce one complete recipe. Preserve the exact wording of ingredients and instructions where possible — do not paraphrase, summarize, or invent quantities. If a field is not visible in any image, leave it empty rather than guessing."""


def parse_recipe_from_images(
    image_paths: list[str],
    source: str = "Cookbook",
) -> RecipeData:
    """Send the images to Claude and return a RecipeData object.

    `source` is stored as the source-site label in Notion (e.g. cookbook name).
    """
    if not image_paths:
        raise ValueError("At least one image path is required.")

    client = anthropic.Anthropic()

    content: list[dict] = [_encode_image(p) for p in image_paths]
    content.append({
        "type": "text",
        "text": "Extract the recipe from the image(s) above into the structured format.",
    })

    # Stream so we can request a larger max_tokens budget — long cookbook
    # recipes (many spices, many steps) can exceed 16K output tokens, and the
    # SDK refuses non-streaming requests at that size due to HTTP timeouts.
    # The streaming helper doesn't surface a parsed result the way
    # messages.parse() does, so we extract and validate the JSON manually.
    with client.messages.stream(
        model="claude-sonnet-4-6",
        max_tokens=32000,
        system=_SYSTEM_PROMPT,
        messages=[{"role": "user", "content": content}],
        output_format=_ParsedRecipe,
    ) as stream:
        final_message = stream.get_final_message()

    raw_json = next(b.text for b in final_message.content if b.type == "text")
    parsed = _ParsedRecipe.model_validate_json(raw_json)

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
    json_ld["sourceImages"] = [os.path.basename(p) for p in image_paths]
    json_ld["sourceCookbook"] = source

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
