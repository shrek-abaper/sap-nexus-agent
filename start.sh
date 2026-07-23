#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd -P)
RUNTIME_DIR=${START_RUNTIME_DIR:-"$ROOT_DIR/runtime/dev-services"}
LOG_DIR="$RUNTIME_DIR/logs"
PID_DIR="$RUNTIME_DIR/pids"
GATEWAY_PORT=${GATEWAY_PORT:-8080}
ODATA_SERVICE_PORT=${ODATA_SERVICE_PORT:-8081}
FRONTEND_PORT=${FRONTEND_PORT:-3000}
FRONTEND_HOST=${FRONTEND_HOST:-0.0.0.0}
JAVA_HOME_DEFAULT=/usr/lib/jvm/java-17-openjdk-amd64
JAVA_HOME=${JAVA_HOME:-$JAVA_HOME_DEFAULT}
GRADLE_USER_HOME=${GRADLE_USER_HOME:-/tmp/gradle-home}
DRY_RUN=0

usage() {
  cat <<'USAGE'
SAP Nexus Agent local service launcher.

Starts the local development services needed for manual Agent testing:
  - Gateway: Java Spring Boot Gateway (JCo + OData thin reverse proxy) from services/gateway/
  - OData service: Python OData read-only microservice (:8081) from services/odata-service/
  - Workbench: Next.js Agent Workbench from frontend/

Usage:
  ./start.sh [--dry-run] [--help]

Environment overrides:
  GATEWAY_PORT=8080
  ODATA_SERVICE_PORT=8081
  FRONTEND_PORT=3000
  FRONTEND_HOST=0.0.0.0
  SAP_NEXUS_GATEWAY_URL=http://127.0.0.1:8080
  SAP_NEXUS_INTENT_MODE=hybrid
  SAP_NEXUS_AGENT_PYTHON=/absolute/path/to/python
  SAP_GATEWAY_ODATA_PROXY_URL=http://127.0.0.1:8081
  JAVA_HOME=/usr/lib/jvm/java-17-openjdk-amd64
  GRADLE_USER_HOME=/tmp/gradle-home
  START_RUNTIME_DIR=runtime/dev-services

Notes:
  - Root .env is loaded via python-dotenv when present, but its contents are never printed.
  - Logs are written under runtime/dev-services/logs/ by default.
  - Press Ctrl+C to stop all child services.
USAGE
}

log() {
  printf '[start] %s\n' "$*"
}

fail() {
  printf '[start] ERROR: %s\n' "$*" >&2
  exit 1
}

append_no_proxy() {
  local current=$1
  shift
  local item
  for item in "$@"; do
    case ",$current," in
      *",$item,"*) ;;
      *) current="${current:+$current,}$item" ;;
    esac
  done
  printf '%s\n' "$current"
}

for arg in "$@"; do
  case "$arg" in
    --dry-run) DRY_RUN=1 ;;
    --help|-h) usage; exit 0 ;;
    *) fail "Unknown argument: $arg" ;;
  esac
done

require_file() {
  local path=$1
  [[ -e "$path" ]] || fail "Required path not found: $path"
}

choose_gradle() {
  if [[ -x "$ROOT_DIR/services/gateway/gradlew" ]]; then
    printf '%s\n' "$ROOT_DIR/services/gateway/gradlew"
  elif [[ -x /tmp/gradle-8.8/bin/gradle ]]; then
    printf '%s\n' /tmp/gradle-8.8/bin/gradle
  else
    fail "No Gradle runner found. Expected services/gateway/gradlew or /tmp/gradle-8.8/bin/gradle."
  fi
}

choose_python() {
  if [[ -x "$ROOT_DIR/.venv/bin/python" ]]; then
    printf '%s\n' "$ROOT_DIR/.venv/bin/python"
  else
    printf '%s\n' python3
  fi
}

load_dotenv() {
  local python_cmd=$1
  local env_file="$ROOT_DIR/.env"
  [[ -f "$env_file" ]] || return 0

  log "Loading root .env via python-dotenv for local process environment (values hidden)."
  # Use python-dotenv instead of shell-sourcing .env because local secret values
  # may contain spaces or shell-sensitive characters.
  eval "$("$python_cmd" - "$env_file" <<'PY'
from pathlib import Path
import shlex
import sys

try:
    from dotenv import dotenv_values
except Exception as exc:
    raise SystemExit(f"python-dotenv is required to load .env safely: {exc}")

for key, value in dotenv_values(Path(sys.argv[1])).items():
    if not key or value is None:
        continue
    print(f"export {key}={shlex.quote(value)}")
PY
  )"
}

