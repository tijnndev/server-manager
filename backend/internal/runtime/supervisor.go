package runtime

import (
	"bufio"
	"context"
	"encoding/json"
	"fmt"
	"io"
	"os"
	"os/exec"
	"path/filepath"
	"regexp"
	"strings"
	"sync"
	"time"

	"github.com/docker/docker/api/types"
	"github.com/docker/docker/api/types/container"
	"github.com/docker/docker/api/types/events"
	"github.com/docker/docker/api/types/filters"
	"github.com/docker/docker/client"
	"github.com/docker/docker/pkg/stdcopy"
	"log/slog"

	"server-manager/backend/internal/hub"
	"server-manager/backend/internal/model"
)

type Status struct {
	Status      string
	CPU         float64
	Memory      uint64
	MemoryLimit uint64
	ContainerID string
	HostPort    int
}

type Supervisor struct {
	hub      *hub.Hub
	OnChange func()
	OnCrash  func(project, service string)

	mu          sync.Mutex
	cli         *client.Client
	configured  map[string][]string
	desired     map[string]string
	state       map[string]map[string]*Status
	watches     map[string]int
	watchCancel map[string]context.CancelFunc
	muteUntil   map[string]time.Time
	logTail     map[string][]string
	crashed     map[string]time.Time
	locks       map[string]*sync.Mutex
	root        context.Context
	cancel      context.CancelFunc
}

func New(h *hub.Hub) *Supervisor {
	ctx, cancel := context.WithCancel(context.Background())
	return &Supervisor{
		hub:         h,
		configured:  map[string][]string{},
		desired:     map[string]string{},
		state:       map[string]map[string]*Status{},
		watches:     map[string]int{},
		watchCancel: map[string]context.CancelFunc{},
		muteUntil:   map[string]time.Time{},
		logTail:     map[string][]string{},
		crashed:     map[string]time.Time{},
		locks:       map[string]*sync.Mutex{},
		root:        ctx,
		cancel:      cancel,
	}
}

func (s *Supervisor) Stop() { s.cancel() }

func (s *Supervisor) SetServices(project string, names []string) {
	s.mu.Lock()
	s.configured[project] = append([]string(nil), names...)
	if s.state[project] == nil {
		s.state[project] = map[string]*Status{}
	}
	for _, name := range names {
		if s.state[project][name] == nil {
			s.state[project][name] = &Status{Status: "missing"}
		}
	}
	s.mu.Unlock()
}

func (s *Supervisor) Forget(project string) {
	s.mu.Lock()
	delete(s.configured, project)
	delete(s.desired, project)
	delete(s.state, project)
	for key := range s.logTail {
		if strings.HasPrefix(key, project+"\x00") {
			delete(s.logTail, key)
		}
	}
	if cancel := s.watchCancel[project]; cancel != nil {
		cancel()
	}
	delete(s.watchCancel, project)
	delete(s.watches, project)
	s.mu.Unlock()
}

func (s *Supervisor) SetDesired(project, state string) {
	s.mu.Lock()
	s.desired[project] = state
	s.mu.Unlock()
}

func (s *Supervisor) Run() {
	for {
		if s.root.Err() != nil {
			return
		}
		cli, err := client.NewClientWithOpts(client.FromEnv, client.WithAPIVersionNegotiation())
		if err != nil {
			slog.Error("docker", "err", err)
			if !sleep(s.root, 3*time.Second) {
				return
			}
			continue
		}
		s.mu.Lock()
		s.cli = cli
		s.mu.Unlock()
		connCtx, cancel := context.WithCancel(s.root)
		s.refreshAll(connCtx)
		s.fireChange()
		go s.statsLoop(connCtx)
		err = s.watchEvents(connCtx, cli)
		cancel()
		s.mu.Lock()
		s.cli = nil
		s.mu.Unlock()
		_ = cli.Close()
		if err != nil && s.root.Err() == nil {
			slog.Error("docker events", "err", err)
		}
		if !sleep(s.root, 2*time.Second) {
			return
		}
	}
}

func (s *Supervisor) watchEvents(ctx context.Context, cli *client.Client) error {
	msgs, errs := cli.Events(ctx, events.ListOptions{})
	for {
		select {
		case <-ctx.Done():
			return ctx.Err()
		case err := <-errs:
			if err == nil {
				return fmt.Errorf("docker events closed")
			}
			return err
		case msg, ok := <-msgs:
			if !ok {
				return fmt.Errorf("docker events closed")
			}
			s.handleEvent(msg)
		}
	}
}

