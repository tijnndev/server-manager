package domain

import (
	"strings"
	"testing"

	"server-manager/backend/internal/model"
)

func TestRender(t *testing.T) {
	body := Render([]model.Domain{{Hostname: "app.example.com", UpstreamPort: 18001}})
	if !strings.Contains(body, "server_name app.example.com") || !strings.Contains(body, "127.0.0.1:18001") {
		t.Fatal(body)
	}
}

func TestValidHost(t *testing.T) {
	if !ValidHost("app.example.com") {
		t.Fatal("expected valid")
	}
	if ValidHost("localhost") || ValidHost("-bad.com") || ValidHost("a..b.com") {
		t.Fatal("expected invalid")
	}
}

func TestZoneName(t *testing.T) {
	if ZoneName("a.b.example.com") != "example.com" {
		t.Fatal(ZoneName("a.b.example.com"))
	}
}
