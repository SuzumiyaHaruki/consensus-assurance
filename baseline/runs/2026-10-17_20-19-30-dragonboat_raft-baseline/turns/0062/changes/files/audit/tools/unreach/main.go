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
			blk, ok := n.(*ast.BlockStmt)
			if !ok {
				return true
			}
			term := false
			for _, st := range blk.List {
				if term {
					fmt.Printf("%s:%d: statement after terminating statement\n", path, fset.Position(st.Pos()).Line)
					break
				}
				switch st.(type) {
				case *ast.ReturnStmt, *ast.BranchStmt:
					term = true
				}
			}
			return true
		})
		return nil
	})
}
