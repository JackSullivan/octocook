"""Octocook backend.

Exposes recipe selection, kitchen presets, scheduling, and per-step
progress endpoints over the existing tools/ Python modules (scheduler,
notion_client_wrapper) and a small SQLite store.

Run:
    cd server && ../.venv/bin/uvicorn app:app --reload --port 8000
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field

# Make tools/ importable so we can reuse scheduler + Notion client without copying.
_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_ROOT / "tools"))

load_dotenv(_ROOT / "tools" / ".env")

from notion_client_wrapper import (  # noqa: E402
    append_json_ld_block,
    find_recipe_json_ld_block,
    get_client,
    list_recipes,
    update_json_ld_block,
)
from recipe_enrichment import enrich_recipe as run_enrichment  # noqa: E402
from scraper import scrape_recipe  # noqa: E402
from scheduler import (  # noqa: E402
    Inventory,
    Step,
    SubstitutionGraph,
    UnsupportedToolError,
    schedule_to_dict,
    solve,
)

import db  # noqa: E402
import presets  # noqa: E402


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


def _fetch_recipe_page(page_id: str) -> tuple[dict, str, str, str, dict | None, str | None]:
    """Return (page, title, icon, block_id, json_ld, error) for a recipe.

    If the page is missing or has no title, raises HTTPException.
    If the JSON-LD block is missing, returns it as None.
    """
    client = get_client()
    try:
        page = client.pages.retrieve(page_id=page_id)
    except Exception as e:
        raise HTTPException(status_code=404, detail=f"Recipe not found: {e}")

    name_prop = page.get("properties", {}).get("Name", {})
    title_parts = name_prop.get("title") or []
    title = "".join(t.get("plain_text", "") for t in title_parts).strip()
    if not title:
        raise HTTPException(status_code=400, detail=f"Recipe page {page_id} has no title.")

    icon = ""
    page_icon = page.get("icon") or {}
    if page_icon.get("type") == "emoji":
        icon = page_icon.get("emoji", "")
    icon = icon or "🍽️"

    try:
        block_id, json_ld = find_recipe_json_ld_block(page_id)
        return page, title, icon, block_id, json_ld, None
    except LookupError as e:
        return page, title, icon, "", None, str(e)


def _load_recipe_steps(page_id: str) -> tuple[list[Step], str, str, bool]:
    """Return (steps, title, icon, enriched). When not enriched, steps is empty.

    Step ids are namespaced with both the title slug AND a short page-id
    suffix so two recipes sharing a title (e.g. multiple "Banana Bread"
    pages) don't produce colliding step ids in a joint schedule.
    """
    _, title, icon, _, json_ld, err = _fetch_recipe_page(page_id)
    if err is not None or json_ld is None:
        # No JSON-LD block at all — treat as unenriched so the caller can
        # surface the enrichment flow.
        return [], title, icon, False

    cook_steps = json_ld.get("cookSteps")
    if not cook_steps:
        return [], title, icon, False

    short_id = page_id.replace("-", "")[:8]
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

@app.get("/recipes", response_model=list[RecipeOut])
def get_recipes() -> list[RecipeOut]:
    try:
        return [
            RecipeOut(
                id=r["page_id"],
                title=r["title"],
                icon=r["icon"],
                found_in=r.get("found_in", ""),
                rating=r.get("rating", ""),
            )
            for r in list_recipes()
        ]
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Notion lookup failed: {e}")


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
    for page_id in body.recipe_ids:
        steps, title, icon, enriched = _load_recipe_steps(page_id)
        if not enriched:
            unenriched.append({"id": page_id, "title": title})
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


@app.post("/recipes/{page_id}/enrich")
def post_enrich_recipe(page_id: str) -> dict:
    """Run cookSteps enrichment for a recipe and write the result back to Notion.

    If the recipe page has no JSON-LD code block yet (older recipes that
    predate the structured-body workflow), we attempt to recover by scraping
    the page's `Link` URL and embedding the JSON-LD before enriching.
    """
    page, title, _, block_id, json_ld, err = _fetch_recipe_page(page_id)

    if err is not None or json_ld is None:
        # No JSON-LD block. Look for a Link property to scrape.
        link_prop = page.get("properties", {}).get("Link", {}) or {}
        url = link_prop.get("url")
        if not url:
            raise HTTPException(
                status_code=400,
                detail=(
                    f"Recipe {title!r} has no recipe content on the Notion page and "
                    "no source URL to scrape. Re-add it via tools/add_recipe.py."
                ),
            )
        try:
            recipe_data = scrape_recipe(url)
        except Exception as e:
            raise HTTPException(
                status_code=500,
                detail=f"Couldn't scrape source URL {url}: {e}",
            )
        json_ld = recipe_data.json_ld
        block_id = append_json_ld_block(page_id, json_ld)

    # Use the default kitchen preset for the tool vocabulary — it's the most
    # comprehensive list and matches what the CLI does today.
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
    update_json_ld_block(block_id, json_ld)
    return {"title": title, "step_count": len(cook_steps)}


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
