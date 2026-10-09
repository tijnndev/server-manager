package api

import (
	"context"
	"crypto/rand"
	"encoding/hex"
	"fmt"
	"io"
	"net/http"
	"os"
	"path/filepath"
	"regexp"
	"strconv"
	"strings"
	"time"

	"github.com/coder/websocket"

	"server-manager/backend/internal/auth"
	"server-manager/backend/internal/domain"
	"server-manager/backend/internal/model"
	"server-manager/backend/internal/notify"
	"server-manager/backend/internal/runtime"
	"server-manager/backend/internal/schedule"
	"server-manager/backend/internal/store"
	"server-manager/backend/internal/template"
)

var nameRe = regexp.MustCompile(`^[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?$`)

func (a *App) login(w http.ResponseWriter, r *http.Request) {
	var body struct {
		Username string `json:"username"`
		Password string `json:"password"`
	}
	if err := readJSON(w, r, &body); err != nil {
		writeErr(w, 400, "invalid json")
		return
	}
	user, hash, err := a.store.UserByUsername(r.Context(), body.Username)
	if err != nil || !auth.CheckPassword(hash, body.Password) {
		writeErr(w, http.StatusUnauthorized, "invalid credentials")
		return
	}
	raw, tokenHash, err := auth.NewToken()
	if err != nil {
		writeErr(w, 500, "session failed")
		return
	}
	if err := a.store.CreateSession(r.Context(), user.ID, tokenHash, time.Now().Add(7*24*time.Hour)); err != nil {
		writeErr(w, 500, "session failed")
		return
	}
	auth.SetCookie(w, raw, a.cfg.CookieSecure)
	a.store.AddActivity(r.Context(), user.ID, "", "login", "")
	writeJSON(w, 200, user)
}

func (a *App) logout(w http.ResponseWriter, r *http.Request) {
	if raw := auth.ReadCookie(r); raw != "" {
		_ = a.store.DeleteSession(r.Context(), auth.HashToken(raw))
	}
	auth.ClearCookie(w)
	writeJSON(w, 200, map[string]bool{"ok": true})
}

func (a *App) me(w http.ResponseWriter, r *http.Request) {
	user, ok := a.require(w, r)
	if !ok {
		return
	}
	writeJSON(w, 200, user)
}

func (a *App) listStacks(w http.ResponseWriter, r *http.Request) {
	user, ok := a.require(w, r)
	if !ok {
		return
	}
	stacks, err := a.views(r.Context(), user)
	if err != nil {
		writeErr(w, 500, err.Error())
		return
	}
	writeJSON(w, 200, stacks)
}

func (a *App) getStack(w http.ResponseWriter, r *http.Request) {
	user, ok := a.require(w, r)
	if !ok {
		return
	}
	st, ok := a.openStack(w, r, user)
	if !ok {
		return
	}
	views := a.sup.Overlay([]model.Stack{st})
	domains, err := a.store.ListDomains(r.Context(), st.ID)
	if err != nil {
		writeErr(w, 500, err.Error())
		return
	}
	writeJSON(w, 200, map[string]any{"stack": views[0], "domains": domains})
}

func (a *App) patchStack(w http.ResponseWriter, r *http.Request) {
	user, ok := a.require(w, r)
	if !ok {
		return
	}
	st, ok := a.openStack(w, r, user)
	if !ok || !a.ownerOr(w, user, st) {
		return
	}
	var body struct {
		Description string `json:"description"`
	}
	if err := readJSON(w, r, &body); err != nil {
		writeErr(w, 400, "invalid json")
		return
	}
	if err := a.store.SetDescription(r.Context(), st.ID, body.Description); err != nil {
		writeErr(w, 500, err.Error())
		return
	}
	writeJSON(w, 200, map[string]bool{"ok": true})
}

func (a *App) ownerOr(w http.ResponseWriter, user model.User, st model.Stack) bool {
	if a.owns(user, st) {
		return true
	}
	writeErr(w, http.StatusForbidden, "owner required")
	return false
}

