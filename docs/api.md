# HTTP API reference

All endpoints are served by the panel on `:7101`. Authentication is via the
`sm_session` cookie (set by `/api/auth/login`). Mutating requests
(POST/PUT/PATCH/DELETE) under `/api/` must include the `X-SM-Request: 1`
header.

Roles: `admin` can do everything; `user` can manage stacks they own or have
been granted as a sub-user.

Errors are returned as `{"error": "message"}` with an appropriate status code.

## Auth

| Method | Path             | Description                          |
| ------ | ---------------- | ------------------------------------ |
| POST   | `/api/auth/login`| Body `{username, password}` → sets session cookie, returns the user. |
| POST   | `/api/auth/logout`| Clears the session.                 |
| GET    | `/api/auth/me`   | Current user.                        |

## Stacks

| Method | Path                              | Description |
| ------ | --------------------------------- | ----------- |
| GET    | `/api/stacks`                     | List stacks visible to the user (with live status overlay). |
| POST   | `/api/stacks`                     | Create a stack. JSON body: `{name, templateId, description, overrides}` **or** `{name, description, compose}`. Also accepts `multipart/form-data` with `name`, `description`, `compose`, `composeFile` and `files[]`. |
| GET    | `/api/stacks/{name}`              | Stack detail + its domains.          |
| PATCH  | `/api/stacks/{name}`              | Update description. Body `{description}`. |
| DELETE | `/api/stacks/{name}`              | Stop, remove containers, delete files and DB rows, and clean up domains. |
| POST   | `/api/stacks/{name}/power/{action}`| `action` ∈ `start`, `stop`, `restart`, `rebuild`. |
| POST   | `/api/stacks/{name}/exec`         | Run a command. Body `{service, command}` → `{output, exitCode}`. |
| GET    | `/api/stacks/{name}/shell?service=`| WebSocket to an interactive `sh` in the service container. |

Stack names must match `^[a-z0-9]([a-z0-9-]{0,61}[a-z0-9])?$`.

### Files

Paths are relative to the stack directory and are validated against path
traversal.

| Method | Path                                  | Description |
| ------ | ------------------------------------- | ----------- |
| GET    | `/api/stacks/{name}/files?path=`      | List a directory. |
| GET    | `/api/stacks/{name}/files/content?path=`| Read a file (≤ 1 MiB). |
| PUT    | `/api/stacks/{name}/files/content?path=`| Write a file. Body `{content}`. |
| DELETE | `/api/stacks/{name}/files?path=`      | Delete a file or directory (not the stack root). |
| POST   | `/api/stacks/{name}/files/mkdir`      | Create a directory. Body `{path}`. |
| POST   | `/api/stacks/{name}/files/upload?path=`| Upload a file (multipart `file`, ≤ 32 MiB). |

### Git

| Method | Path                          | Description |
| ------ | ----------------------------- | ----------- |
| GET    | `/api/stacks/{name}/git`      | Repo overview: remote, branch, commit, ahead/behind, local & remote changes. |
| POST   | `/api/stacks/{name}/git/pull` | Fetch + fast-forward pull (stashes local changes if needed). |
| POST   | `/api/stacks/{name}/git/clone`| Clone a repo into the stack. Body `{url}`. |

SSH remotes are used when an SSH key is present (`DATA_DIR/.ssh` or `~/.ssh`);
otherwise GitHub/GitLab SSH URLs are rewritten to HTTPS and a GitHub token
(Settings or `GITHUB_TOKEN`/`GH_TOKEN`) is used for authentication.

### Domains

| Method | Path                                  | Description |
| ------ | ------------------------------------- | ----------- |
| GET    | `/api/stacks/{name}/domains`          | List published domains. |
| POST   | `/api/stacks/{name}/publish`          | Publish. Body `{hostname, service, tls, cloudflare}`. Writes nginx config, validates, reloads, issues a cert (if `tls`), creates a Cloudflare record (if `cloudflare`). Returns `{nginx, tls, cloudflare, warnings}`. |
| DELETE | `/api/stacks/{name}/domains/{hostname}`| Unpublish and remove the DNS record. |

### Schedules

| Method | Path                                   | Description |
| ------ | -------------------------------------- | ----------- |
| GET    | `/api/stacks/{name}/schedules`         | List cron schedules. |
| POST   | `/api/stacks/{name}/schedules`         | Add. Body `{action, cron}`; `action` ∈ `start`, `stop`, `restart`; `cron` is a standard 5-field expression. |
| DELETE | `/api/stacks/{name}/schedules/{id}`    | Remove. |

### Sub-users

| Method | Path                                  | Description |
| ------ | ------------------------------------- | ----------- |
| GET    | `/api/stacks/{name}/subusers`         | List users with access. |
| POST   | `/api/stacks/{name}/subusers`         | Grant access. Body `{username}`. |
| DELETE | `/api/stacks/{name}/subusers/{userId}`| Revoke access. |

## Templates

| Method | Path                    | Description |
| ------ | ----------------------- | ----------- |
| GET    | `/api/templates`        | List templates (with YAML for admins). |
| PUT    | `/api/templates/{id}`   | Save an override. Body `{yaml}`. Admin only. |
| DELETE | `/api/templates/{id}`   | Reset to the on-disk version. Admin only. |

## Activity, settings, users, mail

| Method | Path            | Description |
| ------ | --------------- | ----------- |
| GET    | `/api/activity` | Recent activity for the user's stacks. |
| GET    | `/api/settings` | Get settings. Admin only. |
| PUT    | `/api/settings` | Save settings. Body `{discordWebhook, cloudflareToken, publicIP, acmeEmail, githubToken}`. Admin only. |
| GET    | `/api/users`    | List users. Admin only. |
| POST   | `/api/users`    | Create a user. Body `{username, password, role}`; `role` ∈ `admin`, `user`. Admin only. |
| GET    | `/api/mail`     | List mail accounts. |
| POST   | `/api/mail`     | Create a mail account. Body `{email, password}`. |
| POST   | `/api/mail/delete`| Delete a mail account. Body `{email}`. |
| POST   | `/api/mail/password`| Change a mail password. Body `{email, password}`. |

## WebSocket

`GET /api/ws` — authenticated WebSocket. The server sends:

- `{"type":"state","stacks":[...]}` — full stack list with live status,
  broadcast on any change (debounced 150 ms).
- `{"type":"log","stack","service","line"}` — a log line for a subscribed
  stack.

The client sends `{"type":"subscribe","stack"}` /
`{"type":"unsubscribe","stack"}` to start/stop receiving logs for a stack.
Recent log lines (up to 200 per service) are replayed on subscribe.