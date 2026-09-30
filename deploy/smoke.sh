#!/usr/bin/env bash
# End-to-end smoke test of deploy/compose.yaml with throwaway certs and secrets.
# Usage: deploy/smoke.sh   (needs docker compose, openssl, curl, python3; port 443 or EASYAUDIT_HTTPS_PORT free)
set -euo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
WORK="$(mktemp -d)"
export EASYAUDIT_SECRETS_DIR="$WORK/secrets"
export EASYAUDIT_CERTS_DIR="$WORK/certs"
export EASYAUDIT_HTTPS_PORT="${EASYAUDIT_HTTPS_PORT:-443}"
export COMPOSE_PROJECT_NAME="easyaudit-smoke"
DC=(docker compose -f "$HERE/compose.yaml")
BASE="https://localhost:${EASYAUDIT_HTTPS_PORT}"
CURL=(curl --silent --show-error --cacert "$EASYAUDIT_CERTS_DIR/tls.crt" --max-time 10)

cleanup() {
  status=$?
  if [ "$status" -ne 0 ]; then "${DC[@]}" logs --no-color --tail=80 || true; fi
  "${DC[@]}" --profile migrate down -v --remove-orphans || true
  rm -rf "$WORK"
  exit "$status"
}
trap cleanup EXIT

fail() { echo "SMOKE FAIL: $*" >&2; exit 1; }
step() { echo "==> $*"; }

step "generating temporary certificate and secrets"
mkdir -p "$EASYAUDIT_SECRETS_DIR" "$EASYAUDIT_CERTS_DIR"
chmod 700 "$EASYAUDIT_SECRETS_DIR" "$EASYAUDIT_CERTS_DIR"
openssl req -x509 -newkey rsa:2048 -nodes -days 1 -subj "/CN=localhost" \
  -addext "subjectAltName=DNS:localhost,IP:127.0.0.1" \
  -keyout "$EASYAUDIT_CERTS_DIR/tls.key" -out "$EASYAUDIT_CERTS_DIR/tls.crt" 2>/dev/null
openssl rand -hex 24 | tr -d '\n' > "$EASYAUDIT_SECRETS_DIR/postgres_password"
openssl rand -hex 32 | tr -d '\n' > "$EASYAUDIT_SECRETS_DIR/garage_rpc_secret"
printf 'GK%s' "$(openssl rand -hex 12)" > "$EASYAUDIT_SECRETS_DIR/s3_access_key_id"
openssl rand -hex 32 | tr -d '\n' > "$EASYAUDIT_SECRETS_DIR/s3_secret_access_key"
# Containers run as non-root uids; the 0700 directories protect these files on the host.
chmod 444 "$EASYAUDIT_SECRETS_DIR"/* "$EASYAUDIT_CERTS_DIR"/*

step "build"
"${DC[@]}" --profile migrate build

step "start postgres and object-storage"
"${DC[@]}" up -d --wait postgres object-storage

step "migrate"
"${DC[@]}" run --rm migrate

step "start api, web, gateway"
"${DC[@]}" up -d --wait gateway

step "SPA loads over HTTPS"
body="$("${CURL[@]}" --fail "$BASE/")" || fail "GET / failed"
grep -q 'id="root"' <<<"$body" || fail "index.html missing #root"
"${CURL[@]}" --fail --output /dev/null "$BASE/cases/some-client-route" || fail "SPA fallback failed"

step "API reachable through gateway"
code="$("${CURL[@]}" --output /dev/null --write-out '%{http_code}' \
  -X POST -H 'content-type: application/json' -d '{}' "$BASE/api/v1/auth/login")"
case "$code" in 4??) ;; *) fail "login returned $code, expected 4xx" ;; esac
ctype="$("${CURL[@]}" --output /dev/null --write-out '%{content_type}' "$BASE/api/v1/does-not-exist")"
case "$ctype" in application/json*) ;; *) fail "/api/v1 fell through to web ($ctype)" ;; esac

step "plain HTTP is not served"
if curl --silent --max-time 3 --output /dev/null "http://localhost:80/" 2>/dev/null; then
  fail "port 80 answered"
fi

step "no host port publishing besides the gateway"
for port in 5432 3900 3901 8000 8080; do
  if (exec 3<>"/dev/tcp/127.0.0.1/$port") 2>/dev/null; then fail "host port $port is open"; fi
done
"${DC[@]}" ps --format json | python3 -c '
import json, sys
raw = sys.stdin.read().strip()
rows = json.loads(raw) if raw.startswith("[") else [json.loads(l) for l in raw.splitlines() if l]
port = int(sys.argv[1])
published = {r["Service"]: sorted({p["PublishedPort"] for p in r.get("Publishers") or [] if p.get("PublishedPort")}) for r in rows}
assert published.get("gateway") == [port], f"gateway must publish only {port}: {published}"
others = {s: v for s, v in published.items() if s != "gateway" and v}
assert not others, f"non-gateway services publish ports: {others}"
' "$EASYAUDIT_HTTPS_PORT" || fail "unexpected published ports"

step "object storage bucket bootstrapped"
"${DC[@]}" exec -T object-storage garage -c /etc/garage.toml bucket info easyaudit-evidence >/dev/null \
  || fail "bucket easyaudit-evidence missing"

echo "SMOKE OK"
