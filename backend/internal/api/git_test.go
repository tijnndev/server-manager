package api

import (
	"os"
	"path/filepath"
	"testing"
)

func TestPreferHTTPS(t *testing.T) {
	cases := map[string]string{
		"git@github.com:org/repo.git":       "https://github.com/org/repo.git",
		"ssh://git@github.com/org/repo.git": "https://github.com/org/repo.git",
		"git@gitlab.com:org/repo.git":       "https://gitlab.com/org/repo.git",
		"ssh://git@gitlab.com/org/repo.git": "https://gitlab.com/org/repo.git",
		"https://github.com/org/repo.git":   "https://github.com/org/repo.git",
		"git@git.example.com:org/repo.git":  "git@git.example.com:org/repo.git",
	}
	for in, want := range cases {
		if got := preferHTTPS(in); got != want {
			t.Fatalf("preferHTTPS(%q) = %q, want %q", in, got, want)
		}
	}
}

func TestValidGitRemote(t *testing.T) {
	if !validGitRemote("https://github.com/org/repo.git") || !validGitRemote("git@github.com:org/repo.git") {
		t.Fatal("expected valid remotes")
	}
	for _, bad := range []string{"", "-oProxyCommand=x", "ext::sh", "file:///tmp/repo", "https://github.com/org/repo.git\nrm -rf"} {
		if validGitRemote(bad) {
			t.Fatalf("expected invalid remote %q", bad)
		}
	}
}

func TestParseHeadSymref(t *testing.T) {
	out := "ref: refs/heads/main\tHEAD\nabc123\tHEAD\n"
	if got := parseHeadSymref(out); got != "main" {
		t.Fatalf("got %q", got)
	}
	if parseHeadSymref("abc123\tHEAD") != "" {
		t.Fatal("expected empty")
	}
}

func TestSSHIdentityPresent(t *testing.T) {
	dir := t.TempDir()
	if sshIdentityPresent(dir) {
		t.Fatal("empty dir")
	}
	if err := os.WriteFile(filepath.Join(dir, "id_ed25519"), []byte("key"), 0o600); err != nil {
		t.Fatal(err)
	}
	if !sshIdentityPresent(dir) {
		t.Fatal("expected key")
	}
}

func TestParsePorcelainAndNameStatus(t *testing.T) {
	local := parsePorcelain(" M compose.yaml\n?? Dockerfile\nD  old.txt\n")
	if len(local) != 3 || local[0].Type != "Modified" || local[1].Type != "Untracked" || local[2].Type != "Deleted" {
		t.Fatalf("porcelain %#v", local)
	}
	remote := parseNameStatus("M\tsrc/app.ts\nA\tnew.ts\nR100\told.ts\tnew-name.ts\n")
	if len(remote) != 3 || remote[0].File != "src/app.ts" || remote[2].Type != "Renamed" || remote[2].File != "new-name.ts" {
		t.Fatalf("name-status %#v", remote)
	}
}

func TestGithubAuthHeader(t *testing.T) {
	got := githubAuthHeader("ghp_test")
	if got != "Authorization: Basic eC1hY2Nlc3MtdG9rZW46Z2hwX3Rlc3Q=" {
		t.Fatalf("got %s", got)
	}
}

func TestSSHCommandQuotesPath(t *testing.T) {
	got := sshCommand(`/var/lib/server manager/.ssh/known_hosts`)
	if got != `ssh -o StrictHostKeyChecking=accept-new -o BatchMode=yes -o UserKnownHostsFile='/var/lib/server manager/.ssh/known_hosts'` {
		t.Fatalf("got %s", got)
	}
}
