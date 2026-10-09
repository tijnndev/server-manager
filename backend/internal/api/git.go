package api

import (
	"context"
	"encoding/base64"
	"fmt"
	"os"
	"os/exec"
	"path/filepath"
	"strconv"
	"strings"
	"time"

	"server-manager/backend/internal/model"
)

type gitChange struct {
	File string `json:"file"`
	Type string `json:"type"`
}

type gitOverview struct {
	Repo          bool        `json:"repo"`
	Remote        string      `json:"remote"`
	Branch        string      `json:"branch"`
	Commit        string      `json:"commit"`
	Ahead         int         `json:"ahead"`
	Behind        int         `json:"behind"`
	LocalChanges  []gitChange `json:"localChanges"`
	RemoteChanges []gitChange `json:"remoteChanges"`
	Error         string      `json:"error,omitempty"`
}

func (a *App) pullStack(st model.Stack) (string, error) {
	return a.syncOrigin(st.Dir)
}

func (a *App) gitOverview(dir string) gitOverview {
	ov := gitOverview{
		Repo:          true,
		LocalChanges:  []gitChange{},
		RemoteChanges: []gitChange{},
	}
	a.ensureHTTPSOrigin(dir)
	if remote, err := a.runGit(dir, "remote", "get-url", "origin"); err == nil {
		ov.Remote = strings.TrimSpace(remote)
	}
	ov.Branch = a.currentBranch(dir)
	if commit, err := a.runGit(dir, "rev-parse", "--short", "HEAD"); err == nil {
		ov.Commit = strings.TrimSpace(commit)
	}
	if out, err := a.runGitTimeout(dir, 25*time.Second, "fetch", "origin", ov.Branch); err != nil {
		ov.Error = out
	}
	ov.Ahead, ov.Behind = a.aheadBehind(dir, ov.Branch)
	if status, err := a.runGit(dir, "status", "--porcelain"); err == nil {
		ov.LocalChanges = parsePorcelain(status)
	}
	ov.RemoteChanges = a.remoteChanges(dir, ov.Branch, ov.Behind)
	return ov
}

func (a *App) syncOrigin(dir string) (string, error) {
	a.ensureHTTPSOrigin(dir)
	branch := a.currentBranch(dir)
	if out, err := a.runGitTimeout(dir, 2*time.Minute, "fetch", "origin", branch); err != nil {
		return out, err
	}
	local, lerr := a.runGit(dir, "rev-parse", "HEAD")
	remote, rerr := a.runGit(dir, "rev-parse", "origin/"+branch)
	if lerr != nil {
		return local, lerr
	}
	if rerr != nil {
		return remote, rerr
	}
	local, remote = strings.TrimSpace(local), strings.TrimSpace(remote)
	if local == remote {
		return "Already up to date.", nil
	}
	out, err := a.runGit(dir, "pull", "--ff-only", "origin", branch)
	if err != nil && localChangesBlockPull(out) {
		if stashOut, stashErr := a.runGit(dir, "stash", "push", "-m", "server-manager"); stashErr != nil {
			return strings.TrimSpace(out + "\n" + stashOut), err
		}
		out, err = a.runGit(dir, "pull", "--ff-only", "origin", branch)
	}
	if err != nil {
		return out, err
	}
	log, _ := a.runGit(dir, "log", "--oneline", local+"..HEAD")
	log = strings.TrimSpace(log)
	if log != "" {
		return log, nil
	}
	if strings.TrimSpace(out) == "" {
		return "Updated.", nil
	}
	return out, nil
}

func (a *App) ensureHTTPSOrigin(dir string) {
	remote, err := a.runGit(dir, "remote", "get-url", "origin")
	if err != nil {
		return
	}
	remote = strings.TrimSpace(remote)
	resolved := a.resolveRemote(remote)
	if resolved != remote {
		_, _ = a.runGit(dir, "remote", "set-url", "origin", resolved)
	}
}

func (a *App) currentBranch(dir string) string {
	branch, err := a.runGit(dir, "rev-parse", "--abbrev-ref", "HEAD")
	branch = strings.TrimSpace(branch)
	if err != nil || branch == "" || branch == "HEAD" {
		return "main"
	}
	return branch
}

func (a *App) aheadBehind(dir, branch string) (int, int) {
	out, err := a.runGit(dir, "rev-list", "--left-right", "--count", "HEAD...origin/"+branch)
	if err != nil {
		return 0, 0
	}
	fields := strings.Fields(out)
	if len(fields) != 2 {
		return 0, 0
	}
	ahead, _ := strconv.Atoi(fields[0])
	behind, _ := strconv.Atoi(fields[1])
	return ahead, behind
}

func (a *App) remoteChanges(dir, branch string, behind int) []gitChange {
	out, err := a.runGit(dir, "diff", "--name-status", "HEAD..origin/"+branch)
	if err == nil {
		if changes := parseNameStatus(out); len(changes) > 0 {
			return changes
		}
	}
	if behind <= 0 {
		return []gitChange{}
	}
	log, err := a.runGit(dir, "log", "--oneline", "HEAD..origin/"+branch)
	if err != nil || strings.TrimSpace(log) == "" {
		return []gitChange{}
	}
	changes := []gitChange{}
	for _, line := range strings.Split(log, "\n") {
		line = strings.TrimSpace(line)
		if line == "" {
			continue
		}
		changes = append(changes, gitChange{File: line, Type: "Commit"})
	}
	return changes
}

