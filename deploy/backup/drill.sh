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

RTO_LIMIT="${DRILL_RTO_LIMIT_SECONDS:-14400}"
[[ "$RTO_LIMIT" =~ ^[1-9][0-9]*$ ]] || fail "DRILL_RTO_LIMIT_SECONDS must be a positive integer"

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
  # A drill whose record cannot be written did not succeed, whatever else happened.
  record_status=0
  write_record || record_status=$?
  "${DC[@]}" "${ALL_PROFILES[@]}" down -v --remove-orphans || true
  rm -rf "$WORK"
  if [ "$status" -eq 0 ] && [ "$record_status" -ne 0 ]; then
    echo "drill: ERROR: could not write the drill record to $RECORD" >&2
    status="$record_status"
  fi
  exit "$status"
}

# expect_refusal PATTERN CMD...: CMD must fail, and its output must say why.
expect_refusal() {
  local pattern="$1" out status=0
  shift
  out="$("$@" 2>&1)" || status=$?
  echo "$out"
  [ "$status" -ne 0 ] || fail "expected a refusal but the command succeeded: $*"
  grep -q -- "$pattern" <<<"$out" || fail "refused for the wrong reason (wanted '$pattern'): $*"
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

step "2. create data through the gateway: plan, case, finding, action, Evidence uploaded as real files"
"${DRILL_API[@]}" seed "${API_ARGS[@]}" --state "$WORK/state.json"
step "2b. read the uploaded objects back from the bucket and compare with what the API reported"
object_tool_net hashsum sha256 --download "$S3_REMOTE" > "$WORK/bucket-hashes.txt"
python3 - "$WORK/state.json" "$WORK/bucket-hashes.txt" <<'PY'
import json, sys
state = json.load(open(sys.argv[1]))
in_bucket = {}
for line in open(sys.argv[2]):
    digest, _, key = line.strip().partition("  ")
    in_bucket[key] = digest
expected = {e["storage_key"]: e["sha256"] for e in state["evidences"]}
assert in_bucket == expected, f"bucket {in_bucket} != registered Evidence {expected}"
print(f"bucket holds exactly the {len(expected)} registered objects, sha256 equal to the server's")
PY

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
expect_refusal "database is not empty" "$BACKUP_DIR_SRC/restore.sh" database "$BACKUP"
expect_refusal "is not empty" "$BACKUP_DIR_SRC/restore.sh" objects "$BACKUP"
cp -a "$BACKUP" "$WORK/other-release"
python3 - "$WORK/other-release/manifest.json" <<'PY'
import json, sys
path = sys.argv[1]
manifest = json.load(open(path))
manifest["release_sha"] = "0" * 40
json.dump(manifest, open(path, "w"))
PY
# Every entry point checks the release before it looks at, let alone writes to, the targets.
for sub in database objects environment; do
  expect_refusal "was taken on release" "$BACKUP_DIR_SRC/restore.sh" "$sub" "$WORK/other-release"
done

step "8. degraded backup: a registered object is lost, the backup is still kept"
LOST_KEY="$(python3 -c 'import json,sys; print(json.load(open(sys.argv[1]))["evidences"][0]["storage_key"])' "$WORK/state.json")"
object_tool_net deletefile "$S3_REMOTE/$LOST_KEY"
degraded_status=0
EASYAUDIT_BACKUP_DIR="$WORK/backups" "$BACKUP_DIR_SRC/backup.sh" || degraded_status=$?
[ "$degraded_status" -eq 3 ] || fail "backup exit status $degraded_status, expected 3 (degraded)"
DEGRADED="$(echo "$WORK"/backups/easyaudit-backup-* | tr ' ' '\n' | grep -v -F "$BACKUP" | sort | tail -1)"
[ -f "$DEGRADED/database.dump" ] && [ -f "$DEGRADED/manifest.json" ] || fail "degraded backup was not kept"
[ "$(manifest_field "$DEGRADED" integrity)" = "degraded" ] || fail "manifest is not marked degraded"
grep -q "$LOST_KEY" "$DEGRADED/manifest.json" || fail "manifest does not name the lost object"
if "$BACKUP_DIR_SRC/verify.sh" "$DEGRADED"; then fail "verify passed a degraded backup"; fi
# The degraded backup does not count for RPO; the earlier integrity-ok one is still fresh.
EASYAUDIT_BACKUP_DIR="$WORK/backups" "$BACKUP_DIR_SRC/check-freshness.sh"
python3 "$BACKUP_DIR_SRC/manifest.py" latest-ok "$WORK/backups" --max-age-hours 24 | grep -q -F "$(basename "$BACKUP")" \
  || fail "freshness must point at the integrity-ok backup, not the degraded one"

step "9. environment restore refuses a non-empty bucket before it writes the database"
"${DC[@]}" "${ALL_PROFILES[@]}" down -v --remove-orphans
"${DC[@]}" up -d --wait object-storage
mkdir -p "$WORK/marker"
echo "not part of any backup" > "$WORK/marker/stray.txt"
object_tool "$WORK/marker" ro copy /data "$S3_REMOTE"
expect_refusal "bucket $BUCKET is not empty" "$BACKUP_DIR_SRC/restore.sh" environment "$BACKUP"
tables="$(db_scalar "select count(*) from information_schema.tables where table_schema not in ('pg_catalog','information_schema')")"
[ "$tables" = "0" ] || fail "the database was written to ($tables tables) although the bucket was not empty"

[ "$RTO_SECONDS" -le "$RTO_LIMIT" ] || fail "actual RTO ${RTO_SECONDS}s exceeds the limit ${RTO_LIMIT}s"
RESULT="pass"
echo "DRILL OK: RTO ${RTO_SECONDS}s (small dataset, warm image cache; see deploy/README.md)"
