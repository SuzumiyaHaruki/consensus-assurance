// Independent reimplementation of golang.org/x/mod/sumdb/dirhash HashZip+Hash1,
// used to verify that a cached module zip hashes to the officially recorded
// value. Standard library only, so it can run offline with no module graph.
package main

import (
	"archive/zip"
	"crypto/sha256"
	"encoding/base64"
	"fmt"
	"io"
	"os"
	"sort"
)

// hash1 mirrors dirhash.Hash1: sha256 over, for each file (sorted),
// "<sha256hex(file)>  <name>\n"; final value "h1:"+base64(sha256(that)).
func hashZip(zipfile string) (string, error) {
	z, err := zip.OpenReader(zipfile)
	if err != nil {
		return "", err
	}
	defer z.Close()

	byName := make(map[string]*zip.File)
	var files []string
	for _, f := range z.File {
		byName[f.Name] = f
		files = append(files, f.Name)
	}
	sort.Strings(files)

	h := sha256.New()
	for _, name := range files {
		rc, err := byName[name].Open()
		if err != nil {
			return "", err
		}
		fh := sha256.New()
		if _, err := io.Copy(fh, rc); err != nil {
			rc.Close()
			return "", err
		}
		rc.Close()
		fmt.Fprintf(h, "%x  %s\n", fh.Sum(nil), name)
	}
	return "h1:" + base64.StdEncoding.EncodeToString(h.Sum(nil)), nil
}

func main() {
	if len(os.Args) != 2 {
		fmt.Fprintln(os.Stderr, "usage: ziphashtool <path-to-module.zip>")
		os.Exit(2)
	}
	sum, err := hashZip(os.Args[1])
	if err != nil {
		fmt.Fprintln(os.Stderr, "error:", err)
		os.Exit(1)
	}
	fmt.Println(sum)
}
