package main

import (
	"flag"
	"fmt"
	"os"
)

// v0 entrypoint. The two-way sync daemon is not yet implemented.

func main() {
	var (
		vault     = flag.String("vault", "", "user's real Obsidian vault path (required)")
		vaultCopy = flag.String("copy", "./var/vault-copy", "agent's vault copy path")
	)
	flag.Parse()

	if *vault == "" {
		fmt.Fprintln(os.Stderr, "sync: --vault is required")
		os.Exit(2)
	}

	fmt.Fprintf(os.Stdout, "sync: vault=%q copy=%q — daemon not yet implemented\n",
		*vault, *vaultCopy)
}
