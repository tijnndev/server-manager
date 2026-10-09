FROM node:22-alpine AS ui
WORKDIR /web
COPY frontend/package.json frontend/package-lock.json ./
RUN npm ci
COPY frontend/ ./
RUN npm run build

FROM golang:1.26-alpine AS build
WORKDIR /src
COPY backend/go.mod backend/go.sum ./
RUN go mod download
COPY backend/ ./
RUN CGO_ENABLED=0 go build -o /server-manager ./cmd/server-manager

FROM docker:27-cli
RUN apk add --no-cache ca-certificates nginx certbot certbot-nginx git openssh-client
# The panel validates and reloads the HOST nginx via bind mounts (compose.nginx.yaml).
# This container config includes sites-enabled so `nginx -t` checks the real configs,
# and its pid path resolves to the host nginx pid file (pid: "host").
RUN printf 'pid /run/nginx.pid;\nevents {}\nhttp {\n\tinclude /etc/nginx/mime.types;\n\tinclude /etc/nginx/sites-enabled/*;\n}\n' > /etc/nginx/nginx.conf
COPY --from=build /server-manager /usr/local/bin/server-manager
COPY --from=ui /web/dist /app/frontend/dist
COPY templates /app/templates
WORKDIR /app
EXPOSE 7101
ENTRYPOINT ["/usr/local/bin/server-manager"]
