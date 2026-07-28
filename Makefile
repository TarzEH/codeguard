.DEFAULT_GOAL := help
SHELL := /bin/bash
COMPOSE := docker compose
VENV := .venv

.PHONY: help install up down restart status logs shell test failover-test lint scale autoscale clean load-test

help: ## Show this help
	@echo ""
	@echo "  codeguard — make targets"
	@echo ""
	@grep -E '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) \
		| awk 'BEGIN {FS = ":.*?## "}; {printf "    \033[1m%-16s\033[0m %s\n", $$1, $$2}'
	@echo ""

install: ## Full install: secrets, cluster, CLI, smoke test
	@./install.sh

up: ## Start the cluster
	@$(COMPOSE) up -d --build

down: ## Stop the cluster (volumes are kept)
	@$(COMPOSE) --profile autoscale down --remove-orphans

restart: down up ## Restart the cluster

status: ## Cluster overview: containers, leader, sharding
	@echo ""
	@$(COMPOSE) ps --format 'table {{.Name}}\t{{.Status}}'
	@echo ""
	@echo "  Leader election:"
	@$(COMPOSE) ps --format '{{.Name}}' backend | while read b; do \
		printf "    %-24s " "$$b"; \
		docker exec $$b python -c "import urllib.request,json;d=json.load(urllib.request.urlopen('http://127.0.0.1:5000/health'));print('leader=%-5s zk=%s mongo=%s'%(d['leader'],d['zookeeper'],d['mongo']))" 2>/dev/null || echo "unreachable"; \
	done
	@echo ""

logs: ## Follow logs (make logs S=backend for one service)
	@$(COMPOSE) logs -f --tail 100 $(S)

shell: ## Open a mongosh shell as the application user
	@set -a; . ./.env; set +a; \
	docker exec -it mongos mongosh --host 127.0.0.1 \
		-u "$$MONGO_APP_USERNAME" -p "$$MONGO_APP_PASSWORD" \
		--authenticationDatabase "$$MONGO_DB" "$$MONGO_DB"

$(VENV): requirements-dev.txt
	@python3 -m venv $(VENV) && $(VENV)/bin/pip install -q -r requirements-dev.txt
	@touch $(VENV)

test: $(VENV) ## Run unit tests (no Docker needed)
	@$(VENV)/bin/pytest

failover-test: ## Kill the leader and prove re-election
	@./tests/integration/failover_test.sh

lint: ## Shellcheck every script
	@command -v shellcheck >/dev/null || { echo "shellcheck not installed: brew install shellcheck"; exit 1; }
	@shellcheck -S warning install.sh src/cli/*.sh scripts/*.sh \
		src/infra/mongo-init/*.sh tests/integration/*.sh && echo "  shell scripts clean"

scale: ## Scale the backend: make scale N=8
	@$(COMPOSE) up -d --no-deps --no-recreate --scale backend=$(or $(N),4) backend

autoscale: ## Start the autoscaler
	@$(COMPOSE) --profile autoscale up -d autoscaler
	@echo "  autoscaler running — follow it with: docker logs -f codeguard_autoscaler"

load-test: $(VENV) ## Load test the API
	@$(VENV)/bin/pip -q install requests
	@$(VENV)/bin/python overload-test-scripts/overload_cli.py --requests $(or $(N),200) --concurrency $(or $(C),20)

clean: ## Stop everything and delete volumes (destroys the cache)
	@$(COMPOSE) --profile autoscale down -v --remove-orphans
	@rm -rf $(VENV) .pytest_cache
	@echo "  cluster and volumes removed"
