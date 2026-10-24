#!/bin/bash
# Point the active macOS network service at the local DLP proxy (127.0.0.1:8080).
set -euo pipefail
PORT=${DLP_PORT:-8080}
IFACE=$(route -n get default 2>/dev/null | awk '/interface:/{print $2}')
SERVICE=$(networksetup -listnetworkserviceorder | grep -B1 "Device: $IFACE)" | head -1 | sed -E 's/^\([0-9*]+\) //')
SERVICE=${DLP_SERVICE:-${SERVICE:-Wi-Fi}}
networksetup -setwebproxy "$SERVICE" 127.0.0.1 "$PORT"
networksetup -setsecurewebproxy "$SERVICE" 127.0.0.1 "$PORT"
networksetup -setproxybypassdomains "$SERVICE" localhost 127.0.0.1 "*.local" 169.254/16
echo "$SERVICE" > /tmp/dlp-proxy-service
echo "System proxy ON for '$SERVICE' -> 127.0.0.1:$PORT"
