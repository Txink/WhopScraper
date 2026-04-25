.PHONY: install dev backend-dev frontend-dev build run stop stop-all test lint typecheck db-migrate db-reset clean

install:
	cd backend && uv venv && uv pip install -e ".[dev]"
	cd backend && uv run playwright install chromium
	cd frontend && npm install

dev:
	@echo "Starting backend + frontend in parallel..."
	@(cd backend && uv run uvicorn app.main:app --reload --host 127.0.0.1 --port 8000) & \
	 (cd frontend && npm run dev) & wait

backend-dev:
	cd backend && uv run uvicorn app.main:app --reload --host 127.0.0.1 --port 8000

frontend-dev:
	cd frontend && npm run dev

build:
	cd frontend && npm run build

run: build
	cd backend && uv run uvicorn app.main:app --host 127.0.0.1 --port 8000

stop:
	@bash scripts/stop.sh

stop-all:
	@bash scripts/stop.sh --all

test:
	cd backend && uv run pytest -v
	cd frontend && npm test

lint:
	cd backend && uv run ruff check .

typecheck:
	cd backend && uv run mypy app
	cd frontend && npm run typecheck

db-migrate:
	cd backend && uv run alembic upgrade head

db-reset:
	rm -f data/signals.db data/signals.db-shm data/signals.db-wal
	$(MAKE) db-migrate

clean:
	find . -type d -name __pycache__ -exec rm -rf {} +
	find . -type d -name .pytest_cache -exec rm -rf {} +
	rm -rf frontend/dist frontend/.vite
