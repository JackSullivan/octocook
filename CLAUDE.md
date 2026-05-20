# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project

Two halves:

- `tools/` — CLIs that ingest recipes, enrich them with structured cook steps, and run the scheduler. Recipe state lives in a Notion database; every CLI both reads from and writes to it.
- `server/` (FastAPI) + `web/` (React + Vite) — the live cooking app. The user picks recipes, a kitchen preset, and a cook count; the backend reuses `tools/scheduler.py` to produce a schedule with a *specific cook assigned to each active step*; the frontend shows each cook their current step, history, and upcoming work, with timers and per-step "Done" marks.

The `tools/` CLIs and the live app share the same Python codebase — `server/app.py` adds `tools/` to `sys.path` rather than copying logic. There is no app server in `README.md`; that section is aspirational and predates this build.

## Setup

Python **3.10+** required (the codebase uses `X | None` union syntax). System Python on macOS is usually 3.9 — use Homebrew's `python@3.12` or similar.

```bash
python3.12 -m venv .venv
.venv/bin/pip install -r tools/requirements.txt -r server/requirements.txt
cp tools/.env.example tools/.env   # fill in NOTION_API_KEY, NOTION_RECIPES_DB_ID, ANTHROPIC_API_KEY

cd web && npm install
```

`server/app.py` calls `load_dotenv(.../tools/.env)`, so the Notion credentials live in `tools/.env` and are shared with the CLIs.

The Notion integration must be shared with the recipes database, and the database is expected to have these properties: `Name` (title), `Rating` (select), `Link` (url), `Tags` (multi-select), `Active Time` (select), `Total Time` (select), `Notable Ingredients` (multi-select), `Found in` (select), `Referred By` (rich_text). See `notion_client_wrapper.build_properties`.

## Running the live app

```bash
# terminal 1 — backend
cd server && ../.venv/bin/uvicorn app:app --reload --port 8000

# terminal 2 — frontend (proxies /api → :8000)
cd web && npm run dev
```

Then open http://localhost:5173. Recipes must already exist in Notion *and* be enriched (`cookSteps` present in their JSON-LD code block) — pick recipes that have been processed by `enrich_recipe.py`.

## Running on Android (Capacitor)

The web app is wrapped with Capacitor (`web/capacitor.config.ts`, `web/android/`) for installation on a phone on the same Wi-Fi as the laptop. The phone loads the UI from the Vite dev server and hits the FastAPI backend directly — no hosted backend.

**One-time setup**

1. Install Android Studio: `brew install --cask android-studio`. On first launch, complete the setup wizard (installs Android SDK + platform tools + an SDK Platform target, e.g. API 35).
2. JDK: use Android Studio's bundled JBR. Add to your shell rc:
   ```bash
   export JAVA_HOME="/Applications/Android Studio.app/Contents/jbr/Contents/Home"
   export ANDROID_HOME="$HOME/Library/Android/sdk"
   export PATH="$PATH:$ANDROID_HOME/platform-tools"
   ```
3. On the phone: Settings → About phone → tap Build number 7× to unlock Developer Options → enable **USB debugging**. Plug in via USB and accept the RSA fingerprint prompt. Verify with `adb devices`.
4. In `web/.env.local` (gitignored) set the API base to your laptop's LAN IP (`ipconfig getifaddr en0`):
   ```
   VITE_API_BASE_URL=http://192.168.0.196:8000
   ```

**Dev loop (live reload)**

```bash
# terminal 1 — backend, bound to the LAN so the phone can reach it
cd server && ../.venv/bin/uvicorn app:app --reload --port 8000 --host 0.0.0.0

# terminal 2 — vite (already listens on 0.0.0.0 via server.host: true)
cd web && npm run dev

# terminal 3 — sync the LAN dev URL into Capacitor + install on the phone
cd web
CAPACITOR_DEV_SERVER_URL=http://192.168.0.196:5173 npm run android:sync
npm run android:run
```

`CAPACITOR_DEV_SERVER_URL` is read by `capacitor.config.ts`; when set, the APK loads from that URL (live reload) instead of bundled assets. Code changes in `web/src/` hot-reload on the phone.

**Standalone APK (no Vite running)**

```bash
cd web
npm run build              # bakes VITE_API_BASE_URL into the bundle
npm run android:sync       # no CAPACITOR_DEV_SERVER_URL → uses web/dist/
npm run android:run
```

The phone still needs the backend reachable on the LAN — there's no embedded backend.

**Notes**