func (a *App) createStack(w http.ResponseWriter, r *http.Request) {
	user, ok := a.require(w, r)
	if !ok {
		return
	}
	if strings.HasPrefix(r.Header.Get("Content-Type"), "multipart/form-data") {
		a.createFromUpload(w, r, user)
		return
	}
	var body struct {
		Name        string            `json:"name"`
		TemplateID  string            `json:"templateId"`
		Description string            `json:"description"`
		Overrides   map[string]string `json:"overrides"`
		Compose     string            `json:"compose"`
	}
	if err := readJSON(w, r, &body); err != nil {
		writeErr(w, 400, "invalid json")
		return
	}
	if strings.TrimSpace(body.Compose) != "" {
		a.writeCustom(w, r, user, body.Name, body.Description, body.Compose, nil)
		return
	}
	a.writeTemplate(w, r, user, body.Name, body.Description, body.TemplateID, body.Overrides)
}

func (a *App) createFromUpload(w http.ResponseWriter, r *http.Request, user model.User) {
	r.Body = http.MaxBytesReader(w, r.Body, 32<<20)
	if err := r.ParseMultipartForm(32 << 20); err != nil {
		writeErr(w, 400, "invalid upload")
		return
	}
	name := r.FormValue("name")
	description := r.FormValue("description")
	compose := r.FormValue("compose")
	if file, _, err := r.FormFile("composeFile"); err == nil {
		defer file.Close()
		b, _ := readAllLimit(file, 2<<20)
		if len(b) > 0 {
			compose = string(b)
		}
	}
	var extras []uploaded
	if r.MultipartForm != nil {
		for _, fh := range r.MultipartForm.File["files"] {
			if strings.Contains(fh.Filename, "/") || strings.Contains(fh.Filename, "\\") || fh.Filename == "" {
				continue
			}
			f, err := fh.Open()
			if err != nil {
				continue
			}
			b, _ := readAllLimit(f, 2<<20)
			f.Close()
			extras = append(extras, uploaded{Name: filepath.Base(fh.Filename), Body: b})
		}
	}
	a.writeCustom(w, r, user, name, description, compose, extras)
}

type uploaded struct {
	Name string
	Body []byte
}

func (a *App) writeTemplate(w http.ResponseWriter, r *http.Request, user model.User, name, description, templateID string, overrides map[string]string) {
	if !nameRe.MatchString(name) {
		writeErr(w, 400, "name must be lowercase letters, numbers and hyphens")
		return
	}
	tpl, ok := a.tpl.Get(templateID)
	if !ok {
		writeErr(w, 400, "unknown template")
		return
	}
	clean := map[string]string{}
	for k, v := range overrides {
		if strings.HasPrefix(k, "script:") || strings.HasPrefix(k, "env:") {
			clean[k] = v
		}
	}
	dir := filepath.Join(a.cfg.DataDir, name)
	if _, err := os.Stat(dir); err == nil {
		writeErr(w, 409, "stack already exists")
		return
	}
	ports := map[string]int{}
	a.alloc.Lock()
	next, err := a.store.NextHostPort(r.Context())
	if err != nil {
		a.alloc.Unlock()
		writeErr(w, 500, err.Error())
		return
	}
	for _, svc := range tpl.Services {
		if svc.InternalPort > 0 {
			ports[svc.Name] = next
			next++
		}
	}
	compose, dockerfile, specs, err := template.Render(tpl, clean, ports)
	if err != nil {
		a.alloc.Unlock()
		writeErr(w, 500, err.Error())
		return
	}
	if err := os.MkdirAll(dir, 0o755); err != nil {
		a.alloc.Unlock()
		writeErr(w, 500, err.Error())
		return
	}
	if err := os.WriteFile(filepath.Join(dir, "compose.yaml"), compose, 0o644); err != nil {
		a.alloc.Unlock()
		_ = os.RemoveAll(dir)
		writeErr(w, 500, err.Error())
		return
	}
	if len(dockerfile) > 0 {
		if err := os.WriteFile(filepath.Join(dir, "Dockerfile"), dockerfile, 0o644); err != nil {
			a.alloc.Unlock()
			_ = os.RemoveAll(dir)
			writeErr(w, 500, err.Error())
			return
		}
	}
	err = a.persistStack(r.Context(), user, name, "template", templateID, description, dir, specs)
	a.alloc.Unlock()
	if err != nil {
		_ = os.RemoveAll(dir)
		writeErr(w, 500, err.Error())
		return
	}
	a.store.AddActivity(r.Context(), user.ID, name, "create", templateID)
	a.PushState()
	writeJSON(w, 201, map[string]string{"name": name})
}

