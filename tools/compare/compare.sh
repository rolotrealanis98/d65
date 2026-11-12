#!/bin/sh
# Open the display-compare page full screen on both displays (Chrome kiosk windows), synced through
# the local compare server. Quit each window with Cmd-Q; stop the server with: compare.sh stop
set -eu
HERE=$(cd "$(dirname "$0")" && pwd)
ROOT=$(cd "$HERE/../.." && pwd)
PORT=8659
URL="http://127.0.0.1:$PORT"
CHROME="/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"
PROFILES="$ROOT/local/compare-chrome"

if [ "${1:-}" = "stop" ]; then
  # Match by the port it listens on, not the command line (it may have been started by a relative path).
  pid=$(lsof -nP -t -iTCP:"$PORT" -sTCP:LISTEN 2>/dev/null || true)
  if [ -n "$pid" ]; then kill $pid && echo "server stopped"; else echo "server not running"; fi
  pkill -f "$PROFILES" || true
  exit 0
fi

if ! curl -fs "$URL/" 2>/dev/null | grep -q "Display Compare"; then
  python3 -I "$HERE/server.py" --port "$PORT" > "$ROOT/local/compare-server.log" 2>&1 &
  for _ in 1 2 3 4 5 6 7 8 9 10; do curl -fs -o /dev/null "$URL/" && break; sleep 0.5; done
fi

# Screen frames in top-left global coordinates, from AppKit (Cocoa uses bottom-left).
frames=$(osascript -l JavaScript -e '
  ObjC.import("AppKit"); var s = $.NSScreen.screens, H = s.objectAtIndex(0).frame.size.height, out = [];
  for (var i = 0; i < s.count; i++) { var f = s.objectAtIndex(i).frame;
    out.push(ObjC.unwrap(s.objectAtIndex(i).localizedName) + "|" + f.origin.x + "|" + (H - f.origin.y - f.size.height) + "|" + f.size.width + "|" + f.size.height); }
  out.join("\n")')

open_on() { # role, name fragment
  line=$(printf '%s\n' "$frames" | grep -i "$2" | head -1)
  [ -n "$line" ] || { echo "no display matching '$2'"; return; }
  x=$(echo "$line" | cut -d'|' -f2); y=$(echo "$line" | cut -d'|' -f3)
  w=$(echo "$line" | cut -d'|' -f4); h=$(echo "$line" | cut -d'|' -f5)
  mkdir -p "$PROFILES/$1"
  "$CHROME" --user-data-dir="$PROFILES/$1" --no-first-run --no-default-browser-check \
    --window-position="$x,$y" --window-size="$w,$h" --kiosk "$URL/?role=$1" >/dev/null 2>&1 &
  echo "opened $1 on $(echo "$line" | cut -d'|' -f1) at $x,$y ${w}x$h"
}
open_on asus "ASUS"
open_on innoview "Innoview"
