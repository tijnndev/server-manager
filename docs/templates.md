# Stack templates

Templates are YAML files in `templates/` (override with `TEMPLATES_DIR`). Each
describes a set of compose services that the panel can render into a new
stack. Admins can edit or replace any template from the **Templates** page;
edits are stored in the database and take precedence over the files on disk.

## Template schema

```yaml
id: nodejs            # unique id, used in the API and URL
name: Node.js         # display name
description: Run a Node.js app from main.js or package.json
dockerfile: |         # optional; written to the stack dir as Dockerfile
  FROM node:22
  ...
fields:               # optional; form fields shown at stack creation
  - key: script       # see "Field keys" below
    label: Start script
    default: node main.js
services:
  - name: app         # service name (compose service)
    image: node:22    # image (omit when build: true)
    build: false      # build from the template Dockerfile
    script: ""        # command override (sh -c)
    command: []       # explicit command (used when no script)
    workdir: /app
    internalPort: 3000# container port; a host port is auto-allocated
    http: true        # mark as an HTTP service (publishable domain)
    logs: true        # stream logs to the UI
    shell: true       # allow the per-service shell
    volumes: [".:/app"]
    env:
      SOME_VAR: value
    dependsOn: [other]
volumes:              # optional top-level compose volumes
  data: {}
```

### Field keys

A field's `key` controls what the value overrides at creation time:

- `script` — the start command for the (single) service.
- `script:<service>` — the start command for a specific service.
- `env:<service>:<VAR>` — set environment variable `VAR` on `<service>`.

Only keys with the `script:` or `env:` prefixes (or the bare `script`) are
accepted from the creation form; everything else is ignored.

### Ports

Any service with `internalPort` gets a host port allocated automatically from
a monotonically increasing counter (persisted in the database), so stacks
never collide. The allocated host port is shown in the UI and used as the
upstream when publishing a domain.

## Built-in templates

| id            | Name           | Notes                                                        |
| ------------- | -------------- | ------------------------------------------------------------ |
| `nodejs`      | Node.js        | `node:22`, runs `node main.js` (editable start script).      |
| `go`          | Go             | `golang:1.26`, runs `go run .`.                              |
| `python`      | Python         | `python:3.12`, installs requirements then runs `python main.py`. |
| `php`         | PHP            | `nginx:alpine` + `php:8.3-fpm`, shared volume.               |
| `static`      | Static site    | `nginx:alpine` serving the stack dir read-only.              |
| `vite-dev`    | Vite dev       | `node:22` dev server with HMR on port 5173.                  |
| `vite-static` | Vite static    | Builds with `node:22`, serves output with `nginx:alpine`.    |
| `build-vite`  | Vite build     | Multi-stage Dockerfile (Node 22 build → httpd) for Vite apps.|
| `mariadb`     | MariaDB        | `mariadb:11` with a persistent volume and root password field. |
| `minecraft`   | Minecraft      | `itzg/minecraft-server` with persistent world data.          |

## Adding a template

1. Drop a new `.yaml` file in `templates/` (or add it via the Templates page).
2. Restart the panel, or reload from the Templates page — the catalog is
   re-read on startup and on every save/reset.
3. The template appears in the "New stack" dialog.

A template must have a non-empty `id`, `name` and at least one service with a
unique, non-empty name, or it will be rejected on load.

## Custom compose

You don't need a template. "New stack" also accepts a raw compose file (paste
or upload, with optional extra files). The panel parses it to discover
services and ports, then runs it exactly as written.