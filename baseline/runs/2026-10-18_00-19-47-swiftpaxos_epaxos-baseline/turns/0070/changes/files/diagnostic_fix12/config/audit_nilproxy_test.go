package config

import "testing"

// config.Read leaves Proxy nil when the configuration has no Proxy section.
// main.go:132 and replica.clientListener call these methods unconditionally.
func TestAuditNilProxyDoesNotPanic(t *testing.T) {
	defer func() {
		if p := recover(); p != nil {
			t.Errorf("nil *ProxyInfo panicked instead of returning the no-proxy default: %v", p)
		}
	}()
	var p *ProxyInfo
	if got := p.ProxyOf("client"); got != "none" {
		t.Errorf("ProxyOf=%q, want none", got)
	}
	if p.IsProxy("server", "client") {
		t.Errorf("IsProxy=true for nil ProxyInfo")
	}
	if p.IsLocal("server", "client") {
		t.Errorf("IsLocal=true for nil ProxyInfo")
	}
}
