# Mail setup

The default `compose.yaml` runs a
[docker-mailserver](https://github.com/docker-mailserver/docker-mailserver)
container (`mailserver`) and a [Roundcube](https://roundcube.net/) webmail
container (`roundcube`). The panel's **Mail** page manages accounts on the
mailserver by running `docker exec mailserver setup email …`.

## Ports

| Port | Service            |
| ---- | ------------------ |
| 25   | SMTP               |
| 143  | IMAP               |
| 465  | SMTPS              |
| 587  | SMTP submission    |
| 993  | IMAPS              |
| 8080 | Roundcube webmail  |

## Configuration

Set these in `.env` (see [configuration.md](configuration.md)):

- `MAIL_HOSTNAME` — the FQDN of your mail server, e.g. `mail.example.com`.
  This must be the hostname clients connect to and must match your DNS.
- `MAIL_DOMAIN` — the domain you send/receive for, e.g. `example.com`.
- `POSTMASTER_ADDRESS` / `POSTMASTER_PASSWORD` — the postmaster account,
  created automatically on first start. **Change the password.**

The mailserver uses a self-signed certificate by default (`SSL_TYPE:
self-signed`). The entrypoint generates one for `MAIL_HOSTNAME` if it is not
already present. For a trusted setup, point `MAIL_HOSTNAME` at a real domain
and let your reverse proxy / ACME handle TLS in front, or configure a real
certificate in the mailserver's `config` volume.

## DNS requirements

For mail to work with external providers you need:

- An **A** (or **MX**) record for `MAIL_HOSTNAME` pointing at your server.
- An **MX** record for `MAIL_DOMAIN` pointing at `MAIL_HOSTNAME`.
- **SPF**, **DKIM** and **DMARC** records for `MAIL_DOMAIN`. docker-mailserver
  generates a DKIM key under `roundcube/config/opendkim/keys/…` once started;
  publish its public key as a TXT record.

## Managing accounts

Use the **Mail** page in the panel to list, create, delete accounts and
change passwords. Each action shells out to the mailserver's `setup` tool, so
the `mailserver` container must be running.

## Data

Mail data, state and logs are stored under `roundcube/` (gitignored):

- `roundcube/maildata` — mailboxes
- `roundcube/mailstate` — IMAP state
- `roundcube/maillogs` — mail logs
- `roundcube/config` — generated config (certs, DKIM, accounts)

Back these up if you need to preserve mail.

## Disabling mail

If you don't want mail, remove the `mailserver` and `roundcube` services from
`compose.yaml` and the related `roundcube/` volumes. The panel's Mail page
will report that the container is not running; everything else works
unchanged.