func (s *Supervisor) handleEvent(msg events.Message) {
	if msg.Type != events.ContainerEventType {
		return
	}
	project := msg.Actor.Attributes["com.docker.compose.project"]
	service := msg.Actor.Attributes["com.docker.compose.service"]
	if project == "" || service == "" || !s.known(project) {
		return
	}
	status := ""
	switch msg.Action {
	case "start", "restart":
		status = "running"
	case "die", "stop", "kill", "oom":
		status = "exited"
	case "destroy":
		status = "missing"
	default:
		if strings.HasPrefix(string(msg.Action), "health_status") {
			return
		}
		return
	}
	s.mu.Lock()
	bucket := s.ensure(project)
	cur := bucket[service]
	if cur == nil {
		cur = &Status{}
		bucket[service] = cur
	}
	cur.Status = status
	if status == "running" {
		cur.ContainerID = msg.Actor.ID
	}
	if status == "missing" {
		cur.ContainerID = ""
	}
	desired := s.desired[project]
	mute := time.Now().Before(s.muteUntil[project])
	last := s.crashed[project+"/"+service]
	s.mu.Unlock()
	if status == "exited" && desired == "running" && !mute && time.Since(last) > time.Minute {
		s.mu.Lock()
		s.crashed[project+"/"+service] = time.Now()
		s.mu.Unlock()
		if s.OnCrash != nil {
			s.OnCrash(project, service)
		}
	}
	s.fireChange()
}

func (s *Supervisor) known(project string) bool {
	s.mu.Lock()
	defer s.mu.Unlock()
	_, ok := s.configured[project]
	return ok
}

func (s *Supervisor) ensure(project string) map[string]*Status {
	if s.state[project] == nil {
		s.state[project] = map[string]*Status{}
	}
	return s.state[project]
}

func (s *Supervisor) Overlay(stacks []model.Stack) []model.Stack {
	s.mu.Lock()
	defer s.mu.Unlock()
	out := make([]model.Stack, len(stacks))
	for i, st := range stacks {
		out[i] = st
		out[i].Services = append([]model.Service(nil), st.Services...)
		bucket := s.state[st.Name]
		for j, svc := range out[i].Services {
			if bucket == nil {
				out[i].Services[j].Status = "missing"
				continue
			}
			if cur := bucket[svc.Name]; cur != nil {
				out[i].Services[j].Status = cur.Status
				out[i].Services[j].CPU = cur.CPU
				out[i].Services[j].Memory = cur.Memory
				out[i].Services[j].MemoryLimit = cur.MemoryLimit
				out[i].Services[j].ContainerID = cur.ContainerID
				if cur.HostPort > 0 {
					out[i].Services[j].HostPort = cur.HostPort
				}
			} else if out[i].Services[j].Status == "" {
				out[i].Services[j].Status = "missing"
			}
		}
	}
	return out
}

func (s *Supervisor) ContainerID(project, service string) string {
	s.mu.Lock()
	defer s.mu.Unlock()
	if cur := s.state[project][service]; cur != nil {
		return cur.ContainerID
	}
	return ""
}

func (s *Supervisor) Apply(project, dir, action string) error {
	lock := s.mutex(project)
	lock.Lock()
	defer lock.Unlock()
	args, timeout, err := actionArgs(action)
	if err != nil {
		return err
	}
	file, err := FindCompose(dir)
	if err != nil {
		return err
	}
	s.mu.Lock()
	s.muteUntil[project] = time.Now().Add(45 * time.Second)
	s.mu.Unlock()
	ctx, cancel := context.WithTimeout(context.Background(), timeout)
	defer cancel()
	applyErr := s.compose(ctx, project, dir, file, args)
	if applyErr != nil && (action == "start" || action == "rebuild") {
		// A container name held by an unmanaged container (e.g. one created by
		// the legacy panel) blocks compose. Replace it and retry once — this is
		// the cutover from the legacy panel. Compose-managed conflicts are
		// reported untouched.
		if name := conflictName(applyErr.Error()); name != "" {
			if rmErr := s.removeUnmanaged(name); rmErr == nil {
				applyErr = s.compose(ctx, project, dir, file, args)
			} else {
				applyErr = fmt.Errorf("%s (could not replace %s: %v)", applyErr, name, rmErr)
			}
		}
	}
	if applyErr != nil {
		s.refreshProject(context.Background(), project)
		s.fireChange()
		return applyErr
	}
	s.mark(project, action)
	s.refreshProject(context.Background(), project)
	s.fireChange()
	return nil
}

