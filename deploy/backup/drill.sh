#!/usr/bin/env bash
# Restore drill: deploy, create data through the real API, back up, destroy everything, restore
# into an empty environment with NEW secrets and certificate, verify, and record the RTO.
#
#   deploy/backup/drill.sh     (needs docker compose, git, openssl, python3; port 443 or EASYAUDIT_HTTPS_PORT free)
#
# Writes the drill record JSON to $DRILL_RECORD (default ./restore-drill-record.json).
set -euo pipefail
TOOL=drill
# shellcheck source=deploy/backup/lib.sh
source "$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/lib.sh"
# shellcheck source=deploy/testenv.sh
source "$DEPLOY_DIR/testenv.sh"

require_commands docker git openssl python3
require_non_root
WORK="$(mktemp -d)"
RECORD="${DRILL_RECORD:-$PWD/restore-drill-record.json}"
EASYAUDIT_RELEASE="$(git -C "$REPO_DIR" rev-parse HEAD)"
export EASYAUDIT_RELEASE
export EASYAUDIT_SECRETS_DIR="$WORK/secrets"
export EASYAUDIT_CERTS_DIR="$WORK/certs"
export EASYAUDIT_HTTPS_PORT="${EASYAUDIT_HTTPS_PORT:-443}"
export COMPOSE_PROJECT_NAME="easyaudit-drill"
BASE="https://localhost:${EASYAUDIT_HTTPS_PORT}"
ADMIN_LOGIN="drill-admin"
ADMIN_PASSWORD="drill-admin-password-1"
DRILL_API=(python3 "$BACKUP_DIR_SRC/drill_api.py")
ALL_PROFILES=(--profile migrate --profile backup)

RESULT="fail"
RESTORE_STARTED_AT="" RESTORE_COMPLETED_AT="" RTO_SECONDS="" BACKUP_TIMESTAMP="" RELEASE_SHA=""

write_record() {
  python3 - "$RECORD" "$RESTORE_STARTED_AT" "$RESTORE_COMPLETED_AT" "$RTO_SECONDS" \
    "$BACKUP_TIMESTAMP" "$RELEASE_SHA" "$RESULT" <<'PY'
import json, sys
path, started, completed, rto, backup_ts, release, result = sys.argv[1:8]
record = {
    "restore_started_at": started or None,
    "restore_completed_at": completed or None,
    "actual_rto_seconds": int(rto) if rto else None,
    "backup_timestamp": backup_ts or None,
    "release_sha": release or None,
    "result": result,
}
with open(path, "w") as handle:
    json.dump(record, handle, indent=2)
    handle.write("\n")
print("==> drill record")
print(json.dumps(record, indent=2))
PY
}

cleanup() {
  status=$?
  if [ "$status" -ne 0 ]; then
    RESULT="fail"
    "${DC[@]}" logs --no-color --tail=80 || true
  fi
  write_record || true
  "${DC[@]}" "${ALL_PROFILES[@]}" down -v --remove-orphans || true
  rm -rf "$WORK"
  exit "$status"
}
trap cleanup EXIT

step "1. deploy with temporary certificate and secrets"
make_test_certs "$EASYAUDIT_CERTS_DIR"
make_test_secrets "$EASYAUDIT_SECRETS_DIR"
"${DC[@]}" "${ALL_PROFILES[@]}" build
"${DC[@]}" up -d --wait postgres object-storage
"${DC[@]}" run --rm -T migrate
"${DC[@]}" up -d --wait gateway
# bootstrap-admin reads the password with getpass, which falls back to stdin without a TTY.
printf '%s\n%s\n' "$ADMIN_PASSWORD" "$ADMIN_PASSWORD" | "${DC[@]}" run --rm -T api \
  easyaudit-next bootstrap-admin --organization-name "Drill Org" \
  --admin-name "Drill Admin" --login-name "$ADMIN_LOGIN"
API_ARGS=(--base "$BASE" --cacert "$EASYAUDIT_CERTS_DIR/tls.crt" --login "$ADMIN_LOGIN" --password "$ADMIN_PASSWORD")
ORG_ID="$("${DRILL_API[@]}" whoami "${API_ARGS[@]}")"
"${DC[@]}" run --rm -T api easyaudit-next publish-scenario --organization-id "$ORG_ID" --key process_review --version 1

