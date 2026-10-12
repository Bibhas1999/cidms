#!/usr/bin/env bash
# One-time set-up of a fresh Oracle Cloud server (Always Free ARM): Oracle Linux 8/9 (user "opc") or Ubuntu
# (user "ubuntu"). deploy.ps1 runs this for you:   sudo bash server-setup.sh
# Installs Docker, opens ports 80/443 in the server's own firewall (Oracle's images block them), adds swap, turns on
# automatic security updates, and schedules the nightly database backup.
set -euo pipefail
. /etc/os-release
APP_USER="${SUDO_USER:-opc}"
echo "== $PRETTY_NAME, app user: $APP_USER"

# Oracle Linux uses ~30 GB of the boot volume by default: grow the disk to the size chosen when making the VM.
if [ -x /usr/libexec/oci-growfs ]; then echo "== growing the disk"; /usr/libexec/oci-growfs -y || true; fi

if [ "$ID" = "ol" ] || [ "${ID_LIKE:-}" != "${ID_LIKE#*rhel}" ]; then
  echo "== packages (dnf)"
  dnf -y install dnf-utils cronie dnf-automatic
  systemctl enable --now crond
  sed -i 's/^apply_updates = .*/apply_updates = yes/' /etc/dnf/automatic.conf
  systemctl enable --now dnf-automatic.timer
  echo "== docker"
  if ! command -v docker >/dev/null; then
    dnf config-manager --add-repo https://download.docker.com/linux/centos/docker-ce.repo
    dnf -y install docker-ce docker-ce-cli containerd.io docker-buildx-plugin docker-compose-plugin
  fi
  echo "== firewall: allow web traffic"
  if systemctl is-active --quiet firewalld; then
    firewall-cmd --permanent --add-service=http
    firewall-cmd --permanent --add-service=https
    firewall-cmd --permanent --add-port=443/udp
    firewall-cmd --reload
  fi
else
  echo "== packages (apt)"
  export DEBIAN_FRONTEND=noninteractive
  apt-get update -y
  apt-get install -y ca-certificates curl unattended-upgrades iptables-persistent cron
  dpkg-reconfigure -f noninteractive unattended-upgrades
  echo "== docker"
  command -v docker >/dev/null || curl -fsSL https://get.docker.com | sh
  echo "== firewall: allow web traffic (Oracle's Ubuntu images reject everything but SSH)"
  for port in 80 443; do
    iptables -C INPUT -p tcp --dport "$port" -j ACCEPT 2>/dev/null || iptables -I INPUT 5 -p tcp --dport "$port" -j ACCEPT
  done
  iptables -C INPUT -p udp --dport 443 -j ACCEPT 2>/dev/null || iptables -I INPUT 5 -p udp --dport 443 -j ACCEPT
  netfilter-persistent save
fi
systemctl enable --now docker
usermod -aG docker "$APP_USER" || true

echo "== swap (4 GB) so builds never run out of memory"
if ! swapon --show | grep -q /swapfile; then
  fallocate -l 4G /swapfile && chmod 600 /swapfile && mkswap /swapfile && swapon /swapfile
  echo "/swapfile none swap sw 0 0" >> /etc/fstab
fi

echo "== app folder and backups (the schedule is set in the app: Settings > Backups)"
mkdir -p /opt/supreme-dms/backups
chown -R "$APP_USER":"$APP_USER" /opt/supreme-dms
timedatectl set-timezone Asia/Kolkata || true
cat > /etc/cron.d/supreme-dms-backup <<CRON
*/5 * * * * $APP_USER /opt/supreme-dms/deploy/backup.sh --if-due >> /opt/supreme-dms/backups/backup.log 2>&1
CRON
chmod 644 /etc/cron.d/supreme-dms-backup

echo "== done (log out and back in once for the docker group to apply)"
