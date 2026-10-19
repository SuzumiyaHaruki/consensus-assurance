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

type scopeVar struct {
	init string
	pos  token.Pos
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
		if !strings.HasSuffix(path, ".go") || strings.HasSuffix(path, "_test.go") || strings.HasSuffix(path, ".pb.go") {
			return nil
		}
		f, err := parser.ParseFile(fset, path, nil, 0)
		if err != nil {
			return nil
		}
		ast.Inspect(f, func(n ast.Node) bool {
			fn, ok := n.(*ast.FuncDecl)
			if !ok || fn.Body == nil {
				return true
			}
			// collect top-level declarations in the function
			top := map[string]string{}
			ast.Inspect(fn.Body, func(m ast.Node) bool {
				as, ok := m.(*ast.AssignStmt)
				if !ok {
					return true
				}
				if as.Tok != token.DEFINE {
					return true
				}
				for i, lhs := range as.Lhs {
					id, ok := lhs.(*ast.Ident)
					if !ok || i >= len(as.Rhs) {
						continue
					}
					if _, exists := top[id.Name]; !exists {
						top[id.Name] = strings.TrimSpace(exprString(fset, as.Rhs[i]))
					}
				}
				return true
			})
			// find inner blocks declaring same name with same init text
			var walk func(n ast.Node, depth int)
			walk = func(n ast.Node, depth int) {
				ast.Inspect(n, func(m ast.Node) bool {
					if m == nil {
						return false
					}
					if blk, ok := m.(*ast.BlockStmt); ok && blk != fn.Body {
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
								if init, ok := top[id.Name]; ok {
									cur := strings.TrimSpace(exprString(fset, as.Rhs[i]))
									if cur == init && cur != "" {
										fmt.Printf("%s:%d: shadow %q = %s (outer same init at line %d)\n",
											path, fset.Position(as.Pos()).Line, id.Name, cur, fset.Position(fn.Pos()).Line)
									}
								}
							}
						}
					}
					return true
				})
			}
			walk(fn.Body, 0)
			return true
		})
		return nil
	})
}

func exprString(fset *token.FileSet, e ast.Expr) string {
	s := &strings.Builder{}
	fmt.Fprint(s, exprText(e))
	return s.String()
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
	default:
		return fmt.Sprintf("%T", e)
	}
}
