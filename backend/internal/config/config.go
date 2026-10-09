package config

import (
	"net/url"
	"os"
	"path/filepath"
	"strings"

	"github.com/go-sql-driver/mysql"
)

type Config struct {
	Addr           string
	DSN            string
	DataDir        string
	TemplatesDir   string
	FrontendDir    string
	AdminUser      string
	AdminPassword  string
	CookieSecure   bool
	NginxAvailable string
	NginxEnabled   string
	MailContainer  string
}

func Load() Config {
	loadDotEnv()
	cfg := Config{
		Addr:           env("PANEL_ADDR", ":7101"),
		DataDir:        env("DATA_DIR", "data/stacks"),
		TemplatesDir:   env("TEMPLATES_DIR", "templates"),
		FrontendDir:    env("FRONTEND_DIR", "frontend/dist"),
		AdminUser:      env("ADMIN_USER", "admin"),
		AdminPassword:  env("ADMIN_PASSWORD", "admin"),
		CookieSecure:   env("COOKIE_SECURE", "") == "1",
		NginxAvailable: env("NGINX_SITES_AVAILABLE", "/etc/nginx/sites-available"),
		NginxEnabled:   env("NGINX_SITES_ENABLED", "/etc/nginx/sites-enabled"),
		MailContainer:  env("MAIL_CONTAINER", "mailserver"),
	}
	switch {
	case os.Getenv("DB_HOST") != "":
		cfg.DSN = dsnFromParts()
	case os.Getenv("DATABASE_DSN") != "":
		cfg.DSN = os.Getenv("DATABASE_DSN")
	default:
		cfg.DSN = mysqlDSN(os.Getenv("DATABASE_URI"))
	}
	root := findRoot()
	cfg.DataDir = anchor(root, cfg.DataDir)
	cfg.TemplatesDir = anchor(root, cfg.TemplatesDir)
	cfg.FrontendDir = anchor(root, cfg.FrontendDir)
	return cfg
}

func findRoot() string {
	cwd, err := os.Getwd()
	if err != nil {
		return "."
	}
	dir := cwd
	for i := 0; i < 4; i++ {
		if _, err := os.Stat(filepath.Join(dir, "templates")); err == nil {
			return dir
		}
		parent := filepath.Dir(dir)
		if parent == dir {
			break
		}
		dir = parent
	}
	return cwd
}

func anchor(root, path string) string {
	if filepath.IsAbs(path) {
		return path
	}
	return filepath.Join(root, filepath.FromSlash(path))
}

func loadDotEnv() {
	for _, path := range []string{".env", filepath.Join("..", ".env")} {
		b, err := os.ReadFile(path)
		if err != nil {
			continue
		}
		for _, line := range strings.Split(string(b), "\n") {
			line = strings.TrimSpace(strings.TrimRight(line, "\r"))
			if line == "" || strings.HasPrefix(line, "#") {
				continue
			}
			key, val, ok := strings.Cut(line, "=")
			if !ok {
				continue
			}
			key = strings.TrimSpace(key)
			if _, exists := os.LookupEnv(key); exists {
				continue
			}
			os.Setenv(key, strings.Trim(strings.TrimSpace(val), `"'`))
		}
		return
	}
}

func env(key, fallback string) string {
	if v := os.Getenv(key); v != "" {
		return v
	}
	return fallback
}

func dsnFromParts() string {
	c := mysql.NewConfig()
	c.User = env("DB_USER", "server-manager")
	c.Passwd = os.Getenv("DB_PASSWORD")
	c.Net = "tcp"
	c.Addr = os.Getenv("DB_HOST") + ":" + env("DB_PORT", "3306")
	c.DBName = env("DB_NAME", "server-manager")
	c.ParseTime = true
	c.MultiStatements = true
	c.Params = map[string]string{"charset": "utf8mb4"}
	return c.FormatDSN()
}

func mysqlDSN(raw string) string {
	raw = strings.TrimSpace(raw)
	if raw == "" {
		return ""
	}
	if strings.Contains(raw, "@tcp(") {
		return raw
	}
	u, err := url.Parse(raw)
	if err != nil {
		return raw
	}
	user := ""
	pass := ""
	if u.User != nil {
		user = u.User.Username()
		pass, _ = u.User.Password()
	}
	db := strings.TrimPrefix(u.Path, "/")
	return user + ":" + pass + "@tcp(" + u.Host + ")/" + db + "?parseTime=true&charset=utf8mb4&multiStatements=true"
}
