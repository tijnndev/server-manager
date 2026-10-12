package mail

import (
	"context"
	"fmt"
	"os/exec"
	"strings"
	"time"
)

type Client struct {
	Container string
}

func (c Client) name() string {
	if c.Container != "" {
		return c.Container
	}
	return "mailserver"
}

func (c Client) Status() (bool, string) {
	out, err := run(10*time.Second, "inspect", "-f", "{{.State.Status}}", c.name())
	text := strings.TrimSpace(string(out))
	if err != nil {
		if strings.Contains(text, "No such container") {
			return false, "Mail server container is not running. Start the mailserver container to manage email accounts."
		}
		if text == "" {
			text = err.Error()
		}
		return false, text
	}
	if text != "running" {
		return false, "Mail server container is " + text + "."
	}
	return true, ""
}

func (c Client) List() ([]string, error) {
	ok, msg := c.Status()
	if !ok {
		return nil, fmt.Errorf("%s", msg)
	}
	out, err := run(35*time.Second, "exec", c.name(), "setup", "email", "list")
	if err != nil {
		return nil, fmt.Errorf("%s", strings.TrimSpace(string(out)))
	}
	var users []string
	for _, line := range strings.Split(strings.TrimSpace(string(out)), "\n") {
		fields := strings.Fields(line)
		if len(fields) > 1 && strings.Contains(fields[1], "@") {
			users = append(users, fields[1])
		}
	}
	if users == nil {
		users = []string{}
	}
	return users, nil
}

func (c Client) Add(email, password string) error {
	return c.mutate("add", email, password)
}

func (c Client) Update(email, password string) error {
	return c.mutate("update", email, password)
}

func (c Client) Delete(email string) error {
	ok, msg := c.Status()
	if !ok {
		return fmt.Errorf("%s", msg)
	}
	out, err := run(35*time.Second, "exec", c.name(), "setup", "email", "del", email)
	if err != nil {
		return fmt.Errorf("%s", strings.TrimSpace(string(out)))
	}
	return nil
}

func (c Client) mutate(action, email, password string) error {
	if !strings.Contains(email, "@") || strings.ContainsAny(email, " \t") || password == "" {
		return fmt.Errorf("email and password are required")
	}
	ok, msg := c.Status()
	if !ok {
		return fmt.Errorf("%s", msg)
	}
	out, err := run(35*time.Second, "exec", c.name(), "setup", "email", action, email, password)
	if err != nil {
		text := strings.TrimSpace(string(out))
		if text == "" {
			text = err.Error()
		}
		return fmt.Errorf("%s", text)
	}
	return nil
}

func run(timeout time.Duration, args ...string) ([]byte, error) {
	ctx, cancel := context.WithTimeout(context.Background(), timeout)
	defer cancel()
	return exec.CommandContext(ctx, "docker", args...).CombinedOutput()
}
