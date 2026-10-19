package dlog

import "testing"

// The nil branches in Logger methods look like intended fallbacks to the
// standard logger, but they continue into l.verbose.
func TestAuditNilLoggerDoesNotPanic(t *testing.T) {
	defer func() {
		if p := recover(); p != nil {
			t.Errorf("nil *Logger panicked instead of using the fallback logger: %v", p)
		}
	}()
	var l *Logger
	l.Println("audit nil logger")
}