func (a *App) writeCustom(w http.ResponseWriter, r *http.Request, user model.User, name, description, compose string, extras []uploaded) {
	if !nameRe.MatchString(name) {
		writeErr(w, 400, "name must be lowercase letters, numbers and hyphens")
		return
	}
	if strings.TrimSpace(compose) == "" {
		writeErr(w, 400, "compose file is required")
		return
	}
	dir := filepath.Join(a.cfg.DataDir, name)
	if _, err := os.Stat(dir); err == nil {
		writeErr(w, 409, "stack already exists")
		return
	}
	if err := os.MkdirAll(dir, 0o755); err != nil {
		writeErr(w, 500, err.Error())
		return
	}
	path := filepath.Join(dir, "compose.yaml")
	if err := os.WriteFile(path, []byte(compose), 0o644); err != nil {
		_ = os.RemoveAll(dir)
		writeErr(w, 500, err.Error())
		return
	}
	for _, extra := range extras {
		if extra.Name == "compose.yaml" {
			continue
		}
		if err := os.WriteFile(filepath.Join(dir, extra.Name), extra.Body, 0o644); err != nil {
			_ = os.RemoveAll(dir)
			writeErr(w, 500, err.Error())
			return
		}
	}
	parsed, err := template.ParseCompose(dir, path)
	if err != nil {
		_ = os.RemoveAll(dir)
		writeErr(w, 400, err.Error())
		return
	}
	var specs []template.Spec
	for _, svc := range parsed {
		specs = append(specs, template.Spec{
			Name: svc.Name, HTTP: svc.HTTP, InternalPort: svc.InternalPort, HostPort: svc.HostPort,
			Logs: svc.Logs, Shell: svc.Shell,
		})
	}
	if err := a.persistStack(r.Context(), user, name, "compose", "", description, dir, specs); err != nil {
		_ = os.RemoveAll(dir)
		writeErr(w, 500, err.Error())
		return
	}
	a.store.AddActivity(r.Context(), user.ID, name, "create", "compose")
	a.PushState()
	writeJSON(w, 201, map[string]string{"name": name})
}

func (a *App) persistStack(ctx context.Context, user model.User, name, source, templateID, description, dir string, specs []template.Spec) error {
	services := make([]model.NewService, len(specs))
	names := make([]string, len(specs))
	for i, spec := range specs {
		services[i] = model.NewService{
			Name: spec.Name, HTTP: spec.HTTP, InternalPort: spec.InternalPort, HostPort: spec.HostPort,
			Logs: spec.Logs, Shell: spec.Shell,
		}
		names[i] = spec.Name
	}
	id, err := newID()
	if err != nil {
		return err
	}
	abs, _ := filepath.Abs(dir)
	err = a.store.CreateStack(ctx, store.NewStack{
		ID: id, Name: name, OwnerID: user.ID, Source: source, TemplateID: templateID,
		Dir: abs, Description: description, Services: services,
	})
	if err != nil {
		return err
	}
	a.sup.SetServices(name, names)
	a.sup.SetDesired(name, "stopped")
	return nil
}

func (a *App) deleteStack(w http.ResponseWriter, r *http.Request) {
	user, ok := a.require(w, r)
	if !ok {
		return
	}
	st, ok := a.openStack(w, r, user)
	if !ok || !a.ownerOr(w, user, st) {
		return
	}
	if err := a.sup.Down(st.Name, st.Dir); err != nil {
		writeErr(w, 500, err.Error())
		return
	}
	root, _ := filepath.Abs(a.cfg.DataDir)
	dir, _ := filepath.Abs(st.Dir)
	if rel, err := filepath.Rel(root, dir); err == nil && rel != ".." && !strings.HasPrefix(rel, ".."+string(filepath.Separator)) {
		_ = os.RemoveAll(dir)
	}
	domains, _ := a.store.ListDomains(r.Context(), st.ID)
	if err := a.store.DeleteStack(r.Context(), st.ID); err != nil {
		writeErr(w, 500, err.Error())
		return
	}
	_ = domain.ApplyNginx(a.cfg.NginxAvailable, a.cfg.NginxEnabled, st.Name, nil)
	settings, _ := a.store.GetSettings(r.Context())
	for _, d := range domains {
		_ = domain.DeleteRecord(settings.CloudflareToken, d.Hostname, d.RecordID)
	}
	a.sup.Forget(st.Name)
	if a.Sched != nil {
		a.Sched.Reload()
	}
	a.store.AddActivity(r.Context(), user.ID, st.Name, "delete", "")
	a.PushState()
	writeJSON(w, 200, map[string]bool{"ok": true})
}

