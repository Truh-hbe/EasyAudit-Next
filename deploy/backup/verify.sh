#!/usr/bin/env bash
# Integrity check for a backup bundle and, unless --bundle-only, the live environment against it.
#
#   deploy/backup/verify.sh BACKUP_DIR [--bundle-only]
#
# 1. bundle: recompute the sha256 of database.dump and every object file and compare with manifest.json;
#            a backup marked integrity "degraded" fails here too
# 2. live:   recompute the sha256 of every object in the bucket, compare with the manifest, and
#            check every Evidence row in the database (object exists, sha256 and size match);
#            also that the database is at the manifest's alembic revision.
# Every inconsistency is listed; any inconsistency makes the exit status non-zero.
set -euo pipefail
TOOL=verify
# shellcheck source=deploy/backup/lib.sh
source "$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/lib.sh"

[ $# -ge 1 ] || fail "usage: verify.sh BACKUP_DIR [--bundle-only]"
BACKUP="$(backup_dir_of "$1")"
BUNDLE_ONLY=false
[ "${2:-}" != "--bundle-only" ] || BUNDLE_ONLY=true

require_commands python3
step "bundle: $BACKUP"
python3 "$MANIFEST_PY" verify-bundle "$BACKUP" --fail-degraded || fail "bundle does not match its manifest"
$BUNDLE_ONLY && { echo "VERIFY OK (bundle only)"; exit 0; }

require_commands docker
require_release
require_running postgres object-storage
TMP="$(mktemp -d)"
trap 'rm -rf "$TMP"' EXIT

step "live: alembic revision"
expected="$(manifest_field "$BACKUP" alembic_revision)"
actual="$(db_scalar "select version_num from alembic_version")"
[ "$actual" = "$expected" ] || fail "database is at alembic revision '$actual', manifest says '$expected'"

step "live: recomputing sha256 of every object in bucket $BUCKET"
object_tool_net lsjson --recursive --files-only "$S3_REMOTE" > "$TMP/lsjson.json"
object_tool_net hashsum sha256 --download "$S3_REMOTE" > "$TMP/hashsum.txt"
db_scalar "select coalesce(json_agg(json_build_object('id', id, 'storage_key', storage_key, 'size_bytes', size_bytes, 'sha256', sha256)), '[]'::json) from evidences" > "$TMP/evidences.json"

step "live: comparing bucket and Evidence rows with the manifest"
python3 "$MANIFEST_PY" verify-live "$BACKUP" --lsjson "$TMP/lsjson.json" --hashsum "$TMP/hashsum.txt" \
  --evidences "$TMP/evidences.json" || fail "live environment is inconsistent with the backup"
echo "VERIFY OK"
