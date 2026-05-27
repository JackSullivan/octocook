"""Octocook backend.

Exposes recipe selection, kitchen presets, scheduling, and per-step
progress endpoints over the existing tools/ Python modules (scheduler,
recipe_backend) and a small SQLite store.

Run:
    cd server && ../.venv/bin/uvicorn app:app --reload --port 8000

Set OCTOCOOK_BACKEND=sqlite in tools/.env (or the environment) to use
the local SQLite recipe store instead of Notion.
"""

from __future__ import annotations

import os
import re
import sys
from pathlib import Path

from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field

# Make tools/ importable so we can reuse scheduler + backends without copying.
_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_ROOT / "tools"))

load_dotenv(_ROOT / "tools" / ".env")

from recipe_backend import RecipeBackend, get_backend  # noqa: E402
from scraper import scrape_recipe  # noqa: E402
from scheduler import (  # noqa: E402
    Inventory,
    Step,
    SubstitutionGraph,
    UnsupportedToolError,
    schedule_to_dict,
    solve,
)
from recipe_enrichment import enrich_recipe as run_enrichment  # noqa: E402

import db  # noqa: E402
import presets  # noqa: E402

_backend: RecipeBackend = get_backend()
_BACKEND_NAME = os.environ.get("OCTOCOOK_BACKEND", "notion").lower()

app = FastAPI(title="Octocook API")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.on_event("startup")
def _startup() -> None:
    db.init_db()


def _slugify(name: str) -> str:
    s = re.sub(r"[^a-zA-Z0-9]+", "_", name).strip("_").lower()
    return s or "recipe"


def _load_recipe_steps(recipe_id: str) -> tuple[list[Step], str, str, bool]:
    """Return (steps, title, icon, enriched). When not enriched, steps is empty."""
    try:
        meta = _backend.get_recipe_metadata(recipe_id)
    except LookupError as e:
        raise HTTPException(status_code=404, detail=str(e))

    title, icon = meta["title"], meta["icon"]

    try:
        json_ld = _backend.get_recipe_json_ld(recipe_id)
    except LookupError:
        return [], title, icon, False

    cook_steps = json_ld.get("cookSteps")
    if not cook_steps:
        return [], title, icon, False

    short_id = recipe_id.replace("-", "")[:8]
    slug = f"{_slugify(title)}_{short_id}"
    steps = [
        Step(
            id=f"{slug}.{raw['id']}",
            recipe=title,
            description=raw["description"],
            duration_min=int(raw["duration_min"]),
            active=bool(raw["active"]),
            tools=list(raw.get("tools", [])),
            depends_on=[f"{slug}.{d}" for d in raw.get("depends_on", [])],
            ingredients=list(raw.get("ingredients", [])),
        )
        for raw in cook_steps
    ]
    return steps, title, icon, True


# ----- Schemas -----

class RecipeOut(BaseModel):
    id: str
    title: str
    icon: str
    found_in: str = ""
    rating: str = ""


class RecipeDetail(BaseModel):
    id: str
    title: str
    icon: str
    found_in: str = ""
    rating: str = ""
    ingredients: list[str] = []
    step_count: int = 0
    enriched: bool = False


class IngestIn(BaseModel):
    url: str


class KitchenOut(BaseModel):
    name: str


class KitchenDetail(BaseModel):
    name: str
    inventory: dict[str, int]
    substitutions_yaml: str


class KitchenIn(BaseModel):
    inventory: dict[str, int]
    substitutions_yaml: str


class KitchenCreateIn(KitchenIn):
    name: str


class CreateSessionIn(BaseModel):
    recipe_ids: list[str] = Field(min_length=1)
    kitchen: str
    num_cooks: int = Field(ge=1, le=8)


class StepDoneIn(BaseModel):
    actual_seconds: int | None = None


# ----- Routes -----

@app.get("/config")
def get_config() -> dict:
    return {"backend": _BACKEND_NAME}


