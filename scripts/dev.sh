#!/usr/bin/env bash
# Start the backend (FastAPI/uvicorn --reload, port 8000) and the frontend (Vite, port 5173) together.
# Ctrl+C stops both. Works with macOS's stock bash 3.2 and with Linux bash.
#
#   scripts/dev.sh               check prerequisites, then start both
#   scripts/dev.sh --check       run every check and print what would start; never launches anything
#   scripts/dev.sh --backend-only | --frontend-only
#   scripts/dev.sh --https       ALSO serve the API over HTTPS on 8443 (self-signed backend/certs/*.pem); HTTP stays on 8000
#   scripts/dev.sh --help
#
# Refuses to start if a port it needs is already in use (for example, a backend you started yourself).
# Environment overrides: DEV_BACKEND_PORT (8000), DEV_HTTPS_PORT (8443), DEV_FRONTEND_PORT (5173), DEV_HOST (127.0.0.1).
# Note: the backend only allows CORS from http://localhost:5173 and http://127.0.0.1:5173 (CORS_ORIGINS in backend/.env),
# and frontend/vite.config.js pins 5173 with strictPort, so change those too if you move the frontend port.
set -u

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
BACKEND="$ROOT/backend"
FRONTEND="$ROOT/frontend"
HOST="${DEV_HOST:-127.0.0.1}"
BPORT="${DEV_BACKEND_PORT:-8000}"
FPORT="${DEV_FRONTEND_PORT:-5173}"
SPORT="${DEV_HTTPS_PORT:-8443}"
CHECK_ONLY=0 RUN_BACKEND=1 RUN_FRONTEND=1 RUN_HTTPS=0

usage() { sed -n '2,14p' "$0" | sed 's/^# \{0,1\}//'; }
for arg in "$@"; do
  case "$arg" in
    --check|--dry-run) CHECK_ONLY=1 ;;
    --backend-only) RUN_FRONTEND=0 ;;
    --frontend-only) RUN_BACKEND=0 ;;
    --https) RUN_HTTPS=1 ;;
    -h|--help) usage; exit 0 ;;
    *) echo "unknown option: $arg (see --help)" >&2; exit 2 ;;
  esac
done
if [ "$RUN_BACKEND" = 0 ] && [ "$RUN_FRONTEND" = 0 ]; then echo "nothing to start" >&2; exit 2; fi
if [ "$RUN_HTTPS" = 1 ] && [ "$RUN_BACKEND" = 0 ]; then echo "--https needs the backend (drop --frontend-only)" >&2; exit 2; fi

# Homebrew paths (node, npm, lsof wrappers) aren't always on PATH in non-login shells on macOS.
for d in /opt/homebrew/bin /usr/local/bin; do
  case ":$PATH:" in *":$d:"*) ;; *) [ -d "$d" ] && PATH="$PATH:$d" ;; esac
done

if [ -t 1 ]; then R=$'\033[31m' G=$'\033[32m' Y=$'\033[33m' B=$'\033[1m' N=$'\033[0m'; else R='' G='' Y='' B='' N=''; fi
ERRORS=0
ok()   { echo "  ${G}ok${N}    $*"; }
warn() { echo "  ${Y}warn${N}  $*"; }
fail() { echo "  ${R}FAIL${N}  $*"; ERRORS=$((ERRORS + 1)); }

# Prints "<command> (pid <pid>)" when something listens on the port, nothing otherwise.
port_owner() {
  local port=$1 out=""
  if command -v lsof >/dev/null 2>&1; then
    out=$(lsof -nP -iTCP:"$port" -sTCP:LISTEN 2>/dev/null | awk 'NR>1 {print $1 " (pid " $2 ")"; exit}')
  fi
  if [ -z "$out" ]; then   # no lsof, or not allowed to see the process: try connecting
    if (exec 3<>"/dev/tcp/127.0.0.1/$port") 2>/dev/null || (exec 3<>"/dev/tcp/localhost/$port") 2>/dev/null; then
      out="unknown process"
    fi
  fi
  [ -n "$out" ] && echo "$out"
  return 0
}

