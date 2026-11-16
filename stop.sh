#!/bin/bash
# Stop the Index Trader dashboard service and remove it from login.
set -euo pipefail

LABEL="com.index-trader.dashboard"
launchctl bootout "gui/$(id -u)/$LABEL" 2>/dev/null || true
rm -f "$HOME/Library/LaunchAgents/$LABEL.plist"
echo "Dashboard stopped. Start it again with ./start.sh"
