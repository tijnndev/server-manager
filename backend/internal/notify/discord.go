package notify

import (
	"bytes"
	"encoding/json"
	"log/slog"
	"net/http"
	"time"
)

func Discord(webhook, content string) {
	if webhook == "" || content == "" {
		return
	}
	body, _ := json.Marshal(map[string]string{"content": content})
	req, err := http.NewRequest(http.MethodPost, webhook, bytes.NewReader(body))
	if err != nil {
		return
	}
	req.Header.Set("Content-Type", "application/json")
	client := &http.Client{Timeout: 8 * time.Second}
	resp, err := client.Do(req)
	if err != nil {
		slog.Error("discord", "err", err)
		return
	}
	resp.Body.Close()
}