func (a *App) attachAndPull(st model.Stack, remote string) (string, error) {
	remote = a.resolveRemote(remote)
	if _, err := a.runGit(st.Dir, "remote", "get-url", "origin"); err != nil {
		if out, addErr := a.runGit(st.Dir, "remote", "add", "origin", remote); addErr != nil {
			return out, addErr
		}
	} else if out, err := a.runGit(st.Dir, "remote", "set-url", "origin", remote); err != nil {
		return out, err
	}
	return a.syncOrigin(st.Dir)
}

func (a *App) cloneInto(st model.Stack, remote string) (string, error) {
	remote = a.resolveRemote(remote)
	empty, err := dirEmpty(st.Dir)
	if err != nil {
		return err.Error(), err
	}
	if empty {
		return a.runGit(st.Dir, "clone", remote, ".")
	}
	sym, err := a.runGit(st.Dir, "ls-remote", "--symref", remote, "HEAD")
	if err != nil {
		return sym, err
	}
	branch := parseHeadSymref(sym)
	if branch == "" {
		branch = "main"
	}
	if out, err := a.runGit(st.Dir, "init"); err != nil {
		return out, err
	}
	if out, err := a.runGit(st.Dir, "remote", "add", "origin", remote); err != nil {
		return out, err
	}
	if out, err := a.runGit(st.Dir, "fetch", "origin"); err != nil {
		return out, err
	}
	out, err := a.runGit(st.Dir, "checkout", "-B", branch, "--track", "origin/"+branch)
	if err != nil && branch != "master" {
		if alt, altErr := a.runGit(st.Dir, "checkout", "-B", "master", "--track", "origin/master"); altErr == nil {
			return alt, nil
		}
	}
	return out, err
}

func (a *App) runGit(dir string, args ...string) (string, error) {
	return a.runGitTimeout(dir, 0, args...)
}

func (a *App) runGitTimeout(dir string, timeout time.Duration, args ...string) (string, error) {
	ctx := context.Background()
	cancel := func() {}
	if timeout > 0 {
		ctx, cancel = context.WithTimeout(context.Background(), timeout)
	}
	defer cancel()
	cmd := exec.CommandContext(ctx, "git", append([]string{"-C", dir}, args...)...)
	env, err := a.gitEnv()
	if err != nil {
		return err.Error(), err
	}
	cmd.Env = env
	out, err := cmd.CombinedOutput()
	text := strings.TrimSpace(string(out))
	if err != nil && text == "" {
		text = err.Error()
	}
	if err != nil && strings.Contains(text, "could not read Username") && a.githubToken() == "" {
		text = "GitHub authentication required. Add a personal access token in Settings."
	}
	return text, err
}

func localChangesBlockPull(out string) bool {
	return strings.Contains(out, "would be overwritten") || strings.Contains(out, "Please commit your changes") || strings.Contains(out, "Your local changes")
}

func parsePorcelain(out string) []gitChange {
	changes := []gitChange{}
	for _, line := range strings.Split(out, "\n") {
		if len(line) < 4 {
			continue
		}
		status := line[:2]
		file := strings.TrimSpace(line[3:])
		if i := strings.LastIndex(file, " -> "); i >= 0 {
			file = file[i+4:]
		}
		kind := porcelainKind(status)
		if kind == "" || file == "" {
			continue
		}
		changes = append(changes, gitChange{File: file, Type: kind})
	}
	return changes
}

func porcelainKind(status string) string {
	switch {
	case strings.Contains(status, "?"):
		return "Untracked"
	case strings.Contains(status, "M"):
		return "Modified"
	case strings.Contains(status, "A"):
		return "Added"
	case strings.Contains(status, "D"):
		return "Deleted"
	case strings.Contains(status, "R"):
		return "Renamed"
	default:
		return ""
	}
}

func parseNameStatus(out string) []gitChange {
	changes := []gitChange{}
	for _, line := range strings.Split(out, "\n") {
		line = strings.TrimSpace(line)
		if line == "" {
			continue
		}
		parts := strings.Split(line, "\t")
		if len(parts) < 2 {
			continue
		}
		file := parts[len(parts)-1]
		kind := nameStatusKind(parts[0])
		if kind == "" || file == "" {
			continue
		}
		changes = append(changes, gitChange{File: file, Type: kind})
	}
	return changes
}

func nameStatusKind(status string) string {
	switch {
	case status == "M" || strings.HasPrefix(status, "M"):
		return "Modified"
	case status == "A" || strings.HasPrefix(status, "A"):
		return "Added"
	case status == "D" || strings.HasPrefix(status, "D"):
		return "Deleted"
	case strings.HasPrefix(status, "R"):
		return "Renamed"
	default:
		return status
	}
}