@app.get("/recipes", response_model=list[RecipeOut])
def get_recipes() -> list[RecipeOut]:
    try:
        return [
            RecipeOut(
                id=r["id"],
                title=r["title"],
                icon=r["icon"],
                found_in=r.get("found_in", ""),
                rating=r.get("rating", ""),
            )
            for r in _backend.list_recipes()
        ]
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Recipe lookup failed: {e}")


@app.get("/recipes/{recipe_id}", response_model=RecipeDetail)
def get_recipe_detail(recipe_id: str) -> RecipeDetail:
    try:
        meta = _backend.get_recipe_metadata(recipe_id)
    except LookupError as e:
        raise HTTPException(status_code=404, detail=str(e))

    ingredients: list[str] = []
    step_count = 0
    enriched = False

    try:
        json_ld = _backend.get_recipe_json_ld(recipe_id)
        ingredients = json_ld.get("recipeIngredient", [])
        cook_steps = json_ld.get("cookSteps", [])
        step_count = len(cook_steps)
        enriched = bool(cook_steps)
    except LookupError:
        pass

    return RecipeDetail(
        id=recipe_id,
        title=meta["title"],
        icon=meta["icon"],
        found_in=meta.get("found_in", ""),
        rating=meta.get("rating", ""),
        ingredients=ingredients,
        step_count=step_count,
        enriched=enriched,
    )


@app.post("/recipes/ingest", response_model=RecipeOut)
def post_ingest_recipe(body: IngestIn) -> RecipeOut:
    if _BACKEND_NAME != "sqlite":
        raise HTTPException(
            status_code=400,
            detail="Recipe ingestion via the API is only available in SQLite mode. "
                   "Use tools/add_recipe.py for Notion-backed ingestion.",
        )
    try:
        recipe_data = scrape_recipe(body.url)
    except Exception as e:
        raise HTTPException(status_code=422, detail=f"Could not scrape URL: {e}")

    try:
        location = _backend.create_recipe(recipe_data)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to save recipe: {e}")

    recipe_id = location.removeprefix("sqlite:")
    try:
        meta = _backend.get_recipe_metadata(recipe_id)
    except LookupError as e:
        raise HTTPException(status_code=500, detail=str(e))

    return RecipeOut(
        id=recipe_id,
        title=meta["title"],
        icon=meta["icon"],
        found_in=meta.get("found_in", ""),
        rating=meta.get("rating", ""),
    )


