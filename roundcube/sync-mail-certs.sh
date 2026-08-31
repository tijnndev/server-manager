#!/bin/bash
set -euo pipefail

DEST_DIR=/etc/server-manager/mail-certs
LIVE_DIR=/etc/letsencrypt/live/mail.tijnn.dev

mkdir -p "$DEST_DIR"
install -m 644 "$LIVE_DIR/fullchain.pem" "$DEST_DIR/fullchain.pem"
install -m 600 "$LIVE_DIR/privkey.pem" "$DEST_DIR/privkey.pem"
openssl x509 -in "$DEST_DIR/fullchain.pem" -noout -issuer -dates -subject

if docker ps -q --filter name=^mailserver$ | grep -q .; then
  docker restart mailserver
fi
