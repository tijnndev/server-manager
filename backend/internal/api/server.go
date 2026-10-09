package api

import (
	"context"
	"encoding/json"
	"net/http"
	"strings"
	"sync"
	"time"

	"github.com/coder/websocket"

	"server-manager/backend/internal/auth"
	"server-manager/backend/internal/config"
	"server-manager/backend/internal/hub"
	"server-manager/backend/internal/mail"
	"server-manager/backend/internal/model"
	"server-manager/backend/internal/notify"
	"server-manager/backend/internal/runtime"
	"server-manager/backend/internal/schedule"
	"server-manager/backend/internal/store"
	"server-manager/backend/internal/template"
)

type App struct {
	cfg    config.Config
	store  *store.Store
	sup    *runtime.Supervisor
	hub    *hub.Hub
	tpl    *template.Catalog
	Sched  *schedule.Runner
	mail   mail.Client
	alloc  sync.Mutex
	pushMu sync.Mutex
	push   *time.Timer
}

func New(cfg config.Config, st *store.Store, sup *runtime.Supervisor, h *hub.Hub, tpl *template.Catalog) *App {
	a := &App{
		cfg:   cfg,
		store: st,
		sup:   sup,
		hub:   h,
		tpl:   tpl,
		mail:  mail.Client{Container: cfg.MailContainer},
	}
	sup.OnChange = a.PushState
	sup.OnCrash = a.Crash
	return a
}

func (a *App) Boot(ctx context.Context) error {
	admin := model.User{Role: "admin"}
	stacks, err := a.store.ListStacks(ctx, admin)
	if err != nil {
		return err
	}
	for _, st := range stacks {
		names := make([]string, len(st.Services))
		for i, svc := range st.Services {
			names[i] = svc.Name
		}
		a.sup.SetServices(st.Name, names)
		a.sup.SetDesired(st.Name, st.Desired)
	}
	return nil
}

func (a *App) Handler() http.Handler {
	mux := http.NewServeMux()
	mux.HandleFunc("POST /api/auth/login", a.login)
	mux.HandleFunc("POST /api/auth/logout", a.logout)
	mux.HandleFunc("GET /api/auth/me", a.me)
	mux.HandleFunc("GET /api/stacks", a.listStacks)
	mux.HandleFunc("POST /api/stacks", a.createStack)
	mux.HandleFunc("GET /api/stacks/{name}", a.getStack)
	mux.HandleFunc("PATCH /api/stacks/{name}", a.patchStack)
	mux.HandleFunc("DELETE /api/stacks/{name}", a.deleteStack)
	mux.HandleFunc("POST /api/stacks/{name}/power/{action}", a.power)
	mux.HandleFunc("POST /api/stacks/{name}/exec", a.exec)
	mux.HandleFunc("GET /api/stacks/{name}/shell", a.shell)
	mux.HandleFunc("GET /api/stacks/{name}/files", a.listFiles)
	mux.HandleFunc("GET /api/stacks/{name}/files/content", a.readFile)
	mux.HandleFunc("PUT /api/stacks/{name}/files/content", a.writeFile)
	mux.HandleFunc("DELETE /api/stacks/{name}/files", a.deleteFile)
	mux.HandleFunc("POST /api/stacks/{name}/files/mkdir", a.mkdir)
	mux.HandleFunc("POST /api/stacks/{name}/files/upload", a.upload)
	mux.HandleFunc("GET /api/stacks/{name}/git", a.gitStatus)
	mux.HandleFunc("POST /api/stacks/{name}/git/pull", a.gitPull)
	mux.HandleFunc("POST /api/stacks/{name}/git/clone", a.gitClone)
	mux.HandleFunc("GET /api/stacks/{name}/domains", a.listDomains)
	mux.HandleFunc("POST /api/stacks/{name}/publish", a.publish)
	mux.HandleFunc("DELETE /api/stacks/{name}/domains/{hostname}", a.unpublish)
	mux.HandleFunc("GET /api/stacks/{name}/schedules", a.listSchedules)
	mux.HandleFunc("POST /api/stacks/{name}/schedules", a.createSchedule)
	mux.HandleFunc("DELETE /api/stacks/{name}/schedules/{id}", a.deleteSchedule)
	mux.HandleFunc("GET /api/stacks/{name}/subusers", a.listSubusers)
	mux.HandleFunc("POST /api/stacks/{name}/subusers", a.addSubuser)
	mux.HandleFunc("DELETE /api/stacks/{name}/subusers/{userId}", a.removeSubuser)
	mux.HandleFunc("GET /api/templates", a.listTemplates)
	mux.HandleFunc("PUT /api/templates/{id}", a.saveTemplate)
	mux.HandleFunc("DELETE /api/templates/{id}", a.resetTemplate)
	mux.HandleFunc("GET /api/activity", a.activity)
	mux.HandleFunc("GET /api/settings", a.getSettings)
	mux.HandleFunc("PUT /api/settings", a.saveSettings)
	mux.HandleFunc("GET /api/users", a.listUsers)
	mux.HandleFunc("POST /api/users", a.createUser)
	mux.HandleFunc("GET /api/mail", a.listMail)
	mux.HandleFunc("POST /api/mail", a.createMail)
	mux.HandleFunc("POST /api/mail/delete", a.deleteMail)
	mux.HandleFunc("POST /api/mail/password", a.mailPassword)
	mux.HandleFunc("GET /api/ws", a.socket)
	mux.HandleFunc("/", a.static)
	return a.guard(mux)
}

func (a *App) guard(next http.Handler) http.Handler {
	return http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		switch r.Method {
		case http.MethodPost, http.MethodPut, http.MethodPatch, http.MethodDelete:
			if strings.HasPrefix(r.URL.Path, "/api/") && r.Header.Get("X-SM-Request") != "1" {
				writeErr(w, http.StatusForbidden, "missing request header")
				return
			}
		}
		next.ServeHTTP(w, r)
	})
}