@app.post("/recipes/{recipe_id}/enrich")
def post_enrich_recipe(recipe_id: str) -> dict:
    """Run cookSteps enrichment for a recipe and write the result back.

    If the recipe has no JSON-LD content yet, attempts to recover by scraping
    the recipe's source URL (if available) and embedding the JSON-LD first.
    """
    try:
        meta = _backend.get_recipe_metadata(recipe_id)
    except LookupError as e:
        raise HTTPException(status_code=404, detail=str(e))

    title = meta["title"]

    try:
        json_ld = _backend.get_recipe_json_ld(recipe_id)
    except LookupError:
        source_url = meta.get("source_url")
        if not source_url:
            raise HTTPException(
                status_code=400,
                detail=(
                    f"Recipe {title!r} has no recipe content and no source URL to "
                    "scrape. Re-add it via tools/add_recipe.py."
                ),
            )
        try:
            recipe_data = scrape_recipe(source_url)
        except Exception as e:
            raise HTTPException(
                status_code=500,
                detail=f"Couldn't scrape source URL {source_url}: {e}",
            )
        json_ld = recipe_data.json_ld
        _backend.append_recipe_json_ld(recipe_id, json_ld)

    inv_path = _ROOT / "tools" / "inventory.yaml"
    subs_path = _ROOT / "tools" / "substitutions.yaml"

    try:
        cook_steps = run_enrichment(
            json_ld,
            inventory_path=inv_path,
            substitutions_path=subs_path,
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Enrichment failed: {e}")

    json_ld["cookSteps"] = cook_steps
    _backend.update_recipe_json_ld(recipe_id, json_ld)
    return {"title": title, "step_count": len(cook_steps)}


@app.get("/kitchens", response_model=list[KitchenOut])
def get_kitchens() -> list[KitchenOut]:
    return [KitchenOut(name=p.name) for p in presets.list_kitchens()]


@app.get("/kitchens/{name}", response_model=KitchenDetail)
def get_kitchen_detail(name: str) -> KitchenDetail:
    try:
        data = presets.read_kitchen(name)
    except KeyError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    return KitchenDetail(**data)


@app.post("/kitchens", response_model=KitchenDetail)
def post_create_kitchen(body: KitchenCreateIn) -> KitchenDetail:
    if presets.kitchen_exists(body.name):
        raise HTTPException(status_code=409, detail=f"Kitchen {body.name!r} already exists.")
    try:
        presets.write_kitchen(body.name, body.inventory, body.substitutions_yaml)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    return KitchenDetail(**presets.read_kitchen(body.name))


@app.put("/kitchens/{name}", response_model=KitchenDetail)
def put_update_kitchen(name: str, body: KitchenIn) -> KitchenDetail:
    if not presets.kitchen_exists(name):
        raise HTTPException(status_code=404, detail=f"Kitchen {name!r} not found.")
    try:
        presets.write_kitchen(name, body.inventory, body.substitutions_yaml)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    return KitchenDetail(**presets.read_kitchen(name))


@app.delete("/kitchens/{name}")
def delete_kitchen_route(name: str) -> dict:
    remaining = [p.name for p in presets.list_kitchens() if p.name != name]
    if not remaining:
        raise HTTPException(status_code=400, detail="Cannot delete the last remaining kitchen.")
    try:
        presets.delete_kitchen(name)
    except KeyError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    return {"deleted": name}


@app.post("/sessions")
def post_session(body: CreateSessionIn) -> dict:
    try:
        kitchen = presets.get_kitchen(body.kitchen)
    except KeyError as e:
        raise HTTPException(status_code=404, detail=str(e))

    all_steps: list[Step] = []
    icons: dict[str, str] = {}
    titles: list[str] = []
    unenriched: list[dict] = []
    for recipe_id in body.recipe_ids:
        steps, title, icon, enriched = _load_recipe_steps(recipe_id)
        if not enriched:
            unenriched.append({"id": recipe_id, "title": title})
            continue
        all_steps.extend(steps)
        icons[title] = icon
        titles.append(title)

    if unenriched:
        raise HTTPException(
            status_code=400,
            detail={"error": "unenriched_recipes", "recipes": unenriched},
        )

    inventory = Inventory.from_yaml(kitchen.inventory_path)
    subs = SubstitutionGraph.from_yaml(kitchen.substitutions_path)

    try:
        schedule = solve(all_steps, inventory, subs, num_cooks=body.num_cooks)
    except UnsupportedToolError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except RuntimeError as e:
        raise HTTPException(status_code=500, detail=str(e))

    payload = schedule_to_dict(schedule)
    payload["icons"] = icons
    payload["num_cooks"] = body.num_cooks

    session_id = db.create_session(
        recipe_titles=titles,
        kitchen=body.kitchen,
        num_cooks=body.num_cooks,
        schedule=payload,
    )
    return {"session_id": session_id, "schedule": payload}


@app.get("/sessions/{session_id}")
def get_session(session_id: str) -> dict:
    sess = db.get_session(session_id)
    if sess is None:
        raise HTTPException(status_code=404, detail="Session not found.")
    return sess


@app.post("/sessions/{session_id}/steps/{step_id}/start")
def post_step_start(session_id: str, step_id: str) -> dict:
    if db.get_session(session_id) is None:
        raise HTTPException(status_code=404, detail="Session not found.")
    started_at = db.mark_step_started(session_id, step_id)
    return {"started_at": started_at}


@app.post("/sessions/{session_id}/steps/{step_id}/done")
def post_step_done(session_id: str, step_id: str, body: StepDoneIn) -> dict:
    if db.get_session(session_id) is None:
        raise HTTPException(status_code=404, detail="Session not found.")
    return db.mark_step_done(session_id, step_id, actual_seconds=body.actual_seconds)
