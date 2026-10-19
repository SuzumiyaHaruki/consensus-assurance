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

type decl struct {
	init string
	line int
}

func declsOf(blk *ast.BlockStmt) map[string]decl {
	m := map[string]decl{}
	for _, st := range blk.List {
		as, ok := st.(*ast.AssignStmt)
		if !ok || as.Tok != token.DEFINE {
			continue
		}
		for i, lhs := range as.Lhs {
			id, ok := lhs.(*ast.Ident)
			if !ok || i >= len(as.Rhs) {
				continue
			}
			if _, exists := m[id.Name]; !exists {
				m[id.Name] = decl{init: exprText(as.Rhs[i])}
			}
		}
	}
	return m
}

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
		if !strings.HasSuffix(path, ".go") || strings.HasSuffix(path, ".pb.go") {
			return nil
		}
		f, err := parser.ParseFile(fset, path, nil, 0)
		if err != nil {
			return nil
		}
		var visit func(blk *ast.BlockStmt, stack []map[string]decl)
		visit = func(blk *ast.BlockStmt, stack []map[string]decl) {
			local := declsOf(blk)
			for name, d := range local {
				for i := len(stack) - 1; i >= 0; i-- {
					if od, ok := stack[i][name]; ok {
						if od.init == d.init && od.init != "" {
							pos := fset.Position(blk.Pos())
							fmt.Printf("%s:%d: inner %q = %s shadows outer at line %d\n", path, pos.Line, name, d.init, od.line)
						}
						break
					}
				}
			}
			// record line numbers using position of declaration stmt
			for _, st := range blk.List {
				as, ok := st.(*ast.AssignStmt)
				if !ok || as.Tok != token.DEFINE {
					continue
				}
				for i, lhs := range as.Lhs {
					id, ok := lhs.(*ast.Ident)
					if !ok || i >= len(as.Rhs) {
						continue
					}
					if d, ok2 := local[id.Name]; ok2 && d.line == 0 {
						d.line = fset.Position(as.Pos()).Line
						local[id.Name] = d
					}
				}
			}
			newStack := append(append([]map[string]decl{}, stack...), local)
			for _, st := range blk.List {
				ast.Inspect(st, func(n ast.Node) bool {
					if b, ok := n.(*ast.BlockStmt); ok && b != blk {
						visit(b, newStack)
						return false
					}
					return true
				})
			}
		}
		ast.Inspect(f, func(n ast.Node) bool {
			if fn, ok := n.(*ast.FuncDecl); ok && fn.Body != nil {
				visit(fn.Body, nil)
				return false
			}
			return true
		})
		return nil
	})
}

func exprText(e ast.Expr) string {
	switch v := e.(type) {
	case *ast.Ident:
		return v.Name
	case *ast.SelectorExpr:
		return exprText(v.X) + "." + v.Sel.Name
	case *ast.BasicLit:
		return v.Value
	case *ast.CallExpr:
		parts := []string{}
		for _, a := range v.Args {
			parts = append(parts, exprText(a))
		}
		return exprText(v.Fun) + "(" + strings.Join(parts, ",") + ")"
	case *ast.UnaryExpr:
		return v.Op.String() + exprText(v.X)
	default:
		return ""
	}
}
