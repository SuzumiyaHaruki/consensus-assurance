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
		f, err := parser.ParseFile(fset, path, nil, 0)
		if err != nil {
			return nil
		}
		ast.Inspect(f, func(n ast.Node) bool {
			switch v := n.(type) {
			case *ast.IfStmt:
				if len(v.Body.List) == 0 {
					fmt.Printf("%s:%d: empty if body\n", path, fset.Position(v.Pos()).Line)
				}
			case *ast.ForStmt:
				if len(v.Body.List) == 0 {
					fmt.Printf("%s:%d: empty for body\n", path, fset.Position(v.Pos()).Line)
				}
			case *ast.RangeStmt:
				if len(v.Body.List) == 0 {
					fmt.Printf("%s:%d: empty range body\n", path, fset.Position(v.Pos()).Line)
				}
			}
			return true
		})
		return nil
	})
}
