# executor

Go service that applies approved proposals. Runs on the host (not in the container) because it holds write credentials.

See [../docs/ARCHITECTURE.md](../docs/ARCHITECTURE.md#the-proposal-queue) for the proposal-queue contract.

## Running

```bash
go run ./cmd/executor --proposals ../var/proposals --vault "$VAULT_PATH"
```