- `androidScheme: 'http'` + `cleartext: true` in `capacitor.config.ts` let the app talk to plain-HTTP backends. Fine for the home network; revisit if this ever leaves the LAN.
- The Android project lives in `web/android/`. It's checked in (Capacitor regenerates if missing), but build artifacts inside (`build/`, `.gradle/`, `local.properties`) are handled by `web/android/.gitignore`.

## Three-stage pipeline

The system is a sequence of three CLIs, each writing back into the recipe's Notion page:

1. **Ingest** — `add_recipe.py`
   - URL form: `python add_recipe.py https://example.com/recipe` → `scraper.scrape_recipe` (recipe-scrapers + JSON-LD extraction).
   - Cookbook form: `python add_recipe.py page1.jpg page2.jpg --source "Cookbook Name" [--photo finished_dish.jpg]` → `vision_recipe.parse_recipe_from_images` (Claude Sonnet vision, streaming because cookbook recipes can blow past 16K output tokens). `--photo` images are uploaded to the page but **not** sent to the model.
   - Both paths land at `notion_client_wrapper.create_recipe_page`, which sets a heuristic emoji icon (`_pick_icon`) and embeds the full JSON-LD as a code block on the page. That code block is the source of truth for downstream stages.

2. **Enrich** — `enrich_recipe.py "Recipe Title"`
   - Loads the JSON-LD code block, asks Claude Sonnet (`recipe_enrichment.enrich_recipe`) to decompose narrative `recipeInstructions` into atomic `cookSteps`, and writes them back into the same JSON-LD block via `update_json_ld_block`.
   - Each step has: `id` (e.g. "S0"), `description`, `duration_min`, `active` (true = cook is occupied), `tools` (controlled vocab — see below), `depends_on`.
   - Idempotent unless `--force`: a recipe that already has `cookSteps` is skipped.

3. **Schedule** — `schedule.py "Recipe A" "Recipe B" ...`
   - Loads `cookSteps` from each named recipe and hands them to `scheduler.solve` (OR-Tools CP-SAT).
   - Prints a human-readable plan and writes `schedule.json` (or stdout with `--json -`).

## Scheduler model (`scheduler.py`)

- Each step is a fixed-duration `IntervalVar`. Precedence comes from `depends_on`.
- Each tool is a renewable resource with capacity from `inventory.yaml`; the `cook` is a tool too, but only "active" steps consume it (passive steps like rising/baking leave the cook free).
- `solve(steps, inventory, subs, num_cooks=None)` has two modes:
  - **`num_cooks=None`** (legacy/CLI path): cook treated as a cumulative resource with capacity from inventory. No per-step assignment; `StepSchedule.cook_id` is `None`.
  - **`num_cooks=N`** (web app path): each active step gets an optional interval per cook + `AddExactlyOne` on per-cook presence vars, with `NoOverlap` over each cook's optional intervals. Result: every active step has a concrete `cook_id ∈ [0, N-1]`. Inventory's cook count is ignored when `num_cooks` is set.
- **Known optimization gap**: only the makespan is minimized — the solver may pack all active work onto one cook if the critical path doesn't benefit from parallelism, leaving other cooks idle. A workload-balance tiebreaker (minimize max per-cook load) would fix this; not implemented yet.
- **Stateful tools** (currently just `oven`, see `_STATEFUL_TOOLS`) are modeled as a single per-recipe **session interval** spanning from a recipe's first oven step to its last. This ensures one recipe owns the oven continuously — another recipe can't preheat to a different temperature in the gap between your preheat and your bake. When editing this, remember stateful steps are excluded from the per-step `tool_intervals` and added back only as the session interval.
- **Substitutions**: tools not in `inventory.yaml` are looked up in `substitutions.yaml`. The first chain entry whose `tool` is in inventory (or `tool: null` = by hand) is applied, scaling the step's duration by `time_multiplier`. If nothing matches, `UnsupportedToolError` is raised — fix by editing one of the two YAML files, not by guessing.
- Tool vocabulary used by the enrichment LLM prompt is the union of keys in `inventory.yaml` and `substitutions.yaml` (`recipe_enrichment._load_tool_vocabulary`). Adding a new tool to either file extends the vocabulary on the next enrich.

## Notion JSON-LD as the persistence layer

There is no local database. The JSON-LD `code` block on each Notion page is the canonical recipe; everything downstream (`enrich_recipe.py`, `schedule.py`) re-parses it via `find_recipe_json_ld_block`. Notes:

