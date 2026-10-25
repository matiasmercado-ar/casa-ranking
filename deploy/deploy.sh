#!/usr/bin/env bash
# Sync the working tree to the LXC and (re)build + restart the container.
# Usage: deploy/deploy.sh   (reads deploy/deploy.env)
set -euo pipefail
cd "$(dirname "$0")/.."
source deploy/deploy.env
HOST_IP=${CT_IP%/*}
TARGET=root@$HOST_IP

rsync -az --delete --exclude .git --exclude .venv --exclude data --exclude .env \
  --exclude 'deploy/deploy.env' --exclude __pycache__ --exclude .pytest_cache ./ "$TARGET:/opt/casa-ranking/"
# Consistent SQLite snapshot before the new version (and any migration) starts; keep the last 10.
ssh "$TARGET" 'cd /opt/casa-ranking && mkdir -p data/backups && chown 10001 data/backups && \
  docker compose exec -T casa-ranking python -c "import sqlite3, time; s = sqlite3.connect(\"/data/casa-ranking.db\"); \
d = sqlite3.connect(time.strftime(\"/data/backups/casa-ranking-%Y%m%d-%H%M%S.db\")); s.backup(d)" \
  && echo "DB backup: $(ls -t data/backups | head -1)" || echo "DB backup FAILED or no running container"; \
  ls -t data/backups/*.db 2>/dev/null | tail -n +11 | xargs -r rm --'
ssh "$TARGET" "cd /opt/casa-ranking && touch .env && \
  (grep -q '^PORT=' .env || echo 'PORT=$APP_PORT' >> .env) && \
  docker compose up -d --build --remove-orphans && docker image prune -f >/dev/null"

for i in $(seq 1 30); do
  if curl -fsS "http://$HOST_IP:$APP_PORT/healthz"; then echo; echo "Up: http://$HOST_IP:$APP_PORT/"; exit 0; fi
  sleep 2
done
echo "Health check failed" >&2; ssh "$TARGET" "cd /opt/casa-ranking && docker compose logs --tail 50" >&2; exit 1
