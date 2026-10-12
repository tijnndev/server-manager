package schedule

import (
	"context"
	"log/slog"
	"sync"

	"github.com/robfig/cron/v3"

	"server-manager/backend/internal/store"
)

type Action func(stack, action string)

type Runner struct {
	store *store.Store
	act   Action
	cron  *cron.Cron
	mu    sync.Mutex
	ids   []cron.EntryID
}

func Start(st *store.Store, act Action) *Runner {
	r := &Runner{
		store: st,
		act:   act,
		cron:  cron.New(),
	}
	r.Reload()
	r.cron.Start()
	return r
}

func (r *Runner) Stop() {
	ctx := r.cron.Stop()
	<-ctx.Done()
}

func (r *Runner) Reload() {
	rows, err := r.store.ListAllSchedules(context.Background())
	if err != nil {
		slog.Error("schedules", "err", err)
		return
	}
	r.mu.Lock()
	defer r.mu.Unlock()
	for _, id := range r.ids {
		r.cron.Remove(id)
	}
	r.ids = nil
	for _, row := range rows {
		row := row
		id, err := r.cron.AddFunc(row.Cron, func() { r.act(row.Stack, row.Action) })
		if err != nil {
			slog.Error("schedule", "cron", row.Cron, "err", err)
			continue
		}
		r.ids = append(r.ids, id)
	}
}

func Valid(spec, action string) bool {
	if action != "start" && action != "stop" && action != "restart" {
		return false
	}
	_, err := cron.ParseStandard(spec)
	return err == nil
}
