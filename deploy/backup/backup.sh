#!/usr/bin/env bash
# Take one backup of the running production environment.
#
#   EASYAUDIT_RELEASE=$(git rev-parse HEAD) EASYAUDIT_BACKUP_DIR=/srv/easyaudit-backups deploy/backup/backup.sh
#
# Result: $EASYAUDIT_BACKUP_DIR/easyaudit-backup-<UTC timestamp>/{database.dump,objects/,manifest.json}
# Order matters: pg_dump first, then mirror the objects. Objects are written once under
# server-generated keys and never overwritten, so the objects copied after the dump are a
# superset of what the dump references. Extra objects are orphans (orphan sweep, Pilot-4B).
#
# Exit status: 0 ok; 1 failed, nothing produced; 3 backup produced but DEGRADED: the dump
# references objects that are missing from the bucket or whose size/sha256 differ from their
# Evidence row. The backup is kept (manifest "integrity": "degraded" lists the problems) so the
# current database is not lost, and the non-zero status makes a systemd timer show "failed".
set -euo pipefail
TOOL=backup
# shellcheck source=deploy/backup/lib.sh
source "$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/lib.sh"

ROOT="${EASYAUDIT_BACKUP_DIR:?set EASYAUDIT_BACKUP_DIR to the backup directory (mode 0700, not on the data disk)}"
RETENTION_DAYS="${EASYAUDIT_BACKUP_RETENTION_DAYS:-14}"
[[ "$RETENTION_DAYS" =~ ^[1-9][0-9]*$ ]] || fail "EASYAUDIT_BACKUP_RETENTION_DAYS must be a positive integer"

require_commands docker python3 flock stat
require_non_root
require_release
umask 077

[ -d "$ROOT" ] || install -d -m 700 "$ROOT"
[ "$(stat -c '%a' "$ROOT")" = "700" ] || fail "$ROOT must have mode 0700 (chmod 700 $ROOT)"
[ "$(stat -c '%u' "$ROOT")" = "$(id -u)" ] || fail "$ROOT must be owned by the invoking user"
exec 9>"$ROOT/.lock"
flock -n 9 || fail "another backup is already running"

require_running postgres object-storage api web gateway

NAME="easyaudit-backup-$(date -u +%Y%m%dT%H%M%SZ)"
STAGE="$ROOT/$NAME.partial"
TMP="$(mktemp -d)"
PRODUCED=false
cleanup() {
  status=$?
  rm -rf "$TMP"
  if [ "$PRODUCED" != true ] && [ "$status" -ne 0 ]; then
    rm -rf "$STAGE"
    echo "backup: FAILED, no backup was produced" >&2
  fi
  exit "$status"
}
trap cleanup EXIT

step "checking that the running images are one release"
: > "$TMP/images.tsv"
for svc in gateway web api postgres object-storage; do
  cid="$("${DC[@]}" ps -q "$svc")"
  image_id="$(docker inspect --format '{{.Image}}' "$cid")"
  revision=""
  case "$svc" in
    web|api|object-storage)
      revision="$(docker image inspect --format "{{ index .Config.Labels \"$IMAGE_REVISION_LABEL\" }}" "$image_id")" ;;
  esac
  printf '%s\t%s\t%s\t%s\n' "$svc" "$(docker inspect --format '{{.Config.Image}}' "$cid")" \
    "$image_id" "$revision" >> "$TMP/images.tsv"
done
python3 "$MANIFEST_PY" collect-images --release "$EASYAUDIT_RELEASE" "$TMP/images.tsv" > "$TMP/images.json"

mkdir "$STAGE" "$STAGE/objects"
STARTED_AT="$(now_utc)"
T0=$SECONDS

step "database: pg_dump"
db_tool pg_dump --format=custom --no-owner --no-privileges > "$STAGE/database.dump"
[ -s "$STAGE/database.dump" ] || fail "pg_dump produced an empty file"

step "objects: mirror bucket $BUCKET"
object_tool "$STAGE/objects" rw copy "$S3_REMOTE" /data

step "manifest"
db_tool pg_restore --data-only --table=evidences --table=alembic_version --file=- \
  < "$STAGE/database.dump" > "$TMP/dump-data.txt"
build_status=0
python3 "$MANIFEST_PY" build --dir "$STAGE" --started-at "$STARTED_AT" \
  --images "$TMP/images.json" --bucket "$BUCKET" --dump-data "$TMP/dump-data.txt" || build_status=$?
[ "$build_status" -eq 0 ] || [ "$build_status" -eq 3 ] || fail "could not write the manifest"

chmod -R go-rwx "$STAGE"
mv "$STAGE" "$ROOT/$NAME"
PRODUCED=true

step "retention: removing backups older than $RETENTION_DAYS days (the newest integrity-ok backup is always kept)"
while IFS= read -r old; do
  [ -n "$old" ] || continue
  echo "removing $old"
  rm -rf "${ROOT:?}/$old"
done < <(python3 "$MANIFEST_PY" retention "$ROOT" --days "$RETENTION_DAYS")

SUMMARY="$ROOT/$NAME ($((SECONDS - T0))s) release=$(manifest_field "$ROOT/$NAME" release_sha) alembic=$(manifest_field "$ROOT/$NAME" alembic_revision)"
if [ "$build_status" -eq 3 ]; then
  echo "BACKUP DEGRADED: $SUMMARY" >&2
  echo "backup: kept; see integrity_problems in its manifest.json (exit status 3)" >&2
  exit 3
fi
echo "BACKUP OK: $SUMMARY"