var conflictRe = regexp.MustCompile(`The container name "/([^"]+)" is already in use by container`)

// conflictName extracts the container name a compose up failed on, if any.
func conflictName(errText string) string {
	m := conflictRe.FindStringSubmatch(errText)
	if len(m) < 2 {
		return ""
	}
	return m[1]
}

// removeUnmanaged force-removes a container blocking a compose name, but only
// when it is not managed by any compose project (e.g. legacy-panel containers).
func (s *Supervisor) removeUnmanaged(name string) error {
	ctx, cancel := context.WithTimeout(s.root, 30*time.Second)
	defer cancel()
	list, err := s.cli.ContainerList(ctx, container.ListOptions{
		All:     true,
		Filters: filters.NewArgs(filters.Arg("name", name)),
	})
	if err != nil {
		return err
	}
	full := "/" + name
	var target *types.Container
	for i := range list {
		for _, n := range list[i].Names {
			if n == full {
				target = &list[i]
				break
			}
		}
	}
	if target == nil {
		return fmt.Errorf("container %s not found", name)
	}
	if proj := target.Labels["com.docker.compose.project"]; proj != "" {
		return fmt.Errorf("container %s belongs to compose project %s", name, proj)
	}
	return s.cli.ContainerRemove(ctx, target.ID, container.RemoveOptions{Force: true})
}

func (s *Supervisor) Down(project, dir string) error {
	file, err := FindCompose(dir)
	if err != nil {
		return nil
	}
	ctx, cancel := context.WithTimeout(context.Background(), 2*time.Minute)
	defer cancel()
	err = s.compose(ctx, project, dir, file, []string{"down", "--remove-orphans"})
	s.Forget(project)
	return err
}

func actionArgs(action string) ([]string, time.Duration, error) {
	switch action {
	case "start":
		return []string{"up", "-d", "--remove-orphans"}, 4 * time.Minute, nil
	case "stop":
		return []string{"stop"}, time.Minute, nil
	case "restart":
		return []string{"restart"}, 2 * time.Minute, nil
	case "rebuild":
		return []string{"up", "-d", "--build", "--remove-orphans"}, 15 * time.Minute, nil
	default:
		return nil, 0, fmt.Errorf("unknown action %s", action)
	}
}

func (s *Supervisor) mark(project, action string) {
	status := "running"
	if action == "stop" {
		status = "exited"
	}
	s.mu.Lock()
	defer s.mu.Unlock()
	bucket := s.ensure(project)
	names := s.configured[project]
	if len(names) == 0 {
		for name := range bucket {
			names = append(names, name)
		}
	}
	for _, name := range names {
		cur := bucket[name]
		if cur == nil {
			cur = &Status{}
			bucket[name] = cur
		}
		cur.Status = status
	}
}

func (s *Supervisor) compose(ctx context.Context, project, dir, file string, args []string) error {
	full := append([]string{"compose", "-p", project, "--project-directory", dir, "-f", file}, args...)
	cmd := exec.CommandContext(ctx, "docker", full...)
	stdout, err := cmd.StdoutPipe()
	if err != nil {
		return err
	}
	stderr, err := cmd.StderrPipe()
	if err != nil {
		return err
	}
	if err := cmd.Start(); err != nil {
		return err
	}
	var tail strings.Builder
	var mu sync.Mutex
	done := make(chan struct{})
	go func() {
		defer close(done)
		s.scanLines(project, stdout, &tail, &mu)
	}()
	s.scanLines(project, stderr, &tail, &mu)
	<-done
	err = cmd.Wait()
	if err != nil {
		text := strings.TrimSpace(tail.String())
		if text == "" {
			return err
		}
		return fmt.Errorf("%s", text)
	}
	return nil
}

func (s *Supervisor) scanLines(project string, r io.Reader, tail *strings.Builder, mu *sync.Mutex) {
	sc := bufio.NewScanner(r)
	sc.Buffer(make([]byte, 64*1024), 1024*1024)
	for sc.Scan() {
		line := sc.Text()
		s.hub.PublishLog(project, "compose", line)
		mu.Lock()
		if tail.Len() < 8000 {
			tail.WriteString(line)
			tail.WriteByte('\n')
		}
		mu.Unlock()
	}
}

