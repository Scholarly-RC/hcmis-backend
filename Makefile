ifneq (,$(wildcard .env))
include .env
export
endif

UV_CACHE_DIR ?= /tmp/uv-cache
DOCKER_CONFIG ?= /tmp/hcmis-docker-config
COMPOSE ?= docker compose
POSTGRES_SERVICE ?= postgres
REDIS_SERVICE ?= redis
DATABASE_URL ?= postgresql+asyncpg://hcmis:hcmis@localhost:$(POSTGRES_HOST_PORT)/hcmis
REDIS_URL ?= redis://localhost:$(REDIS_HOST_PORT)/0
FASTAPI_APP ?= app/main.py
FLYCTL ?= flyctl
DATABASE_HOST := $(strip $(shell printf '%s\n' "$(DATABASE_URL)" | sed -E 's|^[a-z0-9+]+://([^@/]+@)?([^/:?]+).*|\2|'))
DATABASE_PORT := $(strip $(shell printf '%s\n' "$(DATABASE_URL)" | sed -nE 's|^[a-z0-9+]+://([^@/]+@)?[^/:?]+:([0-9]+).*|\2|p'))
REDIS_HOST := $(strip $(shell printf '%s\n' "$(REDIS_URL)" | sed -E 's|^[a-z0-9+]+://([^@/]+@)?([^/:?]+).*|\2|'))
REDIS_PORT := $(strip $(shell printf '%s\n' "$(REDIS_URL)" | sed -nE 's|^[a-z0-9+]+://([^@/]+@)?[^/:?]+:([0-9]+).*|\2|p'))
POSTGRES_HOST_PORT ?= $(if $(DATABASE_PORT),$(DATABASE_PORT),15432)
REDIS_HOST_PORT ?= $(if $(REDIS_PORT),$(REDIS_PORT),16379)
USE_LOCAL_POSTGRES ?= $(if $(filter localhost 127.0.0.1 $(POSTGRES_SERVICE),$(DATABASE_HOST)),1,0)
USE_LOCAL_REDIS ?= $(if $(filter localhost 127.0.0.1 $(REDIS_SERVICE),$(REDIS_HOST)),1,0)
UP_SERVICES := $(strip $(if $(filter 1,$(USE_LOCAL_POSTGRES)),$(POSTGRES_SERVICE)) $(if $(filter 1,$(USE_LOCAL_REDIS)),$(REDIS_SERVICE)))

.PHONY: ruff ty check test docker-config up wait-postgres wait-redis migrate dev db-clear seed-initial seed-performance-questionnaires seed-bootstrap-hr seed-payroll-policy reset-and-seed reset-and-bootstrap-prod fly-deploy

ruff:
	UV_CACHE_DIR=$(UV_CACHE_DIR) uv run ruff check

ty:
	UV_CACHE_DIR=$(UV_CACHE_DIR) uv run ty check

check: ruff ty

test:
	UV_CACHE_DIR=$(UV_CACHE_DIR) uv run pytest

docker-config:
	@mkdir -p $(DOCKER_CONFIG)
	@printf '{}' > $(DOCKER_CONFIG)/config.json

up: docker-config
	@if [ -n "$(UP_SERVICES)" ]; then \
		POSTGRES_HOST_PORT=$(POSTGRES_HOST_PORT) REDIS_HOST_PORT=$(REDIS_HOST_PORT) DOCKER_CONFIG=$(DOCKER_CONFIG) $(COMPOSE) up -d $(UP_SERVICES); \
	else \
		printf '%s\n' "Skipping Docker services because DATABASE_URL/REDIS_URL are not local."; \
	fi

wait-postgres:
	@if [ "$(USE_LOCAL_POSTGRES)" = "1" ]; then \
		until DOCKER_CONFIG=$(DOCKER_CONFIG) $(COMPOSE) exec -T $(POSTGRES_SERVICE) pg_isready -U hcmis -d hcmis >/dev/null 2>&1; do sleep 1; done; \
	fi

wait-redis:
	@if [ "$(USE_LOCAL_REDIS)" = "1" ]; then \
		until DOCKER_CONFIG=$(DOCKER_CONFIG) $(COMPOSE) exec -T $(REDIS_SERVICE) redis-cli ping >/dev/null 2>&1; do sleep 1; done; \
	fi

migrate:
	DATABASE_URL=$(DATABASE_URL) REDIS_URL=$(REDIS_URL) UV_CACHE_DIR=$(UV_CACHE_DIR) uv run alembic upgrade head

dev: docker-config up wait-postgres wait-redis migrate
	DATABASE_URL=$(DATABASE_URL) REDIS_URL=$(REDIS_URL) UV_CACHE_DIR=$(UV_CACHE_DIR) uv run fastapi dev $(FASTAPI_APP) --host 0.0.0.0 --port 8000

db-clear:
	DATABASE_URL=$(DATABASE_URL) REDIS_URL=$(REDIS_URL) UV_CACHE_DIR=$(UV_CACHE_DIR) uv run python -m app.scripts.clear_db_data

seed-initial:
	DATABASE_URL=$(DATABASE_URL) REDIS_URL=$(REDIS_URL) UV_CACHE_DIR=$(UV_CACHE_DIR) uv run python -m app.scripts.seed_initial_data

seed-bootstrap-hr:
	DATABASE_URL=$(DATABASE_URL) REDIS_URL=$(REDIS_URL) UV_CACHE_DIR=$(UV_CACHE_DIR) uv run python -m app.scripts.bootstrap_hr_account

seed-payroll-policy:
	DATABASE_URL=$(DATABASE_URL) REDIS_URL=$(REDIS_URL) UV_CACHE_DIR=$(UV_CACHE_DIR) uv run python -m app.scripts.seed_payroll_policy_official_ph

seed-performance-questionnaires:
	DATABASE_URL=$(DATABASE_URL) REDIS_URL=$(REDIS_URL) UV_CACHE_DIR=$(UV_CACHE_DIR) uv run python -m app.scripts.import_performance_questionnaires

reset-and-seed: db-clear seed-initial seed-performance-questionnaires

reset-and-bootstrap: db-clear seed-bootstrap-hr seed-payroll-policy seed-performance-questionnaires

fly-deploy:
	$(FLYCTL) deploy
