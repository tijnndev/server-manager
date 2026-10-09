package api

import (
	"net/http"
	"os"
	"os/exec"
	"path/filepath"
	"strings"
	"time"

	"server-manager/backend/internal/model"
	"server-manager/backend/internal/safe"
)

func (a *App) listFiles(w http.ResponseWriter, r *http.Request) {
	user, ok := a.require(w, r)
	if !ok {
		return
	}
	st, ok := a.openStack(w, r, user)
	if !ok {
		return
	}
	dir, err := safe.Join(st.Dir, r.URL.Query().Get("path"))
	if err != nil {
		writeErr(w, 400, err.Error())
		return
	}
	entries, err := os.ReadDir(dir)
	if err != nil {
		writeErr(w, 404, "directory not found")
		return
	}
	type row struct {
		Name    string    `json:"name"`
		Dir     bool      `json:"dir"`
		Size    int64     `json:"size"`
		ModTime time.Time `json:"modTime"`
	}
	out := []row{}
	for _, entry := range entries {
		info, err := entry.Info()
		if err != nil {
			continue
		}
		out = append(out, row{Name: entry.Name(), Dir: entry.IsDir(), Size: info.Size(), ModTime: info.ModTime()})
	}
	writeJSON(w, 200, out)
}

func (a *App) readFile(w http.ResponseWriter, r *http.Request) {
	user, ok := a.require(w, r)
	if !ok {
		return
	}
	st, ok := a.openStack(w, r, user)
	if !ok {
		return
	}
	path, err := safe.Join(st.Dir, r.URL.Query().Get("path"))
	if err != nil {
		writeErr(w, 400, err.Error())
		return
	}
	info, err := os.Stat(path)
	if err != nil || info.IsDir() {
		writeErr(w, 404, "file not found")
		return
	}
	if info.Size() > 1<<20 {
		writeErr(w, 400, "file is too large to edit")
		return
	}
	b, err := os.ReadFile(path)
	if err != nil {
		writeErr(w, 500, err.Error())
		return
	}
	writeJSON(w, 200, map[string]string{"content": string(b)})
}

func (a *App) writeFile(w http.ResponseWriter, r *http.Request) {
	user, ok := a.require(w, r)
	if !ok {
		return
	}
	st, ok := a.openStack(w, r, user)
	if !ok {
		return
	}
	path, err := safe.Join(st.Dir, r.URL.Query().Get("path"))
	if err != nil || path == "" {
		writeErr(w, 400, "invalid path")
		return
	}
	var body struct {
		Content string `json:"content"`
	}
	if err := readJSON(w, r, &body); err != nil {
		writeErr(w, 400, "invalid json")
		return
	}
	if err := os.MkdirAll(filepath.Dir(path), 0o755); err != nil {
		writeErr(w, 500, err.Error())
		return
	}
	if err := os.WriteFile(path, []byte(body.Content), 0o644); err != nil {
		writeErr(w, 500, err.Error())
		return
	}
	a.store.AddActivity(r.Context(), user.ID, st.Name, "file", r.URL.Query().Get("path"))
	writeJSON(w, 200, map[string]bool{"ok": true})
}

func (a *App) deleteFile(w http.ResponseWriter, r *http.Request) {
	user, ok := a.require(w, r)
	if !ok {
		return
	}
	st, ok := a.openStack(w, r, user)
	if !ok {
		return
	}
	rel := r.URL.Query().Get("path")
	if rel == "" || rel == "." {
		writeErr(w, 400, "refusing to delete the stack root")
		return
	}
	path, err := safe.Join(st.Dir, rel)
	if err != nil {
		writeErr(w, 400, err.Error())
		return
	}
	if err := os.RemoveAll(path); err != nil {
		writeErr(w, 500, err.Error())
		return
	}
	a.store.AddActivity(r.Context(), user.ID, st.Name, "file-delete", rel)
	writeJSON(w, 200, map[string]bool{"ok": true})
}

func (a *App) mkdir(w http.ResponseWriter, r *http.Request) {
	user, ok := a.require(w, r)
	if !ok {
		return
	}
	st, ok := a.openStack(w, r, user)
	if !ok {
		return
	}
	var body struct {
		Path string `json:"path"`
	}
	if err := readJSON(w, r, &body); err != nil {
		writeErr(w, 400, "invalid json")
		return
	}
	path, err := safe.Join(st.Dir, body.Path)
	if err != nil {
		writeErr(w, 400, err.Error())
		return
	}
	if err := os.MkdirAll(path, 0o755); err != nil {
		writeErr(w, 500, err.Error())
		return
	}
	writeJSON(w, 200, map[string]bool{"ok": true})
}