func (s *Supervisor) mutex(project string) *sync.Mutex {
	s.mu.Lock()
	defer s.mu.Unlock()
	m := s.locks[project]
	if m == nil {
		m = &sync.Mutex{}
		s.locks[project] = m
	}
	return m
}

// FindCompose returns the compose file used for a stack directory.
func FindCompose(dir string) (string, error) {
	for _, name := range []string{"compose.yaml", "compose.yml", "docker-compose.yaml", "docker-compose.yml"} {
		path := filepath.Join(dir, name)
		if st, err := os.Stat(path); err == nil && !st.IsDir() {
			return path, nil
		}
	}
	return "", fmt.Errorf("compose file not found in %s", dir)
}

func (s *Supervisor) client() *client.Client {
	s.mu.Lock()
	defer s.mu.Unlock()
	return s.cli
}

func (s *Supervisor) refreshAll(ctx context.Context) {
	cli := s.client()
	if cli == nil {
		return
	}
	list, err := cli.ContainerList(ctx, container.ListOptions{All: true})
	if err != nil {
		slog.Error("docker ps", "err", err)
		return
	}
	grouped := map[string][]types.Container{}
	for _, c := range list {
		project := c.Labels["com.docker.compose.project"]
		if project != "" && s.known(project) {
			grouped[project] = append(grouped[project], c)
		}
	}
	s.mu.Lock()
	for project := range s.configured {
		s.applyContainers(project, grouped[project])
	}
	s.mu.Unlock()
}

func (s *Supervisor) refreshProject(ctx context.Context, project string) {
	cli := s.client()
	if cli == nil {
		return
	}
	f := filters.NewArgs(filters.Arg("label", "com.docker.compose.project="+project))
	list, err := cli.ContainerList(ctx, container.ListOptions{All: true, Filters: f})
	if err != nil {
		return
	}
	s.mu.Lock()
	s.applyContainers(project, list)
	s.mu.Unlock()
}

func (s *Supervisor) applyContainers(project string, list []types.Container) {
	bucket := s.ensure(project)
	seen := map[string]bool{}
	for _, c := range list {
		service := c.Labels["com.docker.compose.service"]
		if service == "" {
			continue
		}
		seen[service] = true
		cur := bucket[service]
		if cur == nil {
			cur = &Status{}
			bucket[service] = cur
		}
		cur.ContainerID = c.ID
		cur.Status = c.State
		if c.State == "" {
			cur.Status = "missing"
		}
		for _, p := range c.Ports {
			if p.PublicPort > 0 {
				cur.HostPort = int(p.PublicPort)
				break
			}
		}
	}
	for name, cur := range bucket {
		if !seen[name] {
			cur.Status = "missing"
			cur.ContainerID = ""
		}
	}
}

func (s *Supervisor) statsLoop(ctx context.Context) {
	tick := time.NewTicker(5 * time.Second)
	defer tick.Stop()
	for {
		select {
		case <-ctx.Done():
			return
		case <-tick.C:
			s.sampleStats(ctx)
			s.fireChange()
		}
	}
}

func (s *Supervisor) sampleStats(ctx context.Context) {
	cli := s.client()
	if cli == nil {
		return
	}
	type item struct{ project, service, id string }
	var items []item
	s.mu.Lock()
	for project, bucket := range s.state {
		for service, cur := range bucket {
			if cur.Status == "running" && cur.ContainerID != "" {
				items = append(items, item{project, service, cur.ContainerID})
			}
		}
	}
	s.mu.Unlock()
	sem := make(chan struct{}, 4)
	var wg sync.WaitGroup
	for _, it := range items {
		wg.Add(1)
		sem <- struct{}{}
		go func(it item) {
			defer wg.Done()
			defer func() { <-sem }()
			cpu, mem, limit := readStats(ctx, cli, it.id)
			s.mu.Lock()
			if cur := s.state[it.project][it.service]; cur != nil && cur.ContainerID == it.id {
				cur.CPU = cpu
				cur.Memory = mem
				cur.MemoryLimit = limit
			}
			s.mu.Unlock()
		}(it)
	}
	wg.Wait()
}

