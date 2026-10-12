package safe

import "testing"

func TestJoin(t *testing.T) {
	root := t.TempDir()
	got, err := Join(root, "src/app.js")
	if err != nil {
		t.Fatal(err)
	}
	if !stringsHas(got, "src") {
		t.Fatalf("got %s", got)
	}
	if _, err := Join(root, "../etc/passwd"); err == nil {
		t.Fatal("expected rejection")
	}
	if _, err := Join(root, "/etc/passwd"); err == nil {
		t.Fatal("expected rejection")
	}
}

func stringsHas(s, sub string) bool {
	return len(s) >= len(sub) && (s == sub || len(s) > 0 && contains(s, sub))
}

func contains(s, sub string) bool {
	for i := 0; i+len(sub) <= len(s); i++ {
		if s[i:i+len(sub)] == sub {
			return true
		}
	}
	return false
}