func (a *App) require(w http.ResponseWriter, r *http.Request) (model.User, bool) {
	user, err := a.store.UserByToken(r.Context(), auth.ReadCookie(r))
	if err != nil {
		writeErr(w, http.StatusUnauthorized, "login required")
		return model.User{}, false
	}
	return user, true
}

func (a *App) admin(w http.ResponseWriter, r *http.Request) (model.User, bool) {
	user, ok := a.require(w, r)
	if !ok {
		return model.User{}, false
	}
	if user.Role != "admin" {
		writeErr(w, http.StatusForbidden, "admin required")
		return model.User{}, false
	}
	return user, true
}

func (a *App) openStack(w http.ResponseWriter, r *http.Request, user model.User) (model.Stack, bool) {
	st, err := a.store.StackByName(r.Context(), r.PathValue("name"))
	if err != nil {
		writeErr(w, http.StatusNotFound, "stack not found")
		return model.Stack{}, false
	}
	ok, err := a.store.CanAccess(r.Context(), user, st)
	if err != nil || !ok {
		writeErr(w, http.StatusForbidden, "forbidden")
		return model.Stack{}, false
	}
	return st, true
}

func (a *App) owns(user model.User, st model.Stack) bool {
	return user.Role == "admin" || st.OwnerID == user.ID
}

func (a *App) PushState() {
	a.pushMu.Lock()
	defer a.pushMu.Unlock()
	if a.push != nil {
		return
	}
	a.push = time.AfterFunc(150*time.Millisecond, func() {
		a.pushMu.Lock()
		a.push = nil
		a.pushMu.Unlock()
		a.broadcast()
	})
}

func (a *App) broadcast() {
	ctx := context.Background()
	a.hub.ForEach(func(c *hub.Client) {
		a.sendState(ctx, c)
	})
}

func (a *App) sendState(ctx context.Context, c *hub.Client) {
	stacks, err := a.store.ListStacks(ctx, c.User)
	if err != nil {
		return
	}
	a.hub.Send(c, map[string]any{"type": "state", "stacks": a.sup.Overlay(stacks)})
}

func (a *App) Crash(project, service string) {
	a.store.AddActivity(context.Background(), 0, project, "crash", service+" exited while it should be running")
	settings, _ := a.store.GetSettings(context.Background())
	go notify.Discord(settings.DiscordWebhook, "crash "+project+"/"+service)
	a.PushState()
}

func (a *App) Scheduled(name, action string) {
	ctx := context.Background()
	st, err := a.store.StackByName(ctx, name)
	if err != nil {
		return
	}
	user := model.User{Username: "schedule", Role: "admin"}
	if err := a.perform(ctx, user, st, action); err != nil {
		a.store.AddActivity(ctx, 0, name, "schedule", err.Error())
	}
}

func (a *App) views(ctx context.Context, user model.User) ([]model.Stack, error) {
	stacks, err := a.store.ListStacks(ctx, user)
	if err != nil {
		return nil, err
	}
	return a.sup.Overlay(stacks), nil
}

func (a *App) socket(w http.ResponseWriter, r *http.Request) {
	user, err := a.store.UserByToken(r.Context(), auth.ReadCookie(r))
	if err != nil {
		writeErr(w, http.StatusUnauthorized, "login required")
		return
	}
	conn, err := websocket.Accept(w, r, &websocket.AcceptOptions{InsecureSkipVerify: true})
	if err != nil {
		return
	}
	ctx, cancel := context.WithCancel(r.Context())
	defer cancel()
	defer conn.Close(websocket.StatusNormalClosure, "")
	client := a.hub.Add(user)
	defer a.hub.Remove(client)
	stops := map[string]func(){}
	defer func() {
		for _, stop := range stops {
			stop()
		}
	}()
	go func() {
		for {
			select {
			case <-ctx.Done():
				return
			case msg := <-client.Recv():
				if err := conn.Write(ctx, websocket.MessageText, msg); err != nil {
					cancel()
					return
				}
			}
		}
	}()
	a.sendState(ctx, client)
	for {
		_, data, err := conn.Read(ctx)
		if err != nil {
			return
		}
		var cmd struct {
			Type  string `json:"type"`
			Stack string `json:"stack"`
		}
		if json.Unmarshal(data, &cmd) != nil || cmd.Stack == "" {
			continue
		}
		switch cmd.Type {
		case "subscribe":
			if _, ok := stops[cmd.Stack]; ok {
				continue
			}
			st, err := a.store.StackByName(ctx, cmd.Stack)
			if err != nil {
				continue
			}
			ok, _ := a.store.CanAccess(ctx, user, st)
			if !ok {
				continue
			}
			a.hub.Subscribe(client, cmd.Stack)
			stops[cmd.Stack] = a.sup.Watch(cmd.Stack)
		case "unsubscribe":
			a.hub.Unsubscribe(client, cmd.Stack)
			if stop, ok := stops[cmd.Stack]; ok {
				stop()
				delete(stops, cmd.Stack)
			}
		}
	}
}

func writeJSON(w http.ResponseWriter, code int, v any) {
	w.Header().Set("Content-Type", "application/json")
	w.WriteHeader(code)
	_ = json.NewEncoder(w).Encode(v)
}

func writeErr(w http.ResponseWriter, code int, msg string) {
	writeJSON(w, code, map[string]string{"error": msg})
}

func readJSON(w http.ResponseWriter, r *http.Request, dest any) error {
	return json.NewDecoder(http.MaxBytesReader(w, r.Body, 8<<20)).Decode(dest)
}
