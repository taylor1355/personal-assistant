# Convenience targets. Run `make help` to list.

.PHONY: help agent-sync agent-wake executor sync compose-build compose-up lint fmt

help:
	@echo "Targets:"
	@echo "  agent-sync     uv sync the agent package"
	@echo "  agent-wake     run the agent with --reason=manual-test"
	@echo "  executor       run the executor service"
	@echo "  sync           run the sync daemon (requires VAULT_PATH)"
	@echo "  compose-build  build the agent image"
	@echo "  compose-up     start the agent container"
	@echo "  lint           ruff check on agent, go vet on Go modules"
	@echo "  fmt            ruff format on agent, gofmt on Go modules"

agent-sync:
	uv sync --project agent

agent-wake:
	uv run --project agent personal-assistant-agent wake --reason=manual-test

executor:
	cd executor && go run ./cmd/executor

sync:
	@test -n "$$VAULT_PATH" || (echo "VAULT_PATH not set" && exit 2)
	cd sync && go run ./cmd/sync --vault "$$VAULT_PATH"

compose-build:
	docker compose build agent

compose-up:
	docker compose up agent

lint:
	uv run --project agent ruff check agent
	cd executor && go vet ./...
	cd sync && go vet ./...

fmt:
	uv run --project agent ruff format agent
	cd executor && gofmt -w .
	cd sync && gofmt -w .
