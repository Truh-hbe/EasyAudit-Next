#!/usr/bin/env bash
# Monitoring probe for RPO: exits non-zero unless the newest integrity-ok backup is younger than
# EASYAUDIT_BACKUP_MAX_AGE_HOURS (default 24). Degraded and partial backups do not count.
# Needs only python3 and read access to the backup directory (no docker).
#
#   EASYAUDIT_BACKUP_DIR=/srv/easyaudit-backups deploy/backup/check-freshness.sh
set -euo pipefail
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT="${EASYAUDIT_BACKUP_DIR:?set EASYAUDIT_BACKUP_DIR to the backup directory}"
MAX_AGE="${EASYAUDIT_BACKUP_MAX_AGE_HOURS:-24}"
[ -d "$ROOT" ] || { echo "check-freshness: ERROR: $ROOT does not exist" >&2; exit 1; }
exec python3 "$HERE/manifest.py" latest-ok "$ROOT" --max-age-hours "$MAX_AGE"