func (a *App) gitEnv() ([]string, error) {
	dir := filepath.Join(a.cfg.DataDir, ".ssh")
	if err := os.MkdirAll(dir, 0o700); err != nil {
		return nil, err
	}
	known := filepath.Join(dir, "known_hosts")
	f, err := os.OpenFile(known, os.O_CREATE|os.O_WRONLY, 0o600)
	if err != nil {
		return nil, err
	}
	_ = f.Close()

	env := make([]string, 0, len(os.Environ())+5)
	for _, e := range os.Environ() {
		if strings.HasPrefix(e, "GIT_SSH_COMMAND=") || strings.HasPrefix(e, "GIT_TERMINAL_PROMPT=") || strings.HasPrefix(e, "GIT_CONFIG_") {
			continue
		}
		env = append(env, e)
	}
	env = append(env,
		"GIT_TERMINAL_PROMPT=0",
		"GIT_SSH_COMMAND="+sshCommand(known),
	)
	if token := a.githubToken(); token != "" {
		env = append(env,
			"GIT_CONFIG_COUNT=1",
			"GIT_CONFIG_KEY_0=http.https://github.com/.extraheader",
			"GIT_CONFIG_VALUE_0="+githubAuthHeader(token),
		)
	}
	return env, nil
}

func (a *App) githubToken() string {
	if a.store != nil {
		settings, err := a.store.GetSettings(context.Background())
		if err == nil {
			if token := strings.TrimSpace(settings.GithubToken); token != "" {
				return token
			}
		}
	}
	if token := strings.TrimSpace(os.Getenv("GITHUB_TOKEN")); token != "" {
		return token
	}
	return strings.TrimSpace(os.Getenv("GH_TOKEN"))
}

func githubAuthHeader(token string) string {
	return "Authorization: Basic " + base64.StdEncoding.EncodeToString([]byte("x-access-token:"+token))
}

func (a *App) resolveRemote(remote string) string {
	if a.sshKeyPresent() {
		return remote
	}
	return preferHTTPS(remote)
}

func (a *App) sshKeyPresent() bool {
	dirs := []string{filepath.Join(a.cfg.DataDir, ".ssh")}
	if home, err := os.UserHomeDir(); err == nil && home != "" {
		dirs = append(dirs, filepath.Join(home, ".ssh"))
	}
	return sshIdentityPresent(dirs...)
}

func sshCommand(knownHosts string) string {
	return fmt.Sprintf("ssh -o StrictHostKeyChecking=accept-new -o BatchMode=yes -o UserKnownHostsFile=%s", shellQuote(knownHosts))
}

func shellQuote(s string) string {
	if s == "" || strings.ContainsAny(s, " \t'\"\\$") {
		return "'" + strings.ReplaceAll(s, "'", `'\''`) + "'"
	}
	return s
}

func sshIdentityPresent(dirs ...string) bool {
	names := []string{"id_rsa", "id_ed25519", "id_ecdsa", "id_ed25519_sk"}
	for _, dir := range dirs {
		for _, name := range names {
			info, err := os.Stat(filepath.Join(dir, name))
			if err == nil && !info.IsDir() && info.Size() > 0 {
				return true
			}
		}
	}
	return false
}

func preferHTTPS(remote string) string {
	switch {
	case strings.HasPrefix(remote, "git@github.com:"):
		return "https://github.com/" + strings.TrimPrefix(remote, "git@github.com:")
	case strings.HasPrefix(remote, "ssh://git@github.com/"):
		return "https://github.com/" + strings.TrimPrefix(remote, "ssh://git@github.com/")
	case strings.HasPrefix(remote, "git@gitlab.com:"):
		return "https://gitlab.com/" + strings.TrimPrefix(remote, "git@gitlab.com:")
	case strings.HasPrefix(remote, "ssh://git@gitlab.com/"):
		return "https://gitlab.com/" + strings.TrimPrefix(remote, "ssh://git@gitlab.com/")
	default:
		return remote
	}
}

func validGitRemote(remote string) bool {
	if remote == "" || strings.HasPrefix(remote, "-") || strings.ContainsAny(remote, "\n\r") {
		return false
	}
	if strings.Contains(remote, "://") {
		return strings.HasPrefix(remote, "https://") || strings.HasPrefix(remote, "http://") || strings.HasPrefix(remote, "ssh://") || strings.HasPrefix(remote, "git://")
	}
	return strings.HasPrefix(remote, "git@") && strings.Contains(remote, ":")
}

func parseHeadSymref(out string) string {
	for _, line := range strings.Split(out, "\n") {
		line = strings.TrimSpace(line)
		const prefix = "ref: refs/heads/"
		if !strings.HasPrefix(line, prefix) {
			continue
		}
		rest := strings.TrimPrefix(line, prefix)
		if i := strings.IndexAny(rest, " \t"); i >= 0 {
			rest = rest[:i]
		}
		if rest != "" && !strings.Contains(rest, "..") {
			return rest
		}
	}
	return ""
}

func dirEmpty(path string) (bool, error) {
	entries, err := os.ReadDir(path)
	if err != nil {
		return false, err
	}
	return len(entries) == 0, nil
}
