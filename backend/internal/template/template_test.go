package template

import (
	"os"
	"strings"
	"testing"
)

func TestRenderViteDev(t *testing.T) {
	raw := `
id: vite-dev
name: Vite dev
services:
  - name: app
    image: node:22
    script: npm install && npm run dev -- --host 0.0.0.0 --port 5173
    internalPort: 5173
    http: true
    logs: true
    shell: true
    volumes: [".:/app"]
`
	tpl, err := Parse(raw)
	if err != nil {
		t.Fatal(err)
	}
	compose, _, specs, err := Render(tpl, nil, map[string]int{"app": 18001})
	if err != nil {
		t.Fatal(err)
	}
	text := string(compose)
	if !strings.Contains(text, "node:22") || !strings.Contains(text, "npm run dev") || !strings.Contains(text, "18001:5173") {
		t.Fatalf("compose missing runtime: %s", text)
	}
	if len(specs) != 1 || !specs[0].Shell || specs[0].HostPort != 18001 {
		t.Fatalf("spec %+v", specs)
	}
}

func TestBuiltinTemplates(t *testing.T) {
	raws, err := LoadDir("../../../templates")
	if err != nil {
		t.Fatal(err)
	}
	if len(raws) < 8 {
		t.Fatalf("templates: %d", len(raws))
	}
	for id, raw := range raws {
		tpl, err := Parse(raw)
		if err != nil {
			t.Fatalf("%s: %v", id, err)
		}
		ports := map[string]int{}
		n := 18000
		for _, svc := range tpl.Services {
			if svc.InternalPort > 0 {
				ports[svc.Name] = n
				n++
			}
		}
		compose, _, specs, err := Render(tpl, nil, ports)
		if err != nil {
			t.Fatalf("%s render: %v", id, err)
		}
		if len(specs) == 0 || !strings.Contains(string(compose), "services:") {
			t.Fatalf("%s empty compose", id)
		}
		if id == "vite-dev" && !strings.Contains(string(compose), "node:22") {
			t.Fatalf("vite-dev image: %s", compose)
		}
	}
}

func TestParseComposeYAML(t *testing.T) {
	dir := t.TempDir()
	path := dir + "/compose.yaml"
	body := []byte("services:\n  web:\n    image: nginx\n    ports:\n      - \"8080:80\"\n  worker:\n    image: busybox\n")
	if err := os.WriteFile(path, body, 0o644); err != nil {
		t.Fatal(err)
	}
	svcs, err := parseComposeYAML(path)
	if err != nil {
		t.Fatal(err)
	}
	if len(svcs) != 2 {
		t.Fatalf("got %d", len(svcs))
	}
	var web ParsedService
	for _, svc := range svcs {
		if svc.Name == "web" {
			web = svc
		}
	}
	if web.HostPort != 8080 || web.InternalPort != 80 {
		t.Fatalf("web %+v", web)
	}
}
