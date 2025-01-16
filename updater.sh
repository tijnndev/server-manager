#!/bin/bash
export PATH="/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin"
cd /etc/server-manager
/usr/bin/git status
/usr/bin/git pull -v
# pip install -r requirements.txt
# alembic upgrade --autogenerate head
/usr/bin/systemctl restart server-manager