func (a *App) upload(w http.ResponseWriter, r *http.Request) {
	user, ok := a.require(w, r)
	if !ok {
		return
	}
	st, ok := a.openStack(w, r, user)
	if !ok {
		return
	}
	r.Body = http.MaxBytesReader(w, r.Body, 32<<20)
	if err := r.ParseMultipartForm(32 << 20); err != nil {
		writeErr(w, 400, "invalid upload")
		return
	}
	file, header, err := r.FormFile("file")
	if err != nil {
		writeErr(w, 400, "file is required")
		return
	}
	defer file.Close()
	dir, err := safe.Join(st.Dir, r.URL.Query().Get("path"))
	if err != nil {
		writeErr(w, 400, err.Error())
		return
	}
	name := filepath.Base(header.Filename)
	if name == "." || name == string(filepath.Separator) {
		writeErr(w, 400, "invalid file name")
		return
	}
	dest, err := safe.Join(dir, name)
	if err != nil {
		writeErr(w, 400, err.Error())
		return
	}
	body, err := readAllLimit(file, 32<<20)
	if err != nil {
		writeErr(w, 400, err.Error())
		return
	}
	if err := os.MkdirAll(dir, 0o755); err != nil {
		writeErr(w, 500, err.Error())
		return
	}
	if err := os.WriteFile(dest, body, 0o644); err != nil {
		writeErr(w, 500, err.Error())
		return
	}
	writeJSON(w, 200, map[string]string{"name": name})
}

func (a *App) gitStatus(w http.ResponseWriter, r *http.Request) {
	user, ok := a.require(w, r)
	if !ok {
		return
	}
	st, ok := a.openStack(w, r, user)
	if !ok {
		return
	}
	if _, err := os.Stat(filepath.Join(st.Dir, ".git")); err != nil {
		writeJSON(w, 200, map[string]any{"repo": false, "output": ""})
		return
	}
	out, err := git(st, "status", "--porcelain=v1", "-b")
	writeJSON(w, 200, map[string]any{"repo": true, "output": out, "error": errString(err)})
}

func (a *App) gitPull(w http.ResponseWriter, r *http.Request) {
	user, ok := a.require(w, r)
	if !ok {
		return
	}
	st, ok := a.openStack(w, r, user)
	if !ok {
		return
	}
	out, err := git(st, "pull", "--ff-only")
	a.store.AddActivity(r.Context(), user.ID, st.Name, "git-pull", errString(err))
	if err != nil {
		writeJSON(w, 500, map[string]string{"error": out})
		return
	}
	writeJSON(w, 200, map[string]string{"output": out})
}

func (a *App) gitClone(w http.ResponseWriter, r *http.Request) {
	user, ok := a.require(w, r)
	if !ok {
		return
	}
	st, ok := a.openStack(w, r, user)
	if !ok {
		return
	}
	var body struct {
		URL string `json:"url"`
	}
	if err := readJSON(w, r, &body); err != nil {
		writeErr(w, 400, "invalid json")
		return
	}
	remote := strings.TrimSpace(body.URL)
	if remote == "" || strings.HasPrefix(remote, "-") {
		writeErr(w, 400, "invalid git url")
		return
	}
	if _, err := os.Stat(filepath.Join(st.Dir, ".git")); err == nil {
		writeErr(w, 409, "repository already exists")
		return
	}
	cmd := exec.Command("git", "clone", remote, ".")
	cmd.Dir = st.Dir
	out, err := cmd.CombinedOutput()
	text := strings.TrimSpace(string(out))
	a.store.AddActivity(r.Context(), user.ID, st.Name, "git-clone", remote)
	if err != nil {
		if text == "" {
			text = err.Error()
		}
		writeErr(w, 500, text)
		return
	}
	writeJSON(w, 200, map[string]string{"output": text})
}

func git(st model.Stack, args ...string) (string, error) {
	cmd := exec.Command("git", append([]string{"-C", st.Dir}, args...)...)
	out, err := cmd.CombinedOutput()
	return strings.TrimSpace(string(out)), err
}

func errString(err error) string {
	if err == nil {
		return ""
	}
	return err.Error()
}

func (a *App) static(w http.ResponseWriter, r *http.Request) {
	if strings.HasPrefix(r.URL.Path, "/api/") {
		http.NotFound(w, r)
		return
	}
	rel := strings.TrimPrefix(r.URL.Path, "/")
	if rel == "" {
		rel = "index.html"
	}
	path, err := safe.Join(a.cfg.FrontendDir, rel)
	if err != nil {
		http.NotFound(w, r)
		return
	}
	info, err := os.Stat(path)
	if err != nil || info.IsDir() {
		index := filepath.Join(a.cfg.FrontendDir, "index.html")
		if _, statErr := os.Stat(index); statErr != nil {
			http.Error(w, "panel assets are not built", http.StatusNotFound)
			return
		}
		http.ServeFile(w, r, index)
		return
	}
	http.ServeFile(w, r, path)
}
