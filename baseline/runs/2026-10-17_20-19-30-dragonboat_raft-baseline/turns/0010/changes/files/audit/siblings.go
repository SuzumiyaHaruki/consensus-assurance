package main

import (
	"fmt"
	"go/ast"
	"go/parser"
	"go/token"
	"os"
	"path/filepath"
	"sort"
	"strings"
)

type fnInfo struct {
	name    string
	file    string
	line    int
	callees map[string]bool
}

func calleeName(e ast.Expr) string {
	switch v := e.(type) {
	case *ast.Ident:
		return v.Name
	case *ast.SelectorExpr:
		return v.Sel.Name
	case *ast.CallExpr:
		return calleeName(v.Fun)
	}
	return ""
}

func main() {
	fset := token.NewFileSet()
	groups := map[string][]fnInfo{}
	for _, root := range os.Args[1:] {
		filepath.Walk(root, func(path string, info os.FileInfo, err error) error {
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
			for _, d := range f.Decls {
				fn, ok := d.(*ast.FuncDecl)
				if !ok || fn.Body == nil || fn.Recv == nil {
					continue
				}
				callees := map[string]bool{}
				ast.Inspect(fn.Body, func(n ast.Node) bool {
					if c, ok := n.(*ast.CallExpr); ok {
						if name := calleeName(c.Fun); name != "" {
							callees[name] = true
						}
					}
					return true
				})
				name := fn.Name.Name
				prefix := name
				for i := len(name) - 1; i > 0; i-- {
					if name[i] >= 'A' && name[i] <= 'Z' {
						prefix = name[:i]
						break
					}
				}
				groups[prefix] = append(groups[prefix], fnInfo{
					name: name, file: path, line: fset.Position(fn.Pos()).Line, callees: callees,
				})
			}
			return nil
		})
	}
	var keys []string
	for k, v := range groups {
		if len(v) >= 3 {
			keys = append(keys, k)
		}
	}
	sort.Strings(keys)
	for _, k := range keys {
		g := groups[k]
		// intersection of callees
		common := map[string]int{}
		for _, f := range g {
			for c := range f.callees {
				common[c]++
			}
		}
		var shared []string
		for c, n := range common {
			if n == len(g) && c != "Errorf" && c != "Fatalf" && c != "Infof" && c != "Warningf" && c != "Debugf" {
				shared = append(shared, c)
			}
		}
		sort.Strings(shared)
		fmt.Printf("== %s (%d funcs) shared: %v\n", k, len(g), shared)
		for _, f := range g {
			var missing []string
			for _, c := range shared {
				if !f.callees[c] {
					missing = append(missing, c)
				}
			}
			if len(missing) > 0 {
				fmt.Printf("   %s (%s:%d) missing: %v\n", f.name, f.file, f.line, missing)
			}
		}
	}
}
