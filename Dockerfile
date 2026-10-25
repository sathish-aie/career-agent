# syntax=docker/dockerfile:1
#
# One image, the whole app: the React SPA behind nginx, the FastAPI backend, and
# the browser the apply agent drives. `docker compose up --build` starts it.

# --- 1. build the SPA --------------------------------------------------------
FROM node:22-bookworm-slim AS frontend
WORKDIR /build
COPY frontend/package.json frontend/package-lock.json ./
RUN npm ci
COPY frontend/ ./
RUN npm run build

# --- 2. runtime --------------------------------------------------------------
FROM python:3.13-slim-bookworm

# Node, for the two things the apply agent shells out to: `claude` and `npx`.
COPY --from=node:22-bookworm-slim /usr/local/bin/node /usr/local/bin/node
COPY --from=node:22-bookworm-slim /usr/local/lib/node_modules /usr/local/lib/node_modules
RUN ln -s ../lib/node_modules/npm/bin/npm-cli.js /usr/local/bin/npm \
 && ln -s ../lib/node_modules/npm/bin/npx-cli.js /usr/local/bin/npx

# chromium: the apply agent's browser. xvfb + x11vnc + novnc: a display for it,
# and a way for the human to sign in to job sites in it. lsof: chrome.py's
# zombie sweep of the CDP port.
RUN apt-get update && apt-get install -y --no-install-recommends \
      chromium fonts-liberation nginx xvfb x11vnc novnc websockify lsof \
 && rm -rf /var/lib/apt/lists/*

# Pinned to the versions the project was developed against (agent.py pins the
# Playwright MCP server the same way).
ARG CLAUDE_CODE_VERSION=2.1.309
RUN npm install -g @anthropic-ai/claude-code@${CLAUDE_CODE_VERSION} && npm cache clean --force

# `claude` refuses --permission-mode bypassPermissions as root, so run as a user.
# /tmp/.X11-unix is where Xvfb puts its socket, and only root may create it.
RUN useradd --create-home --uid 1000 app \
 && mkdir /state && chown app:app /state \
 && mkdir -m 1777 /tmp/.X11-unix

# Fetch the Playwright MCP server now, as the user that will run it: the first
# apply would otherwise download it while the agent waits for the server to
# connect.
USER app
RUN npx -y @playwright/mcp@0.0.80 --help > /dev/null
USER root

# Python dependencies from the lockfile, then the package itself.
RUN pip install --no-cache-dir uv
ENV UV_PROJECT_ENVIRONMENT=/opt/venv UV_PYTHON_DOWNLOADS=never UV_COMPILE_BYTECODE=1
ENV PATH="/opt/venv/bin:${PATH}"
WORKDIR /app
COPY backend/pyproject.toml backend/uv.lock ./
RUN uv sync --locked --no-dev --no-install-project
COPY backend/src ./src
RUN uv sync --locked --no-dev --no-editable

COPY --from=frontend /build/dist /app/frontend
# First-run copies for /state; the app edits its own copies from then on.
COPY backend/career_brief.toml backend/ats_boards.toml /app/defaults/
COPY docker/nginx.conf docker/entrypoint.sh /app/
COPY docker/chrome /usr/local/bin/chrome
RUN chmod +x /app/entrypoint.sh /usr/local/bin/chrome

# The app reads and writes everything relative to its working directory
# (data/career.db, career_brief.toml, candidate_profile.toml, resume/), so that
# directory is the one volume.
ENV CHROME_PATH=/usr/local/bin/chrome
USER app
WORKDIR /state
VOLUME /state
EXPOSE 8080 6080

HEALTHCHECK --interval=30s --timeout=5s --start-period=40s --retries=3 \
  CMD python -c "import urllib.request as u; u.urlopen('http://127.0.0.1:8080/api/run/status', timeout=4)"

ENTRYPOINT ["/app/entrypoint.sh"]
