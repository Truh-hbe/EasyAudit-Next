#!/usr/bin/env bash
# Restore a backup made by backup.sh. Restore only ever writes into an EMPTY target and there is
# no way to override that: anything already there (tables, objects) makes it refuse.
#
#   restore.sh database    BACKUP_DIR   pg_restore into the empty database of the running postgres
#   restore.sh objects     BACKUP_DIR   copy the bundle's objects into the empty bucket
#   restore.sh environment BACKUP_DIR   whole new environment: release check, build, start
#                                       postgres+object-storage, database, objects, alembic check,
#                                       start api+web+gateway, verify
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
check_bundle() {
  $BUNDLE_CHECKED && return 0
  step "checking the bundle against its manifest"
  BUNDLE_CHECKED=true
  python3 "$MANIFEST_PY" verify-bundle "$BACKUP" || fail "bundle does not match its manifest; not restoring"
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

restore_environment() {
  require_commands git
  local manifest_release head
  manifest_release="$(manifest_field "$BACKUP" release_sha)"
  head="$(git -C "$REPO_DIR" rev-parse HEAD)"
  if [ "$head" != "$manifest_release" ]; then
    fail "this checkout is $head but the backup was taken on release $manifest_release. Check out that release first: git checkout $manifest_release"
  fi
  git -C "$REPO_DIR" diff --quiet HEAD || fail "the checkout has uncommitted changes; images would not match release $head"
  if [ -n "${EASYAUDIT_RELEASE:-}" ] && [ "$EASYAUDIT_RELEASE" != "$head" ]; then
    fail "EASYAUDIT_RELEASE=$EASYAUDIT_RELEASE differs from the checkout $head"
  fi
  export EASYAUDIT_RELEASE="$head"

  local secrets="${EASYAUDIT_SECRETS_DIR:-$DEPLOY_DIR/secrets}" certs="${EASYAUDIT_CERTS_DIR:-$DEPLOY_DIR/certs}" f
  for f in "$secrets"/{postgres_password,garage_rpc_secret,s3_access_key_id,s3_secret_access_key} "$certs"/{tls.crt,tls.key}; do
    [ -f "$f" ] || fail "missing $f (generate new secrets and certificates first, see deploy/README.md section 1)"
  done
  check_bundle

  step "build images for release $head"
  "${DC[@]}" --profile migrate build
  step "start postgres and object-storage"
  "${DC[@]}" up -d --wait postgres object-storage
  restore_database
  restore_objects

  step "alembic: current must equal the manifest revision and this release's head"
  local expected current heads
  expected="$(manifest_field "$BACKUP" alembic_revision)"
  current="$(alembic_revision current)"
  heads="$(alembic_revision heads)"
  [ -n "$current" ] && [ "$current" = "$expected" ] || fail "alembic current is '$current', manifest says '$expected'"
  [ "$current" = "$heads" ] || fail "alembic current '$current' is not this release's head '$heads'; not starting the application"

  step "start api, web, gateway"
  "${DC[@]}" up -d --wait gateway
  "$BACKUP_DIR_SRC/verify.sh" "$BACKUP"
  echo "RESTORE OK: release $head, alembic $current"
}

require_commands docker python3
require_non_root
case "$COMMAND" in
  database) require_release; restore_database ;;
  objects) require_release; restore_objects ;;
  environment) restore_environment ;;
  *) usage ;;
esac
