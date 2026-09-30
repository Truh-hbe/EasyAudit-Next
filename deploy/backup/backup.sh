#!/usr/bin/env bash
# Take one backup of the running production environment.
#
#   EASYAUDIT_RELEASE=$(git rev-parse HEAD) EASYAUDIT_BACKUP_DIR=/srv/easyaudit-backups deploy/backup/backup.sh
#
# Result: $EASYAUDIT_BACKUP_DIR/easyaudit-backup-<UTC timestamp>/{database.dump,objects/,manifest.json}
# Order matters: pg_dump first, then mirror the objects. Objects are written once under
# server-generated keys and never overwritten, so the objects copied after the dump are a
# superset of what the dump references. Anything the dump references but the copy lacks fails
# the backup. Extra objects are orphans (cleaned up by the orphan sweep, roadmap 1.4).
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
cleanup() {
  status=$?
  rm -rf "$TMP"
  if [ "$status" -ne 0 ]; then
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
python3 "$MANIFEST_PY" build --dir "$STAGE" --started-at "$STARTED_AT" \
  --images "$TMP/images.json" --bucket "$BUCKET" --dump-data "$TMP/dump-data.txt"

chmod -R go-rwx "$STAGE"
mv "$STAGE" "$ROOT/$NAME"

step "retention: removing backups older than $RETENTION_DAYS days"
CUTOFF="$(date -u -d "$RETENTION_DAYS days ago" +%Y%m%dT%H%M%SZ)"
for old in "$ROOT"/easyaudit-backup-*; do
  [ -d "$old" ] || continue
  base="${old##*/}"
  [[ "$base" =~ ^easyaudit-backup-([0-9]{8}T[0-9]{6}Z)(\.partial)?$ ]] || continue
  if [[ "${BASH_REMATCH[1]}" < "$CUTOFF" ]]; then
    echo "removing $base"
    rm -rf "$old"
  fi
done

echo "BACKUP OK: $ROOT/$NAME ($((SECONDS - T0))s)"
echo "  release=$(manifest_field "$ROOT/$NAME" release_sha) alembic=$(manifest_field "$ROOT/$NAME" alembic_revision)"
