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
RUN apk add --no-cache ca-certificates nginx certbot certbot-nginx
COPY --from=build /server-manager /usr/local/bin/server-manager
COPY --from=ui /web/dist /app/frontend/dist
COPY templates /app/templates
WORKDIR /app
EXPOSE 7101
ENTRYPOINT ["/usr/local/bin/server-manager"]
