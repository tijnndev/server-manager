package template

import (
	"fmt"
	"os"
	"strconv"
	"strings"

	"context"

	"github.com/compose-spec/compose-go/v2/loader"
	"github.com/compose-spec/compose-go/v2/types"
	"gopkg.in/yaml.v3"
)

type ParsedService struct {
	Name         string
	InternalPort int
	HostPort     int
	Logs         bool
	Shell        bool
	HTTP         bool
}

func ParseCompose(dir, path string) ([]ParsedService, error) {
	if svcs, err := parseComposeGo(dir, path); err == nil && len(svcs) > 0 {
		return svcs, nil
	}
	return parseComposeYAML(path)
}

func parseComposeGo(dir, path string) ([]ParsedService, error) {
	content, err := os.ReadFile(path)
	if err != nil {
		return nil, err
	}
	project, err := loader.LoadWithContext(context.Background(), types.ConfigDetails{
		WorkingDir: dir,
		ConfigFiles: []types.ConfigFile{{
			Filename: path,
			Content:  content,
		}},
	}, func(o *loader.Options) {
		o.SkipValidation = true
	})
	if err != nil {
		return nil, err
	}
	var out []ParsedService
	for _, name := range project.ServiceNames() {
		svc, ok := project.Services[name]
		if !ok {
			continue
		}
		ps := ParsedService{Name: name, Logs: true, Shell: true}
		for _, port := range svc.Ports {
			target := int(port.Target)
			published, _ := strconv.Atoi(port.Published)
			if target > 0 && ps.InternalPort == 0 {
				ps.InternalPort = target
			}
			if published > 0 && ps.HostPort == 0 {
				ps.HostPort = published
			}
		}
		ps.HTTP = ps.InternalPort > 0
		out = append(out, ps)
	}
	return out, nil
}

func parseComposeYAML(path string) ([]ParsedService, error) {
	b, err := os.ReadFile(path)
	if err != nil {
		return nil, err
	}
	var root map[string]any
	if err := yaml.Unmarshal(b, &root); err != nil {
		return nil, err
	}
	services, _ := root["services"].(map[string]any)
	if len(services) == 0 {
		return nil, fmt.Errorf("compose file has no services")
	}
	var out []ParsedService
	for name, raw := range services {
		ps := ParsedService{Name: name, Logs: true, Shell: true}
		if body, ok := raw.(map[string]any); ok {
			host, internal := firstPort(body["ports"])
			ps.HostPort = host
			ps.InternalPort = internal
			ps.HTTP = internal > 0
		}
		out = append(out, ps)
	}
	return out, nil
}

func firstPort(raw any) (host, internal int) {
	list, ok := raw.([]any)
	if !ok {
		return 0, 0
	}
	for _, item := range list {
		switch v := item.(type) {
		case string:
			h, i := splitPort(v)
			if i > 0 {
				return h, i
			}
		case int:
			return 0, v
		case map[string]any:
			internal = asInt(v["target"])
			host = asInt(v["published"])
			if internal > 0 {
				return host, internal
			}
		}
	}
	return 0, 0
}

func splitPort(spec string) (host, internal int) {
	spec = strings.TrimSpace(spec)
	parts := strings.Split(spec, ":")
	switch len(parts) {
	case 1:
		return 0, asInt(parts[0])
	case 2:
		return asInt(parts[0]), asInt(parts[1])
	default:
		return asInt(parts[len(parts)-2]), asInt(parts[len(parts)-1])
	}
}

func asInt(v any) int {
	switch n := v.(type) {
	case int:
		return n
	case int64:
		return int(n)
	case uint32:
		return int(n)
	case uint64:
		return int(n)
	case float64:
		return int(n)
	case string:
		i, _ := strconv.Atoi(strings.TrimSpace(n))
		return i
	default:
		return 0
	}
}
