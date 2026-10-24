#!/bin/bash
# Turn the macOS system proxy back off (service remembered by dlp-on.sh).
SERVICE=${DLP_SERVICE:-$(cat /tmp/dlp-proxy-service 2>/dev/null || echo Wi-Fi)}
networksetup -setwebproxystate "$SERVICE" off
networksetup -setsecurewebproxystate "$SERVICE" off
echo "System proxy OFF for '$SERVICE'"