- Notion `rich_text` length limits are **UTF-16 code units**, so the JSON is split with `_chunk_utf16` (not naive character chunking) — keep using it when rewriting code blocks.
- Notion forbids commas in `multi_select` option names, so `build_properties` splits ingredient strings on commas before tagging.
- The Notion API version in use is 2025-09-03: databases now have `data_sources`, and queries go through `client.data_sources.query` (`_get_data_source_id` in `notion_client_wrapper`), not `client.databases.query`.

## Anthropic SDK conventions

- Model: `claude-sonnet-4-6` (used in both `recipe_enrichment.py` and `vision_recipe.py`).
- Enrichment uses `client.messages.parse(..., output_format=PydanticModel)` for clean structured output.
- Vision uses `client.messages.stream(..., output_format=...)` with `max_tokens=32000` and manually validates the JSON from `get_final_message()` — the non-streaming path times out on long cookbook recipes. Don't "simplify" this back to `messages.parse`.

## Defensive post-processing

`recipe_enrichment._normalize_steps` overrides the LLM's `active` flag to `False` on any step whose description contains "preheat". Apply the same pattern (deterministic override after the LLM) for other known failure modes rather than relying on prompt instructions alone.

## Common workflows

```bash
cd tools

# Ingest a web recipe
python add_recipe.py https://cooking.nytimes.com/recipes/12345 -y

# Ingest a cookbook recipe from photos
python add_recipe.py ~/Desktop/page1.jpg ~/Desktop/page2.jpg --source "Salt Fat Acid Heat" -y

# Add cookSteps to an existing recipe
python enrich_recipe.py "Roast Chicken with Lemon" -y

# Plan a multi-recipe meal
python schedule.py "Roast Chicken with Lemon" "Caesar Salad" "Olive Oil Cake"

# Dry-run modes exist on add_recipe.py and enrich_recipe.py (--dry-run)
```

There is no test suite or linter configured for `tools/`. The web app has `npm run build` (tsc + vite build) and `npm run lint` (eslint).

## Backend architecture (`server/`)

- `app.py` — FastAPI routes. Adds `tools/` to `sys.path` and reuses `scheduler.solve` and `notion_client_wrapper` directly.
- `db.py` — SQLite (file: `server/octocook.db`, override with `OCTOCOOK_DB` env var). Three tables:
  - `sessions` — frozen at creation: recipes, kitchen, cook count, full `schedule_json` (the dict returned by `schedule_to_dict`, plus `icons` and `num_cooks`).
  - `session_steps` — per-(session, step) progress: `started_at`, `completed_at`, `actual_seconds`. Upserted on start/done.
  - `step_actuals` — append-only history of `(recipe_title, step_description, estimated_seconds, actual_seconds)` for future estimate-tuning. Not yet read by anything.
- `presets.py` + `presets/<name>/{inventory,substitutions}.yaml` — kitchen presets. The default preset mirrors `tools/inventory.yaml` and `tools/substitutions.yaml`.

Routes (all under `/`, proxied as `/api/*` from the dev server):

- `GET /recipes` — Notion recipe list (title + icon).
- `GET /kitchens` — preset names.
- `POST /sessions` — body `{recipe_titles, kitchen, num_cooks}` → runs scheduler with `num_cooks`, persists, returns `{session_id, schedule}`. **400 if any recipe lacks `cookSteps`** — enrich first.
- `GET /sessions/{id}` — full session including `step_state`.
- `POST /sessions/{id}/steps/{step_id}/start` and `.../done` — start/finish a step. `done` derives `actual_seconds` from `started_at` if not provided.

## Frontend architecture (`web/`)

- `Setup.tsx` — multi-select recipes, kitchen dropdown, cook count, Start button. On submit → `POST /api/sessions` → switches App into cook view.
- `CookView.tsx` — root cooking screen: tabs for Cook 1..N, polls `GET /api/sessions/{id}` every 5s. `CookPane` filters to one cook's active steps, computes step positions ("X/Y of dish", "X/Y for you") and percent complete, auto-scrolls the current step into view. `StepCard` is the per-step UI with Start-timer / Done buttons and a live elapsed-time display.
- `vite.config.ts` proxies `/api` → `http://127.0.0.1:8000`. Frontend should always hit `/api/*`, never `http://localhost:8000` directly.
- Only **active** steps appear in the per-cook timeline. Passive steps (oven baking, dough rising) have `cook_id: null` and intentionally aren't shown to any cook — they're implicit in the schedule's makespan but aren't anyone's "current task." Adding a background-events panel is a future enhancement.
