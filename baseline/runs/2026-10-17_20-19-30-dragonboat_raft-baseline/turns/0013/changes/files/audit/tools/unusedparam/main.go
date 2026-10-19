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
	fset := token.NewFileSet()
	filepath.Walk(".", func(path string, info os.FileInfo, err error) error {
		if err != nil { return nil }
		if info.IsDir() {
			n := info.Name()
			if n == ".runtime" || n == ".git" || n == "audit" { return filepath.SkipDir }
			return nil
		}
		if !strings.HasSuffix(path, ".go") || strings.HasSuffix(path, "_test.go") || strings.HasSuffix(path, ".pb.go") { return nil }
		if strings.Contains(path, "gorocksdb") { return nil }
		f, err := parser.ParseFile(fset, path, nil, 0)
		if err != nil { return nil }
		ast.Inspect(f, func(n ast.Node) bool {
			fn, ok := n.(*ast.FuncDecl)
			if !ok || fn.Body == nil { return true }
			if fn.Recv != nil && len(fn.Recv.List) > 0 {
				// methods: skip receiver
			}
			used := map[string]bool{}
			ast.Inspect(fn.Body, func(m ast.Node) bool {
				if id, ok := m.(*ast.Ident); ok { used[id.Name] = true }
				return true
			})
			check := func(fl *ast.FieldList) {
				if fl == nil { return }
				for _, fld := range fl.List {
					for _, nm := range fld.Names {
						if nm.Name == "_" || nm.Name == "ctx" { continue }
						if !used[nm.Name] {
							fmt.Printf("%s:%d: func %s: param %q unused\n", path, fset.Position(fn.Pos()).Line, fn.Name.Name, nm.Name)
						}
					}
				}
			}
			check(fn.Type.Params)
			return true
		})
		return nil
	})
}