echo "${B}Checking prerequisites${N} (repo: $ROOT)"
if [ "$RUN_BACKEND" = 1 ]; then
  if [ -x "$BACKEND/.venv/bin/python" ] && [ -x "$BACKEND/.venv/bin/uvicorn" ]; then
    ok "backend venv: $BACKEND/.venv ($("$BACKEND/.venv/bin/python" -V 2>&1))"
  else
    fail "backend venv missing: cd backend && python3 -m venv .venv && .venv/bin/pip install -r requirements.txt"
  fi
  if [ -f "$BACKEND/.env" ]; then
    ok "backend/.env present"
  else
    fail "backend/.env missing: cp backend/.env.example backend/.env, then set DATABASE_URL and JWT_SECRET"
  fi
  if [ -x "$BACKEND/.venv/bin/python" ]; then
    # Uses the app's own settings (env vars > backend/.env), so it checks exactly the database uvicorn will use.
    # SELECT 1 only; nothing is written.
    db_msg=$(cd "$BACKEND" && .venv/bin/python - 2>&1 <<'PY'
import sys
try:
    from sqlalchemy import text
    from config import settings
    from database import engine
    url = engine.url
    with engine.connect() as c:
        c.execute(text("SELECT 1"))
        ver = c.execute(text("SELECT VERSION()")).scalar() if url.get_backend_name() == "mysql" else "sqlite"
    print(f"{url.get_backend_name()} reachable at {url.host or ''}:{url.port or ''}/{url.database} (server {ver})")
except Exception as e:  # noqa: BLE001
    print(f"{type(e).__name__}: {str(e).splitlines()[0][:200]}")
    sys.exit(1)
PY
)
    if [ $? -eq 0 ]; then ok "database: $db_msg"; else fail "database not reachable: $db_msg (is MySQL running? check DATABASE_URL in backend/.env)"; fi
  fi
  owner=$(port_owner "$BPORT")
  if [ -n "$owner" ]; then
    fail "port $BPORT is already in use by $owner. Stop it first, or use --frontend-only to keep that backend"
  else
    ok "port $BPORT free"
  fi
  if [ "$RUN_HTTPS" = 1 ]; then
    if [ -f "$BACKEND/certs/key.pem" ] && [ -f "$BACKEND/certs/cert.pem" ]; then
      ok "TLS cert: backend/certs/cert.pem"
    else
      fail "TLS cert missing: cd backend && .venv/bin/python gen_cert.py"
    fi
    owner=$(port_owner "$SPORT")
    if [ -n "$owner" ]; then fail "port $SPORT is already in use by $owner"; else ok "port $SPORT free (HTTPS)"; fi
  fi
fi
if [ "$RUN_FRONTEND" = 1 ]; then
  if command -v node >/dev/null 2>&1 && command -v npm >/dev/null 2>&1; then
    ok "node $(node -v), npm $(npm -v)"
  else
    fail "node/npm not found on PATH (install Node 20.19+ or 22.12+)"
  fi
  if [ -f "$FRONTEND/package.json" ] && [ -d "$FRONTEND/node_modules" ] && [ -e "$FRONTEND/node_modules/.bin/vite" ]; then
    ok "frontend/node_modules present"
  else
    fail "frontend dependencies missing: cd frontend && npm install"
  fi
  if [ -f "$FRONTEND/.env" ] || [ -f "$FRONTEND/.env.local" ]; then
    ok "frontend env file present"
  else
    warn "no frontend/.env: VITE_API_URL defaults to http://localhost:8000 (optional: cp frontend/.env.example frontend/.env)"
  fi
  owner=$(port_owner "$FPORT")
  if [ -n "$owner" ]; then
    fail "port $FPORT is already in use by $owner. Stop it first (Vite won't move to another port: strictPort)"
  else
    ok "port $FPORT free"
  fi
fi

if [ "$ERRORS" -gt 0 ]; then
  echo "${R}${ERRORS} problem(s) found; not starting.${N}"
  exit 1