func readStats(ctx context.Context, cli *client.Client, id string) (float64, uint64, uint64) {
	resp, err := cli.ContainerStats(ctx, id, false)
	if err != nil {
		return 0, 0, 0
	}
	defer resp.Body.Close()
	var raw statsJSON
	if err := json.NewDecoder(resp.Body).Decode(&raw); err != nil {
		return 0, 0, 0
	}
	cpuDelta := float64(raw.CPUStats.CPUUsage.TotalUsage - raw.PreCPUStats.CPUUsage.TotalUsage)
	sysDelta := float64(raw.CPUStats.SystemUsage - raw.PreCPUStats.SystemUsage)
	online := float64(raw.CPUStats.OnlineCPUs)
	if online == 0 {
		online = float64(len(raw.CPUStats.CPUUsage.PercpuUsage))
	}
	cpu := 0.0
	if sysDelta > 0 && cpuDelta > 0 && online > 0 {
		cpu = (cpuDelta / sysDelta) * online * 100
	}
	return cpu, raw.MemoryStats.Usage, raw.MemoryStats.Limit
}

type statsJSON struct {
	CPUStats struct {
		CPUUsage struct {
			TotalUsage  uint64   `json:"total_usage"`
			PercpuUsage []uint64 `json:"percpu_usage"`
		} `json:"cpu_usage"`
		SystemUsage uint64 `json:"system_cpu_usage"`
		OnlineCPUs  uint32 `json:"online_cpus"`
	} `json:"cpu_stats"`
	PreCPUStats struct {
		CPUUsage struct {
			TotalUsage uint64 `json:"total_usage"`
		} `json:"cpu_usage"`
		SystemUsage uint64 `json:"system_cpu_usage"`
	} `json:"precpu_stats"`
	MemoryStats struct {
		Usage uint64 `json:"usage"`
		Limit uint64 `json:"limit"`
	} `json:"memory_stats"`
}

func (s *Supervisor) Watch(project string) func() {
	s.mu.Lock()
	s.watches[project]++
	start := s.watches[project] == 1
	var ctx context.Context
	if start {
		var cancel context.CancelFunc
		ctx, cancel = context.WithCancel(s.root)
		s.watchCancel[project] = cancel
	}
	s.mu.Unlock()
	if start {
		go s.follow(ctx, project)
	}
	return func() { s.unwatch(project) }
}

func (s *Supervisor) unwatch(project string) {
	s.mu.Lock()
	defer s.mu.Unlock()
	s.watches[project]--
	if s.watches[project] <= 0 {
		s.watches[project] = 0
		if cancel := s.watchCancel[project]; cancel != nil {
			cancel()
		}
		delete(s.watchCancel, project)
	}
}

func (s *Supervisor) follow(ctx context.Context, project string) {
	type run struct {
		id     string
		cancel context.CancelFunc
	}
	active := map[string]run{}
	ended := make(chan string, 16)
	defer func() {
		for _, r := range active {
			r.cancel()
		}
	}()
	tick := time.NewTicker(time.Second)
	defer tick.Stop()
	attach := func(name, id string) {
		if cur, ok := active[name]; ok {
			cur.cancel()
		}
		cctx, cancel := context.WithCancel(ctx)
		active[name] = run{id: id, cancel: cancel}
		go func(name, id string) {
			s.streamLogs(cctx, project, name, id)
			select {
			case ended <- name + "\x00" + id:
			case <-cctx.Done():
			}
		}(name, id)
	}
	for {
		select {
		case <-ctx.Done():
			return
		case key := <-ended:
			name, id, _ := strings.Cut(key, "\x00")
			if cur, ok := active[name]; ok && cur.id == id {
				delete(active, name)
			}
		case <-tick.C:
			names := s.serviceNames(project)
			keep := map[string]bool{}
			for _, name := range names {
				keep[name] = true
				id := s.ContainerID(project, name)
				if id == "" {
					if cur, ok := active[name]; ok {
						cur.cancel()
						delete(active, name)
					}
					continue
				}
				if cur, ok := active[name]; ok && cur.id == id {
					continue
				}
				attach(name, id)
			}
			for name, cur := range active {
				if !keep[name] {
					cur.cancel()
					delete(active, name)
				}
			}
		}
	}
}

func (s *Supervisor) serviceNames(project string) []string {
	s.mu.Lock()
	defer s.mu.Unlock()
	seen := map[string]bool{}
	var names []string
	for _, name := range s.configured[project] {
		if !seen[name] {
			seen[name] = true
			names = append(names, name)
		}
	}
	for name := range s.state[project] {
		if !seen[name] {
			seen[name] = true
			names = append(names, name)
		}
	}
	return names
}

