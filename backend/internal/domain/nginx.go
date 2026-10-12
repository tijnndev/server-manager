package domain

import (
	"fmt"
	"os"
	"os/exec"
	"path/filepath"
	"strconv"
	"strings"
	"syscall"
	"time"

	"server-manager/backend/internal/model"
)

func Render(domains []model.Domain) string {
	var b strings.Builder
	for _, d := range domains {
		if d.TLS {
			// HTTP -> HTTPS redirect
			fmt.Fprintf(&b, `server {
    listen 80;
    server_name %s;
    return 301 https://$host$request_uri;
}

`, d.Hostname)
			fmt.Fprintf(&b, `server {
    listen 443 ssl;
    server_name %s;

    ssl_certificate /etc/letsencrypt/live/%s/fullchain.pem;
    ssl_certificate_key /etc/letsencrypt/live/%s/privkey.pem;
    include /etc/letsencrypt/options-ssl-nginx.conf;
`, d.Hostname, d.Hostname, d.Hostname)
			if _, err := os.Stat("/etc/letsencrypt/ssl-dhparams.pem"); err == nil {
				b.WriteString("    ssl_dhparam /etc/letsencrypt/ssl-dhparams.pem;\n")
			}
			fmt.Fprintf(&b, `
    location / {
        proxy_pass http://127.0.0.1:%d;
        proxy_http_version 1.1;
        proxy_set_header Host $host;
        proxy_set_header Upgrade $http_upgrade;
        proxy_set_header Connection "upgrade";
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
    }
}
`, d.UpstreamPort)
			continue
		}
		fmt.Fprintf(&b, `server {
    listen 80;
    server_name %s;

    location / {
        proxy_pass http://127.0.0.1:%d;
        proxy_http_version 1.1;
        proxy_set_header Host $host;
        proxy_set_header Upgrade $http_upgrade;
        proxy_set_header Connection "upgrade";
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
    }
}
`, d.Hostname, d.UpstreamPort)
	}
	return b.String()
}

func SitePath(available, stack string) string {
	return filepath.Join(available, stack)
}

type Result struct {
	Nginx      bool     `json:"nginx"`
	TLS        bool     `json:"tls"`
	Cloudflare bool     `json:"cloudflare"`
	Warnings   []string `json:"warnings,omitempty"`
}

func ApplyNginx(available, enabled, stack string, domains []model.Domain) error {
	path := SitePath(available, stack)
	link := filepath.Join(enabled, stack)
	if len(domains) == 0 {
		_ = os.Remove(link)
		_ = os.Remove(path)
		return reloadNginx()
	}
	if err := os.MkdirAll(available, 0o755); err != nil {
		return err
	}
	if err := os.MkdirAll(enabled, 0o755); err != nil {
		return err
	}
	next := Render(domains)
	prev, _ := os.ReadFile(path)
	if err := os.WriteFile(path, []byte(next), 0o644); err != nil {
		return err
	}
	if _, err := os.Lstat(link); err == nil {
		_ = os.Remove(link)
	}
	if err := os.Symlink(path, link); err != nil && !os.IsExist(err) {
		return err
	}
	if err := testNginx(); err != nil {
		if len(prev) > 0 {
			_ = os.WriteFile(path, prev, 0o644)
		} else {
			_ = os.Remove(path)
			_ = os.Remove(link)
		}
		return err
	}
	return reloadNginx()
}

func testNginx() error {
	cmd := exec.Command("nginx", "-t")
	out, err := cmd.CombinedOutput()
	if err != nil {
		return fmt.Errorf("nginx -t: %s", strings.TrimSpace(string(out)))
	}
	return nil
}

func reloadNginx() error {
	if pidFile := os.Getenv("NGINX_PID"); pidFile != "" {
		if err := sighup(pidFile); err == nil {
			return nil
		}
	}
	out, err := exec.Command("nginx", "-s", "reload").CombinedOutput()
	if err == nil {
		return nil
	}
	out2, err2 := exec.Command("systemctl", "reload", "nginx").CombinedOutput()
	if err2 == nil {
		return nil
	}
	msg := strings.TrimSpace(string(out2))
	if msg == "" {
		msg = strings.TrimSpace(string(out))
	}
	if msg == "" {
		msg = err.Error()
	}
	return fmt.Errorf("%s", msg)
}

func sighup(path string) error {
	b, err := os.ReadFile(path)
	if err != nil {
		return err
	}
	pid, err := strconv.Atoi(strings.TrimSpace(string(b)))
	if err != nil || pid <= 0 {
		return fmt.Errorf("invalid nginx pid")
	}
	proc, err := os.FindProcess(pid)
	if err != nil {
		return err
	}
	return proc.Signal(syscall.SIGHUP)
}

func EnsureCert(hostname, email string) error {
	if _, err := os.Stat(filepath.Join("/etc/letsencrypt/live", hostname, "fullchain.pem")); err == nil {
		return nil
	}
	args := []string{"--nginx", "-d", hostname, "--non-interactive", "--agree-tos", "--keep-until-expiring"}
	if email != "" {
		args = append(args, "-m", email)
	} else {
		args = append(args, "--register-unsafely-without-email")
	}
	cmd := exec.Command("certbot", args...)
	cmd.WaitDelay = 3 * time.Minute
	out, err := cmd.CombinedOutput()
	if err != nil {
		return fmt.Errorf("certbot: %s", strings.TrimSpace(string(out)))
	}
	return nil
}

func ValidHost(host string) bool {
	host = strings.ToLower(strings.TrimSpace(host))
	if len(host) < 3 || len(host) > 253 || strings.Contains(host, "..") {
		return false
	}
	labels := strings.Split(host, ".")
	if len(labels) < 2 {
		return false
	}
	for _, label := range labels {
		if label == "" || len(label) > 63 {
			return false
		}
		for i, r := range label {
			ok := r >= 'a' && r <= 'z' || r >= '0' && r <= '9' || r == '-'
			if !ok {
				return false
			}
			if r == '-' && (i == 0 || i == len(label)-1) {
				return false
			}
		}
	}
	return true
}
