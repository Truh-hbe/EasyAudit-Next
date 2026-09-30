#!/bin/sh
# Compose DATABASE_URL from discrete settings and a password file so the secret is
# never written into compose files or the environment listing of the compose project.
set -eu
if [ -z "${DATABASE_URL:-}" ] && [ -n "${POSTGRES_PASSWORD_FILE:-}" ]; then
  DATABASE_URL="$(python -c '
import os, urllib.parse as u
pw = open(os.environ["POSTGRES_PASSWORD_FILE"]).read().strip()
print("postgresql+psycopg://{}:{}@{}:5432/{}".format(
    u.quote(os.environ["POSTGRES_USER"], safe=""), u.quote(pw, safe=""),
    os.environ["POSTGRES_HOST"], u.quote(os.environ["POSTGRES_DB"], safe="")))
')"
  export DATABASE_URL
fi
exec "$@"
