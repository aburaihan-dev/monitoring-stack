#!/bin/bash
# Generate configs/nginx/.htpasswd for nginx basic auth.
# Requires: apache2-utils (apt) or httpd-tools (yum) for htpasswd.
set -e

HTPASSWD_FILE="configs/nginx/.htpasswd"

command -v htpasswd &>/dev/null || {
  echo "htpasswd not found. Install it:"
  echo "  Debian/Ubuntu:  sudo apt install apache2-utils"
  echo "  RHEL/CentOS:    sudo yum install httpd-tools"
  echo "  macOS:          brew install httpd"
  echo "  Docker:         docker run --rm -it httpd htpasswd ..."
  exit 1
}

mkdir -p configs/nginx
read -rp "Username [admin]: " USER
USER="${USER:-admin}"
htpasswd -c "${HTPASSWD_FILE}" "${USER}"
echo "✔  ${HTPASSWD_FILE} created for user '${USER}'"
