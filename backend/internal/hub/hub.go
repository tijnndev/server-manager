package hub

import (
	"encoding/json"
	"sync"

	"server-manager/backend/internal/model"
)

type Client struct {
	User model.User
	send chan []byte
	subs map[string]struct{}
}

func newClient(user model.User) *Client {
	return &Client{User: user, send: make(chan []byte, 256), subs: map[string]struct{}{}}
}

func (c *Client) Recv() <-chan []byte { return c.send }

func (c *Client) trySend(b []byte) {
	select {
	case c.send <- b:
	default:
	}
}

type Hub struct {
	mu      sync.Mutex
	clients map[*Client]struct{}
}

func New() *Hub {
	return &Hub{clients: map[*Client]struct{}{}}
}

func (h *Hub) Add(user model.User) *Client {
	c := newClient(user)
	h.mu.Lock()
	h.clients[c] = struct{}{}
	h.mu.Unlock()
	return c
}

func (h *Hub) Remove(c *Client) {
	h.mu.Lock()
	delete(h.clients, c)
	h.mu.Unlock()
}

func (h *Hub) Subscribe(c *Client, stack string) {
	h.mu.Lock()
	c.subs[stack] = struct{}{}
	h.mu.Unlock()
}

func (h *Hub) Unsubscribe(c *Client, stack string) {
	h.mu.Lock()
	delete(c.subs, stack)
	h.mu.Unlock()
}

func (h *Hub) Subscriptions(c *Client) []string {
	h.mu.Lock()
	defer h.mu.Unlock()
	out := make([]string, 0, len(c.subs))
	for name := range c.subs {
		out = append(out, name)
	}
	return out
}

func (h *Hub) Send(c *Client, v any) {
	b, err := json.Marshal(v)
	if err != nil {
		return
	}
	c.trySend(b)
}

func (h *Hub) PublishLog(stack, service, line string) {
	b, err := json.Marshal(map[string]string{
		"type":    "log",
		"stack":   stack,
		"service": service,
		"line":    line,
	})
	if err != nil {
		return
	}
	h.mu.Lock()
	defer h.mu.Unlock()
	for c := range h.clients {
		if _, ok := c.subs[stack]; ok {
			c.trySend(b)
		}
	}
}

func (h *Hub) ForEach(fn func(*Client)) {
	h.mu.Lock()
	list := make([]*Client, 0, len(h.clients))
	for c := range h.clients {
		list = append(list, c)
	}
	h.mu.Unlock()
	for _, c := range list {
		fn(c)
	}
}