func (a *App) power(w http.ResponseWriter, r *http.Request) {
	user, ok := a.require(w, r)
	if !ok {
		return
	}
	st, ok := a.openStack(w, r, user)
	if !ok {
		return
	}
	action := r.PathValue("action")
	if err := a.perform(r.Context(), user, st, action); err != nil {
		writeErr(w, 500, err.Error())
		return
	}
	writeJSON(w, 200, map[string]string{"status": "ok", "action": action})
}

func (a *App) perform(ctx context.Context, user model.User, st model.Stack, action string) error {
	if action == "stop" {
		a.sup.SetDesired(st.Name, "stopped")
	}
	err := a.sup.Apply(st.Name, st.Dir, action)
	if err != nil {
		if action == "stop" {
			a.sup.SetDesired(st.Name, st.Desired)
		}
		a.store.AddActivity(ctx, user.ID, st.Name, action, err.Error())
		return err
	}
	desired := "running"
	if action == "stop" {
		desired = "stopped"
	}
	if err := a.store.SetDesired(ctx, st.ID, desired); err != nil {
		return err
	}
	a.sup.SetDesired(st.Name, desired)
	a.store.AddActivity(ctx, user.ID, st.Name, action, "")
	a.resyncServices(ctx, st)
	settings, _ := a.store.GetSettings(ctx)
	who := user.Username
	if who == "" {
		who = "schedule"
	}
	go notify.Discord(settings.DiscordWebhook, who+" "+action+" "+st.Name)
	a.PushState()
	return nil
}

// resyncServices re-reads the stack's compose file and updates the stored
// service list, so edits made in the Files tab are reflected in the UI.
func (a *App) resyncServices(ctx context.Context, st model.Stack) {
	file, err := runtime.FindCompose(st.Dir)
	if err != nil {
		return
	}
	parsed, err := template.ParseCompose(st.Dir, file)
	if err != nil {
		return
	}
	services := make([]model.NewService, len(parsed))
	names := make([]string, len(parsed))
	changed := len(parsed) != len(st.Services)
	for i, svc := range parsed {
		services[i] = model.NewService{
			Name: svc.Name, HTTP: svc.HTTP, InternalPort: svc.InternalPort, HostPort: svc.HostPort,
			Logs: svc.Logs, Shell: svc.Shell,
		}
		names[i] = svc.Name
		if !changed && (i >= len(st.Services) || st.Services[i].Name != svc.Name || st.Services[i].HostPort != svc.HostPort || st.Services[i].InternalPort != svc.InternalPort) {
			changed = true
		}
	}
	if !changed {
		return
	}
	if err := a.store.SyncStackServices(ctx, st.ID, services); err != nil {
		return
	}
	a.sup.SetServices(st.Name, names)
}

func (a *App) exec(w http.ResponseWriter, r *http.Request) {
	user, ok := a.require(w, r)
	if !ok {
		return
	}
	st, ok := a.openStack(w, r, user)
	if !ok {
		return
	}
	var body struct {
		Service string `json:"service"`
		Command string `json:"command"`
	}
	if err := readJSON(w, r, &body); err != nil || strings.TrimSpace(body.Command) == "" {
		writeErr(w, 400, "service and command are required")
		return
	}
	if !hasService(st, body.Service) {
		writeErr(w, 404, "unknown service")
		return
	}
	ctx, cancel := context.WithTimeout(r.Context(), 30*time.Second)
	defer cancel()
	out, code, err := a.sup.Exec(ctx, st.Name, body.Service, body.Command)
	if err != nil {
		writeErr(w, 409, err.Error())
		return
	}
	writeJSON(w, 200, map[string]any{"output": out, "exitCode": code})
}

