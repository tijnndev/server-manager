package model

import "time"

type User struct {
	ID       int    `json:"id"`
	Username string `json:"username"`
	Role     string `json:"role"`
}

type Service struct {
	Name         string  `json:"name"`
	HTTP         bool    `json:"http"`
	InternalPort int     `json:"internalPort"`
	HostPort     int     `json:"hostPort"`
	Logs         bool    `json:"logs"`
	Shell        bool    `json:"shell"`
	Status       string  `json:"status"`
	CPU          float64 `json:"cpu"`
	Memory       uint64  `json:"memory"`
	MemoryLimit  uint64  `json:"memoryLimit"`
	ContainerID  string  `json:"containerId"`
}

type Stack struct {
	ID          string    `json:"id"`
	Name        string    `json:"name"`
	OwnerID     int       `json:"-"`
	Owner       string    `json:"owner"`
	Source      string    `json:"source"`
	TemplateID  string    `json:"templateId"`
	Dir         string    `json:"-"`
	Desired     string    `json:"desired"`
	Description string    `json:"description"`
	CreatedAt   time.Time `json:"createdAt"`
	Services    []Service `json:"services"`
}

type Domain struct {
	ID           int    `json:"id"`
	StackID      string `json:"-"`
	ServiceName  string `json:"service"`
	Hostname     string `json:"hostname"`
	UpstreamPort int    `json:"upstreamPort"`
	TLS          bool   `json:"tls"`
	Cloudflare   bool   `json:"cloudflare"`
	RecordID     string `json:"-"`
}

type Subuser struct {
	ID       int    `json:"id"`
	Username string `json:"username"`
	UserID   int    `json:"userId"`
}

type Activity struct {
	ID        int64     `json:"id"`
	UserID    int       `json:"userId"`
	Username  string    `json:"username"`
	StackName string    `json:"stack"`
	Action    string    `json:"action"`
	Detail    string    `json:"detail"`
	CreatedAt time.Time `json:"createdAt"`
}

type Schedule struct {
	ID      int    `json:"id"`
	StackID string `json:"-"`
	Stack   string `json:"stack"`
	Action  string `json:"action"`
	Cron    string `json:"cron"`
	Enabled bool   `json:"enabled"`
}

type Settings struct {
	DiscordWebhook  string `json:"discordWebhook"`
	CloudflareToken string `json:"cloudflareToken"`
	PublicIP        string `json:"publicIP"`
	AcmeEmail       string `json:"acmeEmail"`
	GithubToken     string `json:"githubToken"`
}

type NewService struct {
	Name         string
	HTTP         bool
	InternalPort int
	HostPort     int
	Logs         bool
	Shell        bool
}
