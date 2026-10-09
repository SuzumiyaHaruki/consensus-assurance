// Verifies a signed sumdb note (golang.org/x/mod/sumdb/note format) using the
// official sum.golang.org public key, with only the standard library.
package main

import (
	"bytes"
	"crypto/ed25519"
	"encoding/base64"
	"fmt"
	"os"
	"strings"
)

// sum.golang.org key, as embedded in cmd/go (src/cmd/go/internal/modfetch/key.go).
const sumKey = "sum.golang.org+033de0ae+Ac4zctda0e5eza+HJyk9SxEdh+s3Ux18htTTAD8OuAn8"

func main() {
	if len(os.Args) != 2 {
		fmt.Fprintln(os.Stderr, "usage: notecheck <signed-note-file>")
		os.Exit(2)
	}
	data, err := os.ReadFile(os.Args[1])
	if err != nil {
		fmt.Fprintln(os.Stderr, err)
		os.Exit(1)
	}

	parts := strings.SplitN(sumKey, "+", 3)
	if len(parts) != 3 {
		fmt.Fprintln(os.Stderr, "bad key")
		os.Exit(1)
	}
	pub, err := base64.StdEncoding.DecodeString(parts[2])
	if err != nil {
		pub, err = base64.RawStdEncoding.DecodeString(parts[2])
	}
	fmt.Fprintf(os.Stderr, "key b64=%q declen=%d err=%v\n", parts[2], len(pub), err)
	// x/mod/sumdb/note key encoding: 1 algorithm byte (0=Ed25519) || 32-byte pubkey.
	if err == nil && len(pub) == ed25519.PublicKeySize+1 {
		fmt.Fprintf(os.Stderr, "key algo byte=0x%02x\n", pub[0])
		pub = pub[1:]
	}
	if err != nil || len(pub) != ed25519.PublicKeySize {
		fmt.Fprintln(os.Stderr, "bad key material: len", len(pub), "err", err)
		os.Exit(1)
	}

	// Split text from signature lines. Signature lines begin with "\u2014 ".
	sep := []byte("\u2014 ")
	idx := bytes.Index(data, append([]byte("\n"), sep...))
	if idx < 0 {
		fmt.Fprintln(os.Stderr, "no signature line found")
		os.Exit(1)
	}
	msgWithNL := data[:idx+1]   // text includes its trailing newline
	msgNoNL := data[:idx]       // text without the final newline
	sigBlock := data[idx+1:]    // "— name base64sig\n..."

	verified := false
	for _, line := range bytes.Split(sigBlock, []byte("\n")) {
		if !bytes.HasPrefix(line, sep) {
			continue
		}
		fields := bytes.Fields(line[len(sep):])
		if len(fields) != 2 || string(fields[0]) != "sum.golang.org" {
			continue
		}
		sig, err := base64.StdEncoding.DecodeString(string(fields[1]))
		if err != nil {
			continue
		}
		fmt.Fprintf(os.Stderr, "sig declen=%d first=0x%02x\n", len(sig), sig[0])
		var sigVariants [][]byte
		for _, off := range []int{0, 1, 4} {
			if off+ed25519.SignatureSize <= len(sig) {
				sigVariants = append(sigVariants, sig[off:off+ed25519.SignatureSize])
			}
		}
		for _, s := range sigVariants {
			for _, m := range [][]byte{msgWithNL, msgNoNL} {
				if ed25519.Verify(ed25519.PublicKey(pub), m, s) {
					verified = true
				}
			}
		}
		if verified {
			break
		}
	}
	if verified {
		fmt.Println("SIGNATURE VALID for key", parts[0], "keyhash", parts[1])
		fmt.Printf("signed text:\n%s", msgWithNL)
		return
	}
	fmt.Println("SIGNATURE INVALID")
	os.Exit(1)
}
