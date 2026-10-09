package store

import (
	"context"
	"database/sql"
	"errors"
	"fmt"
	"strings"
	"time"

	"server-manager/backend/internal/auth"
	"server-manager/backend/internal/model"
)

var ErrNotFound = errors.New("not found")

type Store struct {
	db *sql.DB
}

func New(db *sql.DB) *Store { return &Store{db: db} }

func (s *Store) SeedAdmin(ctx context.Context, username, password string) (bool, error) {
	var n int
	if err := s.db.QueryRowContext(ctx, `SELECT COUNT(*) FROM v2_users`).Scan(&n); err != nil {
		return false, err
	}
	if n > 0 {
		return false, nil
	}
	hash, err := auth.HashPassword(password)
	if err != nil {
		return false, err
	}
	_, err = s.db.ExecContext(ctx, `INSERT INTO v2_users (username, password_hash, role) VALUES (?, ?, 'admin')`, username, hash)
	return err == nil, err
}

func (s *Store) CreateUser(ctx context.Context, username, password, role string) (model.User, error) {
	if role != "admin" && role != "user" {
		role = "user"
	}
	hash, err := auth.HashPassword(password)
	if err != nil {
		return model.User{}, err
	}
	res, err := s.db.ExecContext(ctx, `INSERT INTO v2_users (username, password_hash, role) VALUES (?, ?, ?)`, username, hash, role)
	if err != nil {
		return model.User{}, err
	}
	id, _ := res.LastInsertId()
	return model.User{ID: int(id), Username: username, Role: role}, nil
}

func (s *Store) UserByUsername(ctx context.Context, username string) (model.User, string, error) {
	var u model.User
	var hash string
	err := s.db.QueryRowContext(ctx, `SELECT id, username, role, password_hash FROM v2_users WHERE username = ?`, username).
		Scan(&u.ID, &u.Username, &u.Role, &hash)
	if errors.Is(err, sql.ErrNoRows) {
		return model.User{}, "", ErrNotFound
	}
	return u, hash, err
}

func (s *Store) UserByID(ctx context.Context, id int) (model.User, error) {
	var u model.User
	err := s.db.QueryRowContext(ctx, `SELECT id, username, role FROM v2_users WHERE id = ?`, id).Scan(&u.ID, &u.Username, &u.Role)
	if errors.Is(err, sql.ErrNoRows) {
		return model.User{}, ErrNotFound
	}
	return u, err
}

func (s *Store) ListUsers(ctx context.Context) ([]model.User, error) {
	rows, err := s.db.QueryContext(ctx, `SELECT id, username, role FROM v2_users ORDER BY username`)
	if err != nil {
		return nil, err
	}
	defer rows.Close()
	var out []model.User
	for rows.Next() {
		var u model.User
		if err := rows.Scan(&u.ID, &u.Username, &u.Role); err != nil {
			return nil, err
		}
		out = append(out, u)
	}
	return out, rows.Err()
}

func (s *Store) CreateSession(ctx context.Context, userID int, tokenHash string, expires time.Time) error {
	_, err := s.db.ExecContext(ctx, `INSERT INTO v2_sessions (token_hash, user_id, expires_at) VALUES (?, ?, ?)`, tokenHash, userID, expires)
	return err
}

func (s *Store) DeleteSession(ctx context.Context, tokenHash string) error {
	_, err := s.db.ExecContext(ctx, `DELETE FROM v2_sessions WHERE token_hash = ?`, tokenHash)
	return err
}

func (s *Store) UserByToken(ctx context.Context, raw string) (model.User, error) {
	if raw == "" {
		return model.User{}, ErrNotFound
	}
	hash := auth.HashToken(raw)
	var u model.User
	var expires time.Time
	err := s.db.QueryRowContext(ctx, `
		SELECT u.id, u.username, u.role, s.expires_at
		FROM v2_sessions s JOIN v2_users u ON u.id = s.user_id
		WHERE s.token_hash = ?`, hash).Scan(&u.ID, &u.Username, &u.Role, &expires)
	if errors.Is(err, sql.ErrNoRows) {
		return model.User{}, ErrNotFound
	}
	if err != nil {
		return model.User{}, err
	}
	if time.Now().After(expires) {
		_, _ = s.db.ExecContext(ctx, `DELETE FROM v2_sessions WHERE token_hash = ?`, hash)
		return model.User{}, ErrNotFound
	}
	return u, nil
}

type NewStack struct {
	ID          string
	Name        string
	OwnerID     int
	Source      string
	TemplateID  string
	Dir         string
	Description string
	Services    []model.NewService
}

