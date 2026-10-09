package api

import (
	"fmt"
	"os"
	"os/exec"
	"path/filepath"
	"strings"

	"server-manager/backend/internal/model"
)

func (a *App) pullStack(st model.Stack) (string, error) {
	remote, err := a.runGit(st.Dir, "remote", "get-url", "origin")
	if err != nil {
		return a.runGit(st.Dir, "pull", "--ff-only")
	}
	resolved := a.resolveRemote(strings.TrimSpace(remote))
	if resolved == strings.TrimSpace(remote) {
		return a.runGit(st.Dir, "pull", "--ff-only")
	}
	branch, berr := a.runGit(st.Dir, "rev-parse", "--abbrev-ref", "HEAD")
	branch = strings.TrimSpace(branch)
	if berr != nil || branch == "" || branch == "HEAD" {
		return a.runGit(st.Dir, "pull", "--ff-only", resolved)
	}
	return a.runGit(st.Dir, "pull", "--ff-only", resolved, branch)
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
	if out, err := a.runGit(st.Dir, "fetch", "origin"); err != nil {
		return out, err
	}
	out, err := a.runGit(st.Dir, "pull", "--ff-only")
	if err == nil {
		return out, nil
	}
	branch, berr := a.runGit(st.Dir, "rev-parse", "--abbrev-ref", "HEAD")
	branch = strings.TrimSpace(branch)
	if berr != nil || branch == "" || branch == "HEAD" {
		return out, err
	}
	return a.runGit(st.Dir, "pull", "--ff-only", "origin", branch)
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
	cmd := exec.Command("git", append([]string{"-C", dir}, args...)...)
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
	return text, err
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

	env := make([]string, 0, len(os.Environ())+2)
	for _, e := range os.Environ() {
		if strings.HasPrefix(e, "GIT_SSH_COMMAND=") || strings.HasPrefix(e, "GIT_TERMINAL_PROMPT=") {
			continue
		}
		env = append(env, e)
	}
	env = append(env,
		"GIT_TERMINAL_PROMPT=0",
		"GIT_SSH_COMMAND="+sshCommand(known),
	)
	return env, nil
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