print_plan() {
  local gradle_cmd=$1
  local python_cmd=$2
  cat <<PLAN
Dry run: SAP Nexus Agent services would start with:
  OData svc  : cd services/odata-service && PYTHONPATH=. ODATA_SERVICE_PORT=$ODATA_SERVICE_PORT $python_cmd -c 'from odata_service.server import run; run(...)'
  Gateway    : cd services/gateway && JAVA_HOME=$JAVA_HOME GRADLE_USER_HOME=$GRADLE_USER_HOME SERVER_PORT=$GATEWAY_PORT SAP_GATEWAY_ODATA_PROXY_URL=http://127.0.0.1:$ODATA_SERVICE_PORT $gradle_cmd --no-daemon bootRun
  Workbench  : npm --prefix frontend run dev -- --hostname $FRONTEND_HOST --port $FRONTEND_PORT
  Agent      : SAP_NEXUS_GATEWAY_URL=${SAP_NEXUS_GATEWAY_URL:-http://127.0.0.1:$GATEWAY_PORT} SAP_NEXUS_INTENT_MODE=${SAP_NEXUS_INTENT_MODE:-hybrid}
  Logs       : $LOG_DIR
PLAN
}

start_service() {
  local name=$1
  local log_file=$2
  shift 2

  log "Starting $name; log: $log_file"
  setsid "$@" >"$log_file" 2>&1 &
  local pid=$!
  printf '%s\n' "$pid" >"$PID_DIR/$name.pid"
  log "$name pid=$pid"
}

stop_services() {
  local status=$?
  trap - INT TERM EXIT

  if [[ -d "$PID_DIR" ]]; then
    for pid_file in "$PID_DIR"/*.pid; do
      [[ -e "$pid_file" ]] || continue
      local pid
      pid=$(cat "$pid_file")
      if kill -0 "$pid" 2>/dev/null; then
        log "Stopping pid=$pid ($(basename "$pid_file" .pid))"
        kill -- "-$pid" 2>/dev/null || kill "$pid" 2>/dev/null || true
      fi
      rm -f "$pid_file"
    done
  fi

  wait 2>/dev/null || true
  exit "$status"
}

require_file "$ROOT_DIR/services/gateway/settings.gradle"
require_file "$ROOT_DIR/services/odata-service/odata_service/server.py"
require_file "$ROOT_DIR/frontend/package.json"
require_file "$ROOT_DIR/frontend/node_modules"

GRADLE_CMD=$(choose_gradle)
PYTHON_CMD=$(choose_python)

if [[ "$DRY_RUN" == "1" ]]; then
  print_plan "$GRADLE_CMD" "$PYTHON_CMD"
  exit 0
fi

mkdir -p "$LOG_DIR" "$PID_DIR"

if [[ -f "$ROOT_DIR/.env" ]]; then
  load_dotenv "$PYTHON_CMD"
else
  log "Root .env not found. Gateway may start with degraded SAP connectivity."
fi

if [[ -d "$JAVA_HOME" ]]; then
  export JAVA_HOME
else
  log "JAVA_HOME path not found: $JAVA_HOME. Continuing with system Java."
  unset JAVA_HOME
fi

export GRADLE_USER_HOME
export SERVER_PORT="$GATEWAY_PORT"
export ODATA_SERVICE_PORT
NO_PROXY=$(append_no_proxy "${NO_PROXY:-}" localhost 127.0.0.1 0.0.0.0)
no_proxy=$(append_no_proxy "${no_proxy:-$NO_PROXY}" localhost 127.0.0.1 0.0.0.0)
export NO_PROXY no_proxy
export SAP_NEXUS_AGENT_ROOT="${SAP_NEXUS_AGENT_ROOT:-$ROOT_DIR}"
if [[ -z "${SAP_NEXUS_AGENT_PYTHON:-}" ]]; then
  if [[ -x "$ROOT_DIR/.venv/bin/python" ]]; then
    export SAP_NEXUS_AGENT_PYTHON="$ROOT_DIR/.venv/bin/python"
  else
    export SAP_NEXUS_AGENT_PYTHON="python3"
  fi
else
  export SAP_NEXUS_AGENT_PYTHON
fi
export SAP_NEXUS_GATEWAY_URL="${SAP_NEXUS_GATEWAY_URL:-http://127.0.0.1:$GATEWAY_PORT}"
export SAP_NEXUS_INTENT_MODE="${SAP_NEXUS_INTENT_MODE:-hybrid}"
export SAPNEXUS_REGISTRY_PATH="${SAPNEXUS_REGISTRY_PATH:-$ROOT_DIR/registry/capabilities.yaml}"
export SAPNEXUS_REGISTRY_BINDINGS_PATH="${SAPNEXUS_REGISTRY_BINDINGS_PATH:-$ROOT_DIR/registry/executor-bindings.yaml}"
export SAPNEXUS_TRACE_PATH="${SAPNEXUS_TRACE_PATH:-$ROOT_DIR/runtime/gateway-jco/traces.jsonl}"
export SAP_GATEWAY_ODATA_PROXY_URL="${SAP_GATEWAY_ODATA_PROXY_URL:-http://127.0.0.1:$ODATA_SERVICE_PORT}"

trap stop_services INT TERM EXIT

start_service odata-service "$LOG_DIR/odata-service.log" bash -lc "cd '$ROOT_DIR/services/odata-service' && export PYTHONPATH=. && exec '$PYTHON_CMD' -c 'import os; from odata_service.server import run; run(int(os.environ.get(\"ODATA_SERVICE_PORT\", \"$ODATA_SERVICE_PORT\")))'"
start_service gateway "$LOG_DIR/gateway.log" bash -lc "cd '$ROOT_DIR/services/gateway' && exec '$GRADLE_CMD' --no-daemon bootRun"
start_service workbench "$LOG_DIR/workbench.log" npm --prefix "$ROOT_DIR/frontend" run dev -- --hostname "$FRONTEND_HOST" --port "$FRONTEND_PORT"

cat <<READY
[start] Services are starting.
[start] Gateway health:   http://127.0.0.1:$GATEWAY_PORT/health
[start] OData service:     http://127.0.0.1:$ODATA_SERVICE_PORT/execute
[start] Workbench UI:     http://127.0.0.1:$FRONTEND_PORT/workbench
[start] Root redirect:    http://127.0.0.1:$FRONTEND_PORT/
[start] Logs:             $LOG_DIR
[start] Press Ctrl+C to stop all services.
READY

wait