func (s *Store) NextHostPort(ctx context.Context) (int, error) {
	var p sql.NullInt64
	err := s.db.QueryRowContext(ctx, `SELECT COALESCE(MAX(host_port), 17999) FROM v2_services`).Scan(&p)
	if err != nil {
		return 0, err
	}
	return int(p.Int64) + 1, nil
}

func (s *Store) CreateStack(ctx context.Context, in NewStack) error {
	tx, err := s.db.BeginTx(ctx, nil)
	if err != nil {
		return err
	}
	defer tx.Rollback()
	_, err = tx.ExecContext(ctx, `
		INSERT INTO v2_stacks (id, name, owner_id, source, template_id, dir, desired_state, description)
		VALUES (?, ?, ?, ?, NULLIF(?, ''), ?, 'stopped', ?)`,
		in.ID, in.Name, in.OwnerID, in.Source, in.TemplateID, in.Dir, in.Description)
	if err != nil {
		return err
	}
	for _, svc := range in.Services {
		_, err = tx.ExecContext(ctx, `
			INSERT INTO v2_services (stack_id, name, http, internal_port, host_port, logs_enabled, shell)
			VALUES (?, ?, ?, NULLIF(?, 0), NULLIF(?, 0), ?, ?)`,
			in.ID, svc.Name, boolInt(svc.HTTP), svc.InternalPort, svc.HostPort, boolInt(svc.Logs), boolInt(svc.Shell))
		if err != nil {
			return err
		}
	}
	return tx.Commit()
}

// SyncStackServices replaces a stack's stored service list with the services
// currently defined in its compose file.
func (s *Store) SyncStackServices(ctx context.Context, stackID string, services []model.NewService) error {
	tx, err := s.db.BeginTx(ctx, nil)
	if err != nil {
		return err
	}
	defer tx.Rollback()
	if _, err := tx.ExecContext(ctx, `DELETE FROM v2_services WHERE stack_id = ?`, stackID); err != nil {
		return err
	}
	for _, svc := range services {
		_, err = tx.ExecContext(ctx, `
			INSERT INTO v2_services (stack_id, name, http, internal_port, host_port, logs_enabled, shell)
			VALUES (?, ?, ?, NULLIF(?, 0), NULLIF(?, 0), ?, ?)`,
			stackID, svc.Name, boolInt(svc.HTTP), svc.InternalPort, svc.HostPort, boolInt(svc.Logs), boolInt(svc.Shell))
		if err != nil {
			return err
		}
	}
	return tx.Commit()
}

func (s *Store) ListStacks(ctx context.Context, user model.User) ([]model.Stack, error) {
	q := `
		SELECT s.id, s.name, s.owner_id, u.username, s.source, IFNULL(s.template_id, ''), s.dir,
		       s.desired_state, s.description, s.created_at
		FROM v2_stacks s
		JOIN v2_users u ON u.id = s.owner_id`
	args := []any{}
	if user.Role != "admin" {
		q += ` WHERE s.owner_id = ? OR EXISTS (SELECT 1 FROM v2_subusers su WHERE su.stack_id = s.id AND su.user_id = ?)`
		args = append(args, user.ID, user.ID)
	}
	q += ` ORDER BY s.name`
	rows, err := s.db.QueryContext(ctx, q, args...)
	if err != nil {
		return nil, err
	}
	defer rows.Close()
	var stacks []model.Stack
	index := map[string]int{}
	for rows.Next() {
		var st model.Stack
		if err := rows.Scan(&st.ID, &st.Name, &st.OwnerID, &st.Owner, &st.Source, &st.TemplateID, &st.Dir, &st.Desired, &st.Description, &st.CreatedAt); err != nil {
			return nil, err
		}
		index[st.ID] = len(stacks)
		stacks = append(stacks, st)
	}
	if err := rows.Err(); err != nil {
		return nil, err
	}
	if len(stacks) == 0 {
		return []model.Stack{}, nil
	}
	if err := s.attachServices(ctx, stacks); err != nil {
		return nil, err
	}
	return stacks, nil
}

func (s *Store) StackByName(ctx context.Context, name string) (model.Stack, error) {
	var st model.Stack
	err := s.db.QueryRowContext(ctx, `
		SELECT s.id, s.name, s.owner_id, u.username, s.source, IFNULL(s.template_id, ''), s.dir,
		       s.desired_state, s.description, s.created_at
		FROM v2_stacks s JOIN v2_users u ON u.id = s.owner_id
		WHERE s.name = ?`, name).Scan(&st.ID, &st.Name, &st.OwnerID, &st.Owner, &st.Source, &st.TemplateID, &st.Dir, &st.Desired, &st.Description, &st.CreatedAt)
	if errors.Is(err, sql.ErrNoRows) {
		return model.Stack{}, ErrNotFound
	}
	if err != nil {
		return model.Stack{}, err
	}
	list := []model.Stack{st}
	if err := s.attachServices(ctx, list); err != nil {
		return model.Stack{}, err
	}
	return list[0], nil
}

