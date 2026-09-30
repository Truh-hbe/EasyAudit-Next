#!/bin/sh
# Start Garage and idempotently bootstrap: single-node layout, bucket, and an
# operator-supplied access key (imported, so credentials never appear in compose).
set -eu

CONFIG=/etc/garage.toml
BUCKET="${S3_BUCKET:-easyaudit-evidence}"
KEY_ID="$(cat /run/secrets/s3_access_key_id)"
KEY_SECRET="$(cat /run/secrets/s3_secret_access_key)"
g() { garage -c "$CONFIG" "$@"; }

garage -c "$CONFIG" server &
server_pid=$!
trap 'kill -TERM "$server_pid" 2>/dev/null' TERM INT

i=0
until g status >/dev/null 2>&1; do
  i=$((i + 1))
  [ "$i" -le 60 ] || { echo "garage did not become ready" >&2; exit 1; }
  kill -0 "$server_pid" 2>/dev/null || { echo "garage exited early" >&2; exit 1; }
  sleep 1
done

if g status | grep -q "NO ROLE ASSIGNED"; then
  node_id="$(g node id -q | cut -d@ -f1)"
  g layout assign -z dc1 -c 10G "$node_id"
  g layout apply --version 1
fi
g bucket info "$BUCKET" >/dev/null 2>&1 || g bucket create "$BUCKET"
g key info "$KEY_ID" >/dev/null 2>&1 || g key import --yes -n easyaudit-app "$KEY_ID" "$KEY_SECRET"
g bucket allow --read --write --owner "$BUCKET" --key "$KEY_ID"
echo "object-storage bootstrap complete (bucket=$BUCKET)"

wait "$server_pid"
