#!/usr/bin/env bash
# NVIDIA's base has no RunPod service script: explicitly provide key-only SSH.
set -Eeuo pipefail
umask 077
mkdir -p /run/sshd /root/.ssh
chmod 700 /root/.ssh
if [[ -n "${PUBLIC_KEY:-}" ]]; then
    printf '%s\n' "$PUBLIC_KEY" >> /root/.ssh/authorized_keys
    chmod 600 /root/.ssh/authorized_keys
fi
ssh-keygen -A
/usr/sbin/sshd -t
if [[ "${WAN_AUTOSTART:-0}" == 1 ]]; then
    # SSH stays available even when mount/startup checks fail.
    /opt/wan-cloud-toolkit/docker/autostart.sh &
fi
exec /usr/sbin/sshd -D -e