func (s *Store) attachServices(ctx context.Context, stacks []model.Stack) error {
	ids := make([]any, len(stacks))
	marks := make([]string, len(stacks))
	index := map[string]int{}
	for i, st := range stacks {
		ids[i] = st.ID
		marks[i] = "?"
		index[st.ID] = i
		stacks[i].Services = []model.Service{}
	}
	q := fmt.Sprintf(`SELECT stack_id, name, http, IFNULL(internal_port, 0), IFNULL(host_port, 0), logs_enabled, shell
		FROM v2_services WHERE stack_id IN (%s) ORDER BY id`, strings.Join(marks, ","))
	rows, err := s.db.QueryContext(ctx, q, ids...)
	if err != nil {
		return err
	}
	defer rows.Close()
	for rows.Next() {
		var stackID, name string
		var httpOn, logs, shell int
		var internal, host int
		if err := rows.Scan(&stackID, &name, &httpOn, &internal, &host, &logs, &shell); err != nil {
			return err
		}
		i, ok := index[stackID]
		if !ok {
			continue
		}
		stacks[i].Services = append(stacks[i].Services, model.Service{
			Name: name, HTTP: httpOn == 1, InternalPort: internal, HostPort: host,
			Logs: logs == 1, Shell: shell == 1, Status: "missing",
		})
	}
	return rows.Err()
}

func (s *Store) DeleteStack(ctx context.Context, id string) error {
	tx, err := s.db.BeginTx(ctx, nil)
	if err != nil {
		return err
	}
	defer tx.Rollback()
	for _, q := range []string{
		`DELETE FROM v2_services WHERE stack_id = ?`,
		`DELETE FROM v2_domains WHERE stack_id = ?`,
		`DELETE FROM v2_subusers WHERE stack_id = ?`,
		`DELETE FROM v2_schedules WHERE stack_id = ?`,
		`DELETE FROM v2_stacks WHERE id = ?`,
	} {
		if _, err := tx.ExecContext(ctx, q, id); err != nil {
			return err
		}
	}
	return tx.Commit()
}

func (s *Store) SetDesired(ctx context.Context, id, state string) error {
	_, err := s.db.ExecContext(ctx, `UPDATE v2_stacks SET desired_state = ? WHERE id = ?`, state, id)
	return err
}

func (s *Store) SetDescription(ctx context.Context, id, description string) error {
	_, err := s.db.ExecContext(ctx, `UPDATE v2_stacks SET description = ? WHERE id = ?`, description, id)
	return err
}

func (s *Store) CanAccess(ctx context.Context, user model.User, stack model.Stack) (bool, error) {
	if user.Role == "admin" || stack.OwnerID == user.ID {
		return true, nil
	}
	var n int
	err := s.db.QueryRowContext(ctx, `SELECT COUNT(*) FROM v2_subusers WHERE stack_id = ? AND user_id = ?`, stack.ID, user.ID).Scan(&n)
	return n > 0, err
}

func (s *Store) ListDomains(ctx context.Context, stackID string) ([]model.Domain, error) {
	rows, err := s.db.QueryContext(ctx, `
		SELECT id, stack_id, service_name, hostname, upstream_port, tls, cloudflare, cf_record_id
		FROM v2_domains WHERE stack_id = ? ORDER BY hostname`, stackID)
	if err != nil {
		return nil, err
	}
	defer rows.Close()
	var out []model.Domain
	for rows.Next() {
		var d model.Domain
		var tls, cf int
		if err := rows.Scan(&d.ID, &d.StackID, &d.ServiceName, &d.Hostname, &d.UpstreamPort, &tls, &cf, &d.RecordID); err != nil {
			return nil, err
		}
		d.TLS, d.Cloudflare = tls == 1, cf == 1
		out = append(out, d)
	}
	if out == nil {
		out = []model.Domain{}
	}
	return out, rows.Err()
}

