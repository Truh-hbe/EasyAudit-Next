#!/usr/bin/env bash
# Sourced by smoke.sh and backup/drill.sh: throwaway certificate and secrets for test runs.
# Never used for real deployments (see README for those).

# make_test_secrets DIR: same shape as README section 1, but random and disposable.
make_test_secrets() {
  local dir="$1"
  install -d -m 700 "$dir"
  openssl rand -hex 24 | tr -d '\n' > "$dir/postgres_password"
  openssl rand -hex 32 | tr -d '\n' > "$dir/garage_rpc_secret"
  printf 'GK%s' "$(openssl rand -hex 12)" > "$dir/s3_access_key_id"
  openssl rand -hex 32 | tr -d '\n' > "$dir/s3_secret_access_key"
  # Containers run as non-root uids; the 0700 directory protects these files on the host.
  chmod 444 "$dir"/*
}

# make_test_certs DIR: self-signed certificate for localhost.
make_test_certs() {
  local dir="$1"
  install -d -m 700 "$dir"
  openssl req -x509 -newkey rsa:2048 -nodes -days 1 -subj "/CN=localhost" \
    -addext "subjectAltName=DNS:localhost,IP:127.0.0.1" \
    -keyout "$dir/tls.key" -out "$dir/tls.crt" 2>/dev/null
  chmod 444 "$dir"/*
}