fi
[ "$RUN_BACKEND" = 1 ] && B_CMD="(cd backend && .venv/bin/uvicorn main:app --reload --host $HOST --port $BPORT)"
[ "$RUN_FRONTEND" = 1 ] && F_CMD="(cd frontend && npm run dev -- --host $HOST --port $FPORT)"
[ "$RUN_HTTPS" = 1 ] && S_CMD="(cd backend && STARTUP_RECOVERY=false .venv/bin/uvicorn main:app --reload --host $HOST --port $SPORT --ssl-keyfile certs/key.pem --ssl-certfile certs/cert.pem)"
if [ "$CHECK_ONLY" = 1 ]; then
  echo "${G}All checks passed.${N} Would run:"
  [ "$RUN_BACKEND" = 1 ] && echo "  $B_CMD"
  [ "$RUN_HTTPS" = 1 ] && echo "  $S_CMD"
  [ "$RUN_FRONTEND" = 1 ] && echo "  $F_CMD"
  exit 0
fi

# ---- launch: each child gets its own process group (job control), so cleanup can kill whole trees
# (uvicorn's reloader + worker, npm -> vite) without touching anything else.
set -m
PIDS=""
CLEANED=0
cleanup() {
  [ "$CLEANED" = 1 ] && return
  CLEANED=1
  trap - INT TERM HUP EXIT
  echo
  echo "${B}Stopping...${N}"
  for pid in $PIDS; do kill -TERM -- "-$pid" 2>/dev/null || kill -TERM "$pid" 2>/dev/null; done
  for _ in 1 2 3 4 5 6 7 8 9 10; do
    alive=0
    for pid in $PIDS; do kill -0 -- "-$pid" 2>/dev/null && alive=1; done
    [ "$alive" = 0 ] && break
    sleep 0.5
  done
  for pid in $PIDS; do kill -KILL -- "-$pid" 2>/dev/null; done
  echo "Stopped backend and frontend."
}
trap 'cleanup; exit 130' INT
trap 'cleanup; exit 143' TERM HUP
trap cleanup EXIT

prefix() { local tag=$1; while IFS= read -r line; do printf '%s %s\n' "$tag" "$line"; done; }

if [ "$RUN_BACKEND" = 1 ]; then
  (cd "$BACKEND" && exec .venv/bin/uvicorn main:app --reload --host "$HOST" --port "$BPORT" 2>&1 | prefix "[backend ]") &
  PIDS="$PIDS $!"
fi
if [ "$RUN_HTTPS" = 1 ]; then
  # Second server process: STARTUP_RECOVERY=false so it never marks the HTTP process's running jobs as failed.
  (cd "$BACKEND" && STARTUP_RECOVERY=false exec .venv/bin/uvicorn main:app --reload --host "$HOST" --port "$SPORT" \
     --ssl-keyfile certs/key.pem --ssl-certfile certs/cert.pem 2>&1 | prefix "[https   ]") &
  PIDS="$PIDS $!"
fi
if [ "$RUN_FRONTEND" = 1 ]; then
  (cd "$FRONTEND" && exec npm run dev -- --host "$HOST" --port "$FPORT" 2>&1 | prefix "[frontend]") &
  PIDS="$PIDS $!"
fi

wait_for() {  # wait_for <port> <name>: up to 30 s
  local i
  for i in $(seq 1 60); do
    [ -n "$(port_owner "$1")" ] && return 0
    sleep 0.5
  done
  echo "${Y}warning: $2 not listening on port $1 after 30 s (see its log lines above)${N}"
  return 1
}
[ "$RUN_BACKEND" = 1 ] && wait_for "$BPORT" backend
[ "$RUN_HTTPS" = 1 ] && wait_for "$SPORT" https
[ "$RUN_FRONTEND" = 1 ] && wait_for "$FPORT" frontend
echo
echo "${B}Running${N} (Ctrl+C stops everything):"
[ "$RUN_BACKEND" = 1 ] && echo "  API        http://$HOST:$BPORT   (docs: http://$HOST:$BPORT/docs, health: http://$HOST:$BPORT/health)"
[ "$RUN_HTTPS" = 1 ] && echo "  API HTTPS  https://$HOST:$SPORT  (self-signed: curl -k / accept once in the browser)"
[ "$RUN_FRONTEND" = 1 ] && echo "  Frontend   http://localhost:$FPORT"
echo

# Exit (and clean up the other one) as soon as either process stops.
while :; do
  for pid in $PIDS; do
    if ! kill -0 "$pid" 2>/dev/null; then
      echo "${Y}A dev process exited; shutting down the rest.${N}"
      exit 1
    fi
  done
  sleep 1
done