func (s *Store) SaveDomain(ctx context.Context, d model.Domain) error {
	_, err := s.db.ExecContext(ctx, `
		INSERT INTO v2_domains (stack_id, service_name, hostname, upstream_port, tls, cloudflare, cf_record_id)
		VALUES (?, ?, ?, ?, ?, ?, ?)
		ON DUPLICATE KEY UPDATE service_name = VALUES(service_name), upstream_port = VALUES(upstream_port),
		  tls = VALUES(tls), cloudflare = VALUES(cloudflare), cf_record_id = VALUES(cf_record_id)`,
		d.StackID, d.ServiceName, d.Hostname, d.UpstreamPort, boolInt(d.TLS), boolInt(d.Cloudflare), d.RecordID)
	return err
}

func (s *Store) DeleteDomain(ctx context.Context, stackID, hostname string) (model.Domain, error) {
	var d model.Domain
	var tls, cf int
	err := s.db.QueryRowContext(ctx, `
		SELECT id, stack_id, service_name, hostname, upstream_port, tls, cloudflare, cf_record_id
		FROM v2_domains WHERE stack_id = ? AND hostname = ?`, stackID, hostname).
		Scan(&d.ID, &d.StackID, &d.ServiceName, &d.Hostname, &d.UpstreamPort, &tls, &cf, &d.RecordID)
	if errors.Is(err, sql.ErrNoRows) {
		return model.Domain{}, ErrNotFound
	}
	if err != nil {
		return model.Domain{}, err
	}
	d.TLS, d.Cloudflare = tls == 1, cf == 1
	_, err = s.db.ExecContext(ctx, `DELETE FROM v2_domains WHERE id = ?`, d.ID)
	return d, err
}

func (s *Store) ListSubusers(ctx context.Context, stackID string) ([]model.Subuser, error) {
	rows, err := s.db.QueryContext(ctx, `
		SELECT su.id, su.user_id, u.username
		FROM v2_subusers su JOIN v2_users u ON u.id = su.user_id
		WHERE su.stack_id = ? ORDER BY u.username`, stackID)
	if err != nil {
		return nil, err
	}
	defer rows.Close()
	var out []model.Subuser
	for rows.Next() {
		var su model.Subuser
		if err := rows.Scan(&su.ID, &su.UserID, &su.Username); err != nil {
			return nil, err
		}
		out = append(out, su)
	}
	if out == nil {
		out = []model.Subuser{}
	}
	return out, rows.Err()
}

func (s *Store) AddSubuser(ctx context.Context, stackID string, userID int) error {
	_, err := s.db.ExecContext(ctx, `INSERT INTO v2_subusers (stack_id, user_id) VALUES (?, ?)`, stackID, userID)
	return err
}

func (s *Store) RemoveSubuser(ctx context.Context, stackID string, userID int) error {
	_, err := s.db.ExecContext(ctx, `DELETE FROM v2_subusers WHERE stack_id = ? AND user_id = ?`, stackID, userID)
	return err
}

func (s *Store) AddActivity(ctx context.Context, userID int, stackName, action, detail string) {
	var uid any
	if userID > 0 {
		uid = userID
	}
	_, _ = s.db.ExecContext(ctx, `INSERT INTO v2_activity (user_id, stack_name, action, detail) VALUES (?, ?, ?, ?)`, uid, stackName, action, detail)
}

func (s *Store) ListActivity(ctx context.Context, user model.User, stackNames []string) ([]model.Activity, error) {
	q := `SELECT a.id, IFNULL(a.user_id, 0), IFNULL(u.username, ''), a.stack_name, a.action, IFNULL(a.detail, ''), a.created_at
		FROM v2_activity a LEFT JOIN v2_users u ON u.id = a.user_id`
	args := []any{}
	if user.Role != "admin" {
		marks := []string{"?"}
		args = append(args, user.ID)
		for _, name := range stackNames {
			marks = append(marks, "?")
			args = append(args, name)
		}
		q += ` WHERE a.user_id = ? OR a.stack_name IN (` + strings.Join(marks[1:], ",") + `)`
		if len(stackNames) == 0 {
			q = `SELECT a.id, IFNULL(a.user_id, 0), IFNULL(u.username, ''), a.stack_name, a.action, IFNULL(a.detail, ''), a.created_at
				FROM v2_activity a LEFT JOIN v2_users u ON u.id = a.user_id WHERE a.user_id = ?`
			args = []any{user.ID}
		}
	}
	q += ` ORDER BY a.id DESC LIMIT 200`
	rows, err := s.db.QueryContext(ctx, q, args...)
	if err != nil {
		return nil, err
	}
	defer rows.Close()
	var out []model.Activity
	for rows.Next() {
		var a model.Activity
		if err := rows.Scan(&a.ID, &a.UserID, &a.Username, &a.StackName, &a.Action, &a.Detail, &a.CreatedAt); err != nil {
			return nil, err
		}
		out = append(out, a)
	}
	if out == nil {
		out = []model.Activity{}
	}
	return out, rows.Err()
}

