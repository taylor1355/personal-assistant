package main

import (
	"flag"
	"fmt"
	"os"
)

// v0 entrypoint. The proposal-watching loop and vault-write adapters are
// not yet implemented; this prints its config and exits so we can wire
// the service into scripts and CI before the real logic lands.

func main() {
	var (
		proposalsPath = flag.String("proposals", "./var/proposals", "directory watched for proposals")
		vaultPath     = flag.String("vault", "./var/vault-copy", "user vault path for writes")
	)
	flag.Parse()

	fmt.Fprintf(os.Stdout, "executor: proposals=%q vault=%q — loop not yet implemented\n",
		*proposalsPath, *vaultPath)
}