step "2. create data through the gateway: plan, case, finding, action, evidence"
"${DRILL_API[@]}" prepare-objects "$WORK/objs"
object_tool "$WORK/objs" ro copy /data "$S3_REMOTE"
"${DRILL_API[@]}" seed "${API_ARGS[@]}" --objects "$WORK/objects.json" --state "$WORK/state.json"

step "3. backup"
EASYAUDIT_BACKUP_DIR="$WORK/backups" "$BACKUP_DIR_SRC/backup.sh"
BACKUP="$(echo "$WORK"/backups/easyaudit-backup-*)"
BACKUP_TIMESTAMP="$(manifest_field "$BACKUP" backup_timestamp)"
RELEASE_SHA="$(manifest_field "$BACKUP" release_sha)"

step "4. destroy the environment (down -v) and its secrets and certificate"
"${DC[@]}" "${ALL_PROFILES[@]}" down -v --remove-orphans
[ -z "$(docker volume ls -q --filter "label=com.docker.compose.project=$COMPOSE_PROJECT_NAME")" ] \
  || fail "volumes survived down -v"
OLD_PASSWORD="$(cat "$EASYAUDIT_SECRETS_DIR/postgres_password")"
rm -rf "$EASYAUDIT_SECRETS_DIR" "$EASYAUDIT_CERTS_DIR"
make_test_certs "$EASYAUDIT_CERTS_DIR"
make_test_secrets "$EASYAUDIT_SECRETS_DIR"
[ "$OLD_PASSWORD" != "$(cat "$EASYAUDIT_SECRETS_DIR/postgres_password")" ] || fail "secrets were not regenerated"

step "5. restore into the empty environment"
RESTORE_STARTED_AT="$(now_utc)"
RESTORE_T0="$(date +%s)"
"$BACKUP_DIR_SRC/restore.sh" environment "$BACKUP"

step "6. verify"
expected="$(manifest_field "$BACKUP" alembic_revision)"
current="$("${DC[@]}" run --rm -T migrate alembic current 2>/dev/null | awk '/^[0-9A-Za-z_]+( \(head\))?$/ {print $1; exit}')"
heads="$("${DC[@]}" run --rm -T migrate alembic heads 2>/dev/null | awk '/^[0-9A-Za-z_]+( \(head\))?$/ {print $1; exit}')"
[ -n "$current" ] && [ "$current" = "$heads" ] && [ "$current" = "$expected" ] \
  || fail "alembic current='$current' head='$heads' manifest='$expected'"
# The certificate is new, so trust the new one. The account, password hash and all data come from the backup.
API_ARGS=(--base "$BASE" --cacert "$EASYAUDIT_CERTS_DIR/tls.crt" --login "$ADMIN_LOGIN" --password "$ADMIN_PASSWORD")
# EXTENSION POINT (Pilot-4B): drill_api.py `check` must also download every Evidence through the
# API and compare the bytes' sha256. Until the download endpoint exists, verify.sh (object-level
# sha256 against the manifest, Evidence rows against objects) stands in for it.
"${DRILL_API[@]}" check "${API_ARGS[@]}" --state "$WORK/state.json"
"$BACKUP_DIR_SRC/verify.sh" "$BACKUP"
RESTORE_COMPLETED_AT="$(now_utc)"
RTO_SECONDS="$(( $(date +%s) - RESTORE_T0 ))"

step "7. restore refuses non-empty targets and a mismatched release"
if "$BACKUP_DIR_SRC/restore.sh" database "$BACKUP"; then fail "restore database wrote into a non-empty database"; fi
if "$BACKUP_DIR_SRC/restore.sh" objects "$BACKUP"; then fail "restore objects wrote into a non-empty bucket"; fi
cp -a "$BACKUP" "$WORK/other-release"
python3 - "$WORK/other-release/manifest.json" <<'PY'
import json, sys
path = sys.argv[1]
manifest = json.load(open(path))
manifest["release_sha"] = "0" * 40
json.dump(manifest, open(path, "w"))
PY
if "$BACKUP_DIR_SRC/restore.sh" environment "$WORK/other-release"; then fail "restore environment ignored a release mismatch"; fi

RESULT="pass"
echo "DRILL OK: RTO ${RTO_SECONDS}s (small dataset, warm image cache; see deploy/README.md)"