func (s *Store) ListSchedules(ctx context.Context, stackID string) ([]model.Schedule, error) {
	rows, err := s.db.QueryContext(ctx, `
		SELECT sc.id, sc.stack_id, st.name, sc.action, sc.cron, sc.enabled
		FROM v2_schedules sc JOIN v2_stacks st ON st.id = sc.stack_id
		WHERE sc.stack_id = ? ORDER BY sc.id`, stackID)
	if err != nil {
		return nil, err
	}
	defer rows.Close()
	return scanSchedules(rows)
}

func (s *Store) ListAllSchedules(ctx context.Context) ([]model.Schedule, error) {
	rows, err := s.db.QueryContext(ctx, `
		SELECT sc.id, sc.stack_id, st.name, sc.action, sc.cron, sc.enabled
		FROM v2_schedules sc JOIN v2_stacks st ON st.id = sc.stack_id
		WHERE sc.enabled = 1`)
	if err != nil {
		return nil, err
	}
	defer rows.Close()
	return scanSchedules(rows)
}

func scanSchedules(rows *sql.Rows) ([]model.Schedule, error) {
	var out []model.Schedule
	for rows.Next() {
		var sc model.Schedule
		var enabled int
		if err := rows.Scan(&sc.ID, &sc.StackID, &sc.Stack, &sc.Action, &sc.Cron, &enabled); err != nil {
			return nil, err
		}
		sc.Enabled = enabled == 1
		out = append(out, sc)
	}
	if out == nil {
		out = []model.Schedule{}
	}
	return out, rows.Err()
}

func (s *Store) CreateSchedule(ctx context.Context, stackID, action, cron string) (int, error) {
	res, err := s.db.ExecContext(ctx, `INSERT INTO v2_schedules (stack_id, action, cron, enabled) VALUES (?, ?, ?, 1)`, stackID, action, cron)
	if err != nil {
		return 0, err
	}
	id, _ := res.LastInsertId()
	return int(id), nil
}

func (s *Store) DeleteSchedule(ctx context.Context, stackID string, id int) error {
	_, err := s.db.ExecContext(ctx, `DELETE FROM v2_schedules WHERE id = ? AND stack_id = ?`, id, stackID)
	return err
}

func (s *Store) GetSettings(ctx context.Context) (model.Settings, error) {
	var st model.Settings
	err := s.db.QueryRowContext(ctx, `SELECT discord_webhook, cloudflare_token, public_ip, acme_email FROM v2_settings WHERE id = 1`).
		Scan(&st.DiscordWebhook, &st.CloudflareToken, &st.PublicIP, &st.AcmeEmail)
	if errors.Is(err, sql.ErrNoRows) {
		return model.Settings{}, nil
	}
	return st, err
}

func (s *Store) SaveSettings(ctx context.Context, st model.Settings) error {
	_, err := s.db.ExecContext(ctx, `
		INSERT INTO v2_settings (id, discord_webhook, cloudflare_token, public_ip, acme_email)
		VALUES (1, ?, ?, ?, ?)
		ON DUPLICATE KEY UPDATE discord_webhook = VALUES(discord_webhook), cloudflare_token = VALUES(cloudflare_token),
		  public_ip = VALUES(public_ip), acme_email = VALUES(acme_email)`,
		st.DiscordWebhook, st.CloudflareToken, st.PublicIP, st.AcmeEmail)
	return err
}

func (s *Store) ListOverrides(ctx context.Context) (map[string]string, error) {
	rows, err := s.db.QueryContext(ctx, `SELECT id, yaml FROM v2_template_overrides`)
	if err != nil {
		return nil, err
	}
	defer rows.Close()
	out := map[string]string{}
	for rows.Next() {
		var id, yaml string
		if err := rows.Scan(&id, &yaml); err != nil {
			return nil, err
		}
		out[id] = yaml
	}
	return out, rows.Err()
}

func (s *Store) SaveOverride(ctx context.Context, id, yaml string) error {
	_, err := s.db.ExecContext(ctx, `
		INSERT INTO v2_template_overrides (id, yaml) VALUES (?, ?)
		ON DUPLICATE KEY UPDATE yaml = VALUES(yaml)`, id, yaml)
	return err
}

func (s *Store) DeleteOverride(ctx context.Context, id string) error {
	_, err := s.db.ExecContext(ctx, `DELETE FROM v2_template_overrides WHERE id = ?`, id)
	return err
}

func boolInt(v bool) int {
	if v {
		return 1
	}
	return 0
}
