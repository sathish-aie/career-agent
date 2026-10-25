#!/bin/bash
# One container, five processes: a virtual display for Chrome, a VNC bridge so
# the human can sign in to job sites in it, nginx (the SPA and the /api proxy)
# and the backend. If any one exits the container stops, and the restart policy
# brings it back.
set -e
cd /state
mkdir -p data resume /tmp/nginx

# First run: the project's own brief and boards. The app edits these copies.
for f in career_brief.toml ats_boards.toml; do
  [ -e "$f" ] || cp "/app/defaults/$f" "$f"
done

# No setup step for the login-encryption key: make one and keep it with the
# data. Set CREDENTIAL_KEY yourself to keep it apart from the volume.
if [ -z "$CREDENTIAL_KEY" ]; then
  [ -s data/.credential_key ] || python -c \
    "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())" > data/.credential_key
  export CREDENTIAL_KEY="$(cat data/.credential_key)"
fi
[ -n "$CLAUDE_CODE_OAUTH_TOKEN" ] || \
  echo "WARNING: CLAUDE_CODE_OAUTH_TOKEN is not set (backend/.env) -- scoring and the apply agent will fail" >&2

# The last container's Chrome left its profile lock and X11 socket behind. A new
# container has a new hostname, which Chrome reads as "profile in use elsewhere".
rm -f "${CHROME_PROFILE_DIR:-data/chrome-profile}"/Singleton{Lock,Socket,Cookie} /tmp/.X99-lock

export DISPLAY=:99
Xvfb :99 -screen 0 1280x800x24 -nolisten tcp &
for _ in $(seq 40); do [ -e /tmp/.X11-unix/X99 ] && break; sleep 0.25; done
x11vnc -display :99 -forever -shared -nopw -localhost -quiet &
websockify --web /usr/share/novnc 6080 localhost:5900 &
nginx -e /dev/stderr -c /app/nginx.conf -g 'daemon off;' &
career-agent serve &

stop() { kill $(jobs -p) 2>/dev/null || true; wait; }
trap 'stop; exit 0' TERM INT
wait -n && code=0 || code=$?
stop
exit $code
