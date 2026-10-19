package main

import (
	"fmt"
	"go/ast"
	"go/parser"
	"go/token"
	"os"
	"path/filepath"
	"strings"
)

func main() {
	// collect all identifiers used in source (non-test)
	used := map[string]int{}
	fset := token.NewFileSet()
	files := []string{}
	filepath.Walk(".", func(path string, info os.FileInfo, err error) error {
		if err != nil {
			return nil
		}
		if info.IsDir() {
			n := info.Name()
			if n == ".runtime" || n == ".git" || n == "audit" {
				return filepath.SkipDir
			}
			return nil
		}
		if !strings.HasSuffix(path, ".go") || strings.HasSuffix(path, "_test.go") || strings.HasSuffix(path, ".pb.go") {
			return nil
		}
		files = append(files, path)
		return nil
	})
	asts := map[string]*ast.File{}
	for _, p := range files {
		f, err := parser.ParseFile(fset, p, nil, 0)
		if err != nil {
			continue
		}
		asts[p] = f
		ast.Inspect(f, func(n ast.Node) bool {
			if id, ok := n.(*ast.Ident); ok {
				used[id.Name]++
			}
			return true
		})
	}
	// now report struct fields declared with non-embedded type whose name appears only once
	for p, f := range asts {
		ast.Inspect(f, func(n ast.Node) bool {
			ts, ok := n.(*ast.TypeSpec)
			if !ok {
				return true
			}
			st, ok := ts.Type.(*ast.StructType)
			if !ok {
				return true
			}
			for _, fld := range st.Fields.List {
				for _, nm := range fld.Names {
					if nm.Name == "_" {
						continue
					}
					if used[nm.Name] <= 1 {
						fmt.Printf("%s:%d: field %s.%s used %d times\n", p, fset.Position(nm.Pos()).Line, ts.Name.Name, nm.Name, used[nm.Name])
					}
				}
			}
			return true
		})
	}
}
