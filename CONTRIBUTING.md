# Contributing

Thanks for considering a contribution to server-manager. This project is a
single-binary Go backend plus a React frontend, deployed as one Docker
container. Keep that shape in mind when proposing changes.

## Ground rules

- Read the [Code of Conduct](.github/CODE_OF_CONDUCT.md).
- One concern per pull request. Small, focused diffs are easier to review.
- Match the existing style. The backend is plain Go with no framework; the
  frontend is React + TypeScript with no component library.
- No new runtime dependencies without a good reason. The backend deliberately
  keeps a small dependency surface.

## Setting up

```bash
# Backend (Go 1.26+)
cd backend
go build ./...
go test ./...

# Frontend (Node 22+)
cd frontend
npm ci
npm run build     # typecheck + production build
npm run dev       # dev server on :5174, proxies /api to :7101
```

The backend reads a `.env` file (or `../.env`) for configuration; see
[docs/configuration.md](docs/configuration.md).

## Testing

- Backend: `go test ./...` from `backend/`. There are unit tests for the
  template renderer, compose parsing, path safety, nginx rendering and
  runtime actions.
- Frontend: `npm run build` runs the TypeScript compiler; there is no test
  runner configured. Verify UI changes by running `npm run dev` against a
  local backend.

## Pull request checklist

- [ ] `go build ./...` and `go test ./...` pass
- [ ] `npm run build` passes (typecheck + build)
- [ ] New configuration options are documented in `docs/configuration.md`
      and added to `.env.example`
- [ ] New API endpoints are documented in `docs/api.md`
- [ ] New templates are documented in `docs/templates.md`
- [ ] No secrets, generated artifacts or local data committed (see `.gitignore`)

## Where things live

| Area            | Location                          |
| --------------- | --------------------------------- |
| HTTP routes     | `backend/internal/api/routes.go`  |
| Supervisor      | `backend/internal/runtime/`       |
| nginx / TLS / CF| `backend/internal/domain/`        |
| Templates       | `templates/` (YAML)               |
| DB schema       | `backend/internal/db/db.go`       |
| Frontend pages  | `frontend/src/pages/`             |
| API client      | `frontend/src/api.ts`             |
| Deploy / migrate| `deploy/`                         |

## Reporting issues

Use the issue tracker. For bugs, include:

- The output of `docker compose ps` and the relevant panel logs
- The compose file of the affected stack (redact secrets)
- Steps to reproduce

For security issues, do **not** open a public issue — see
[SECURITY.md](SECURITY.md).