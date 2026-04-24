# sync

Two-way sync daemon between the user's real Obsidian vault and the agent's container-mounted copy.

See [../docs/ARCHITECTURE.md](../docs/ARCHITECTURE.md#vault-handling) for the sync contract.

## Running

```bash
go run ./cmd/sync --vault "$VAULT_PATH" --copy ./var/vault-copy
```
