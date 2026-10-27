#!/usr/bin/env bash
# One-time host setup for Debian or Ubuntu, run as root. Safe to run again.
# Usage: bootstrap-host.sh [user] [swap size]   (defaults: deploy 3G)
set -euo pipefail

user="${1:-deploy}"
swap_size="${2:-3G}"

if [[ $EUID -ne 0 ]]; then
  echo "Run as root." >&2
  exit 1
fi
. /etc/os-release
if [[ "$ID" != debian && "$ID" != ubuntu ]]; then
  echo "Only Debian and Ubuntu are supported, found $ID." >&2
  exit 1
fi
# Password login is turned off below, so a key must already work.
if [[ ! -s /root/.ssh/authorized_keys ]] && [[ ! -s "/home/$user/.ssh/authorized_keys" ]]; then
  echo "Add an SSH public key to /root/.ssh/authorized_keys first." >&2
  exit 1
fi

export DEBIAN_FRONTEND=noninteractive
apt-get update
apt-get upgrade -y
apt-get install -y ca-certificates curl ufw unattended-upgrades

# Deploy user with the same SSH keys as root.
if ! id "$user" >/dev/null 2>&1; then
  adduser --disabled-password --gecos "" "$user"
fi
install -d -m 700 -o "$user" -g "$user" "/home/$user/.ssh"
if [[ ! -s "/home/$user/.ssh/authorized_keys" ]]; then
  install -m 600 -o "$user" -g "$user" /root/.ssh/authorized_keys "/home/$user/.ssh/authorized_keys"
fi
usermod -aG sudo "$user"
echo "$user ALL=(ALL) NOPASSWD:ALL" >"/etc/sudoers.d/90-$user"
chmod 440 "/etc/sudoers.d/90-$user"

# SSH: keys only, no root login.
cat >/etc/ssh/sshd_config.d/10-out-of-frame.conf <<'EOF'
PasswordAuthentication no
KbdInteractiveAuthentication no
PermitRootLogin no
EOF
sshd -t
systemctl reload ssh

# Firewall: SSH, HTTP and HTTPS. Docker publishes only Caddy's ports 80 and 443.
ufw allow OpenSSH
ufw allow 80/tcp
ufw allow 443/tcp
ufw allow 443/udp
ufw --force enable

# Automatic security updates.
cat >/etc/apt/apt.conf.d/20auto-upgrades <<'EOF'
APT::Periodic::Update-Package-Lists "1";
APT::Periodic::Unattended-Upgrade "1";
EOF

# Docker Engine and the Compose plugin from Docker's apt repository, unless already installed.
if ! docker compose version >/dev/null 2>&1; then
  install -d -m 755 /etc/apt/keyrings
  curl -fsSL "https://download.docker.com/linux/$ID/gpg" -o /etc/apt/keyrings/docker.asc
  chmod a+r /etc/apt/keyrings/docker.asc
  echo "deb [arch=$(dpkg --print-architecture) signed-by=/etc/apt/keyrings/docker.asc] https://download.docker.com/linux/$ID $VERSION_CODENAME stable" \
    >/etc/apt/sources.list.d/docker.list
  apt-get update
  apt-get install -y docker-ce docker-ce-cli containerd.io docker-compose-plugin
fi
usermod -aG docker "$user"

# Logs: containers write to the journal, which keeps entries for up to 24 hours.
install -d -m 755 /etc/systemd/journald.conf.d
cat >/etc/systemd/journald.conf.d/10-out-of-frame.conf <<'EOF'
[Journal]
MaxRetentionSec=24h
MaxFileSec=1h
SystemMaxUse=200M
EOF
systemctl restart systemd-journald
daemon_json='{"log-driver": "journald"}'
if [[ ! -s /etc/docker/daemon.json ]] || grep -q '"log-driver": "journald"' /etc/docker/daemon.json; then
  install -d -m 755 /etc/docker
  echo "$daemon_json" >/etc/docker/daemon.json
  systemctl restart docker
else
  echo "Warning: /etc/docker/daemon.json has other settings. Add $daemon_json by hand." >&2
fi
# rsyslog would copy the journal to files kept longer than 24 hours. The other services are
# not needed on a VPS and use memory.
for unit in rsyslog.service snapd.service snapd.socket ModemManager.service udisks2.service \
  multipathd.service multipathd.socket; do
  if systemctl list-unit-files "$unit" --no-legend | grep -q .; then
    # Static units cannot be disabled; stopping them is enough.
    systemctl disable --now "$unit" 2>/dev/null || systemctl stop "$unit"
  fi
done

# Swap: the services use more memory during a run.
if ! swapon --show | grep -q .; then
  fallocate -l "$swap_size" /swapfile
  chmod 600 /swapfile
  mkswap /swapfile
  swapon /swapfile
fi
if [[ -f /swapfile ]] && ! grep -q '^/swapfile ' /etc/fstab; then
  echo '/swapfile none swap sw 0 0' >>/etc/fstab
fi
echo 'vm.swappiness=10' >/etc/sysctl.d/90-out-of-frame.conf
sysctl --system >/dev/null

echo "Done. Log in as $user and check SSH access before closing this root session."
