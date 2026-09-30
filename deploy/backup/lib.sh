#!/usr/bin/env bash
# Shared helpers for backup.sh, restore.sh, verify.sh and drill.sh. Source it; do not execute it.
# Assumes the caller ran `set -euo pipefail`.
# shellcheck disable=SC2034  # the variables below are used by the scripts that source this file

BACKUP_DIR_SRC="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
DEPLOY_DIR="$(cd "$BACKUP_DIR_SRC/.." && pwd)"
REPO_DIR="$(cd "$DEPLOY_DIR/.." && pwd)"
DC=(docker compose -f "$DEPLOY_DIR/compose.yaml")
BUCKET="easyaudit-evidence"
S3_REMOTE="ea:$BUCKET"
MANIFEST_PY="$BACKUP_DIR_SRC/manifest.py"
DB_NAME="easyaudit"
IMAGE_REVISION_LABEL="org.opencontainers.image.revision"

fail() { echo "${TOOL:-backup}: ERROR: $*" >&2; exit 1; }
step() { echo "==> $*"; }
now_utc() { date -u +%Y-%m-%dT%H:%M:%SZ; }

require_commands() {
  local cmd
  for cmd in "$@"; do command -v "$cmd" >/dev/null 2>&1 || fail "required command not found: $cmd"; done
}

# The compose file refuses to load without the release; the tools additionally check that it is
# the checkout's HEAD so images cannot be built from one commit and labelled with another.
require_release() {
  [ -n "${EASYAUDIT_RELEASE:-}" ] || fail "EASYAUDIT_RELEASE is not set (export EASYAUDIT_RELEASE=\$(git rev-parse HEAD))"
}

# Containers run as the invoking uid so they can write the 0700 backup directory; running as
# root would make them root too.
require_non_root() {
  [ "$(id -u)" -ne 0 ] || fail "run as a dedicated non-root user that is in the docker group (containers inherit your uid)"
}

# Backups are read and written by containers under the operator's uid.
run_as() { echo "$(id -u):$(id -g)"; }

db_tool() { "${DC[@]}" run --rm -T db-tool "$@"; }

# object_tool MOUNT_DIR MODE ARGS...: rclone with MOUNT_DIR at /data (MODE ro|rw), as the operator's uid.
object_tool() {
  local dir="$1" mode="$2"
  shift 2
  "${DC[@]}" run --rm -T --user "$(run_as)" -v "$dir:/data:$mode" object-tool "$@"
}
# object_tool_net ARGS...: rclone against the bucket only, no local mount.
object_tool_net() { "${DC[@]}" run --rm -T object-tool "$@"; }

service_running() {
  local cid
  cid="$("${DC[@]}" ps -q "$1")"
  [ -n "$cid" ] && [ "$(docker inspect --format '{{.State.Running}}' "$cid")" = "true" ]
}

require_running() {
  local svc
  for svc in "$@"; do service_running "$svc" || fail "service '$svc' is not running (docker compose up -d --wait first)"; done
}

# db_scalar SQL: one value from the live database.
db_scalar() { db_tool psql -X -At -v ON_ERROR_STOP=1 -c "$1"; }

# Refuse to restore into a database that already has tables.
require_empty_database() {
  local tables
  tables="$(db_scalar "select count(*) from information_schema.tables where table_schema not in ('pg_catalog','information_schema')")"
  [ "$tables" = "0" ] || fail "refusing to restore: the database is not empty ($tables tables). Restore only writes into an empty database; use a fresh environment (docker compose down -v)."
}

# Refuse to restore into a bucket that already has objects.
require_empty_bucket() {
  local listing
  listing="$(object_tool_net lsf --max-depth 1 "$S3_REMOTE")" || fail "cannot list bucket $BUCKET"
  [ -z "$listing" ] || fail "refusing to restore: bucket $BUCKET is not empty. Restore only writes into an empty bucket; use a fresh environment (docker compose down -v)."
}

# Backup directory names: easyaudit-backup-YYYYmmddTHHMMSSZ
backup_dir_of() {
  local dir="$1"
  [ -d "$dir" ] || fail "backup directory not found: $dir"
  [ -f "$dir/manifest.json" ] || fail "$dir has no manifest.json (incomplete or not a backup)"
  (cd "$dir" && pwd)
}

manifest_field() { python3 -c 'import json,sys; print(json.load(open(sys.argv[1]))[sys.argv[2]])' "$1/manifest.json" "$2"; }
