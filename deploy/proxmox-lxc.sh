#!/usr/bin/env bash
# One-time: create a Debian LXC on Proxmox with Docker inside, ready for deploy.sh.
# Usage: deploy/proxmox-lxc.sh   (reads deploy/deploy.env)
set -euo pipefail
cd "$(dirname "$0")"
source ./deploy.env
HOST_IP=${CT_IP%/*}
PUBKEY=$(cat "${SSH_PUBKEY/#\~/$HOME}")

ssh "$PVE_HOST" "export LC_ALL=C PATH=\$PATH:/usr/sbin; set -e
  if sudo -n pct status $CTID >/dev/null 2>&1 || sudo -n qm status $CTID >/dev/null 2>&1; then
    echo 'ID $CTID already exists, refusing to touch it' >&2; exit 1
  fi
  echo '$PUBKEY' > /tmp/casa-key.pub
  sudo -n pct create $CTID $CT_TEMPLATE --hostname $CT_NAME --description 'Casa Ranking (docker compose in /opt/casa-ranking)' \
    --cores 1 --memory $CT_MEMORY --swap 512 --rootfs $CT_STORAGE:$CT_DISK \
    --net0 name=eth0,bridge=$CT_BRIDGE,ip=$CT_IP,gw=$CT_GW,firewall=0 --nameserver $CT_DNS \
    --unprivileged 1 --features nesting=1,keyctl=1 --onboot 1 --ssh-public-keys /tmp/casa-key.pub
  rm -f /tmp/casa-key.pub
  sudo -n pct start $CTID
  sleep 5
  sudo -n pct exec $CTID -- bash -c 'export DEBIAN_FRONTEND=noninteractive
    apt-get update -q && apt-get install -y -q docker.io docker-compose rsync curl ca-certificates
    systemctl enable --now docker
    mkdir -p /opt/casa-ranking/data && chown 10001 /opt/casa-ranking/data'
"
echo "LXC $CTID ready at $HOST_IP. Next: deploy/deploy.sh"
