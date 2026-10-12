package runtime

import (
	"os"
	"path/filepath"
	"testing"
)

func TestRestartTargetsPublishedService(t *testing.T) {
	dir := t.TempDir()
	compose := []byte(`services:
  lokalis-ai:
    build: .
    ports:
      - "8012:80"
  build-vite:
    image: node:22
    command: ["tail", "-f", "/dev/null"]
`)
	path := filepath.Join(dir, "compose.yaml")
	if err := os.WriteFile(path, compose, 0o644); err != nil {
		t.Fatal(err)
	}
	got := publishedServices(dir, path)
	if len(got) != 1 || got[0] != "lokalis-ai" {
		t.Fatalf("published services: %#v", got)
	}
	steps, _, err := actionSteps(dir, path, "restart")
	if err != nil {
		t.Fatal(err)
	}
	if len(steps) != 1 || steps[0][0] != "restart" || steps[0][1] != "lokalis-ai" {
		t.Fatalf("restart steps: %#v", steps)
	}
}

func TestRebuildViteUsesNoCache(t *testing.T) {
	dir := t.TempDir()
	if err := os.WriteFile(filepath.Join(dir, "compose.yaml"), []byte("services:\n  app:\n    build: .\n    ports: [\"80:80\"]\n"), 0o644); err != nil {
		t.Fatal(err)
	}
	if err := os.WriteFile(filepath.Join(dir, "Dockerfile"), []byte("FROM node:22 AS build\nRUN npm run build\nFROM httpd:alpine\n"), 0o644); err != nil {
		t.Fatal(err)
	}
	steps, _, err := actionSteps(dir, filepath.Join(dir, "compose.yaml"), "rebuild")
	if err != nil {
		t.Fatal(err)
	}
	if len(steps) != 2 || steps[0][0] != "build" || steps[0][1] != "--no-cache" {
		t.Fatalf("build step: %#v", steps)
	}
	if steps[1][0] != "up" || !containsArg(steps[1], "--force-recreate") {
		t.Fatalf("up step: %#v", steps[1])
	}
}