func (a *App) shell(w http.ResponseWriter, r *http.Request) {
	user, err := a.store.UserByToken(r.Context(), auth.ReadCookie(r))
	if err != nil {
		writeErr(w, 401, "login required")
		return
	}
	st, ok := a.openStack(w, r, user)
	if !ok {
		return
	}
	service := r.URL.Query().Get("service")
	if !hasService(st, service) {
		writeErr(w, 404, "unknown service")
		return
	}
	conn, err := websocket.Accept(w, r, &websocket.AcceptOptions{InsecureSkipVerify: true})
	if err != nil {
		return
	}
	defer conn.Close(websocket.StatusNormalClosure, "")
	ctx, cancel := context.WithCancel(r.Context())
	defer cancel()
	hijack, err := a.sup.Shell(ctx, st.Name, service)
	if err != nil {
		_ = conn.Write(ctx, websocket.MessageText, []byte(err.Error()))
		return
	}
	defer hijack.Close()
	go func() {
		buf := make([]byte, 4096)
		for {
			n, err := hijack.Reader.Read(buf)
			if n > 0 {
				_ = conn.Write(ctx, websocket.MessageBinary, buf[:n])
			}
			if err != nil {
				cancel()
				return
			}
		}
	}()
	for {
		_, data, err := conn.Read(ctx)
		if err != nil {
			return
		}
		if _, err := hijack.Conn.Write(data); err != nil {
			return
		}
	}
}

func hasService(st model.Stack, name string) bool {
	for _, svc := range st.Services {
		if svc.Name == name {
			return true
		}
	}
	return false
}

func (a *App) listDomains(w http.ResponseWriter, r *http.Request) {
	user, ok := a.require(w, r)
	if !ok {
		return
	}
	st, ok := a.openStack(w, r, user)
	if !ok {
		return
	}
	domains, err := a.store.ListDomains(r.Context(), st.ID)
	if err != nil {
		writeErr(w, 500, err.Error())
		return
	}
	writeJSON(w, 200, domains)
}

func (a *App) publish(w http.ResponseWriter, r *http.Request) {
	user, ok := a.require(w, r)
	if !ok {
		return
	}
	st, ok := a.openStack(w, r, user)
	if !ok || !a.ownerOr(w, user, st) {
		return
	}
	var body struct {
		Hostname   string `json:"hostname"`
		Service    string `json:"service"`
		TLS        bool   `json:"tls"`
		Cloudflare bool   `json:"cloudflare"`
	}
	if err := readJSON(w, r, &body); err != nil {
		writeErr(w, 400, "invalid json")
		return
	}
	body.Hostname = strings.ToLower(strings.TrimSpace(body.Hostname))
	if !domain.ValidHost(body.Hostname) {
		writeErr(w, 400, "invalid hostname")
		return
	}
	views := a.sup.Overlay([]model.Stack{st})
	var port int
	found := false
	for _, svc := range views[0].Services {
		if svc.Name == body.Service {
			found = true
			port = svc.HostPort
		}
	}
	if !found {
		writeErr(w, 404, "unknown service")
		return
	}
	if port <= 0 {
		writeErr(w, 400, "service has no published port")
		return
	}
	existing, err := a.store.ListDomains(r.Context(), st.ID)
	if err != nil {
		writeErr(w, 500, err.Error())
		return
	}
	next := []model.Domain{{
		StackID: st.ID, ServiceName: body.Service, Hostname: body.Hostname, UpstreamPort: port,
		TLS: body.TLS, Cloudflare: body.Cloudflare,
	}}
	for _, d := range existing {
		if d.Hostname != body.Hostname {
			next = append(next, d)
		}
	}
	if err := domain.ApplyNginx(a.cfg.NginxAvailable, a.cfg.NginxEnabled, st.Name, next); err != nil {
		writeErr(w, 500, err.Error())
		return
	}
	result := domain.Result{Nginx: true}
	settings, _ := a.store.GetSettings(r.Context())
	recordID := ""
	if body.Cloudflare {
		id, err := domain.EnsureRecord(settings.CloudflareToken, body.Hostname, settings.PublicIP, true)
		if err != nil {
			result.Warnings = append(result.Warnings, err.Error())
		} else {
			recordID = id
			result.Cloudflare = true
		}
	}
	if err := a.store.SaveDomain(r.Context(), model.Domain{
		StackID: st.ID, ServiceName: body.Service, Hostname: body.Hostname, UpstreamPort: port,
		TLS: body.TLS, Cloudflare: body.Cloudflare, RecordID: recordID,
	}); err != nil {
		writeErr(w, 500, err.Error())
		return
	}
	if body.TLS {
		if err := domain.EnsureCert(body.Hostname, settings.AcmeEmail); err != nil {
			result.Warnings = append(result.Warnings, err.Error())
		} else {
			result.TLS = true
		}
	}
	a.store.AddActivity(r.Context(), user.ID, st.Name, "publish", body.Hostname)
	writeJSON(w, 200, result)
}

