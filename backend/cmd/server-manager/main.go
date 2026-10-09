package main

import (
	"context"
	"log"
	"log/slog"
	"net/http"
	"os"
	"os/signal"
	"syscall"
	"time"

	"server-manager/backend/internal/api"
	"server-manager/backend/internal/config"
	"server-manager/backend/internal/db"
	"server-manager/backend/internal/hub"
	"server-manager/backend/internal/runtime"
	"server-manager/backend/internal/schedule"
	"server-manager/backend/internal/store"
	"server-manager/backend/internal/template"
)

func main() {
	cfg := config.Load()
	conn, err := db.Open(cfg.DSN)
	if err != nil {
		log.Fatal(err)
	}
	defer conn.Close()
	if err := db.Migrate(conn); err != nil {
		log.Fatal(err)
	}
	st := store.New(conn)
	ctx := context.Background()
	seeded, err := st.SeedAdmin(ctx, cfg.AdminUser, cfg.AdminPassword)
	if err != nil {
		log.Fatal(err)
	}
	if seeded && cfg.AdminPassword == "admin" {
		slog.Warn("created admin user with the default password; set ADMIN_PASSWORD")
	}
	overrides, err := st.ListOverrides(ctx)
	if err != nil {
		log.Fatal(err)
	}
	catalog := template.NewCatalog(cfg.TemplatesDir)
	if err := catalog.Reload(overrides); err != nil {
		log.Fatal(err)
	}
	h := hub.New()
	sup := runtime.New(h)
	app := api.New(cfg, st, sup, h, catalog)
	if err := app.Boot(ctx); err != nil {
		log.Fatal(err)
	}
	sched := schedule.Start(st, app.Scheduled)
	app.Sched = sched
	go sup.Run()

	srv := &http.Server{
		Addr:              cfg.Addr,
		Handler:           app.Handler(),
		ReadHeaderTimeout: 10 * time.Second,
	}
	go func() {
		slog.Info("listening", "addr", cfg.Addr)
		if err := srv.ListenAndServe(); err != nil && err != http.ErrServerClosed {
			log.Fatal(err)
		}
	}()
	stop := make(chan os.Signal, 1)
	signal.Notify(stop, os.Interrupt, syscall.SIGTERM)
	<-stop
	sched.Stop()
	sup.Stop()
	shutdown, cancel := context.WithTimeout(context.Background(), 10*time.Second)
	defer cancel()
	_ = srv.Shutdown(shutdown)
}
