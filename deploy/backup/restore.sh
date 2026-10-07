#!/usr/bin/env bash
# Restore a backup made by backup.sh. Restore only ever writes into an EMPTY target and there is
# no way to override that: anything already there (tables, objects) makes it refuse.
#
#   restore.sh database    BACKUP_DIR   pg_restore into the empty database of the running postgres
#   restore.sh objects     BACKUP_DIR   copy the bundle's objects into the empty bucket
#   restore.sh environment BACKUP_DIR   whole new environment: release check, degraded-backup
#                                       rejection, build, start postgres+object-storage, database,
#                                       objects, alembic check, full verify (data only, no entry
#                                       point running), start api+web internally and check them,
#                                       and only then the gateway
#
# `environment` needs new secrets and certificates already in place (README section 1); they are
# not part of a backup.
set -euo pipefail
TOOL=restore
# shellcheck source=deploy/backup/lib.sh
source "$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/lib.sh"

usage() { fail "usage: restore.sh {database|objects|environment} BACKUP_DIR"; }
[ $# -eq 2 ] || usage
COMMAND="$1"
BACKUP="$(backup_dir_of "$2")"

BUNDLE_CHECKED=false
# `environment` ends in verify.sh --fail-degraded, which a degraded backup can never pass, so it
# refuses one before writing anything. The `database` and `objects` sub-steps never open traffic
# and still accept a degraded bundle (with its problems shown first) for investigation.
REJECT_DEGRADED=false
check_bundle() {
  $BUNDLE_CHECKED && return 0
  step "checking the bundle against its manifest"
  BUNDLE_CHECKED=true
  python3 "$MANIFEST_PY" verify-bundle "$BACKUP" || fail "bundle does not match its manifest; not restoring"
  if $REJECT_DEGRADED; then
    python3 "$MANIFEST_PY" verify-bundle "$BACKUP" --fail-degraded \
      || fail "degraded backup: an environment restore would end in a failed final verification; nothing was written. Restore the parts separately (restore.sh database / objects) to investigate, or use an integrity-ok backup"
  else
    python3 "$MANIFEST_PY" show-integrity "$BACKUP"
  fi
}

restore_database() {
  require_running postgres
  check_bundle
  require_empty_database
  step "database: pg_restore"
  db_tool pg_restore --exit-on-error --single-transaction --no-owner --no-privileges \
    --dbname "$DB_NAME" < "$BACKUP/database.dump"
  local expected actual
  expected="$(manifest_field "$BACKUP" alembic_revision)"
  actual="$(db_scalar "select version_num from alembic_version")"
  [ "$actual" = "$expected" ] || fail "restored database is at '$actual', manifest says '$expected'"
}

restore_objects() {
  require_running object-storage
  check_bundle
  require_empty_bucket
  step "objects: copy into bucket $BUCKET"
  object_tool "$BACKUP/objects" ro copy /data "$S3_REMOTE"
}

# First revision printed by `alembic <cmd>` in the release's own image (stderr carries logging).
alembic_revision() {
  "${DC[@]}" run --rm -T migrate alembic "$1" 2>/dev/null | awk '/^[0-9A-Za-z_]+( \(head\))?$/ {print $1; exit}'
}

# The entrypoints (gateway, and api/web that it depends on) must not stay up after a failed restore.
# Stop, never `down -v`: containers are kept for inspection, database and object volumes untouched.
ENTRYPOINTS_STARTED=false
isolate_entrypoints() {
  echo "restore: ERROR: restore failed after the application was started; stopping gateway, web and api." >&2
  "${DC[@]}" stop gateway web api >&2 || echo "restore: ERROR: could not stop the entrypoints; stop gateway, web and api by hand" >&2
  "${DC[@]}" logs --no-color --tail=100 gateway web api >&2 || true
  echo "restore: database and object volumes, logs and $BACKUP/manifest.json are kept; nothing was deleted. Investigate before opening traffic." >&2
}
on_exit() {
  local status=$?
  if [ "$status" -ne 0 ] && $ENTRYPOINTS_STARTED; then isolate_entrypoints; fi
  exit "$status"
}

restore_environment() {
  require_commands git
  REJECT_DEGRADED=true
  local head
  head="$(git -C "$REPO_DIR" rev-parse HEAD)"
  # A new environment builds from this checkout, so it defaults to (and must equal) HEAD.
  export EASYAUDIT_RELEASE="${EASYAUDIT_RELEASE:-$head}"
  require_release_match "$BACKUP"
  git -C "$REPO_DIR" diff --quiet HEAD || fail "the checkout has uncommitted changes; images would not match release $head"

  local secrets="${EASYAUDIT_SECRETS_DIR:-$DEPLOY_DIR/secrets}" certs="${EASYAUDIT_CERTS_DIR:-$DEPLOY_DIR/certs}" f
  for f in "$secrets"/{postgres_password,garage_rpc_secret,s3_access_key_id,s3_secret_access_key} "$certs"/{tls.crt,tls.key}; do
    [ -f "$f" ] || fail "missing $f (generate new secrets and certificates first, see deploy/README.md section 1)"
  done
  check_bundle

  step "build images for release $head"
  "${DC[@]}" --profile migrate build
  step "start postgres and object-storage"
  "${DC[@]}" up -d --wait postgres object-storage
  # Both targets must be empty before anything is written.
  require_empty_database
  require_empty_bucket
  restore_database
  restore_objects

  step "alembic: current must equal the manifest revision and this release's head"
  local expected current heads
  expected="$(manifest_field "$BACKUP" alembic_revision)"
  current="$(alembic_revision current)"
  heads="$(alembic_revision heads)"
  [ -n "$current" ] && [ "$current" = "$expected" ] || fail "alembic current is '$current', manifest says '$expected'"
  [ "$current" = "$heads" ] || fail "alembic current '$current' is not this release's head '$heads'; not starting the application"

  # verify.sh needs only postgres and object-storage, so the whole data verification (bundle,
  # revision, every object, every Evidence row) runs while no entry point exists.
  step "verify the restored data before any entry point is started"
  "$BACKUP_DIR_SRC/verify.sh" "$BACKUP"

  trap on_exit EXIT
  ENTRYPOINTS_STARTED=true
  step "start api and web (internal network only) and check the application"
  "${DC[@]}" up -d --wait api web
  "${DC[@]}" run --rm -T api easyaudit-next verify-evidence
  step "open the gateway"
  "${DC[@]}" up -d --wait gateway
  echo "RESTORE OK: release $head, alembic $current"
}

require_commands docker python3
require_non_root
case "$COMMAND" in
  database) require_release_match "$BACKUP"; restore_database ;;
  objects) require_release_match "$BACKUP"; restore_objects ;;
  environment) restore_environment ;;
  *) usage ;;
esac
