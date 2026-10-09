// Verifies the sum.golang.org signed lookup record for a module using the
// real golang.org/x/mod/sumdb/note implementation.
package main

import (
	"fmt"
	"os"

	"golang.org/x/mod/sumdb/note"
)

// sum.golang.org verifier key, as embedded in cmd/go
// (src/cmd/go/internal/modfetch/key.go).
const sumKey = "sum.golang.org+033de0ae+Ac4zctda0e5eza+HJyk9SxEdh+s3Ux18htTTAD8OuAn8"

func main() {
	// Control: the well-formed signed note from the sumdb/note package docs.
	const exampleVKey = "PeterNeumann+c74f20a3+ARpc2QcUPDhMQegwxbzhKqiBfsVkmqq/LDE4izWy10TW"
	exampleMsg := []byte("If you think cryptography is the answer to your problem,\n" +
		"then you don't know what your problem is.\n" +
		"\n" +
		"— PeterNeumann x08go/ZJkuBS9UG/SffcvIAQxVBtiFupLLr8pAcElZInNIuGUgYN1FFYC2pZSNXgKvqfqdngotpRZb6KE6RyyBwJnAM=\n")
	if ev, err := note.NewVerifier(exampleVKey); err != nil {
		fmt.Fprintln(os.Stderr, "control NewVerifier:", err)
	} else if _, err := note.Open(exampleMsg, note.VerifierList(ev)); err != nil {
		fmt.Println("CONTROL FAILED (library usage wrong):", err)
	} else {
		fmt.Println("CONTROL OK: documented example note verifies")
	}

	if len(os.Args) != 2 {
		fmt.Fprintln(os.Stderr, "usage: notecheck2 <signed-note-file>")
		os.Exit(2)
	}

	verifier, err := note.NewVerifier(sumKey)
	if err != nil {
		fmt.Fprintln(os.Stderr, "NewVerifier:", err)
		os.Exit(1)
	}

	data, err := os.ReadFile(os.Args[1])
	if err != nil {
		fmt.Fprintln(os.Stderr, err)
		os.Exit(1)
	}

	n, err := note.Open(data, note.VerifierList(verifier))
	if err != nil {
		fmt.Println("SIGNATURE INVALID:", err)
		os.Exit(1)
	}
	fmt.Println("SIGNATURE VALID")
	fmt.Printf("signed text:\n%s", n.Text)
}
