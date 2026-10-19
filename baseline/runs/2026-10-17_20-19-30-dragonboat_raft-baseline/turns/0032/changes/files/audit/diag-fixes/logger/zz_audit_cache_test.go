//go:build dragonboat_audit

// Audit-only check: the logger cache is keyed by package name only, so the
// first GetLogger/GetMonkeyLogger call decides the mode for that package.

package logger

import "testing"

func TestAuditMonkeyLoggerCache(t *testing.T) {
	_loggers.mu.Lock()
	_loggers.loggers = make(map[string]*dragonboatLogger)
	_loggers.mu.Unlock()
	ml := GetMonkeyLogger("audit-pkg")
	l := GetLogger("audit-pkg")
	_ = ml
	dl, ok := l.(*dragonboatLogger)
	if !ok {
		t.Fatalf("unexpected logger type %T", l)
	}
	if dl.monkeyLogger {
		t.Fatalf("GetLogger(\"audit-pkg\") returned the monkey-mode logger " +
			"created by the earlier GetMonkeyLogger call")
	}
}
