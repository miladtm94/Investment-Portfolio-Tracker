SITE_DIR := $(shell pwd)
ENV_FILE := .env
COMPOSE := docker compose

ifneq ("$(wildcard $(ENV_FILE))","")
include $(ENV_FILE)
endif

POSTGRES_USER ?= invest
POSTGRES_PASSWORD ?= investpass
POSTGRES_DB ?= investment_platform
FRONTEND_PORT ?= 3000
BACKEND_PORT ?= 8010
POSTGRES_PORT ?= 15432
REDIS_PORT ?= 16379
FLOWER_PORT ?= 5555
DATABASE_URL ?= postgresql+asyncpg://$(POSTGRES_USER):$(POSTGRES_PASSWORD)@localhost:$(POSTGRES_PORT)/$(POSTGRES_DB)
REDIS_URL ?= redis://localhost:$(REDIS_PORT)/0
CELERY_BROKER_URL ?= redis://localhost:$(REDIS_PORT)/1
NEXT_PUBLIC_API_URL ?= http://localhost:$(BACKEND_PORT)
NEXTAUTH_URL ?= http://localhost:$(FRONTEND_PORT)

APP_URL := http://localhost:$(FRONTEND_PORT)
PYTHON := ./.venv/bin/python
BACKEND_PYTHON := ../.venv/bin/python
PIP := ./.venv/bin/pip

.EXPORT_ALL_VARIABLES:

.PHONY: ensure-env ensure-volumes serve dev docker restart rebuild clean-rebuild stop logs logs-backend logs-frontend status infra backend frontend dev-local install backend-install frontend-install type-check test repair-assets push open help

ensure-env: ## Create .env from .env.example if missing
	@if [ ! -f "$(ENV_FILE)" ]; then \
		cp .env.example .env; \
		echo "Created .env from .env.example. Review keys before syncing brokers."; \
	fi

ensure-volumes: ## Create Docker volumes expected by compose
	@docker volume inspect investment-platform_postgres_data >/dev/null 2>&1 || docker volume create investment-platform_postgres_data >/dev/null

serve: ensure-env ensure-volumes ## Start everything with Docker (backend + frontend + db + redis)
	$(COMPOSE) up -d

dev: serve ## Alias for serve

docker: serve ## Alias for serve

restart: ensure-env ensure-volumes ## Restart backend and frontend Docker services
	$(COMPOSE) restart backend frontend

rebuild: ensure-env ensure-volumes ## Rebuild Docker images with cache and restart
	$(COMPOSE) build
	$(COMPOSE) up -d --remove-orphans

clean-rebuild: ensure-env ensure-volumes ## Rebuild from scratch without Docker cache
	$(COMPOSE) down --remove-orphans
	$(COMPOSE) build --no-cache
	$(COMPOSE) up -d

stop: ## Stop all services
	$(COMPOSE) down --remove-orphans

logs: ## Tail live logs from all containers
	$(COMPOSE) logs -f

logs-backend: ## Tail backend logs
	$(COMPOSE) logs -f backend

logs-frontend: ## Tail frontend logs
	$(COMPOSE) logs -f frontend

status: ## Show container status
	$(COMPOSE) ps

infra: ensure-env ensure-volumes ## Start only Postgres and Redis for local backend/frontend
	$(COMPOSE) up -d postgres redis

install: backend-install frontend-install ## Install local backend/frontend dependencies

.venv/bin/uvicorn: backend/requirements.txt
	python3 -m venv .venv
	$(PIP) install -r backend/requirements.txt

backend-install: .venv/bin/uvicorn ## Install backend dependencies into .venv

frontend-install: ## Install frontend dependencies
	npm --prefix frontend install

backend: ensure-env infra backend-install ## Run backend locally using root .env
	cd backend && \
	DATABASE_URL="$(DATABASE_URL)" \
	REDIS_URL="$(REDIS_URL)" \
	CELERY_BROKER_URL="$(CELERY_BROKER_URL)" \
	$(BACKEND_PYTHON) -m uvicorn main:app --reload --host 0.0.0.0 --port $(BACKEND_PORT)

frontend: ensure-env frontend-install ## Run frontend locally using root .env
	cd frontend && \
	NEXT_PUBLIC_API_URL="$(NEXT_PUBLIC_API_URL)" \
	NEXTAUTH_URL="$(NEXTAUTH_URL)" \
	NEXTAUTH_SECRET="$(NEXTAUTH_SECRET)" \
	npm run dev -- --port $(FRONTEND_PORT)

dev-local: ensure-env infra ## Run backend and frontend locally from one command
	$(MAKE) -j2 backend frontend

type-check: ## Run frontend type-check
	npm --prefix frontend run type-check

test: ## Run backend tests inside local .venv
	cd backend && $(BACKEND_PYTHON) -m pytest tests -q

repair-assets: ## Dry-run repair of ASX holdings stored as USD (APPLY=1 to commit)
	$(COMPOSE) exec backend python scripts/repair_asx_assets.py $(if $(APPLY),--apply,)

open: ## Open frontend in browser
	open $(APP_URL)

push: ## Commit all changes and push - usage: make push MSG="your message"
	@if [ -z "$(MSG)" ]; then \
		echo "Usage: make push MSG=\"your commit message\""; \
		exit 1; \
	fi
	git -C "$(SITE_DIR)" pull --rebase
	git -C "$(SITE_DIR)" add -A
	git -C "$(SITE_DIR)" commit -m "$(MSG)" || echo "Nothing new to commit."
	git -C "$(SITE_DIR)" push

help: ## Show this help
	@awk 'BEGIN {FS = ":.*## "}; /^[a-zA-Z_-]+:.*## / {printf "  %-15s %s\n", $$1, $$2}' Makefile
