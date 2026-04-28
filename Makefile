SITE_DIR := $(shell pwd)
COMPOSE := docker compose
FRONTEND_PORT ?= 3000
BACKEND_PORT ?= 8010
POSTGRES_PORT ?= 15432
REDIS_PORT ?= 16379
FLOWER_PORT ?= 5555
APP_URL := http://localhost:$(FRONTEND_PORT)
export FRONTEND_PORT BACKEND_PORT POSTGRES_PORT REDIS_PORT FLOWER_PORT

.PHONY: ensure-volumes serve rebuild clean-rebuild stop logs status push open help

ensure-volumes: ## Create Docker volumes expected by compose
	@docker volume inspect investment-platform_postgres_data >/dev/null 2>&1 || docker volume create investment-platform_postgres_data >/dev/null

serve: ensure-volumes ## Start the services (backend on 8010, frontend on 3000)
	$(COMPOSE) up -d

rebuild: ensure-volumes ## Rebuild Docker images with cache and restart (use after dependency changes)
	$(COMPOSE) build
	$(COMPOSE) up -d --remove-orphans

clean-rebuild: ensure-volumes ## Rebuild from scratch without Docker cache (rare; redownloads dependencies)
	$(COMPOSE) down --remove-orphans
	$(COMPOSE) build --no-cache
	$(COMPOSE) up -d

stop: ## Stop all services
	$(COMPOSE) down --remove-orphans

logs: ## Tail live logs from all containers
	$(COMPOSE) logs -f

status: ## Show container status
	$(COMPOSE) ps

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
