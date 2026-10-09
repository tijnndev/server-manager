package safe

import (
	"fmt"
	"path/filepath"
	"strings"
)

func Join(root, rel string) (string, error) {
	if rel == "" {
		rel = "."
	}
	if filepath.IsAbs(rel) || strings.HasPrefix(rel, "/") || strings.HasPrefix(rel, `\`) || strings.Contains(rel, ":") {
		return "", fmt.Errorf("invalid path")
	}
	rel = filepath.Clean(rel)
	if rel == ".." || strings.HasPrefix(rel, ".."+string(filepath.Separator)) || filepath.IsAbs(rel) || strings.HasPrefix(rel, `\`) {
		return "", fmt.Errorf("invalid path")
	}
	rootAbs, err := filepath.Abs(root)
	if err != nil {
		return "", err
	}
	full := filepath.Join(rootAbs, rel)
	back, err := filepath.Rel(rootAbs, full)
	if err != nil || back == ".." || strings.HasPrefix(back, ".."+string(filepath.Separator)) {
		return "", fmt.Errorf("invalid path")
	}
	return full, nil
}
