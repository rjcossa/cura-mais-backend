.PHONY: help install keys migrate seed run test lint openapi docker-up docker-down docker-logs

help:
	@echo "Targets:"
	@echo "  install       Create venv and install dependencies"
	@echo "  keys          Generate JWT signing keys + print MFA/pepper secrets"
	@echo "  migrate       Apply database migrations"
	@echo "  seed          Seed roles and permissions"
	@echo "  run           Run the API with auto-reload"
	@echo "  test          Run the test suite"
	@echo "  lint          Run ruff"
	@echo "  openapi       Regenerate openapi/identity-api.{json,yaml}"
	@echo "  docker-up     Start db + app + adminer via docker compose"
	@echo "  docker-down   Stop docker compose services"
	@echo "  docker-logs   Tail app logs from docker compose"

install:
	python3 -m venv .venv
	.venv/bin/pip install --upgrade pip
	.venv/bin/pip install -e ".[dev]"

keys:
	.venv/bin/python scripts/generate_jwt_keys.py

migrate:
	.venv/bin/alembic upgrade head

seed:
	.venv/bin/python -m scripts.seed_roles_permissions

run:
	.venv/bin/uvicorn app.main:app --reload

test:
	.venv/bin/pytest

lint:
	.venv/bin/ruff check app scripts tests

openapi:
	.venv/bin/python -m scripts.export_openapi

docker-up:
	docker compose up --build -d

docker-down:
	docker compose down

docker-logs:
	docker compose logs -f app
