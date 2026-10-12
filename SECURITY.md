# Security Policy

## Supported versions

The latest release on the `remake` branch. Older commits are not supported.

## Reporting a vulnerability

Please **do not** open a public issue for security vulnerabilities.

Report them by emailing the maintainer (see the repository owner) with:

- A description of the vulnerability and its impact
- Steps or a proof of concept to reproduce it
- Any suggested mitigation

I will acknowledge receipt within 48 hours and aim to provide a fix or a
mitigation plan within a reasonable timeframe.

## Scope

The panel is a privileged component by design: it holds the Docker socket,
writes host nginx configs, runs certbot and executes commands inside
containers. Threats that require access to the host or to the Docker socket
are out of scope.

In-scope areas include, but are not limited to:

- Authentication and session handling (`backend/internal/auth`)
- Authorization / access control on API routes (`backend/internal/api`)
- Path traversal in the file API (`backend/internal/safe`)
- Command injection in git, exec and compose handling
- Unsafe handling of user-supplied hostnames, compose files or template YAML

## General guidance

- Set a strong `ADMIN_PASSWORD` and change the defaults in `.env.example`.
- Run the panel behind TLS and set `COOKIE_SECURE=1` in production.
- Keep the host, Docker, nginx and certbot up to date.
- Restrict network access to port 7101 if you do not need it publicly.