func (a *App) unpublish(w http.ResponseWriter, r *http.Request) {
	user, ok := a.require(w, r)
	if !ok {
		return
	}
	st, ok := a.openStack(w, r, user)
	if !ok || !a.ownerOr(w, user, st) {
		return
	}
	host := strings.ToLower(r.PathValue("hostname"))
	removed, err := a.store.DeleteDomain(r.Context(), st.ID, host)
	if err != nil {
		writeErr(w, 404, "domain not found")
		return
	}
	left, err := a.store.ListDomains(r.Context(), st.ID)
	if err != nil {
		writeErr(w, 500, err.Error())
		return
	}
	if err := domain.ApplyNginx(a.cfg.NginxAvailable, a.cfg.NginxEnabled, st.Name, left); err != nil {
		writeErr(w, 500, err.Error())
		return
	}
	settings, _ := a.store.GetSettings(r.Context())
	if removed.Cloudflare {
		_ = domain.DeleteRecord(settings.CloudflareToken, removed.Hostname, removed.RecordID)
	}
	a.store.AddActivity(r.Context(), user.ID, st.Name, "unpublish", host)
	writeJSON(w, 200, map[string]bool{"ok": true})
}

func (a *App) listSchedules(w http.ResponseWriter, r *http.Request) {
	user, ok := a.require(w, r)
	if !ok {
		return
	}
	st, ok := a.openStack(w, r, user)
	if !ok {
		return
	}
	rows, err := a.store.ListSchedules(r.Context(), st.ID)
	if err != nil {
		writeErr(w, 500, err.Error())
		return
	}
	writeJSON(w, 200, rows)
}

func (a *App) createSchedule(w http.ResponseWriter, r *http.Request) {
	user, ok := a.require(w, r)
	if !ok {
		return
	}
	st, ok := a.openStack(w, r, user)
	if !ok || !a.ownerOr(w, user, st) {
		return
	}
	var body struct {
		Action string `json:"action"`
		Cron   string `json:"cron"`
	}
	if err := readJSON(w, r, &body); err != nil || !schedule.Valid(strings.TrimSpace(body.Cron), body.Action) {
		writeErr(w, 400, "cron must be five fields and action start, stop or restart")
		return
	}
	id, err := a.store.CreateSchedule(r.Context(), st.ID, body.Action, strings.TrimSpace(body.Cron))
	if err != nil {
		writeErr(w, 500, err.Error())
		return
	}
	if a.Sched != nil {
		a.Sched.Reload()
	}
	a.store.AddActivity(r.Context(), user.ID, st.Name, "schedule", body.Action+" "+body.Cron)
	writeJSON(w, 201, map[string]any{"id": id})
}

func (a *App) deleteSchedule(w http.ResponseWriter, r *http.Request) {
	user, ok := a.require(w, r)
	if !ok {
		return
	}
	st, ok := a.openStack(w, r, user)
	if !ok || !a.ownerOr(w, user, st) {
		return
	}
	id, err := strconv.Atoi(r.PathValue("id"))
	if err != nil {
		writeErr(w, 400, "invalid id")
		return
	}
	if err := a.store.DeleteSchedule(r.Context(), st.ID, id); err != nil {
		writeErr(w, 500, err.Error())
		return
	}
	if a.Sched != nil {
		a.Sched.Reload()
	}
	writeJSON(w, 200, map[string]bool{"ok": true})
}

func (a *App) listSubusers(w http.ResponseWriter, r *http.Request) {
	user, ok := a.require(w, r)
	if !ok {
		return
	}
	st, ok := a.openStack(w, r, user)
	if !ok {
		return
	}
	rows, err := a.store.ListSubusers(r.Context(), st.ID)
	if err != nil {
		writeErr(w, 500, err.Error())
		return
	}
	writeJSON(w, 200, rows)
}

