package template

import (
	"fmt"
	"os"
	"path/filepath"
	"strings"

	"gopkg.in/yaml.v3"
)

type Field struct {
	Key     string `yaml:"key" json:"key"`
	Label   string `yaml:"label" json:"label"`
	Default string `yaml:"default" json:"default"`
}

type Service struct {
	Name         string            `yaml:"name" json:"name"`
	Image        string            `yaml:"image,omitempty" json:"image,omitempty"`
	Build        bool              `yaml:"build,omitempty" json:"build,omitempty"`
	Script       string            `yaml:"script,omitempty" json:"script,omitempty"`
	Command      []string          `yaml:"command,omitempty" json:"command,omitempty"`
	Workdir      string            `yaml:"workdir,omitempty" json:"workdir,omitempty"`
	InternalPort int               `yaml:"internalPort,omitempty" json:"internalPort,omitempty"`
	HTTP         bool              `yaml:"http,omitempty" json:"http,omitempty"`
	Logs         bool              `yaml:"logs" json:"logs"`
	Shell        bool              `yaml:"shell" json:"shell"`
	Volumes      []string          `yaml:"volumes,omitempty" json:"volumes,omitempty"`
	Env          map[string]string `yaml:"env,omitempty" json:"env,omitempty"`
	DependsOn    []string          `yaml:"dependsOn,omitempty" json:"dependsOn,omitempty"`
}

type Template struct {
	ID          string         `yaml:"id" json:"id"`
	Name        string         `yaml:"name" json:"name"`
	Description string         `yaml:"description" json:"description"`
	Dockerfile  string         `yaml:"dockerfile,omitempty" json:"dockerfile,omitempty"`
	Fields      []Field        `yaml:"fields,omitempty" json:"fields,omitempty"`
	Services    []Service      `yaml:"services" json:"services"`
	Volumes     map[string]any `yaml:"volumes,omitempty" json:"volumes,omitempty"`
	Raw         string         `yaml:"-" json:"yaml,omitempty"`
}

type Spec struct {
	Name         string
	HTTP         bool
	InternalPort int
	HostPort     int
	Logs         bool
	Shell        bool
}

func Parse(raw string) (Template, error) {
	var t Template
	if err := yaml.Unmarshal([]byte(raw), &t); err != nil {
		return Template{}, err
	}
	if t.ID == "" || t.Name == "" || len(t.Services) == 0 {
		return Template{}, fmt.Errorf("template needs id, name and services")
	}
	seen := map[string]bool{}
	for _, svc := range t.Services {
		if svc.Name == "" || seen[svc.Name] {
			return Template{}, fmt.Errorf("invalid service name")
		}
		seen[svc.Name] = true
	}
	t.Raw = raw
	return t, nil
}

func Render(t Template, overrides map[string]string, ports map[string]int) ([]byte, []byte, []Spec, error) {
	services := map[string]composeSvc{}
	var specs []Spec
	for _, svc := range t.Services {
		script := svc.Script
		if v, ok := overrides["script:"+svc.Name]; ok && v != "" {
			script = v
		}
		env := map[string]string{}
		for k, v := range svc.Env {
			env[k] = v
		}
		for k, v := range overrides {
			prefix := "env:" + svc.Name + ":"
			if strings.HasPrefix(k, prefix) && v != "" {
				env[strings.TrimPrefix(k, prefix)] = v
			}
		}
		cs := composeSvc{
			Image:      svc.Image,
			WorkingDir: svc.Workdir,
			Volumes:    svc.Volumes,
			Restart:    "unless-stopped",
		}
		if len(env) > 0 {
			cs.Environment = env
		}
		if len(svc.DependsOn) > 0 {
			cs.DependsOn = svc.DependsOn
		}
		if svc.Build {
			cs.Build = "."
			cs.Image = ""
		}
		if script != "" {
			cs.Command = []string{"sh", "-c", script}
		} else if len(svc.Command) > 0 {
			cs.Command = svc.Command
		}
		host := ports[svc.Name]
		if svc.InternalPort > 0 && host > 0 {
			cs.Ports = []string{fmt.Sprintf("%d:%d", host, svc.InternalPort)}
		}
		services[svc.Name] = cs
		specs = append(specs, Spec{
			Name: svc.Name, HTTP: svc.HTTP, InternalPort: svc.InternalPort, HostPort: host,
			Logs: svc.Logs, Shell: svc.Shell,
		})
	}
	file := composeFile{Services: services}
	if len(t.Volumes) > 0 {
		file.Volumes = t.Volumes
	}
	body, err := yaml.Marshal(file)
	if err != nil {
		return nil, nil, nil, err
	}
	var dockerfile []byte
	if strings.TrimSpace(t.Dockerfile) != "" {
		dockerfile = []byte(t.Dockerfile)
		if !strings.HasSuffix(t.Dockerfile, "\n") {
			dockerfile = append(dockerfile, '\n')
		}
	}
	return body, dockerfile, specs, nil
}

type composeFile struct {
	Services map[string]composeSvc `yaml:"services"`
	Volumes  map[string]any        `yaml:"volumes,omitempty"`
}

type composeSvc struct {
	Image       string            `yaml:"image,omitempty"`
	Build       string            `yaml:"build,omitempty"`
	WorkingDir  string            `yaml:"working_dir,omitempty"`
	Command     []string          `yaml:"command,omitempty"`
	Ports       []string          `yaml:"ports,omitempty"`
	Volumes     []string          `yaml:"volumes,omitempty"`
	Environment map[string]string `yaml:"environment,omitempty"`
	DependsOn   []string          `yaml:"depends_on,omitempty"`
	Restart     string            `yaml:"restart,omitempty"`
}

func LoadDir(dir string) (map[string]string, error) {
	out := map[string]string{}
	entries, err := os.ReadDir(dir)
	if err != nil {
		if os.IsNotExist(err) {
			return out, nil
		}
		return nil, err
	}
	for _, entry := range entries {
		if entry.IsDir() {
			continue
		}
		name := entry.Name()
		if !strings.HasSuffix(name, ".yaml") && !strings.HasSuffix(name, ".yml") {
			continue
		}
		b, err := os.ReadFile(filepath.Join(dir, name))
		if err != nil {
			return nil, err
		}
		t, err := Parse(string(b))
		if err != nil {
			return nil, fmt.Errorf("%s: %w", name, err)
		}
		out[t.ID] = string(b)
	}
	return out, nil
}
