PYTHON := python3.12
VENV   := .venv
PIP    := $(VENV)/bin/pip
UVICORN := $(VENV)/bin/uvicorn

.PHONY: help setup install install-py install-web env backend frontend dev android-sync android-run

help:
	@echo "Usage:"
	@echo "  make setup        — create venv, install all deps, copy .env if missing"
	@echo "  make backend      — run FastAPI server on :8000 (requires setup)"
	@echo "  make frontend     — run Vite dev server on :5173 (requires setup)"
	@echo "  make dev          — run backend + frontend concurrently"
	@echo "  make android-sync — sync Capacitor + push to connected Android device"
	@echo "  make android-run  — run app on connected Android device"

# ── Setup ─────────────────────────────────────────────────────────────────────

setup: $(VENV)/bin/activate install-web env
	@echo "Setup complete. Fill in tools/.env then run: make dev"

$(VENV)/bin/activate:
	$(PYTHON) -m venv $(VENV)

install: install-py install-web

install-py: $(VENV)/bin/activate
	$(PIP) install -r tools/requirements.txt -r server/requirements.txt

install-web:
	cd web && npm install

env:
	@if [ ! -f tools/.env ]; then \
		cp tools/.env.example tools/.env; \
		echo "Created tools/.env — fill in your API keys before running the app."; \
	fi

# ── Running ───────────────────────────────────────────────────────────────────

backend:
	cd server && ../$(UVICORN) app:app --reload --port 8000

frontend:
	cd web && npm run dev

# Run both concurrently; Ctrl-C kills both.
dev:
	@trap 'kill 0' INT; \
	$(MAKE) backend & \
	$(MAKE) frontend & \
	wait

# ── Android ───────────────────────────────────────────────────────────────────

# Usage: make android-sync LANIP=192.168.0.x
android-sync:
	cd web && CAPACITOR_DEV_SERVER_URL=http://$(LANIP):5173 npm run android:sync

android-run:
	cd web && npm run android:run
