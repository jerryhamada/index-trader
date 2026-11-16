#!/bin/bash
# Start the Index Trader dashboard as a background service and open it.
#
#   ./start.sh            install the service, start it, open the dashboard
#   ./start.sh --no-open  the same without opening a browser
#
# The service starts again at every login and restarts itself if it stops, so
# the dashboard stays up with no terminal window open. It runs on this Mac
# only: while the Mac is asleep or off nothing runs, and it catches up on the
# missed data when the Mac wakes. Stop it with ./stop.sh.
set -euo pipefail

DIR="$(cd "$(dirname "$0")" && pwd)"
PORT="${PORT:-8787}"
LABEL="com.index-trader.dashboard"
DOMAIN="gui/$(id -u)"
PLIST="$HOME/Library/LaunchAgents/$LABEL.plist"
LOG="$HOME/Library/Logs/index-trader.log"
URL="http://127.0.0.1:$PORT"

if [ ! -x "$DIR/.venv/bin/python" ]; then
  echo "Setting up Python packages (first run only)..."
  python3 -m venv "$DIR/.venv"
  "$DIR/.venv/bin/pip" install -q -r "$DIR/requirements.txt"
fi

xml() { printf '%s' "$1" | sed -e 's/&/\&amp;/g' -e 's/</\&lt;/g' -e 's/>/\&gt;/g'; }

mkdir -p "$(dirname "$PLIST")" "$(dirname "$LOG")"
cat > "$PLIST" <<EOF
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>Label</key><string>$LABEL</string>
  <key>ProgramArguments</key>
  <array>
    <string>$(xml "$DIR/.venv/bin/python")</string>
    <string>$(xml "$DIR/server.py")</string>
  </array>
  <key>WorkingDirectory</key><string>$(xml "$DIR")</string>
  <key>EnvironmentVariables</key>
  <dict>
    <key>PORT</key><string>$PORT</string>
    <key>PYTHONUNBUFFERED</key><string>1</string>
  </dict>
  <key>RunAtLoad</key><true/>
  <key>KeepAlive</key><true/>
  <key>ThrottleInterval</key><integer>10</integer>
  <key>StandardOutPath</key><string>$(xml "$LOG")</string>
  <key>StandardErrorPath</key><string>$(xml "$LOG")</string>
</dict>
</plist>
EOF

# Replace any copy that is already running, then start the new one.
if launchctl print "$DOMAIN/$LABEL" >/dev/null 2>&1; then
  launchctl bootout "$DOMAIN/$LABEL" 2>/dev/null || true
  for _ in $(seq 1 20); do
    launchctl print "$DOMAIN/$LABEL" >/dev/null 2>&1 || break
    sleep 0.25
  done
fi
launchctl bootstrap "$DOMAIN" "$PLIST"

for _ in $(seq 1 40); do
  if curl -sf "$URL/api/state" >/dev/null 2>&1; then
    echo "Dashboard is running at $URL"
    echo "It restarts at login and if it ever stops. Stop it with ./stop.sh"
    [ "${1:-}" = "--no-open" ] || open "$URL"
    exit 0
  fi
  sleep 0.5
done

echo "The service was installed but is not answering at $URL."
echo "If macOS is asking whether Python may access files in your Desktop folder, click Allow."
echo "The service retries on its own every 10 seconds. Log: $LOG"
exit 1