func (a *App) addSubuser(w http.ResponseWriter, r *http.Request) {
	user, ok := a.require(w, r)
	if !ok {
		return
	}
	st, ok := a.openStack(w, r, user)
	if !ok || !a.ownerOr(w, user, st) {
		return
	}
	var body struct {
		Username string `json:"username"`
	}
	if err := readJSON(w, r, &body); err != nil {
		writeErr(w, 400, "invalid json")
		return
	}
	other, _, err := a.store.UserByUsername(r.Context(), body.Username)
	if err != nil {
		writeErr(w, 404, "user not found")
		return
	}
	if other.ID == st.OwnerID {
		writeErr(w, 400, "owner already has access")
		return
	}
	if err := a.store.AddSubuser(r.Context(), st.ID, other.ID); err != nil {
		writeErr(w, 409, "user already added")
		return
	}
	a.store.AddActivity(r.Context(), user.ID, st.Name, "subuser", body.Username)
	writeJSON(w, 201, map[string]bool{"ok": true})
}

func (a *App) removeSubuser(w http.ResponseWriter, r *http.Request) {
	user, ok := a.require(w, r)
	if !ok {
		return
	}
	st, ok := a.openStack(w, r, user)
	if !ok || !a.ownerOr(w, user, st) {
		return
	}
	id, err := strconv.Atoi(r.PathValue("userId"))
	if err != nil {
		writeErr(w, 400, "invalid user")
		return
	}
	if err := a.store.RemoveSubuser(r.Context(), st.ID, id); err != nil {
		writeErr(w, 500, err.Error())
		return
	}
	writeJSON(w, 200, map[string]bool{"ok": true})
}

func (a *App) listTemplates(w http.ResponseWriter, r *http.Request) {
	if _, ok := a.require(w, r); !ok {
		return
	}
	writeJSON(w, 200, a.tpl.List())
}

func (a *App) saveTemplate(w http.ResponseWriter, r *http.Request) {
	user, ok := a.admin(w, r)
	if !ok {
		return
	}
	var body struct {
		YAML string `json:"yaml"`
	}
	if err := readJSON(w, r, &body); err != nil {
		writeErr(w, 400, "invalid json")
		return
	}
	t, err := template.Parse(body.YAML)
	if err != nil {
		writeErr(w, 400, err.Error())
		return
	}
	if t.ID != r.PathValue("id") {
		writeErr(w, 400, "yaml id must match the url")
		return
	}
	if err := a.store.SaveOverride(r.Context(), t.ID, body.YAML); err != nil {
		writeErr(w, 500, err.Error())
		return
	}
	if err := a.reloadTemplates(r.Context()); err != nil {
		writeErr(w, 500, err.Error())
		return
	}
	a.store.AddActivity(r.Context(), user.ID, "", "template", t.ID)
	writeJSON(w, 200, map[string]bool{"ok": true})
}

func (a *App) resetTemplate(w http.ResponseWriter, r *http.Request) {
	user, ok := a.admin(w, r)
	if !ok {
		return
	}
	id := r.PathValue("id")
	if err := a.store.DeleteOverride(r.Context(), id); err != nil {
		writeErr(w, 500, err.Error())
		return
	}
	if err := a.reloadTemplates(r.Context()); err != nil {
		writeErr(w, 500, err.Error())
		return
	}
	a.store.AddActivity(r.Context(), user.ID, "", "template-reset", id)
	writeJSON(w, 200, map[string]bool{"ok": true})
}

func (a *App) reloadTemplates(ctx context.Context) error {
	overrides, err := a.store.ListOverrides(ctx)
	if err != nil {
		return err
	}
	return a.tpl.Reload(overrides)
}

func (a *App) activity(w http.ResponseWriter, r *http.Request) {
	user, ok := a.require(w, r)
	if !ok {
		return
	}
	stacks, err := a.store.ListStacks(r.Context(), user)
	if err != nil {
		writeErr(w, 500, err.Error())
		return
	}
	names := make([]string, len(stacks))
	for i, st := range stacks {
		names[i] = st.Name
	}
	rows, err := a.store.ListActivity(r.Context(), user, names)
	if err != nil {
		writeErr(w, 500, err.Error())
		return
	}
	writeJSON(w, 200, rows)
}

func (a *App) getSettings(w http.ResponseWriter, r *http.Request) {
	if _, ok := a.admin(w, r); !ok {
		return
	}
	settings, err := a.store.GetSettings(r.Context())
	if err != nil {
		writeErr(w, 500, err.Error())
		return
	}
	writeJSON(w, 200, settings)
}