func (s *Supervisor) streamLogs(ctx context.Context, project, service, id string) {
	cli := s.client()
	if cli == nil {
		return
	}
	reader, err := cli.ContainerLogs(ctx, id, container.LogsOptions{
		ShowStdout: true,
		ShowStderr: true,
		Follow:     true,
		Tail:       "200",
	})
	if err != nil {
		s.hub.PublishLog(project, service, err.Error())
		return
	}
	defer reader.Close()
	out := &lineWriter{send: func(line string) {
		s.rememberLogLine(project, service, line)
		s.hub.PublishLog(project, service, line)
	}}
	_, _ = stdcopy.StdCopy(out, out, reader)
}

const logTailCap = 200

func (s *Supervisor) rememberLogLine(project, service, line string) {
	key := project + "\x00" + service
	s.mu.Lock()
	defer s.mu.Unlock()
	buf := append(s.logTail[key], line)
	if len(buf) > logTailCap {
		buf = buf[len(buf)-logTailCap:]
	}
	s.logTail[key] = buf
}

// LogTail returns the most recent buffered log lines for a service, so that
// clients subscribing to an already-watched stack still get a replay.
func (s *Supervisor) LogTail(project, service string) []string {
	s.mu.Lock()
	defer s.mu.Unlock()
	buf := s.logTail[project+"\x00"+service]
	out := make([]string, len(buf))
	copy(out, buf)
	return out
}

func (s *Supervisor) Exec(ctx context.Context, project, service, command string) (string, int, error) {
	id := s.ContainerID(project, service)
	if id == "" {
		return "", 1, fmt.Errorf("%s is not running", service)
	}
	cli := s.client()
	if cli == nil {
		return "", 1, fmt.Errorf("docker unavailable")
	}
	created, err := cli.ContainerExecCreate(ctx, id, container.ExecOptions{
		AttachStdout: true,
		AttachStderr: true,
		Cmd:          []string{"sh", "-c", command},
	})
	if err != nil {
		return "", 1, err
	}
	attach, err := cli.ContainerExecAttach(ctx, created.ID, container.ExecAttachOptions{})
	if err != nil {
		return "", 1, err
	}
	defer attach.Close()
	var stdout, stderr strings.Builder
	_, _ = stdcopy.StdCopy(&limitWriter{w: &stdout, n: 64 * 1024}, &limitWriter{w: &stderr, n: 16 * 1024}, attach.Reader)
	inspect, err := cli.ContainerExecInspect(ctx, created.ID)
	code := 1
	if err == nil {
		code = inspect.ExitCode
	}
	text := stdout.String() + stderr.String()
	return text, code, nil
}

func (s *Supervisor) Shell(ctx context.Context, project, service string) (types.HijackedResponse, error) {
	id := s.ContainerID(project, service)
	if id == "" {
		return types.HijackedResponse{}, fmt.Errorf("%s is not running", service)
	}
	cli := s.client()
	if cli == nil {
		return types.HijackedResponse{}, fmt.Errorf("docker unavailable")
	}
	created, err := cli.ContainerExecCreate(ctx, id, container.ExecOptions{
		AttachStdin:  true,
		AttachStdout: true,
		AttachStderr: true,
		Tty:          true,
		Cmd:          []string{"sh"},
	})
	if err != nil {
		return types.HijackedResponse{}, err
	}
	return cli.ContainerExecAttach(ctx, created.ID, container.ExecAttachOptions{Tty: true})
}

func (s *Supervisor) fireChange() {
	if s.OnChange != nil {
		s.OnChange()
	}
}

type lineWriter struct {
	send func(string)
	buf  string
}

func (w *lineWriter) Write(p []byte) (int, error) {
	w.buf += string(p)
	for {
		i := strings.IndexByte(w.buf, '\n')
		if i < 0 {
			break
		}
		line := strings.TrimRight(w.buf[:i], "\r")
		w.buf = w.buf[i+1:]
		if line != "" {
			w.send(line)
		}
	}
	return len(p), nil
}

type limitWriter struct {
	w io.Writer
	n int
}

func (w *limitWriter) Write(p []byte) (int, error) {
	if w.n <= 0 {
		return len(p), nil
	}
	if len(p) > w.n {
		p = p[:w.n]
	}
	n, err := w.w.Write(p)
	w.n -= n
	if err != nil {
		return n, err
	}
	return len(p), nil
}

func sleep(ctx context.Context, d time.Duration) bool {
	t := time.NewTimer(d)
	defer t.Stop()
	select {
	case <-ctx.Done():
		return false
	case <-t.C:
		return true
	}
}
