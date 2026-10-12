package domain

import (
	"bytes"
	"encoding/json"
	"fmt"
	"io"
	"net/http"
	"net/url"
	"strings"
	"time"
)

func ZoneName(domain string) string {
	domain = strings.TrimPrefix(strings.ToLower(strings.TrimSpace(domain)), "*.")
	parts := strings.Split(domain, ".")
	if len(parts) >= 2 {
		return strings.Join(parts[len(parts)-2:], ".")
	}
	return domain
}

func EnsureRecord(token, hostname, ip string, proxied bool) (string, error) {
	if token == "" {
		return "", fmt.Errorf("cloudflare token is empty")
	}
	if ip == "" {
		return "", fmt.Errorf("public IP is empty")
	}
	zoneID, err := zoneID(token, ZoneName(hostname))
	if err != nil {
		return "", err
	}
	records, err := listRecords(token, zoneID, hostname)
	if err != nil {
		return "", err
	}
	ttl := 120
	if proxied {
		ttl = 1
	}
	body := map[string]any{
		"type": "A", "name": hostname, "content": ip, "ttl": ttl, "proxied": proxied,
	}
	if len(records) > 0 {
		id, _ := records[0]["id"].(string)
		if err := writeRecord(http.MethodPut, token, zoneID, id, body); err != nil {
			return "", err
		}
		return id, nil
	}
	if err := writeRecord(http.MethodPost, token, zoneID, "", body); err != nil {
		return "", err
	}
	records, err = listRecords(token, zoneID, hostname)
	if err != nil || len(records) == 0 {
		return "", err
	}
	id, _ := records[0]["id"].(string)
	return id, nil
}

func DeleteRecord(token, hostname, recordID string) error {
	if token == "" || recordID == "" {
		return nil
	}
	zoneID, err := zoneID(token, ZoneName(hostname))
	if err != nil {
		return err
	}
	req, err := http.NewRequest(http.MethodDelete, "https://api.cloudflare.com/client/v4/zones/"+zoneID+"/dns_records/"+recordID, nil)
	if err != nil {
		return err
	}
	req.Header.Set("Authorization", "Bearer "+token)
	resp, err := http.DefaultClient.Do(req)
	if err != nil {
		return err
	}
	defer resp.Body.Close()
	if resp.StatusCode >= 300 {
		b, _ := io.ReadAll(io.LimitReader(resp.Body, 4000))
		return fmt.Errorf("cloudflare delete: %s", strings.TrimSpace(string(b)))
	}
	return nil
}

func zoneID(token, name string) (string, error) {
	q := url.Values{"name": {name}, "per_page": {"50"}, "status": {"active"}}
	zones, err := getZones(token, q)
	if err != nil {
		return "", err
	}
	if id := bestZone(name, zones); id != "" {
		return id, nil
	}
	zones, err = getZones(token, url.Values{"per_page": {"50"}, "status": {"active"}})
	if err != nil {
		return "", err
	}
	if id := bestZone(name, zones); id != "" {
		return id, nil
	}
	return "", fmt.Errorf("cloudflare zone not found for %s", name)
}

func bestZone(domain string, zones []map[string]any) string {
	domain = strings.ToLower(domain)
	bestLen := -1
	bestID := ""
	for _, zone := range zones {
		name, _ := zone["name"].(string)
		name = strings.ToLower(name)
		if domain == name || strings.HasSuffix(domain, "."+name) {
			if len(name) > bestLen {
				bestLen = len(name)
				bestID, _ = zone["id"].(string)
			}
		}
	}
	return bestID
}

func getZones(token string, q url.Values) ([]map[string]any, error) {
	req, err := http.NewRequest(http.MethodGet, "https://api.cloudflare.com/client/v4/zones?"+q.Encode(), nil)
	if err != nil {
		return nil, err
	}
	req.Header.Set("Authorization", "Bearer "+token)
	var payload struct {
		Success bool             `json:"success"`
		Result  []map[string]any `json:"result"`
		Errors  []map[string]any `json:"errors"`
	}
	if err := do(req, &payload); err != nil {
		return nil, err
	}
	if !payload.Success {
		return nil, fmt.Errorf("cloudflare zones: %v", payload.Errors)
	}
	return payload.Result, nil
}

func listRecords(token, zoneID, name string) ([]map[string]any, error) {
	q := url.Values{"type": {"A"}, "name": {name}}
	req, err := http.NewRequest(http.MethodGet, "https://api.cloudflare.com/client/v4/zones/"+zoneID+"/dns_records?"+q.Encode(), nil)
	if err != nil {
		return nil, err
	}
	req.Header.Set("Authorization", "Bearer "+token)
	var payload struct {
		Success bool             `json:"success"`
		Result  []map[string]any `json:"result"`
		Errors  []map[string]any `json:"errors"`
	}
	if err := do(req, &payload); err != nil {
		return nil, err
	}
	if !payload.Success {
		return nil, fmt.Errorf("cloudflare records: %v", payload.Errors)
	}
	return payload.Result, nil
}

func writeRecord(method, token, zoneID, id string, body map[string]any) error {
	buf, _ := json.Marshal(body)
	u := "https://api.cloudflare.com/client/v4/zones/" + zoneID + "/dns_records"
	if id != "" {
		u += "/" + id
	}
	req, err := http.NewRequest(method, u, bytes.NewReader(buf))
	if err != nil {
		return err
	}
	req.Header.Set("Authorization", "Bearer "+token)
	req.Header.Set("Content-Type", "application/json")
	var payload struct {
		Success bool             `json:"success"`
		Errors  []map[string]any `json:"errors"`
	}
	if err := do(req, &payload); err != nil {
		return err
	}
	if !payload.Success {
		return fmt.Errorf("cloudflare record: %v", payload.Errors)
	}
	return nil
}

func do(req *http.Request, dest any) error {
	client := &http.Client{Timeout: 15 * time.Second}
	resp, err := client.Do(req)
	if err != nil {
		return err
	}
	defer resp.Body.Close()
	b, err := io.ReadAll(io.LimitReader(resp.Body, 1<<20))
	if err != nil {
		return err
	}
	if err := json.Unmarshal(b, dest); err != nil {
		return fmt.Errorf("cloudflare: %s", strings.TrimSpace(string(b)))
	}
	return nil
}