func (a *App) saveSettings(w http.ResponseWriter, r *http.Request) {
	user, ok := a.admin(w, r)
	if !ok {
		return
	}
	var body model.Settings
	if err := readJSON(w, r, &body); err != nil {
		writeErr(w, 400, "invalid json")
		return
	}
	if err := a.store.SaveSettings(r.Context(), body); err != nil {
		writeErr(w, 500, err.Error())
		return
	}
	a.store.AddActivity(r.Context(), user.ID, "", "settings", "")
	writeJSON(w, 200, map[string]bool{"ok": true})
}

func (a *App) listUsers(w http.ResponseWriter, r *http.Request) {
	if _, ok := a.admin(w, r); !ok {
		return
	}
	users, err := a.store.ListUsers(r.Context())
	if err != nil {
		writeErr(w, 500, err.Error())
		return
	}
	writeJSON(w, 200, users)
}

func (a *App) createUser(w http.ResponseWriter, r *http.Request) {
	user, ok := a.admin(w, r)
	if !ok {
		return
	}
	var body struct {
		Username string `json:"username"`
		Password string `json:"password"`
		Role     string `json:"role"`
	}
	if err := readJSON(w, r, &body); err != nil {
		writeErr(w, 400, "invalid json")
		return
	}
	if !nameRe.MatchString(body.Username) || len(body.Password) < 8 {
		writeErr(w, 400, "username must be a slug and password at least 8 characters")
		return
	}
	created, err := a.store.CreateUser(r.Context(), body.Username, body.Password, body.Role)
	if err != nil {
		writeErr(w, 409, "user exists")
		return
	}
	a.store.AddActivity(r.Context(), user.ID, "", "user", created.Username)
	writeJSON(w, 201, created)
}

func (a *App) listMail(w http.ResponseWriter, r *http.Request) {
	if _, ok := a.require(w, r); !ok {
		return
	}
	users, err := a.mail.List()
	if err != nil {
		writeJSON(w, 200, map[string]any{"users": []string{}, "error": err.Error()})
		return
	}
	writeJSON(w, 200, map[string]any{"users": users})
}

func (a *App) createMail(w http.ResponseWriter, r *http.Request) {
	user, ok := a.require(w, r)
	if !ok {
		return
	}
	var body struct {
		Email    string `json:"email"`
		Password string `json:"password"`
	}
	if err := readJSON(w, r, &body); err != nil {
		writeErr(w, 400, "invalid json")
		return
	}
	if err := a.mail.Add(body.Email, body.Password); err != nil {
		writeErr(w, 500, err.Error())
		return
	}
	a.store.AddActivity(r.Context(), user.ID, "", "mail", body.Email)
	writeJSON(w, 200, map[string]string{"message": "created"})
}

func (a *App) deleteMail(w http.ResponseWriter, r *http.Request) {
	user, ok := a.require(w, r)
	if !ok {
		return
	}
	var body struct {
		Email string `json:"email"`
	}
	if err := readJSON(w, r, &body); err != nil || body.Email == "" {
		writeErr(w, 400, "email is required")
		return
	}
	if err := a.mail.Delete(body.Email); err != nil {
		writeErr(w, 500, err.Error())
		return
	}
	a.store.AddActivity(r.Context(), user.ID, "", "mail-delete", body.Email)
	writeJSON(w, 200, map[string]string{"message": "deleted"})
}

func (a *App) mailPassword(w http.ResponseWriter, r *http.Request) {
	if _, ok := a.require(w, r); !ok {
		return
	}
	var body struct {
		Email    string `json:"email"`
		Password string `json:"password"`
	}
	if err := readJSON(w, r, &body); err != nil {
		writeErr(w, 400, "invalid json")
		return
	}
	if err := a.mail.Update(body.Email, body.Password); err != nil {
		writeErr(w, 500, err.Error())
		return
	}
	writeJSON(w, 200, map[string]string{"message": "updated"})
}

func newID() (string, error) {
	b := make([]byte, 16)
	if _, err := rand.Read(b); err != nil {
		return "", err
	}
	return hex.EncodeToString(b), nil
}

func readAllLimit(r io.Reader, n int64) ([]byte, error) {
	b, err := io.ReadAll(io.LimitReader(r, n+1))
	if err != nil {
		return nil, err
	}
	if int64(len(b)) > n {
		return nil, fmt.Errorf("file too large")
	}
	return b, nil
}
