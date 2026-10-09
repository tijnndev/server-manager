package template

import (
	"fmt"
	"sync"
)

type Catalog struct {
	dir   string
	mu    sync.RWMutex
	items map[string]Template
}

func NewCatalog(dir string) *Catalog {
	return &Catalog{dir: dir, items: map[string]Template{}}
}

func (c *Catalog) Reload(overrides map[string]string) error {
	files, err := LoadDir(c.dir)
	if err != nil {
		return err
	}
	merged := map[string]string{}
	for id, raw := range files {
		merged[id] = raw
	}
	for id, raw := range overrides {
		merged[id] = raw
	}
	items := map[string]Template{}
	for id, raw := range merged {
		t, err := Parse(raw)
		if err != nil {
			return err
		}
		if t.ID != id {
			return fmt.Errorf("template id %s does not match %s", t.ID, id)
		}
		t.Raw = raw
		items[t.ID] = t
	}
	c.mu.Lock()
	c.items = items
	c.mu.Unlock()
	return nil
}

func (c *Catalog) List() []Template {
	c.mu.RLock()
	defer c.mu.RUnlock()
	out := make([]Template, 0, len(c.items))
	for _, t := range c.items {
		out = append(out, t)
	}
	return out
}

func (c *Catalog) Get(id string) (Template, bool) {
	c.mu.RLock()
	defer c.mu.RUnlock()
	t, ok := c.items[id]
	return t, ok
}
