#!/bin/bash
# Certbot deploy hook.
# ln -sf /etc/server-manager/roundcube/certbot-deploy-mailserver.sh \
#        /etc/letsencrypt/renewal-hooks/deploy/mailserver.sh

set -euo pipefail
/etc/server-manager/roundcube/sync-mail-certs.sh
